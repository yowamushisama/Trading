"""Order state machine: tracks lifecycle from PENDING_LOCAL → FILLED/CANCELED."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Callable

from loguru import logger

from btc_bot.exchange.base import ExchangeAdapter, OrderResult
from btc_bot.risk.kill_switch import KillSwitchState
from btc_bot.risk.protection import ProtectionStatus


TERMINAL_STATUSES = {"FILLED", "CANCELED", "EXPIRED", "REJECTED", "STOP_HIT", "TP_HIT"}


@dataclass
class ManagedOrder:
    client_order_id: str
    symbol: str
    side: str
    qty: float
    price: float | None
    strategy: str
    stale_seconds: int
    result: OrderResult | None = None
    created_at: datetime = field(default_factory=lambda: datetime.now(tz=timezone.utc))

    def is_stale(self) -> bool:
        if self.result and self.result.status in TERMINAL_STATUSES:
            return False
        elapsed = (datetime.now(tz=timezone.utc) - self.created_at).total_seconds()
        return elapsed >= self.stale_seconds

    def is_terminal(self) -> bool:
        return self.result is not None and self.result.status in TERMINAL_STATUSES


class OrderManager:
    def __init__(
        self,
        adapter: ExchangeAdapter,
        kill_switch: KillSwitchState,
        protection_timeout_seconds: int = 5,
    ) -> None:
        self.adapter = adapter
        self.kill_switch = kill_switch
        self.protection_timeout_seconds = protection_timeout_seconds
        self._orders: dict[str, ManagedOrder] = {}
        self.protection = ProtectionStatus()

    def submit(self, order: ManagedOrder) -> OrderResult:
        """Submit order and track it. Increments kill switch on rejection."""
        if order.price is not None:
            result = self.adapter.place_limit_order(
                symbol=order.symbol,
                side=order.side,
                qty=order.qty,
                price=order.price,
                client_order_id=order.client_order_id,
            )
        else:
            result = self.adapter.place_market_order(
                symbol=order.symbol,
                side=order.side,
                qty=order.qty,
                client_order_id=order.client_order_id,
            )

        if result.status == "REJECTED":
            self.kill_switch.record_order_rejection()
        else:
            self.kill_switch.record_order_success()

        order.result = result
        self._orders[order.client_order_id] = order
        return result

    def cancel_stale_orders(self, symbol: str) -> list[str]:
        cancelled = []
        for cid, order in list(self._orders.items()):
            if order.is_stale() and not order.is_terminal():
                try:
                    self.adapter.cancel_order(symbol, cid)
                    cancelled.append(cid)
                    logger.warning(f"Cancelled stale order {cid}")
                except Exception as e:
                    self.kill_switch.record_api_error()
                    logger.error(f"Failed to cancel stale order {cid}: {e}")
        return cancelled

    def check_protection_timeout(self, flatten_callback: Callable[[], None]) -> None:
        """Call on every loop tick. Triggers emergency flatten if unprotected too long."""
        if self.protection.needs_emergency_flatten(self.protection_timeout_seconds):
            logger.critical("Protection timeout! Emergency flatten triggered.")
            self.protection.trigger_emergency()
            flatten_callback()
