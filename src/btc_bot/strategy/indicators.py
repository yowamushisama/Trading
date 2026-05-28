"""Technical indicators computed on pandas DataFrames.

All functions expect a DataFrame with columns: open, high, low, close, volume
and return a Series or scalar. Column names are lowercase.
"""

from __future__ import annotations

import numpy as np
import pandas as pd


def ema(series: pd.Series, period: int) -> pd.Series:
    return series.ewm(span=period, adjust=False).mean()


def sma(series: pd.Series, period: int) -> pd.Series:
    return series.rolling(window=period).mean()


def rsi(series: pd.Series, period: int = 14) -> pd.Series:
    delta = series.diff()
    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)
    avg_gain = gain.ewm(com=period - 1, adjust=False).mean()
    avg_loss = loss.ewm(com=period - 1, adjust=False).mean()
    rs = avg_gain / avg_loss.replace(0, np.nan)
    return 100 - (100 / (1 + rs))


def atr(df: pd.DataFrame, period: int = 14) -> pd.Series:
    high, low, prev_close = df["high"], df["low"], df["close"].shift(1)
    tr = pd.concat(
        [high - low, (high - prev_close).abs(), (low - prev_close).abs()], axis=1
    ).max(axis=1)
    return tr.ewm(com=period - 1, adjust=False).mean()


def atr_pct(df: pd.DataFrame, period: int = 14) -> pd.Series:
    return atr(df, period) / df["close"]


def adx(df: pd.DataFrame, period: int = 14) -> pd.Series:
    """Average Directional Index."""
    high, low, close = df["high"], df["low"], df["close"]
    prev_high = high.shift(1)
    prev_low = low.shift(1)

    dm_plus = (high - prev_high).clip(lower=0)
    dm_minus = (prev_low - low).clip(lower=0)

    # When +DM == -DM both are set to 0
    mask = dm_plus == dm_minus
    dm_plus[mask] = 0
    dm_minus[mask] = 0

    tr_series = pd.concat(
        [high - low, (high - close.shift(1)).abs(), (low - close.shift(1)).abs()], axis=1
    ).max(axis=1)

    atr_s = tr_series.ewm(com=period - 1, adjust=False).mean()
    di_plus = 100 * dm_plus.ewm(com=period - 1, adjust=False).mean() / atr_s
    di_minus = 100 * dm_minus.ewm(com=period - 1, adjust=False).mean() / atr_s

    dx = (100 * (di_plus - di_minus).abs() / (di_plus + di_minus).replace(0, np.nan))
    return dx.ewm(com=period - 1, adjust=False).mean()


def volume_zscore(volume: pd.Series, lookback: int = 20) -> pd.Series:
    roll_mean = volume.rolling(lookback).mean()
    roll_std = volume.rolling(lookback).std()
    return (volume - roll_mean) / roll_std.replace(0, np.nan)


def swing_high(df: pd.DataFrame, lookback: int = 12) -> pd.Series:
    return df["high"].rolling(lookback).max()


def swing_low(df: pd.DataFrame, lookback: int = 12) -> pd.Series:
    return df["low"].rolling(lookback).min()
