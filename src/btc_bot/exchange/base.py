"""ExchangeAdapter interface — spot-first, futures-ready."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Literal

from btc_bot.risk.sizing import ExchangeFilters


@dataclass
class OrderResult:
    client_order_id: str
    exchange_order_id: str | None
    status: str  # PENDING_LOCAL | NEW | PARTIALLY_FILLED | FILLED | CANCELED | REJECTED
    qty_filled: float
    avg_price: float
    raw: dict


@dataclass
class Balance:
    asset: str
    free: float
    locked: float


class ExchangeAdapter(ABC):
    """Interface for all exchange interactions.
    Never assume an order is filled until confirmed by the exchange.
    """

    @abstractmethod
    def get_balance(self, asset: str) -> Balance:
        ...

    @abstractmethod
    def get_exchange_filters(self, symbol: str) -> ExchangeFilters:
        ...

    @abstractmethod
    def place_limit_order(
        self,
        symbol: str,
        side: Literal["BUY", "SELL"],
        qty: float,
        price: float,
        client_order_id: str,
        time_in_force: str = "GTC",
    ) -> OrderResult:
        ...

    @abstractmethod
    def place_market_order(
        self,
        symbol: str,
        side: Literal["BUY", "SELL"],
        qty: float,
        client_order_id: str,
    ) -> OrderResult:
        ...

    @abstractmethod
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
        ...

    @abstractmethod
    def cancel_order(self, symbol: str, client_order_id: str) -> OrderResult:
        ...

    @abstractmethod
    def get_open_orders(self, symbol: str) -> list[OrderResult]:
        ...

    @abstractmethod
    def get_order_status(self, symbol: str, client_order_id: str) -> OrderResult:
        ...
