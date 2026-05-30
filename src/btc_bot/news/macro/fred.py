"""FRED API client for US macro rate and liquidity series.

Series used:
  DFF    — effective federal funds rate (daily)
  DGS10  — 10-year Treasury yield (daily)
  T10YIE — 10-year breakeven inflation rate (daily)
  WALCL  — Fed balance sheet total assets (weekly)

FRED_API_KEY is required; free key at https://fred.stlouisfed.org/docs/api/api_key.html
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Optional

import requests
from loguru import logger

FRED_BASE = "https://api.stlouisfed.org/fred/series/observations"
REQUEST_TIMEOUT = 15

# Series we pull and their cache retention
RATE_SERIES: list[str] = ["DFF", "DGS10", "T10YIE", "WALCL"]


@dataclass
class FredObservation:
    date: str        # YYYY-MM-DD
    value: float


@dataclass
class FredSeriesResult:
    series_id: str
    observations: list[FredObservation]
    fetched_at: datetime
    ok: bool
    error: str = ""


class FredClient:
    def __init__(self, api_key: str) -> None:
        if not api_key:
            raise ValueError("FRED_API_KEY is required. Get one free at https://fred.stlouisfed.org/docs/api/api_key.html")
        self._api_key = api_key

    def fetch_series(self, series_id: str, days: int = 60) -> FredSeriesResult:
        """Fetch the most recent `days` observations for a series."""
        start = (datetime.now(timezone.utc) - timedelta(days=days)).strftime("%Y-%m-%d")
        params = {
            "series_id": series_id,
            "api_key": self._api_key,
            "file_type": "json",
            "observation_start": start,
            "sort_order": "asc",
        }
        fetched_at = datetime.now(timezone.utc)
        try:
            resp = requests.get(FRED_BASE, params=params, timeout=REQUEST_TIMEOUT, verify=False)
            resp.raise_for_status()
            data = resp.json()
            obs = []
            for row in data.get("observations", []):
                try:
                    val = float(row["value"])
                    obs.append(FredObservation(date=row["date"], value=val))
                except (ValueError, KeyError):
                    pass  # "." placeholder for missing data
            return FredSeriesResult(
                series_id=series_id,
                observations=obs,
                fetched_at=fetched_at,
                ok=True,
            )
        except Exception as e:
            logger.warning(f"FRED fetch failed for {series_id}: {e}")
            return FredSeriesResult(
                series_id=series_id,
                observations=[],
                fetched_at=fetched_at,
                ok=False,
                error=str(e),
            )

    def fetch_all_rate_series(self, days: int = 60) -> dict[str, FredSeriesResult]:
        results = {}
        for sid in RATE_SERIES:
            results[sid] = self.fetch_series(sid, days=days)
            time.sleep(0.3)  # FRED rate limit: 120 req/min
        return results


def compute_rate_subscore(series: dict[str, FredSeriesResult]) -> tuple[float, dict]:
    """
    Returns (subscore, snapshot_dict).
    subscore ∈ [-0.25, +0.25].
    Sign: hawkish (rising rates, shrinking balance sheet) → negative for BTC.
    """
    snapshot: dict = {}
    component_scores: list[float] = []

    def last_two(result: FredSeriesResult) -> tuple[Optional[float], Optional[float]]:
        obs = [o for o in result.observations if o.value is not None]
        if len(obs) >= 2:
            return obs[-2].value, obs[-1].value
        if len(obs) == 1:
            return obs[-1].value, obs[-1].value
        return None, None

    # DGS10 — 10d direction: 10d-ago vs latest
    dgs10 = series.get("DGS10")
    if dgs10 and dgs10.ok and len(dgs10.observations) >= 2:
        obs = dgs10.observations
        latest = obs[-1].value
        ten_ago = obs[max(0, len(obs) - 10)].value
        delta = latest - ten_ago  # positive = hawkish
        snapshot["DGS10_latest"] = latest
        snapshot["DGS10_10d_delta"] = round(delta, 4)
        # Every +0.25pp move → -0.05 score, capped at ±0.10
        score = max(-0.10, min(0.10, -delta * 0.20))
        component_scores.append(score)

    # DFF — fed funds direction
    dff = series.get("DFF")
    if dff and dff.ok and len(dff.observations) >= 2:
        prev, curr = last_two(dff)
        if prev is not None and curr is not None:
            snapshot["DFF_latest"] = curr
            snapshot["DFF_prev"] = prev
            delta = curr - prev
            score = max(-0.08, min(0.08, -delta * 0.50))
            component_scores.append(score)

    # WALCL — balance sheet: growing = liquidity bullish for BTC
    walcl = series.get("WALCL")
    if walcl and walcl.ok and len(walcl.observations) >= 4:
        obs = walcl.observations
        latest = obs[-1].value
        four_ago = obs[max(0, len(obs) - 4)].value
        pct_change = (latest - four_ago) / four_ago if four_ago else 0
        snapshot["WALCL_latest"] = latest
        snapshot["WALCL_4w_pct"] = round(pct_change, 6)
        # +1% weekly expansion → +0.03; -1% contraction → -0.03; cap ±0.07
        score = max(-0.07, min(0.07, pct_change * 3.0))
        component_scores.append(score)

    if not component_scores:
        return 0.0, snapshot

    raw = sum(component_scores)
    return max(-0.25, min(0.25, raw)), snapshot
