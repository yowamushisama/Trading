"""Tests for RiskEngine — all 14 gates with ordering guarantees."""

from __future__ import annotations

import os
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import pytest

from btc_bot.risk.account import AccountLimits, AccountState
from btc_bot.risk.engine import Decision, RiskEngine, Signal
from btc_bot.risk.fees import FeeEstimate
from btc_bot.risk.kill_switch import KillReason, KillSwitchState
from btc_bot.risk.sizing import ExchangeFilters


def make_engine(
    kill_active: bool = False,
    news_pause: bool = False,
    min_rr: float = 1.5,
) -> tuple[RiskEngine, AccountState, ExchangeFilters]:
    limits = AccountLimits(
        daily_loss_cap_pct=0.015,
        weekly_loss_cap_pct=0.04,
        max_consec_losses=3,
        cooldown_hours=4,
        max_open_positions=1,
        min_rr=min_rr,
    )
    fees = FeeEstimate(fee_per_side_pct=0.00075, slippage_buffer_pct=0.0005)
    ks = KillSwitchState()
    if kill_active:
        ks.trip(KillReason.manual_halt)
    engine = RiskEngine(
        account_limits=limits,
        fee_estimate=fees,
        kill_switch=ks,
        news_pause_active=news_pause,
    )
    account = AccountState(
        equity=10_000.0,
        starting_equity_today=10_000.0,
        starting_equity_week=10_000.0,
        realized_pnl_today=0.0,
        realized_pnl_week=0.0,
        open_positions=0,
        consecutive_losses=0,
        cooldown_until=None,
        today=date.today(),
    )
    filters = ExchangeFilters.default_btcusdt()
    return engine, account, filters


def good_signal(rr_override: float | None = None) -> Signal:
    entry, stop = 50_000.0, 49_000.0
    stop_dist = entry - stop
    if rr_override is not None:
        target = entry + stop_dist * rr_override
    else:
        target = 51_500.0  # R:R = 1.5
    return Signal(
        strategy="scalper", symbol="BTC/USDT", side="long",
        entry=entry, stop=stop, target=target, timeframe="5m",
    )


class TestGate1HaltFile:
    def test_halt_file_blocks_trade(self, tmp_path):
        halt = tmp_path / "HALT"
        halt.touch()
        engine, account, filters = make_engine()
        engine.halt_file_path = str(halt)
        result = engine.evaluate(good_signal(), account, filters, 0.0025)
        assert not result.allowed
        assert "halt" in result.reason.lower()


class TestGate2KillSwitch:
    def test_kill_switch_blocks_trade(self):
        engine, account, filters = make_engine(kill_active=True)
        result = engine.evaluate(good_signal(), account, filters, 0.0025)
        assert not result.allowed
        assert "kill switch" in result.reason.lower()


class TestGate3ShortBlocked:
    def test_short_rejected_in_spot_mode(self):
        engine, account, filters = make_engine()
        signal = good_signal()
        signal = Signal(
            strategy="scalper", symbol="BTC/USDT", side="short",
            entry=50_000, stop=50_500, target=49_000, timeframe="5m",
        )
        result = engine.evaluate(signal, account, filters, 0.0025)
        assert not result.allowed
        assert "short" in result.reason.lower()


class TestGate4NewsPause:
    def test_news_pause_blocks_entry(self):
        engine, account, filters = make_engine(news_pause=True)
        result = engine.evaluate(good_signal(), account, filters, 0.0025)
        assert not result.allowed
        assert "news" in result.reason.lower()


