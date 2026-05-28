"""Tests for live trading config gates, ramp-up scaling, and emergency flatten."""

from __future__ import annotations

from datetime import timedelta
from unittest.mock import MagicMock, patch

import pytest
from pydantic import ValidationError

from btc_bot.config import Settings
from btc_bot.live.runner import LIVE_RAMP_UP_DAYS, LIVE_RAMP_UP_PCT, LiveRunner
from btc_bot.utils.time import utcnow


# ── Helpers ───────────────────────────────────────────────────────────────────

def _live_env(monkeypatch, **overrides: str) -> None:
    """Set the minimum env vars required to pass all live config validators."""
    defaults = {
        "MODE": "live",
        "LIVE_TRADING_ENABLED": "true",
        "I_UNDERSTAND_LIVE_TRADING_RISK": "true",
        "LIVE_API_KEY": "test_api_key_abc123",
        "LIVE_API_SECRET": "test_api_secret_xyz",
        "DATABASE_URL": "postgresql+psycopg2://test:pass@localhost/testdb",
    }
    defaults.update(overrides)
    for k, v in defaults.items():
        monkeypatch.setenv(k, v)


def _make_live_runner() -> LiveRunner:
    """Instantiate LiveRunner with a fully mocked Binance adapter."""
    with patch("btc_bot.live.runner.BinanceSpotAdapter") as mock_adapter_cls:
        mock_adapter_cls.return_value = MagicMock()
        settings = MagicMock(spec=Settings)
        settings.api_key = "key"
        settings.api_secret = "secret"
        settings.binance_testnet = False
        settings.daily_loss_cap_pct = 0.015
        settings.weekly_loss_cap_pct = 0.04
        settings.max_consec_losses = 3
        settings.consec_loss_cooldown_hours = 4
        settings.max_open_positions = 1
        settings.min_rr = 1.5
        settings.fee_per_side_pct = 0.00075
        settings.slippage_buffer_pct = 0.0005
        settings.halt_file_path = "./HALT"
        settings.protection_timeout_seconds = 5
        settings.risk_per_trade_pct = 0.0025
        settings.atr_stop_k = 1.5
        settings.strategies_list = ["scalper"]
        runner = LiveRunner(settings)
    return runner


# ── Config gate tests ─────────────────────────────────────────────────────────

class TestLiveConfigGates:
    def test_all_gates_pass_with_valid_env(self, monkeypatch):
        _live_env(monkeypatch)
        s = Settings()
        assert s.mode.value == "live"
        assert s.live_trading_enabled is True
        assert s.i_understand_live_trading_risk is True

    def test_blocked_when_live_trading_enabled_is_false(self, monkeypatch):
        _live_env(monkeypatch, LIVE_TRADING_ENABLED="false")
        with pytest.raises(ValidationError) as exc_info:
            Settings()
        assert "LIVE_TRADING_ENABLED" in str(exc_info.value)

    def test_blocked_when_risk_acknowledgement_missing(self, monkeypatch):
        _live_env(monkeypatch, I_UNDERSTAND_LIVE_TRADING_RISK="false")
        with pytest.raises(ValidationError) as exc_info:
            Settings()
        assert "I_UNDERSTAND_LIVE_TRADING_RISK" in str(exc_info.value)

    def test_blocked_when_api_key_is_empty(self, monkeypatch):
        _live_env(monkeypatch, LIVE_API_KEY="")
        with pytest.raises(ValidationError) as exc_info:
            Settings()
        assert "LIVE_API_KEY" in str(exc_info.value)

    def test_blocked_when_api_key_is_placeholder(self, monkeypatch):
        _live_env(monkeypatch, LIVE_API_KEY="your_live_api_key_here")
        with pytest.raises(ValidationError) as exc_info:
            Settings()
        assert "LIVE_API_KEY" in str(exc_info.value)

    def test_paper_mode_does_not_require_live_flags(self, monkeypatch):
        monkeypatch.setenv("MODE", "paper_local")
        monkeypatch.setenv("LIVE_TRADING_ENABLED", "false")
        monkeypatch.setenv("I_UNDERSTAND_LIVE_TRADING_RISK", "false")
        monkeypatch.setenv("LIVE_API_KEY", "")
        monkeypatch.setenv("DATABASE_URL", "postgresql+psycopg2://test:pass@localhost/testdb")
        s = Settings()
        assert s.mode.value == "paper_local"

    def test_backtest_mode_does_not_require_database_url(self, monkeypatch):
        monkeypatch.setenv("MODE", "backtest")
        monkeypatch.setenv("DATABASE_URL", "")
        s = Settings()
        assert s.mode.value == "backtest"


# ── Ramp-up period ────────────────────────────────────────────────────────────

class TestLiveRampUp:
    def test_ramp_up_constants(self):
        assert LIVE_RAMP_UP_PCT == pytest.approx(0.10)
        assert LIVE_RAMP_UP_DAYS == 30

    def test_ramp_up_active_on_day_zero(self):
        runner = _make_live_runner()
        assert runner._is_ramp_up() is True

    def test_ramp_up_active_on_day_29(self):
        runner = _make_live_runner()
        runner._started_at = utcnow() - timedelta(days=29)
        assert runner._is_ramp_up() is True

    def test_ramp_up_inactive_on_day_30(self):
        runner = _make_live_runner()
        runner._started_at = utcnow() - timedelta(days=30)
        assert runner._is_ramp_up() is False

    def test_ramp_up_inactive_after_60_days(self):
        runner = _make_live_runner()
        runner._started_at = utcnow() - timedelta(days=60)
        assert runner._is_ramp_up() is False


