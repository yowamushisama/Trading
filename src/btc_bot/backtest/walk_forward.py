"""Walk-forward testing: 6-month train / 1-month OOS, monthly roll."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta

import pandas as pd
from loguru import logger

from btc_bot.backtest.metrics import BacktestMetrics
from btc_bot.backtest.runner import BacktestConfig, BacktestRunner
from btc_bot.strategy.base import BaseStrategy


@dataclass
class WalkForwardResult:
    windows: list[tuple[datetime, datetime, BacktestMetrics]]

    @property
    def oos_profit_factors(self) -> list[float]:
        return [m.profit_factor for _, _, m in self.windows]

    @property
    def avg_oos_pf(self) -> float:
        pfs = self.oos_profit_factors
        return sum(pfs) / len(pfs) if pfs else 0.0

    @property
    def passes(self) -> bool:
        return all(pf > 1.0 for pf in self.oos_profit_factors)


def run_walk_forward(
    strategy: BaseStrategy,
    exec_df: pd.DataFrame,
    confirm_df: pd.DataFrame,
    regime_df: pd.DataFrame,
    config: BacktestConfig,
    train_months: int = 6,
    oos_months: int = 1,
) -> WalkForwardResult:
    results = []
    start = exec_df["open_time"].min()
    end = exec_df["open_time"].max()

    train_delta = timedelta(days=train_months * 30)
    oos_delta = timedelta(days=oos_months * 30)

    oos_start = start + train_delta
    while oos_start + oos_delta <= end:
        oos_end = oos_start + oos_delta

        exec_oos = exec_df[
            (exec_df["open_time"] >= oos_start) & (exec_df["open_time"] < oos_end)
        ]
        confirm_oos = confirm_df[
            (confirm_df["open_time"] >= oos_start - train_delta)
            & (confirm_df["open_time"] < oos_end)
        ]
        regime_oos = regime_df[
            (regime_df["open_time"] >= oos_start - train_delta)
            & (regime_df["open_time"] < oos_end)
        ]

        if len(exec_oos) < 100:
            oos_start += oos_delta
            continue

        runner = BacktestRunner(
            strategy=strategy,
            config=config,
            exec_df=exec_oos,
            confirm_df=confirm_oos,
            regime_df=regime_oos,
        )
        metrics = runner.run()
        results.append((oos_start, oos_end, metrics))
        logger.info(
            f"WF window {oos_start.date()} → {oos_end.date()}: {metrics.summary()}"
        )
        oos_start += oos_delta

    return WalkForwardResult(windows=results)
