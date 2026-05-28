"""Tests for fee and slippage viability calculations."""

from __future__ import annotations

import pytest
from btc_bot.risk.fees import FeeEstimate


def make_fee(fee_pct: float = 0.00075, slip_pct: float = 0.0005) -> FeeEstimate:
    return FeeEstimate(fee_per_side_pct=fee_pct, slippage_buffer_pct=slip_pct)


class TestFeeEstimate:
    def test_round_trip_is_double_per_side(self):
        f = make_fee(0.001)
        assert f.round_trip_pct == pytest.approx(0.002)

    def test_total_cost_includes_slippage_both_sides(self):
        f = make_fee(0.001, 0.0005)
        assert f.total_cost_pct == pytest.approx(0.002 + 0.001)

    def test_viable_trade_accepted(self):
        f = make_fee()
        # large enough move
        ok, reason = f.is_viable(50_000, 49_000, 51_500)
        assert ok, reason

    def test_tiny_move_rejected(self):
        f = make_fee(0.001, 0.001)
        # target barely above entry — move < fees
        ok, reason = f.is_viable(50_000, 49_500, 50_010)
        assert not ok
        assert "Expected move" in reason

    def test_zero_entry_rejected(self):
        f = make_fee()
        ok, reason = f.is_viable(0, 49_000, 51_000)
        assert not ok

    def test_negative_price_rejected(self):
        f = make_fee()
        ok, reason = f.is_viable(50_000, -100, 51_000)
        assert not ok

    def test_stop_too_tight_rejected(self):
        f = make_fee(fee_pct=0.00001, slip_pct=0.00001)  # tiny fees so fee gate passes
        # stop 5 away from entry = 0.01% (< 0.1%), target 2000 away so target move is fine
        ok, reason = f.is_viable(50_000, 49_995, 52_000)
        assert not ok
        assert "tight" in reason.lower()