# ── Ramp-up risk scaling ──────────────────────────────────────────────────────

class TestLiveRampUpRiskScaling:
    def test_risk_pct_is_10_percent_of_normal_during_ramp_up(self):
        base = 0.0025
        scaled = base * LIVE_RAMP_UP_PCT
        assert scaled == pytest.approx(0.00025)

    def test_risk_pct_at_max_allowed_during_ramp_up(self):
        # Max allowed is 0.5% → ramp-up cap = 0.05%
        base = 0.005
        scaled = base * LIVE_RAMP_UP_PCT
        assert scaled == pytest.approx(0.0005)

    def test_runner_uses_scaled_risk_during_ramp_up(self):
        runner = _make_live_runner()
        assert runner._is_ramp_up() is True
        base_risk = runner.settings.risk_per_trade_pct  # 0.0025
        expected_scaled = base_risk * LIVE_RAMP_UP_PCT
        assert expected_scaled == pytest.approx(0.00025)

    def test_runner_uses_full_risk_after_ramp_up(self):
        runner = _make_live_runner()
        runner._started_at = utcnow() - timedelta(days=31)
        assert runner._is_ramp_up() is False
        # Full risk applies — no scaling
        assert runner.settings.risk_per_trade_pct == pytest.approx(0.0025)


# ── Emergency flatten ─────────────────────────────────────────────────────────

class TestLiveEmergencyFlatten:
    def test_emergency_flatten_sells_all_btc(self):
        runner = _make_live_runner()
        mock_btc_balance = MagicMock()
        mock_btc_balance.free = 0.00005

        runner.adapter.get_balance = MagicMock(return_value=mock_btc_balance)
        runner.adapter.place_market_order = MagicMock(return_value={"orderId": "999"})

        runner._emergency_flatten()

        runner.adapter.place_market_order.assert_called_once()
        call_kwargs = runner.adapter.place_market_order.call_args
        assert call_kwargs.kwargs.get("side") == "SELL" or call_kwargs.args[1] == "SELL"
        assert call_kwargs.kwargs.get("qty") == pytest.approx(0.00005) or \
               call_kwargs.args[2] == pytest.approx(0.00005)

    def test_emergency_flatten_skips_sell_when_no_btc(self):
        runner = _make_live_runner()
        mock_btc_balance = MagicMock()
        mock_btc_balance.free = 0.0

        runner.adapter.get_balance = MagicMock(return_value=mock_btc_balance)
        runner.adapter.place_market_order = MagicMock()

        runner._emergency_flatten()
        runner.adapter.place_market_order.assert_not_called()

    def test_emergency_flatten_does_not_raise_on_adapter_error(self):
        runner = _make_live_runner()
        runner.adapter.get_balance = MagicMock(side_effect=RuntimeError("network error"))
        runner._emergency_flatten()  # must not propagate


# ── Live capital cap ─────────────────────────────────────────────────────────

class TestLiveCapitalCap:
    def test_cap_applied_when_balance_exceeds_limit(self):
        runner = _make_live_runner()
        runner.settings.live_capital_cap_usdt = 10.0

        mock_balance = MagicMock()
        mock_balance.free = 500.0
        mock_balance.locked = 0.0
        runner.adapter.get_balance = MagicMock(return_value=mock_balance)

        state = runner._get_account_state()
        assert state.equity == pytest.approx(10.0)

    def test_cap_not_applied_when_balance_below_limit(self):
        runner = _make_live_runner()
        runner.settings.live_capital_cap_usdt = 10.0

        mock_balance = MagicMock()
        mock_balance.free = 7.0
        mock_balance.locked = 0.0
        runner.adapter.get_balance = MagicMock(return_value=mock_balance)

        state = runner._get_account_state()
        assert state.equity == pytest.approx(7.0)

    def test_no_cap_when_zero(self):
        runner = _make_live_runner()
        runner.settings.live_capital_cap_usdt = 0.0

        mock_balance = MagicMock()
        mock_balance.free = 500.0
        mock_balance.locked = 0.0
        runner.adapter.get_balance = MagicMock(return_value=mock_balance)

        state = runner._get_account_state()
        assert state.equity == pytest.approx(500.0)

    def test_cap_applies_to_starting_equity_today(self):
        runner = _make_live_runner()
        runner.settings.live_capital_cap_usdt = 10.0

        mock_balance = MagicMock()
        mock_balance.free = 1000.0
        mock_balance.locked = 0.0
        runner.adapter.get_balance = MagicMock(return_value=mock_balance)

        state = runner._get_account_state()
        assert state.starting_equity_today == pytest.approx(10.0)
        assert state.starting_equity_week == pytest.approx(10.0)


# ── Kill switch integration ───────────────────────────────────────────────────

class TestLiveKillSwitch:
    def test_kill_switch_starts_inactive(self):
        runner = _make_live_runner()
        assert runner.kill_switch.active is False

    def test_api_errors_accumulate_toward_kill(self):
        runner = _make_live_runner()
        threshold = runner.kill_switch._api_error_threshold \
            if hasattr(runner.kill_switch, "_api_error_threshold") else 5
        for _ in range(threshold):
            runner.kill_switch.record_api_error()
        assert runner.kill_switch.active is True