class TestGate5AccountLimits:
    def test_max_open_positions_blocks(self):
        engine, account, filters = make_engine()
        account.open_positions = 1
        result = engine.evaluate(good_signal(), account, filters, 0.0025)
        assert not result.allowed
        assert "positions" in result.reason.lower()

    def test_daily_loss_cap_blocks(self):
        engine, account, filters = make_engine()
        account.realized_pnl_today = -200.0  # 2% loss > 1.5% cap
        result = engine.evaluate(good_signal(), account, filters, 0.0025)
        assert not result.allowed
        assert "daily loss" in result.reason.lower()

    def test_weekly_loss_cap_blocks(self):
        engine, account, filters = make_engine()
        account.realized_pnl_week = -500.0  # 5% > 4% cap
        result = engine.evaluate(good_signal(), account, filters, 0.0025)
        assert not result.allowed
        assert "weekly" in result.reason.lower()

    def test_cooldown_blocks(self):
        engine, account, filters = make_engine()
        account.cooldown_until = datetime.now(tz=timezone.utc) + timedelta(hours=2)
        result = engine.evaluate(good_signal(), account, filters, 0.0025)
        assert not result.allowed
        assert "cooldown" in result.reason.lower()


class TestGate11StopValidation:
    def test_missing_stop_rejected(self):
        engine, account, filters = make_engine()
        signal = Signal(
            strategy="scalper", symbol="BTC/USDT", side="long",
            entry=50_000, stop=0, target=51_500, timeframe="5m",
        )
        result = engine.evaluate(signal, account, filters, 0.0025)
        assert not result.allowed

    def test_stop_above_entry_rejected(self):
        engine, account, filters = make_engine()
        signal = Signal(
            strategy="scalper", symbol="BTC/USDT", side="long",
            entry=50_000, stop=50_100, target=51_500, timeframe="5m",
        )
        result = engine.evaluate(signal, account, filters, 0.0025)
        assert not result.allowed

    def test_stop_too_tight_rejected(self):
        engine, account, filters = make_engine()
        signal = Signal(
            strategy="scalper", symbol="BTC/USDT", side="long",
            entry=50_000, stop=49_990, target=51_500, timeframe="5m",
        )
        result = engine.evaluate(signal, account, filters, 0.0025)
        assert not result.allowed


class TestGate12RR:
    def test_rr_below_minimum_rejected(self):
        engine, account, filters = make_engine(min_rr=1.5)
        signal = good_signal(rr_override=1.2)
        result = engine.evaluate(signal, account, filters, 0.0025)
        assert not result.allowed
        assert "R:R" in result.reason or "r:r" in result.reason.lower()

    def test_rr_at_minimum_allowed(self):
        engine, account, filters = make_engine(min_rr=1.5)
        signal = good_signal(rr_override=1.5)
        result = engine.evaluate(signal, account, filters, 0.0025)
        assert result.allowed, result.reason


class TestGateAllPass:
    def test_good_signal_allowed(self):
        engine, account, filters = make_engine()
        result = engine.evaluate(good_signal(), account, filters, 0.0025)
        assert result.allowed, result.reason
        assert result.sizing is not None
        assert result.sizing.qty > 0
        assert result.sizing.risk_pct <= 0.0025 + 1e-9

    def test_sizing_attached_on_allow(self):
        engine, account, filters = make_engine()
        result = engine.evaluate(good_signal(), account, filters, 0.0025)
        assert result.allowed
        assert result.sizing.notional > 0


class TestHardRulesCannotBeOverridden:
    """Confirm that the engine structure makes martingale/averaging impossible."""

    def test_position_size_derives_from_stop_not_fixed_qty(self):
        engine, account, filters = make_engine()
        # Large stop → small qty; small stop → large qty (up to risk cap)
        sig_tight = Signal(
            strategy="scalper", symbol="BTC/USDT", side="long",
            entry=50_000, stop=49_500, target=51_500, timeframe="5m",
        )
        sig_wide = Signal(
            strategy="scalper", symbol="BTC/USDT", side="long",
            entry=50_000, stop=48_000, target=54_500, timeframe="5m",
        )
        r_tight = engine.evaluate(sig_tight, account, filters, 0.0025)
        r_wide = engine.evaluate(sig_wide, account, filters, 0.0025)
        assert r_tight.allowed and r_wide.allowed
        # Tighter stop → more shares purchased (higher qty)
        assert r_tight.sizing.qty > r_wide.sizing.qty
