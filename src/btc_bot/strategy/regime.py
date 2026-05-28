"""Market regime classifier: trend / range / chop."""

from __future__ import annotations

from enum import Enum

import pandas as pd

from btc_bot.strategy.indicators import adx, atr_pct, ema


class Regime(str, Enum):
    trend_up = "trend_up"
    trend_down = "trend_down"
    range_bound = "range_bound"
    chop = "chop"
    high_volatility = "high_volatility"


def classify_regime(
    df: pd.DataFrame,
    ema_period: int = 200,
    adx_period: int = 14,
    adx_trend_threshold: float = 25.0,
    atr_low: float = 0.004,   # 0.4%
    atr_high: float = 0.025,  # 2.5%
) -> Regime:
    """Classify the current regime from the last closed candle."""
    if len(df) < ema_period + 10:
        return Regime.chop

    close = df["close"]
    ema200 = ema(close, ema_period)
    adx_val = adx(df, adx_period)
    atr_val = atr_pct(df, adx_period)

    last_close = float(close.iloc[-1])
    last_ema200 = float(ema200.iloc[-1])
    last_adx = float(adx_val.iloc[-1])
    last_atr_pct = float(atr_val.iloc[-1])

    if last_atr_pct > atr_high:
        return Regime.high_volatility

    if last_atr_pct < atr_low:
        return Regime.chop

    if last_adx >= adx_trend_threshold:
        return Regime.trend_up if last_close > last_ema200 else Regime.trend_down

    return Regime.range_bound


def is_long_biased(regime: Regime) -> bool:
    return regime == Regime.trend_up
