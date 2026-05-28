"""Tests for exchange filter parsing and validation."""

from __future__ import annotations

import pytest
from btc_bot.risk.sizing import ExchangeFilters


BINANCE_BTCUSDT_FILTERS = [
    {"filterType": "PRICE_FILTER", "minPrice": "0.01000000", "maxPrice": "1000000.00000000", "tickSize": "0.01000000"},
    {"filterType": "LOT_SIZE", "minQty": "0.00001000", "maxQty": "9000.00000000", "stepSize": "0.00001000"},
    {"filterType": "MIN_NOTIONAL", "minNotional": "5.00000000", "applyToMarket": True, "avgPriceMins": 5},
    {"filterType": "PERCENT_PRICE_BY_SIDE", "bidMultiplierUp": "5", "bidMultiplierDown": "0.2", "askMultiplierUp": "5", "askMultiplierDown": "0.2", "avgPriceMins": 5},
]


class TestExchangeFiltersFromExchangeInfo:
    def test_parses_lot_size(self):
        f = ExchangeFilters.from_exchange_info(BINANCE_BTCUSDT_FILTERS)
        assert f.step_size == pytest.approx(0.00001)
        assert f.min_qty == pytest.approx(0.00001)
        assert f.max_qty == pytest.approx(9000.0)

    def test_parses_price_filter(self):
        f = ExchangeFilters.from_exchange_info(BINANCE_BTCUSDT_FILTERS)
        assert f.tick_size == pytest.approx(0.01)
        assert f.min_price == pytest.approx(0.01)

    def test_parses_min_notional(self):
        f = ExchangeFilters.from_exchange_info(BINANCE_BTCUSDT_FILTERS)
        assert f.min_notional == pytest.approx(5.0)

    def test_empty_filters_returns_defaults(self):
        f = ExchangeFilters.from_exchange_info([])
        assert f.min_notional == pytest.approx(10.0)
        assert f.step_size > 0
        assert f.tick_size > 0

    def test_default_btcusdt_sensible_values(self):
        f = ExchangeFilters.default_btcusdt()
        assert f.step_size == pytest.approx(0.00001)
        assert f.min_notional == pytest.approx(5.0)
        assert f.min_qty > 0
        assert f.max_qty > f.min_qty
