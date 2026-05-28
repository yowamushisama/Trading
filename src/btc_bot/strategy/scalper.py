"""5m/15m/1H momentum scalper strategy — longs only on Spot."""

from __future__ import annotations

import pandas as pd

from btc_bot.risk.engine import Signal
from btc_bot.strategy.base import BaseStrategy, StrategyConfig
from btc_bot.strategy.indicators import atr, ema, rsi, swing_high, volume_zscore
from btc_bot.strategy.regime import classify_regime, is_long_biased


class ScalperStrategy(BaseStrategy):
    """
    1H trend gate + 15m confirmation + 5m execution trigger.
    Long entries only; short side designed but requires futures mode.
    """

    def __init__(
        self,
        atr_stop_k: float = 1.5,
        min_rr: float = 1.5,
        volume_multiplier: float = 1.3,
        breakout_lookback: int = 12,
        rsi_low: float = 45.0,
        rsi_high: float = 70.0,
    ) -> None:
        super().__init__(
            StrategyConfig(
                name="scalper",
                execution_tf="5m",
                confirm_tf="15m",
                regime_tf="1h",
                atr_stop_k=atr_stop_k,
                min_rr=min_rr,
            )
        )
        self.volume_multiplier = volume_multiplier
        self.breakout_lookback = breakout_lookback
        self.rsi_low = rsi_low
        self.rsi_high = rsi_high

    def on_candles(
        self,
        exec_df: pd.DataFrame,
        confirm_df: pd.DataFrame,
        regime_df: pd.DataFrame,
    ) -> Signal | None:
        # ── 1H regime gate ────────────────────────────────────────
        regime = classify_regime(regime_df)
        if not is_long_biased(regime):
            return None

        # ── 15m confirmation ──────────────────────────────────────
        if len(confirm_df) < 60:
            return None
        close_15 = confirm_df["close"]
        ema20_15 = ema(close_15, 20)
        ema50_15 = ema(close_15, 50)
        rsi_15 = rsi(close_15, 14)
        vol_z_15 = volume_zscore(confirm_df["volume"], 20)

        if float(ema20_15.iloc[-1]) <= float(ema50_15.iloc[-1]):
            return None
        rsi_val = float(rsi_15.iloc[-1])
        if not (self.rsi_low <= rsi_val <= self.rsi_high):
            return None
        if float(vol_z_15.iloc[-1]) <= 0:
            return None

        # ── 5m execution trigger ──────────────────────────────────
        if len(exec_df) < 30:
            return None

        close_5 = exec_df["close"]
        vol_5 = exec_df["volume"]
        atr_5 = atr(exec_df, 14)
        ema20_5 = ema(close_5, 20)
        vol_avg = vol_5.rolling(20).mean()

        last = exec_df.iloc[-1]
        prev_high = swing_high(exec_df, self.breakout_lookback).iloc[-2]

        current_close = float(close_5.iloc[-1])
        current_vol = float(vol_5.iloc[-1])
        avg_vol = float(vol_avg.iloc[-1])
        atr_val = float(atr_5.iloc[-1])
        ema20_val = float(ema20_5.iloc[-1])

        breakout = (
            current_close > float(prev_high)
            and current_vol >= self.volume_multiplier * avg_vol
        )
        pullback = (
            current_close > ema20_val
            and float(exec_df["low"].iloc[-1]) <= ema20_val * 1.001
            and current_close > float(exec_df["open"].iloc[-1])  # bullish candle
        )

        if not (breakout or pullback):
            return None

        entry = current_close
        stop = entry - self.config.atr_stop_k * atr_val
        stop_dist = entry - stop
        target = entry + stop_dist * self.config.min_rr

        return Signal(
            strategy=self.name,
            symbol="BTC/USDT",
            side="long",
            entry=entry,
            stop=stop,
            target=target,
            timeframe=self.config.execution_tf,
            reason=f"{'breakout' if breakout else 'pullback'} | regime={regime.value} | RSI={rsi_val:.1f}",
        )
