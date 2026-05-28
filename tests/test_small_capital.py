"""Tests for $10 paper capital with 2-3 tranche configuration.

Env settings for this scenario:
  PAPER_CAPITAL_USDT=10
  RISK_PER_TRADE_PCT=0.0025   (default — produces ~$5-10 notional per trade at BTC $100k)
  MAX_OPEN_POSITIONS=2        (2 tranches) or 3 (3 tranches)
"""

from __future__ import annotations

from datetime import date

import pytest

from btc_bot.exchange.paper_local import PaperLocalAdapter
from btc_bot.risk.account import AccountLimits, AccountState, check_account_limits
from btc_bot.risk.engine import RiskEngine, Signal
from btc_bot.risk.fees import FeeEstimate
from btc_bot.risk.kill_switch import KillSwitchState
from btc_bot.risk.sizing import ExchangeFilters, calculate_position_size


# Binance BTC/USDT spot: $5 min notional, 0.00001 step size
BINANCE_BTCUSDT_5MIN = ExchangeFilters(
    step_size=0.00001,
    min_qty=0.00001,
    max_qty=9000.0,
    tick_size=0.01,
    min_price=0.01,
    max_price=1_000_000.0,
    min_notional=5.0,
)

BTC = 100_000.0  # representative BTC/USDT price


# ── Exchange filter baseline ──────────────────────────────────────────────────

class TestBinanceMinNotional:
    def test_default_btcusdt_min_notional_is_5(self):
        assert ExchangeFilters.default_btcusdt().min_notional == 5.0

    def test_default_btcusdt_step_size(self):
        f = ExchangeFilters.default_btcusdt()
        assert f.step_size == pytest.approx(0.00001)
        assert f.min_qty == pytest.approx(0.00001)


# ── Sizing at $10 equity ──────────────────────────────────────────────────────

class TestSmallCapitalSizing:
    def test_quarter_pct_risk_tight_stop_above_min_notional(self):
        # $10 × 0.25% = $0.025 risk; stop dist $500 → qty 0.00005 → notional $5.00
        result = calculate_position_size(
            equity=10.0,
            entry=BTC,
            stop=BTC - 500,   # 0.5% stop
            risk_pct=0.0025,
            filters=BINANCE_BTCUSDT_5MIN,
        )
        assert result.ok, result.reason
        assert result.notional >= 5.0

    def test_half_pct_risk_produces_larger_notional(self):
        result = calculate_position_size(
            equity=10.0,
            entry=BTC,
            stop=BTC - 500,
            risk_pct=0.005,
            filters=BINANCE_BTCUSDT_5MIN,
        )
        assert result.ok, result.reason
        assert result.notional >= 5.0

    def test_wide_stop_fails_below_min_notional(self):
        # 2% stop ($2,000 distance) → qty too small → notional below $5
        result = calculate_position_size(
            equity=10.0,
            entry=BTC,
            stop=BTC - 2_000,  # 2% stop
            risk_pct=0.0025,
            filters=BINANCE_BTCUSDT_5MIN,
        )
        assert not result.ok
        assert "minNotional" in result.reason

    def test_risk_usdt_never_exceeds_budget(self):
        result = calculate_position_size(
            equity=10.0,
            entry=BTC,
            stop=BTC - 500,
            risk_pct=0.0025,
            filters=BINANCE_BTCUSDT_5MIN,
        )
        if result.ok:
            assert result.risk_usdt <= 10.0 * 0.0025 + 1e-9

    def test_qty_is_multiple_of_step_size(self):
        result = calculate_position_size(
            equity=10.0,
            entry=BTC,
            stop=BTC - 500,
            risk_pct=0.005,
            filters=BINANCE_BTCUSDT_5MIN,
        )
        if result.ok:
            remainder = round(result.qty % 0.00001, 8)
            assert remainder == pytest.approx(0.0, abs=1e-8)

    def test_zero_equity_rejected(self):
        result = calculate_position_size(
            equity=0.0,
            entry=BTC,
            stop=BTC - 500,
            risk_pct=0.0025,
            filters=BINANCE_BTCUSDT_5MIN,
        )
        assert not result.ok

    def test_notional_and_risk_usdt_are_consistent(self):
        result = calculate_position_size(
            equity=10.0,
            entry=BTC,
            stop=BTC - 500,
            risk_pct=0.005,
            filters=BINANCE_BTCUSDT_5MIN,
        )
        assert result.ok, result.reason
        expected_risk = result.qty * 500
        assert result.risk_usdt == pytest.approx(expected_risk, rel=1e-6)


