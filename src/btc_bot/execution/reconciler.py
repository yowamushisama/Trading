"""REST reconciler — compares local DB state vs exchange every N seconds.

This is the fallback when the user-data WebSocket is disconnected.
On any mismatch it logs a risk_event and can trip the kill switch.
"""

from __future__ import annotations

import time
import threading
from datetime import datetime, timezone

from loguru import logger
from sqlalchemy.orm import Session

from btc_bot.exchange.base import ExchangeAdapter
from btc_bot.risk.kill_switch import KillSwitchState
from btc_bot.storage.repos import log_risk_event, update_order_status


class Reconciler:
    def __init__(
        self,
        adapter: ExchangeAdapter,
        kill_switch: KillSwitchState,
        symbol: str,
        interval_seconds: int = 30,
    ) -> None:
        self.adapter = adapter
        self.kill_switch = kill_switch
        self.symbol = symbol
        self.interval_seconds = interval_seconds
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._session_factory = None

    def set_session_factory(self, factory) -> None:
        self._session_factory = factory

    def start(self) -> None:
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, daemon=True, name="Reconciler")
        self._thread.start()
        logger.info("Reconciler started")

    def stop(self) -> None:
        self._stop.set()

    def _run(self) -> None:
        while not self._stop.is_set():
            try:
                self.reconcile_once()
            except Exception as e:
                logger.error(f"Reconciler error: {e}")
                self.kill_switch.record_api_error()
            self._stop.wait(timeout=self.interval_seconds)

    def reconcile_once(self) -> list[str]:
        """Fetch open orders from exchange and sync to DB. Returns list of mismatched IDs."""
        try:
            exchange_orders = self.adapter.get_open_orders(self.symbol)
        except Exception as e:
            self.kill_switch.record_api_error()
            logger.error(f"Reconciler: failed to fetch open orders: {e}")
            return []

        exchange_ids = {o.client_order_id: o for o in exchange_orders}

        if self._session_factory is None:
            return []

        mismatches: list[str] = []
        with self._session_factory() as session:
            from btc_bot.storage.models import Order
            local_open = (
                session.query(Order)
                .filter(Order.symbol == self.symbol)
                .filter(Order.status.notin_(["FILLED", "CANCELED", "EXPIRED", "REJECTED"]))
                .all()
            )

            for local_order in local_open:
                cid = local_order.client_order_id
                if cid in exchange_ids:
                    ex = exchange_ids[cid]
                    if ex.status != local_order.status:
                        logger.warning(
                            f"Reconciler mismatch {cid}: local={local_order.status} "
                            f"exchange={ex.status}"
                        )
                        update_order_status(
                            session, cid, ex.status, ex.qty_filled, ex.exchange_order_id
                        )
                        mismatches.append(cid)
                else:
                    # Local thinks order is open but exchange doesn't — query it directly
                    try:
                        fresh = self.adapter.get_order_status(self.symbol, cid)
                        if fresh.status in ("FILLED", "CANCELED", "EXPIRED", "REJECTED"):
                            update_order_status(
                                session, cid, fresh.status, fresh.qty_filled
                            )
                            mismatches.append(cid)
                    except Exception as e:
                        logger.warning(f"Could not query order {cid}: {e}")

            if mismatches:
                log_risk_event(
                    session,
                    kind="reconciler_mismatch",
                    severity="warn",
                    payload={"mismatched_ids": mismatches},
                )

        if mismatches:
            logger.warning(f"Reconciler fixed {len(mismatches)} mismatches: {mismatches}")

        return mismatches

    def check_position_integrity(
        self,
        session: Session,
        symbol: str,
    ) -> bool:
        """Compare local open trade qty vs exchange BTC balance. Trips kill switch on mismatch."""
        from btc_bot.storage.repos import get_open_trades

        local_trades = get_open_trades(session)
        local_qty = sum(float(t.qty) for t in local_trades if t.symbol == symbol)

        try:
            ex_balance = self.adapter.get_balance("BTC")
            exchange_qty = ex_balance.free + ex_balance.locked
        except Exception as e:
            self.kill_switch.record_api_error()
            return False

        tolerance = 0.00001
        if abs(local_qty - exchange_qty) > tolerance:
            self.kill_switch.check_position_mismatch(local_qty, exchange_qty, tolerance)
            return False
        return True
