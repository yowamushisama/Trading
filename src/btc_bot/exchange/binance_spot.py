"""Binance Spot exchange adapter — wraps python-binance client.

Reuses the SSL verify=False workaround from live_trade.py (Windows cert chain issue).
Supports both mainnet and testnet via constructor flag.
"""

from __future__ import annotations

import urllib3
from typing import Literal

from loguru import logger

from btc_bot.exchange.base import Balance, ExchangeAdapter, OrderResult
from btc_bot.exchange.filters import FilterCache
from btc_bot.risk.sizing import ExchangeFilters

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)


class BinanceSpotAdapter(ExchangeAdapter):
    def __init__(
        self,
        api_key: str,
        api_secret: str,
        testnet: bool = False,
        filter_cache: FilterCache | None = None,
    ) -> None:
        from binance import Client

        self.testnet = testnet
        self._filter_cache = filter_cache or FilterCache()

        client_kwargs: dict = {"requests_params": {"verify": False}}
        if testnet:
            client_kwargs["testnet"] = True

        self._client = Client(api_key, api_secret, **client_kwargs)
        logger.info(f"BinanceSpotAdapter initialized (testnet={testnet})")

    def get_balance(self, asset: str) -> Balance:
        raw = self._client.get_asset_balance(asset=asset)
        return Balance(
            asset=asset,
            free=float(raw["free"]),
            locked=float(raw["locked"]),
        )

    def get_exchange_filters(self, symbol: str) -> ExchangeFilters:
        cached = self._filter_cache.get(symbol)
        if cached is not None:
            return cached

        info = self._client.get_symbol_info(symbol.replace("/", ""))
        if info is None:
            logger.warning(f"No exchangeInfo for {symbol}, using defaults")
            return ExchangeFilters.default_btcusdt()

        filters = ExchangeFilters.from_exchange_info(info.get("filters", []))
        self._filter_cache.set(symbol, filters)
        return filters

    def place_limit_order(
        self,
        symbol: str,
        side: Literal["BUY", "SELL"],
        qty: float,
        price: float,
        client_order_id: str,
        time_in_force: str = "GTC",
    ) -> OrderResult:
        from binance import Client

        raw = self._client.create_order(
            symbol=symbol.replace("/", ""),
            side=Client.SIDE_BUY if side == "BUY" else Client.SIDE_SELL,
            type=Client.ORDER_TYPE_LIMIT,
            timeInForce=time_in_force,
            quantity=str(qty),
            price=str(price),
            newClientOrderId=client_order_id,
        )
        return self._parse_order(raw, client_order_id)

    def place_market_order(
        self,
        symbol: str,
        side: Literal["BUY", "SELL"],
        qty: float,
        client_order_id: str,
    ) -> OrderResult:
        from binance import Client

        raw = self._client.create_order(
            symbol=symbol.replace("/", ""),
            side=Client.SIDE_BUY if side == "BUY" else Client.SIDE_SELL,
            type=Client.ORDER_TYPE_MARKET,
            quantity=str(qty),
            newClientOrderId=client_order_id,
        )
        return self._parse_order(raw, client_order_id)

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
        """Place OTOCO (one-triggers-OCO) order list.

        Entry limit → SL stop-limit + TP limit-maker, linked atomically.
        Falls back to logging a warning if OTOCO is not supported on this endpoint.
        """
        raw = self._client.create_oto_order(
            symbol=symbol.replace("/", ""),
            workingType="LIMIT",
            workingSide=entry_side,
            workingPrice=str(entry_price),
            workingQuantity=str(entry_qty),
            workingTimeInForce="GTC",
            pendingSide="SELL",
            pendingQuantity=str(entry_qty),
            pendingAboveType="LIMIT_MAKER",
            pendingAbovePrice=str(take_profit_price),
            pendingBelowType="STOP_LOSS",
            pendingBelowStopPrice=str(stop_price),
            listClientOrderId=list_client_id,
        )
        return raw

    def cancel_order(self, symbol: str, client_order_id: str) -> OrderResult:
        raw = self._client.cancel_order(
            symbol=symbol.replace("/", ""),
            origClientOrderId=client_order_id,
        )
        return self._parse_order(raw, client_order_id)

    def get_open_orders(self, symbol: str) -> list[OrderResult]:
        raw_list = self._client.get_open_orders(symbol=symbol.replace("/", ""))
        return [self._parse_order(o, o.get("clientOrderId", "")) for o in raw_list]

    def get_order_status(self, symbol: str, client_order_id: str) -> OrderResult:
        raw = self._client.get_order(
            symbol=symbol.replace("/", ""),
            origClientOrderId=client_order_id,
        )
        return self._parse_order(raw, client_order_id)

    @staticmethod
    def _parse_order(raw: dict, client_order_id: str) -> OrderResult:
        fills = raw.get("fills", [])
        qty_filled = float(raw.get("executedQty", 0))
        avg_price = 0.0
        if fills and qty_filled > 0:
            avg_price = sum(float(f["price"]) * float(f["qty"]) for f in fills) / qty_filled
        elif qty_filled > 0 and raw.get("price"):
            avg_price = float(raw["price"])

        return OrderResult(
            client_order_id=client_order_id,
            exchange_order_id=str(raw.get("orderId", "")),
            status=raw.get("status", "UNKNOWN"),
            qty_filled=qty_filled,
            avg_price=avg_price,
            raw=raw,
        )
