"""Backtest performance metrics."""

from __future__ import annotations

import math
from dataclasses import dataclass, field

import numpy as np
import pandas as pd


@dataclass
class BacktestMetrics:
    total_trades: int = 0
    wins: int = 0
    losses: int = 0
    gross_pnl: float = 0.0
    net_pnl: float = 0.0
    total_fees: float = 0.0
    total_slippage: float = 0.0
    r_multiples: list[float] = field(default_factory=list)
    equity_curve: list[float] = field(default_factory=list)
    drawdowns: list[float] = field(default_factory=list)
    unrealistic_fill_pnl: float = 0.0  # PnL from fills > 10% candle volume

    @property
    def win_rate(self) -> float:
        return self.wins / self.total_trades if self.total_trades else 0.0

    @property
    def profit_factor(self) -> float:
        gross_wins = sum(r for r in self.r_multiples if r > 0)
        gross_losses = abs(sum(r for r in self.r_multiples if r < 0))
        return gross_wins / gross_losses if gross_losses else float("inf")

    @property
    def max_drawdown(self) -> float:
        if not self.equity_curve:
            return 0.0
        peak = self.equity_curve[0]
        max_dd = 0.0
        for eq in self.equity_curve:
            peak = max(peak, eq)
            dd = (peak - eq) / peak if peak > 0 else 0
            max_dd = max(max_dd, dd)
        return max_dd

    @property
    def avg_r(self) -> float:
        return float(np.mean(self.r_multiples)) if self.r_multiples else 0.0

    @property
    def expectancy(self) -> float:
        """Average R per trade."""
        return self.avg_r

    @property
    def longest_losing_streak(self) -> int:
        current = max_streak = 0
        for r in self.r_multiples:
            if r < 0:
                current += 1
                max_streak = max(max_streak, current)
            else:
                current = 0
        return max_streak

    @property
    def sharpe(self) -> float:
        if len(self.r_multiples) < 2:
            return 0.0
        arr = np.array(self.r_multiples)
        std = float(np.std(arr, ddof=1))
        return float(np.mean(arr)) / std if std > 0 else 0.0

    @property
    def sortino(self) -> float:
        if len(self.r_multiples) < 2:
            return 0.0
        arr = np.array(self.r_multiples)
        downside = arr[arr < 0]
        if len(downside) == 0:
            return float("inf")
        downside_std = float(np.std(downside, ddof=1))
        return float(np.mean(arr)) / downside_std if downside_std > 0 else 0.0

    @property
    def fee_as_pct_of_gross(self) -> float:
        gross = abs(self.gross_pnl)
        return self.total_fees / gross if gross > 0 else 0.0

    @property
    def unrealistic_fill_pct_of_profit(self) -> float:
        net = self.net_pnl
        return self.unrealistic_fill_pnl / net if net > 0 else 0.0

    def passes_stress_test(
        self,
        min_pf: float = 1.2,
        max_dd: float = 0.15,
        max_losing_streak: int = 8,
        max_unrealistic_pct: float = 0.20,
    ) -> tuple[bool, list[str]]:
        failures = []
        if self.profit_factor < min_pf:
            failures.append(f"PF {self.profit_factor:.2f} < {min_pf}")
        if self.max_drawdown > max_dd:
            failures.append(f"Max DD {self.max_drawdown:.2%} > {max_dd:.2%}")
        if self.longest_losing_streak > max_losing_streak:
            failures.append(
                f"Losing streak {self.longest_losing_streak} > {max_losing_streak}"
            )
        if self.unrealistic_fill_pct_of_profit > max_unrealistic_pct:
            failures.append(
                f"Unrealistic fills {self.unrealistic_fill_pct_of_profit:.2%} > {max_unrealistic_pct:.2%}"
            )
        return len(failures) == 0, failures

    def summary(self) -> str:
        return (
            f"Trades={self.total_trades} WR={self.win_rate:.1%} PF={self.profit_factor:.2f} "
            f"MaxDD={self.max_drawdown:.2%} AvgR={self.avg_r:.2f} "
            f"Sharpe={self.sharpe:.2f} Sortino={self.sortino:.2f} "
            f"Streak={self.longest_losing_streak} Expectancy={self.expectancy:.3f} "
            f"FeePct={self.fee_as_pct_of_gross:.2%} NetPnL={self.net_pnl:.2f}"
        )
