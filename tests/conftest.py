"""Shared pytest fixtures."""

from __future__ import annotations

import pytest

from btc_bot.risk.account import AccountLimits, AccountState
from btc_bot.risk.fees import FeeEstimate
from btc_bot.risk.kill_switch import KillSwitchState
from btc_bot.risk.sizing import ExchangeFilters
from btc_bot.risk.engine import RiskEngine, Signal


@pytest.fixture
def default_limits() -> AccountLimits:
    return AccountLimits(
        daily_loss_cap_pct=0.015,
        weekly_loss_cap_pct=0.04,
        max_consec_losses=3,
        cooldown_hours=4,
        max_open_positions=1,
        min_rr=1.5,
    )


@pytest.fixture
def default_account() -> AccountState:
    from datetime import date
    return AccountState(
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


@pytest.fixture
def default_filters() -> ExchangeFilters:
    return ExchangeFilters.default_btcusdt()


@pytest.fixture
def default_fees() -> FeeEstimate:
    return FeeEstimate(fee_per_side_pct=0.00075, slippage_buffer_pct=0.0005)


@pytest.fixture
def kill_switch() -> KillSwitchState:
    return KillSwitchState()


@pytest.fixture
def risk_engine(default_limits, default_fees, kill_switch) -> RiskEngine:
    return RiskEngine(
        account_limits=default_limits,
        fee_estimate=default_fees,
        kill_switch=kill_switch,
    )


@pytest.fixture
def valid_long_signal() -> Signal:
    """A valid long signal with good R:R and realistic prices."""
    return Signal(
        strategy="scalper",
        symbol="BTC/USDT",
        side="long",
        entry=50_000.0,
        stop=49_250.0,    # 1.5% stop
        target=51_125.0,  # 2.25% target → R:R = 1.5
        timeframe="5m",
        reason="test signal",
    )
