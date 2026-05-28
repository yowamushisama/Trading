"""Paper trading against live mainnet candles — no exchange orders placed.

Simulates fills, fees, and slippage against real market data.
Identical to backtest fill model but runs in real-time.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Literal

from loguru import logger

from btc_bot.exchange.base import Balance, ExchangeAdapter, OrderResult
from btc_bot.risk.sizing import ExchangeFilters


@dataclass
class PaperOrder:
    client_order_id: str
    side: str
    qty: float
    limit_price: float | None
    stop_trigger: float | None
    take_profit: float | None
    status: str = "NEW"
    qty_filled: float = 0.0
    avg_fill_price: float = 0.0
    created_at: datetime = field(default_factory=lambda: datetime.now(tz=timezone.utc))


class PaperLocalAdapter(ExchangeAdapter):
    """Simulated exchange adapter using live mainnet candle data."""

    def __init__(
        self,
        initial_usdt: float = 10_000.0,
        fee_per_side_pct: float = 0.00075,
        slippage_pct: float = 0.0005,
    ) -> None:
        self.balances: dict[str, float] = {"USDT": initial_usdt, "BTC": 0.0}
        self.fee_per_side_pct = fee_per_side_pct
        self.slippage_pct = slippage_pct
        self._orders: dict[str, PaperOrder] = {}
        self._filters = ExchangeFilters.default_btcusdt()

    def get_balance(self, asset: str) -> Balance:
        free = self.balances.get(asset, 0.0)
        return Balance(asset=asset, free=free, locked=0.0)

    def get_exchange_filters(self, symbol: str) -> ExchangeFilters:
        return self._filters

    def place_limit_order(
        self,
        symbol: str,
        side: Literal["BUY", "SELL"],
        qty: float,
        price: float,
        client_order_id: str,
        time_in_force: str = "GTC",
    ) -> OrderResult:
        order = PaperOrder(
            client_order_id=client_order_id,
            side=side,
            qty=qty,
            limit_price=price,
            stop_trigger=None,
            take_profit=None,
        )
        self._orders[client_order_id] = order
        logger.info(f"[PAPER] LIMIT {side} {qty} @ {price} | id={client_order_id}")
        return self._to_result(order)

    def place_market_order(
        self,
        symbol: str,
        side: Literal["BUY", "SELL"],
        qty: float,
        client_order_id: str,
    ) -> OrderResult:
        order = PaperOrder(
            client_order_id=client_order_id,
            side=side,
            qty=qty,
            limit_price=None,
            stop_trigger=None,
            take_profit=None,
            status="MARKET_PENDING",
        )
        self._orders[client_order_id] = order
        return self._to_result(order)

    def place_otoco_order(
        self,
        symbol: str,
        entry_side: Literal["BUY"],
        entry_qty: float,
        entry_price: float,
        stop_price: float,
        take_profit_price: float,
        list_client_id: str,
    ) -> dict:
        order = PaperOrder(
            client_order_id=list_client_id,
            side=entry_side,
            qty=entry_qty,
            limit_price=entry_price,
            stop_trigger=stop_price,
            take_profit=take_profit_price,
        )
        self._orders[list_client_id] = order
        logger.info(
            f"[PAPER] OTOCO entry@{entry_price} SL@{stop_price} TP@{take_profit_price}"
        )
        return {"listClientOrderId": list_client_id, "status": "EXECUTING"}

    def on_candle(self, candle: dict) -> list[str]:
        """Process a new candle and fill any triggered orders. Returns filled IDs."""
        filled = []
        low = float(candle["low"])
        high = float(candle["high"])
        close = float(candle["close"])

        for cid, order in list(self._orders.items()):
            # ENTRY_FILLED = entry of OTOCO done, now watching SL/TP
            if order.status == "ENTRY_FILLED":
                if order.stop_trigger is not None and low <= order.stop_trigger:
                    self._exit_fill(order, order.stop_trigger * (1 - self.slippage_pct), "STOP_HIT")
                    filled.append(cid)
                elif order.take_profit is not None and high >= order.take_profit:
                    self._exit_fill(order, order.take_profit * (1 - self.slippage_pct), "TP_HIT")
                    filled.append(cid)
                continue

            if order.status not in ("NEW", "MARKET_PENDING", "EXECUTING"):
                continue

            if order.status == "MARKET_PENDING":
                fill_price = close * (1 + self.slippage_pct)
                self._fill(order, fill_price)
                filled.append(cid)
                continue

            if order.limit_price is not None:
                lp = order.limit_price
                if order.side == "BUY" and low <= lp <= high:
                    fill_price = lp * (1 + self.slippage_pct)
                    if order.stop_trigger is not None or order.take_profit is not None:
                        # OTOCO: entry filled → transition to protection-watching state
                        self._fill(order, fill_price, status="ENTRY_FILLED")
                    else:
                        self._fill(order, fill_price)
                    filled.append(cid)
                elif order.side == "SELL" and low <= lp <= high:
                    fill_price = lp * (1 - self.slippage_pct)
                    self._fill(order, fill_price)
                    filled.append(cid)

        return filled

    def _fill(self, order: PaperOrder, fill_price: float, status: str = "FILLED") -> None:
        order.status = status
        order.qty_filled = order.qty
        order.avg_fill_price = fill_price
        notional = order.qty * fill_price
        fee = notional * self.fee_per_side_pct

        if order.side == "BUY":
            self.balances["USDT"] = self.balances.get("USDT", 0) - notional - fee
            self.balances["BTC"] = self.balances.get("BTC", 0) + order.qty
        else:
            self.balances["USDT"] = self.balances.get("USDT", 0) + notional - fee
            self.balances["BTC"] = self.balances.get("BTC", 0) - order.qty

        logger.info(
            f"[PAPER] FILL {order.side} {order.qty} @ {fill_price:.2f} | {status} | "
            f"USDT={self.balances['USDT']:.2f} BTC={self.balances['BTC']:.6f}"
        )

    def _exit_fill(self, order: PaperOrder, fill_price: float, reason: str) -> None:
        """Close an open OTOCO position (SL or TP hit)."""
        order.status = reason
        qty = order.qty
        notional = qty * fill_price
        fee = notional * self.fee_per_side_pct
        self.balances["USDT"] = self.balances.get("USDT", 0) + notional - fee
        self.balances["BTC"] = self.balances.get("BTC", 0) - qty
        logger.info(
            f"[PAPER] EXIT {qty} BTC @ {fill_price:.2f} | {reason} | "
            f"USDT={self.balances['USDT']:.2f} BTC={self.balances['BTC']:.6f}"
        )

    def cancel_order(self, symbol: str, client_order_id: str) -> OrderResult:
        if client_order_id in self._orders:
            self._orders[client_order_id].status = "CANCELED"
        return OrderResult(
            client_order_id=client_order_id,
            exchange_order_id=None,
            status="CANCELED",
            qty_filled=0.0,
            avg_price=0.0,
            raw={},
        )

    def get_open_orders(self, symbol: str) -> list[OrderResult]:
        return [
            self._to_result(o)
            for o in self._orders.values()
            if o.status in ("NEW", "EXECUTING", "MARKET_PENDING", "ENTRY_FILLED")
        ]

    def get_order_status(self, symbol: str, client_order_id: str) -> OrderResult:
        order = self._orders.get(client_order_id)
        if order is None:
            return OrderResult(
                client_order_id=client_order_id,
                exchange_order_id=None,
                status="UNKNOWN",
                qty_filled=0.0,
                avg_price=0.0,
                raw={},
            )
        return self._to_result(order)

    @staticmethod
    def _to_result(order: PaperOrder) -> OrderResult:
        return OrderResult(
            client_order_id=order.client_order_id,
            exchange_order_id=None,
            status=order.status,
            qty_filled=order.qty_filled,
            avg_price=order.avg_fill_price,
            raw={},
        )
