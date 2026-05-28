"""4H/1D/1W swing strategy — longs only on Spot. Shorts designed but disabled."""

from __future__ import annotations

import pandas as pd

from btc_bot.risk.engine import Signal
from btc_bot.strategy.base import BaseStrategy, StrategyConfig
from btc_bot.strategy.indicators import atr, ema, rsi, swing_low


class SwingStrategy(BaseStrategy):
    """
    1W trend filter + 1D confirmation + 4H execution.
    Targets larger moves (2R+) with structural trailing stops.
    """

    def __init__(
        self,
        atr_stop_k: float = 1.5,
        min_rr: float = 2.0,
        rsi_min: float = 50.0,
    ) -> None:
        super().__init__(
            StrategyConfig(
                name="swing",
                execution_tf="4h",
                confirm_tf="1d",
                regime_tf="1w",
                atr_stop_k=atr_stop_k,
                min_rr=min_rr,
            )
        )
        self.rsi_min = rsi_min

    def on_candles(
        self,
        exec_df: pd.DataFrame,
        confirm_df: pd.DataFrame,
        regime_df: pd.DataFrame,
    ) -> Signal | None:
        # ── 1W trend gate: close > EMA(50, weekly) ────────────────
        if len(regime_df) < 60:
            return None
        ema50_weekly = ema(regime_df["close"], 50)
        if float(regime_df["close"].iloc[-1]) <= float(ema50_weekly.iloc[-1]):
            return None

        # ── 1D confirmation ───────────────────────────────────────
        if len(confirm_df) < 60:
            return None
        close_1d = confirm_df["close"]
        ema20_1d = ema(close_1d, 20)
        ema50_1d = ema(close_1d, 50)
        rsi_1d = rsi(close_1d, 14)
        atr_1d = atr(confirm_df, 14)

        last_close_1d = float(close_1d.iloc[-1])
        ema20_1d_val = float(ema20_1d.iloc[-1])
        ema50_1d_val = float(ema50_1d.iloc[-1])
        rsi_1d_val = float(rsi_1d.iloc[-1])
        atr_1d_val = float(atr_1d.iloc[-1])

        if ema20_1d_val <= ema50_1d_val:
            return None
        if rsi_1d_val < self.rsi_min:
            return None
        # Not overextended: close not > 2*ATR above EMA20
        if last_close_1d > ema20_1d_val + 2 * atr_1d_val:
            return None

        # ── 4H execution trigger ──────────────────────────────────
        if len(exec_df) < 30:
            return None
        close_4h = exec_df["close"]
        ema20_4h = ema(close_4h, 20)
        atr_4h = atr(exec_df, 14)

        current_close = float(close_4h.iloc[-1])
        current_low = float(exec_df["low"].iloc[-1])
        current_open = float(exec_df["open"].iloc[-1])
        ema20_4h_val = float(ema20_4h.iloc[-1])
        atr_4h_val = float(atr_4h.iloc[-1])

        # Pullback to EMA20 with bullish reversal candle
        pullback_to_ema = current_low <= ema20_4h_val * 1.002
        bullish_candle = current_close > current_open
        if not (pullback_to_ema and bullish_candle):
            return None

        # Volume confirmation
        vol_avg = exec_df["volume"].rolling(20).mean().iloc[-1]
        if float(exec_df["volume"].iloc[-1]) < vol_avg:
            return None

        entry = current_close
        swing_low_val = float(swing_low(exec_df, 10).iloc[-1])
        atr_stop = entry - self.config.atr_stop_k * atr_4h_val
        stop = min(atr_stop, swing_low_val - 0.01 * atr_4h_val)
        stop_dist = entry - stop
        if stop_dist <= 0:
            return None
        target = entry + stop_dist * self.config.min_rr

        return Signal(
            strategy=self.name,
            symbol="BTC/USDT",
            side="long",
            entry=entry,
            stop=stop,
            target=target,
            timeframe=self.config.execution_tf,
            reason=f"4H pullback to EMA20 | RSI_1D={rsi_1d_val:.1f}",
        )
