"""Tests for position sizing including property-based tests via Hypothesis."""

from __future__ import annotations

import pytest
from hypothesis import given, settings, assume
from hypothesis import strategies as st

from btc_bot.risk.sizing import (
    ExchangeFilters,
    SizingResult,
    calculate_position_size,
    round_step,
    round_tick,
)


BTCUSDT = ExchangeFilters.default_btcusdt()


class TestRoundStep:
    def test_rounds_down(self):
        assert round_step(0.12345, 0.001) == pytest.approx(0.123)

    def test_exact_multiple(self):
        assert round_step(0.1, 0.1) == pytest.approx(0.1)

    def test_zero_step_returns_value(self):
        assert round_step(1.23456, 0) == pytest.approx(1.23456)


class TestCalculatePositionSize:
    def test_basic_sizing(self):
        result = calculate_position_size(
            equity=10_000,
            entry=50_000,
            stop=49_000,
            risk_pct=0.0025,
            filters=BTCUSDT,
        )
        assert result.ok, result.reason
        # risk_budget = 25 USDT; stop_dist = 1000; raw_qty = 0.025
        assert result.qty == pytest.approx(0.025, abs=1e-5)

    def test_risk_never_exceeds_budget(self):
        result = calculate_position_size(
            equity=10_000, entry=50_000, stop=49_000,
            risk_pct=0.0025, filters=BTCUSDT,
        )
        assert result.ok
        assert result.risk_pct <= 0.0025 + 1e-9

    def test_stop_at_or_above_entry_rejected(self):
        result = calculate_position_size(
            equity=10_000, entry=50_000, stop=50_001,
            risk_pct=0.0025, filters=BTCUSDT,
        )
        assert not result.ok
        assert "below entry" in result.reason

    def test_zero_equity_rejected(self):
        result = calculate_position_size(
            equity=0, entry=50_000, stop=49_000,
            risk_pct=0.0025, filters=BTCUSDT,
        )
        assert not result.ok

    def test_tight_stop_rejected(self):
        result = calculate_position_size(
            equity=10_000, entry=50_000, stop=49_990,
            risk_pct=0.0025, filters=BTCUSDT,
        )
        assert not result.ok
        assert "0.1%" in result.reason

    def test_below_min_notional_rejected(self):
        # Very small equity → notional will be too small
        result = calculate_position_size(
            equity=10,
            entry=50_000,
            stop=49_000,
            risk_pct=0.0025,
            filters=BTCUSDT,
        )
        assert not result.ok
        assert "minNotional" in result.reason

    def test_exceeds_hard_cap_rejected(self):
        # Use risk_pct at limit (0.005 = 0.5%) — calculate_position_size has max_pct=0.005
        # Force actual_risk above cap by using a very tight stop that forces large qty
        filters = ExchangeFilters(
            step_size=1.0, min_qty=1.0, max_qty=100.0,
            tick_size=1.0, min_price=1.0, max_price=1_000_000.0,
            min_notional=1.0,
        )
        # Entry 1000, stop 999 (0.1%), risk_pct=0.001 → qty=10, notional=10000
        # actual_risk_pct = 10*1/10000 = 0.001 → fine
        result = calculate_position_size(
            equity=10_000, entry=1000, stop=999,
            risk_pct=0.006,  # Above 0.005 hard cap
            filters=filters,
        )
        assert not result.ok

    def test_qty_is_multiple_of_step_size(self):
        filters = ExchangeFilters(
            step_size=0.001, min_qty=0.001, max_qty=9000.0,
            tick_size=0.01, min_price=0.01, max_price=1_000_000.0,
            min_notional=5.0,
        )
        result = calculate_position_size(
            equity=10_000, entry=50_000, stop=49_000,
            risk_pct=0.0025, filters=filters,
        )
        assert result.ok
        # qty should be a multiple of 0.001
        remainder = round(result.qty % 0.001, 8)
        assert remainder == pytest.approx(0.0, abs=1e-9)


@given(
    equity=st.floats(min_value=100, max_value=10_000_000, allow_nan=False, allow_infinity=False),
    entry=st.floats(min_value=1000, max_value=200_000, allow_nan=False, allow_infinity=False),
    stop_offset_pct=st.floats(min_value=0.002, max_value=0.05, allow_nan=False),
    risk_pct=st.floats(min_value=0.0001, max_value=0.005, allow_nan=False),
)
@settings(max_examples=500)
def test_sizing_never_exceeds_risk_cap(
    equity: float, entry: float, stop_offset_pct: float, risk_pct: float
):
    stop = entry * (1 - stop_offset_pct)
    result = calculate_position_size(
        equity=equity,
        entry=entry,
        stop=stop,
        risk_pct=risk_pct,
        filters=BTCUSDT,
    )
    if result.ok:
        # Actual risk must never exceed the cap (with tiny floating point tolerance)
        assert result.risk_pct <= risk_pct + 1e-9, (
            f"risk_pct overshoot: actual={result.risk_pct} budget={risk_pct}"
        )
        # Qty must be positive
        assert result.qty > 0
        # Notional must be positive
        assert result.notional > 0
