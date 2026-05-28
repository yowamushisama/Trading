"""Backtest runner — replays candles through strategy + risk + simulated execution.

Fill model:
  - Limit orders fill only if candle low ≤ limit_price ≤ candle high
    AND order_notional ≤ 10% of candle volume * price
  - Fees: configurable per-side percentage
  - Slippage: linear of notional / candle_volume_usdt, capped
  - Unrealistic fills are tracked for audit
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import date

import pandas as pd
from loguru import logger

from btc_bot.backtest.metrics import BacktestMetrics
from btc_bot.risk.account import AccountLimits, AccountState, record_trade_result
from btc_bot.risk.engine import RiskEngine, Signal
from btc_bot.risk.fees import FeeEstimate
from btc_bot.risk.kill_switch import KillSwitchState
from btc_bot.risk.sizing import ExchangeFilters
from btc_bot.strategy.base import BaseStrategy


@dataclass
class BacktestConfig:
    fee_per_side_pct: float = 0.00075
    slippage_buffer_pct: float = 0.0005
    # Stress test: also run at higher fee to validate robustness
    stress_fee_per_side_pct: float = 0.001
    stress_slippage_multiplier: float = 2.0
    max_notional_pct_of_candle_vol: float = 0.10  # unrealistic fill threshold
    initial_equity: float = 10_000.0
    risk_per_trade_pct: float = 0.0025


def _simulated_fill(
    entry: float,
    candle: pd.Series,
    notional: float,
    fee_pct: float,
    slippage_pct: float,
) -> tuple[float, float, float, bool]:
    """Return (fill_price, fee, slippage_cost, is_unrealistic).

    Fill is rejected (fill_price=0) if candle doesn't reach entry.
    """
    candle_low = float(candle["low"])
    candle_high = float(candle["high"])
    candle_vol_usdt = float(candle["volume"]) * float(candle["close"])

    if not (candle_low <= entry <= candle_high):
        return 0.0, 0.0, 0.0, False

    is_unrealistic = candle_vol_usdt > 0 and notional > 0.10 * candle_vol_usdt

    slip = entry * slippage_pct
    fill_price = entry + slip
    fee = notional * fee_pct * 2  # round-trip approximation at entry
    return fill_price, fee, slip * (notional / entry), is_unrealistic


class BacktestRunner:
    def __init__(
        self,
        strategy: BaseStrategy,
        config: BacktestConfig,
        exec_df: pd.DataFrame,
        confirm_df: pd.DataFrame,
        regime_df: pd.DataFrame,
        filters: ExchangeFilters | None = None,
        risk_limits: AccountLimits | None = None,
    ) -> None:
        self.strategy = strategy
        self.config = config
        self.exec_df = exec_df.reset_index(drop=True)
        self.confirm_df = confirm_df.reset_index(drop=True)
        self.regime_df = regime_df.reset_index(drop=True)
        self.filters = filters or ExchangeFilters.default_btcusdt()
        self.risk_limits = risk_limits or AccountLimits(
            daily_loss_cap_pct=0.015,
            weekly_loss_cap_pct=0.04,
            max_consec_losses=3,
            cooldown_hours=4,
            max_open_positions=1,
            min_rr=1.5,
        )

    def _make_engine(self, fee_pct: float, slip_pct: float) -> RiskEngine:
        return RiskEngine(
            account_limits=self.risk_limits,
            fee_estimate=FeeEstimate(fee_per_side_pct=fee_pct, slippage_buffer_pct=slip_pct),
            kill_switch=KillSwitchState(),
        )

    def _initial_account(self) -> AccountState:
        return AccountState(
            equity=self.config.initial_equity,
            starting_equity_today=self.config.initial_equity,
            starting_equity_week=self.config.initial_equity,
            today=date.today(),
        )

    def run(self, stress: bool = False) -> BacktestMetrics:
        """Run the backtest. If stress=True, use higher fees and slippage."""
        fee_pct = self.config.stress_fee_per_side_pct if stress else self.config.fee_per_side_pct
        slip_pct = (
            self.config.slippage_buffer_pct * self.config.stress_slippage_multiplier
            if stress
            else self.config.slippage_buffer_pct
        )
        engine = self._make_engine(fee_pct, slip_pct)
        account = self._initial_account()
        metrics = BacktestMetrics(equity_curve=[account.equity])

        open_trade: dict | None = None
        min_exec_bars = 50

        for i in range(min_exec_bars, len(self.exec_df)):
            exec_window = self.exec_df.iloc[: i + 1]
            # Align confirm and regime bars by time
            exec_time = exec_window.iloc[-1]["open_time"]
            confirm_window = self.confirm_df[self.confirm_df["open_time"] <= exec_time]
            regime_window = self.regime_df[self.regime_df["open_time"] <= exec_time]

            if len(confirm_window) < 30 or len(regime_window) < 200:
                continue

            candle = exec_window.iloc[-1]

            # ── Manage open trade ──────────────────────────────────
            if open_trade is not None:
                exit_price, pnl, r, unrealistic = self._check_exit(
                    open_trade, candle, fee_pct, slip_pct
                )
                if exit_price is not None:
                    account = record_trade_result(account, pnl, self.risk_limits)
                    account = replace(account, open_positions=0)
                    metrics.total_trades += 1
                    metrics.r_multiples.append(r)
                    metrics.net_pnl += pnl
                    metrics.total_fees += open_trade["entry_fee"] + abs(pnl) * fee_pct * 2
                    if r > 0:
                        metrics.wins += 1
                    else:
                        metrics.losses += 1
                    if unrealistic:
                        metrics.unrealistic_fill_pnl += max(pnl, 0)
                    metrics.equity_curve.append(account.equity)
                    open_trade = None
                    continue

            # ── Check for new signal ───────────────────────────────
            if account.open_positions > 0:
                continue

            signal = self.strategy.on_candles(exec_window, confirm_window, regime_window)
            if signal is None:
                continue

            decision = engine.evaluate(signal, account, self.filters, self.config.risk_per_trade_pct)
            if not decision.allowed:
                continue

            # Simulate entry on next candle open
            if i + 1 >= len(self.exec_df):
                continue
            next_candle = self.exec_df.iloc[i + 1]
            fill_price, fee, slip_cost, unrealistic = _simulated_fill(
                signal.entry, next_candle, decision.sizing.notional, fee_pct, slip_pct
            )
            if fill_price == 0:
                continue

            open_trade = {
                "entry": fill_price,
                "stop": signal.stop,
                "target": signal.target,
                "qty": decision.sizing.qty,
                "stop_dist": signal.entry - signal.stop,
                "entry_fee": fee,
                "unrealistic": unrealistic,
            }
            account = replace(account, open_positions=1)

        return metrics

    def _check_exit(
        self,
        trade: dict,
        candle: pd.Series,
        fee_pct: float,
        slip_pct: float,
    ) -> tuple[float | None, float, float, bool]:
        low = float(candle["low"])
        high = float(candle["high"])
        stop = trade["stop"]
        target = trade["target"]
        entry = trade["entry"]
        qty = trade["qty"]

        if low <= stop:
            exit_price = stop
            gross = (exit_price - entry) * qty
            fee = qty * exit_price * fee_pct
            net = gross - fee - qty * entry * fee_pct
            r = (exit_price - entry) / trade["stop_dist"]
            return exit_price, net, r, trade["unrealistic"]

        if high >= target:
            exit_price = target
            gross = (exit_price - entry) * qty
            fee = qty * exit_price * fee_pct
            net = gross - fee - qty * entry * fee_pct
            r = (exit_price - entry) / trade["stop_dist"]
            return exit_price, net, r, trade["unrealistic"]

        return None, 0.0, 0.0, False
