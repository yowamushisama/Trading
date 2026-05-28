"""Strategy interface. Every strategy implements on_candles() → Signal | None."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import datetime

import pandas as pd

from btc_bot.risk.engine import Signal


@dataclass
class StrategyConfig:
    name: str
    execution_tf: str   # e.g. "5m"
    confirm_tf: str     # e.g. "15m"
    regime_tf: str      # e.g. "1h"
    atr_period: int = 14
    atr_stop_k: float = 1.5
    min_rr: float = 1.5


class BaseStrategy(ABC):
    def __init__(self, config: StrategyConfig) -> None:
        self.config = config

    @abstractmethod
    def on_candles(
        self,
        exec_df: pd.DataFrame,   # execution timeframe candles
        confirm_df: pd.DataFrame,  # confirmation timeframe
        regime_df: pd.DataFrame,   # regime timeframe
    ) -> Signal | None:
        """Evaluate candles and return a Signal or None if no setup."""
        ...

    @property
    def name(self) -> str:
        return self.config.name
