"""Tests for the kill switch."""

from __future__ import annotations

import time
from datetime import datetime, timezone

import pytest
from btc_bot.risk.kill_switch import KillReason, KillSwitchState


class TestKillSwitchAPIErrors:
    def test_three_errors_trip_switch(self):
        ks = KillSwitchState(api_error_limit=3, api_error_window_seconds=60)
        ks.record_api_error()
        ks.record_api_error()
        assert not ks.active
        ks.record_api_error()
        assert ks.active
        assert ks.reason == KillReason.api_errors

    def test_errors_outside_window_reset_count(self):
        ks = KillSwitchState(api_error_limit=3, api_error_window_seconds=1)
        ks.record_api_error()
        ks.record_api_error()
        # Simulate window expiry by backdating the start
        from datetime import timedelta
        ks.api_error_window_start -= timedelta(seconds=2)
        ks.record_api_error()  # Should reset count to 1, not trip
        assert not ks.active
        assert ks.api_error_count == 1


class TestKillSwitchOrderRejects:
    def test_three_rejects_trip_switch(self):
        ks = KillSwitchState(order_reject_limit=3)
        ks.record_order_rejection()
        ks.record_order_rejection()
        assert not ks.active
        ks.record_order_rejection()
        assert ks.active
        assert ks.reason == KillReason.order_rejections

    def test_success_resets_reject_count(self):
        ks = KillSwitchState(order_reject_limit=3)
        ks.record_order_rejection()
        ks.record_order_rejection()
        ks.record_order_success()
        assert ks.consecutive_order_rejects == 0
        assert not ks.active


class TestKillSwitchMissingCandles:
    def test_two_missing_candles_trip_switch(self):
        ks = KillSwitchState(missing_candle_limit=2)
        ks.record_missing_candle()
        assert not ks.active
        ks.record_missing_candle()
        assert ks.active
        assert ks.reason == KillReason.missing_candles


class TestKillSwitchVolatility:
    def test_atr_spike_trips_switch(self):
        ks = KillSwitchState(atr_spike_multiplier=4.0)
        ks.check_volatility(current_atr=5000, median_atr_30d=1000)
        assert ks.active
        assert ks.reason == KillReason.volatility_spike

    def test_normal_atr_no_trip(self):
        ks = KillSwitchState(atr_spike_multiplier=4.0)
        ks.check_volatility(current_atr=3999, median_atr_30d=1000)
        assert not ks.active

    def test_zero_median_no_crash(self):
        ks = KillSwitchState()
        ks.check_volatility(current_atr=9999, median_atr_30d=0)
        assert not ks.active  # division guard


class TestKillSwitchPositionMismatch:
    def test_mismatch_trips_switch(self):
        ks = KillSwitchState()
        ks.check_position_mismatch(local_qty=0.1, exchange_qty=0.0)
        assert ks.active
        assert ks.reason == KillReason.position_mismatch

    def test_within_tolerance_no_trip(self):
        ks = KillSwitchState()
        ks.check_position_mismatch(local_qty=0.1, exchange_qty=0.10005, tolerance=0.001)
        assert not ks.active


class TestKillSwitchReset:
    def test_reset_clears_state(self):
        ks = KillSwitchState()
        ks.trip(KillReason.manual_halt)
        assert ks.active
        ks.reset()
        assert not ks.active
        assert ks.reason is None
        assert ks.api_error_count == 0