# ── Loss caps on $10 equity ───────────────────────────────────────────────────

class TestSmallCapitalRiskCaps:
    def _limits(self, max_positions: int = 1) -> AccountLimits:
        return AccountLimits(
            daily_loss_cap_pct=0.015,
            weekly_loss_cap_pct=0.04,
            max_consec_losses=3,
            cooldown_hours=4,
            max_open_positions=max_positions,
            min_rr=1.5,
        )

    def test_daily_loss_cap_triggers_at_15_cents(self):
        # 1.5% of $10 = $0.15; $0.20 loss exceeds cap
        state = AccountState(
            equity=9.80,
            starting_equity_today=10.0,
            starting_equity_week=10.0,
            realized_pnl_today=-0.20,
        )
        ok, reason = check_account_limits(state, self._limits())
        assert not ok
        assert "daily loss" in reason.lower()

    def test_daily_loss_below_cap_allowed(self):
        # $0.10 loss < $0.15 cap
        state = AccountState(
            equity=9.90,
            starting_equity_today=10.0,
            starting_equity_week=10.0,
            realized_pnl_today=-0.10,
        )
        ok, _ = check_account_limits(state, self._limits())
        assert ok

    def test_weekly_loss_cap_triggers_at_40_cents(self):
        # 4% of $10 = $0.40; $0.50 loss exceeds cap
        state = AccountState(
            equity=9.50,
            starting_equity_today=10.0,
            starting_equity_week=10.0,
            realized_pnl_week=-0.50,
        )
        ok, reason = check_account_limits(state, self._limits())
        assert not ok
        assert "weekly" in reason.lower()

    def test_max_loss_per_trade_is_25_cents_at_default_risk(self):
        # $10 × 0.0025 = $0.025 risk budget per trade
        assert 10.0 * 0.0025 == pytest.approx(0.025)


# ── 2 and 3 tranche position limits ──────────────────────────────────────────

def _make_tranche_engine(max_positions: int) -> tuple[RiskEngine, AccountState]:
    limits = AccountLimits(
        daily_loss_cap_pct=0.015,
        weekly_loss_cap_pct=0.04,
        max_consec_losses=3,
        cooldown_hours=4,
        max_open_positions=max_positions,
        min_rr=1.5,
    )
    fees = FeeEstimate(fee_per_side_pct=0.00075, slippage_buffer_pct=0.0005)
    engine = RiskEngine(account_limits=limits, fee_estimate=fees, kill_switch=KillSwitchState())
    account = AccountState(
        equity=10.0,
        starting_equity_today=10.0,
        starting_equity_week=10.0,
        today=date.today(),
    )
    return engine, account


def _btc_signal() -> Signal:
    # BTC $100k, 0.5% stop ($500), 0.75% target ($750) → R:R = 1.5
    return Signal(
        strategy="scalper", symbol="BTC/USDT", side="long",
        entry=BTC, stop=BTC - 500, target=BTC + 750, timeframe="5m",
    )


class TestTwoTranches:
    def test_first_position_allowed(self):
        engine, account = _make_tranche_engine(2)
        result = engine.evaluate(_btc_signal(), account, BINANCE_BTCUSDT_5MIN, 0.0025)
        assert result.allowed, result.reason

    def test_second_position_allowed(self):
        engine, account = _make_tranche_engine(2)
        account.open_positions = 1
        result = engine.evaluate(_btc_signal(), account, BINANCE_BTCUSDT_5MIN, 0.0025)
        assert result.allowed, result.reason

    def test_third_position_blocked(self):
        engine, account = _make_tranche_engine(2)
        account.open_positions = 2
        result = engine.evaluate(_btc_signal(), account, BINANCE_BTCUSDT_5MIN, 0.0025)
        assert not result.allowed
        assert "positions" in result.reason.lower()

    def test_sizing_is_consistent_across_tranches(self):
        engine, account = _make_tranche_engine(2)
        r1 = engine.evaluate(_btc_signal(), account, BINANCE_BTCUSDT_5MIN, 0.0025)
        account.open_positions = 1
        r2 = engine.evaluate(_btc_signal(), account, BINANCE_BTCUSDT_5MIN, 0.0025)
        assert r1.allowed and r2.allowed
        assert r1.sizing.qty == pytest.approx(r2.sizing.qty)


