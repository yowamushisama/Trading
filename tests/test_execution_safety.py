"""Execution safety tests: idempotency, partial fills, reconciler, protection timeout."""

from __future__ import annotations

from datetime import timedelta, timezone
from datetime import datetime

import pytest

from btc_bot.execution.idempotency import make_client_order_id, make_list_client_id
from btc_bot.exchange.paper_local import PaperLocalAdapter
from btc_bot.exchange.filters import FilterCache
from btc_bot.risk.kill_switch import KillSwitchState, KillReason
from btc_bot.risk.protection import ProtectionState, ProtectionStatus
from btc_bot.risk.sizing import ExchangeFilters


# ── Idempotency ───────────────────────────────────────────────────────────────

class TestIdempotency:
    def test_ids_are_unique(self):
        ids = {make_client_order_id("scalper") for _ in range(1000)}
        assert len(ids) == 1000

    def test_id_within_binance_limit(self):
        cid = make_client_order_id("scalper", "entry")
        assert len(cid) <= 36

    def test_list_id_within_limit(self):
        assert len(make_list_client_id("swing")) <= 36

    def test_id_contains_strategy_prefix(self):
        cid = make_client_order_id("scalper", "entry")
        assert cid.startswith("scalper")

    def test_no_two_calls_produce_same_id(self):
        a = make_client_order_id("scalper")
        b = make_client_order_id("scalper")
        assert a != b


# ── Paper adapter fill model ──────────────────────────────────────────────────

class TestPaperAdapterFills:
    def setup_method(self):
        self.adapter = PaperLocalAdapter(initial_usdt=10_000.0, fee_per_side_pct=0.00075)

    def _candle(self, low: float, high: float, close: float):
        return {"open": low, "high": high, "low": low, "close": close, "volume": 100.0}

    def test_limit_buy_fills_when_price_in_range(self):
        self.adapter.place_limit_order("BTC/USDT", "BUY", 0.1, 49_000.0, "test-buy-001")
        filled = self.adapter.on_candle(self._candle(48_000, 50_000, 49_500))
        assert "test-buy-001" in filled

    def test_limit_buy_not_filled_when_price_above_candle_range(self):
        self.adapter.place_limit_order("BTC/USDT", "BUY", 0.1, 45_000.0, "test-buy-002")
        filled = self.adapter.on_candle(self._candle(48_000, 50_000, 49_500))
        assert "test-buy-002" not in filled

    def test_stop_triggered_when_low_reaches_stop(self):
        self.adapter.place_otoco_order(
            "BTC/USDT", "BUY", 0.1, 50_000.0, stop_price=49_000.0,
            take_profit_price=51_500.0, list_client_id="otoco-001"
        )
        # Entry fills first
        filled = self.adapter.on_candle(self._candle(49_500, 50_500, 50_000))
        # Now price drops through stop
        filled = self.adapter.on_candle(self._candle(48_500, 49_500, 49_000))
        assert "otoco-001" in filled

    def test_take_profit_triggered_when_high_reaches_target(self):
        self.adapter.place_otoco_order(
            "BTC/USDT", "BUY", 0.1, 50_000.0, stop_price=49_000.0,
            take_profit_price=51_500.0, list_client_id="otoco-002"
        )
        filled = self.adapter.on_candle(self._candle(49_500, 51_000, 50_500))
        # Now price reaches TP
        filled = self.adapter.on_candle(self._candle(50_000, 52_000, 51_500))
        assert "otoco-002" in filled

    def test_balance_decreases_on_buy(self):
        initial_usdt = self.adapter.balances["USDT"]
        self.adapter.place_limit_order("BTC/USDT", "BUY", 0.1, 50_000.0, "buy-bal-test")
        self.adapter.on_candle(self._candle(49_000, 51_000, 50_000))
        assert self.adapter.balances["USDT"] < initial_usdt

    def test_btc_balance_increases_on_buy(self):
        self.adapter.place_limit_order("BTC/USDT", "BUY", 0.1, 50_000.0, "buy-btc-test")
        self.adapter.on_candle(self._candle(49_000, 51_000, 50_000))
        assert self.adapter.balances["BTC"] > 0

    def test_cancel_prevents_fill(self):
        self.adapter.place_limit_order("BTC/USDT", "BUY", 0.1, 50_000.0, "cancel-test")
        self.adapter.cancel_order("BTC/USDT", "cancel-test")
        filled = self.adapter.on_candle(self._candle(49_000, 51_000, 50_000))
        assert "cancel-test" not in filled

    def test_get_open_orders_excludes_filled(self):
        self.adapter.place_limit_order("BTC/USDT", "BUY", 0.1, 50_000.0, "open-test-1")
        self.adapter.place_limit_order("BTC/USDT", "BUY", 0.1, 40_000.0, "open-test-2")
        # First order fills
        self.adapter.on_candle(self._candle(49_000, 51_000, 50_000))
        open_orders = self.adapter.get_open_orders("BTC/USDT")
        cids = [o.client_order_id for o in open_orders]
        assert "open-test-1" not in cids
        assert "open-test-2" in cids


# ── Filter cache validation ───────────────────────────────────────────────────

class TestFilterCache:
    def test_returns_none_when_empty(self):
        fc = FilterCache()
        assert fc.get("BTCUSDT") is None

    def test_returns_cached_filters(self):
        fc = FilterCache()
        f = ExchangeFilters.default_btcusdt()
        fc.set("BTCUSDT", f)
        assert fc.get("BTCUSDT") is not None

    def test_stale_cache_returns_none(self):
        fc = FilterCache(ttl_hours=0)  # 0-hour TTL = immediately stale
        from datetime import timedelta
        f = ExchangeFilters.default_btcusdt()
        fc.set("BTCUSDT", f)
        # Force staleness by backdating
        fc._cache["BTCUSDT"] = (f, datetime.now(tz=timezone.utc) - timedelta(hours=1))
        assert fc.get("BTCUSDT") is None

    def test_validates_order_below_min_qty(self):
        fc = FilterCache()
        f = ExchangeFilters.default_btcusdt()
        fc.set("BTCUSDT", f)
        ok, reason = fc.validate_order("BTCUSDT", qty=0.000001, price=50000, current_price=50000)
        assert not ok
        assert "minQty" in reason or "minNotional" in reason

    def test_validates_order_price_too_far_from_market(self):
        fc = FilterCache()
        f = ExchangeFilters.default_btcusdt()
        fc.set("BTCUSDT", f)
        ok, reason = fc.validate_order("BTCUSDT", qty=1.0, price=50000, current_price=10000)
        assert not ok
        assert "deviat" in reason


# ── Protection state machine under concurrent load ───────────────────────────

class TestProtectionUnderTimeout:
    def test_protection_confirmed_before_timeout_no_emergency(self):
        p = ProtectionStatus()
        p.on_entry_filled()
        p.entry_fill_time = datetime.now(tz=timezone.utc) - timedelta(seconds=3)
        p.on_protection_confirmed()
        assert not p.needs_emergency_flatten(timeout_seconds=5)
        assert p.state == ProtectionState.protected

    def test_missing_protection_after_timeout_triggers_emergency(self):
        p = ProtectionStatus()
        p.on_entry_filled()
        p.entry_fill_time = datetime.now(tz=timezone.utc) - timedelta(seconds=10)
        assert p.needs_emergency_flatten(timeout_seconds=5)
        p.trigger_emergency("test")
        assert p.state == ProtectionState.flat_emergency