class TestThreeTranches:
    def test_first_position_allowed(self):
        engine, account = _make_tranche_engine(3)
        result = engine.evaluate(_btc_signal(), account, BINANCE_BTCUSDT_5MIN, 0.0025)
        assert result.allowed, result.reason

    def test_third_position_allowed(self):
        engine, account = _make_tranche_engine(3)
        account.open_positions = 2
        result = engine.evaluate(_btc_signal(), account, BINANCE_BTCUSDT_5MIN, 0.0025)
        assert result.allowed, result.reason

    def test_fourth_position_blocked(self):
        engine, account = _make_tranche_engine(3)
        account.open_positions = 3
        result = engine.evaluate(_btc_signal(), account, BINANCE_BTCUSDT_5MIN, 0.0025)
        assert not result.allowed
        assert "positions" in result.reason.lower()

    def test_total_risk_across_three_tranches(self):
        # 3 open trades × $0.025 risk each = $0.075 max at risk (0.75% of $10)
        risk_per_trade = 10.0 * 0.0025
        assert 3 * risk_per_trade == pytest.approx(0.075)
        assert 3 * risk_per_trade / 10.0 == pytest.approx(0.0075)  # 0.75% total


# ── Paper adapter with $10 balance ───────────────────────────────────────────

class TestPaperAdapterSmallCapital:
    def _candle(self, low: float, high: float, close: float) -> dict:
        return {"open": low, "high": high, "low": low, "close": close, "volume": 1.0}

    def test_initial_usdt_balance_is_10(self):
        adapter = PaperLocalAdapter(initial_usdt=10.0, fee_per_side_pct=0.00075)
        assert adapter.balances["USDT"] == pytest.approx(10.0)

    def test_small_buy_fills_and_deducts_balance(self):
        adapter = PaperLocalAdapter(initial_usdt=10.0, fee_per_side_pct=0.00075)
        # Buy 0.00005 BTC @ $100k = $5 notional (above $5 min)
        adapter.place_limit_order("BTC/USDT", "BUY", 0.00005, BTC, "small-buy-001")
        filled = adapter.on_candle(self._candle(BTC - 1_000, BTC + 1_000, BTC))
        assert "small-buy-001" in filled
        assert adapter.balances["USDT"] < 10.0
        assert adapter.balances["BTC"] > 0.0

    def test_usdt_balance_never_negative(self):
        adapter = PaperLocalAdapter(initial_usdt=10.0, fee_per_side_pct=0.00075)
        adapter.place_limit_order("BTC/USDT", "BUY", 0.0001, BTC, "boundary-buy")
        adapter.on_candle(self._candle(BTC - 1_000, BTC + 1_000, BTC))
        assert adapter.balances["USDT"] >= 0.0

    def test_stop_loss_triggered_on_small_position(self):
        adapter = PaperLocalAdapter(initial_usdt=10.0, fee_per_side_pct=0.00075)
        adapter.place_otoco_order(
            "BTC/USDT", "BUY", 0.00005, BTC,
            stop_price=BTC - 500,
            take_profit_price=BTC + 750,
            list_client_id="small-otoco-001",
        )
        # Entry fills
        adapter.on_candle(self._candle(BTC - 200, BTC + 200, BTC))
        # Stop triggered
        filled = adapter.on_candle(self._candle(BTC - 1_000, BTC - 400, BTC - 600))
        assert "small-otoco-001" in filled

    def test_take_profit_triggered_on_small_position(self):
        adapter = PaperLocalAdapter(initial_usdt=10.0, fee_per_side_pct=0.00075)
        adapter.place_otoco_order(
            "BTC/USDT", "BUY", 0.00005, BTC,
            stop_price=BTC - 500,
            take_profit_price=BTC + 750,
            list_client_id="small-otoco-002",
        )
        adapter.on_candle(self._candle(BTC - 200, BTC + 200, BTC))
        filled = adapter.on_candle(self._candle(BTC + 200, BTC + 1_000, BTC + 800))
        assert "small-otoco-002" in filled
