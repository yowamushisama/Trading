"""Unit tests for deterministic macro sub-score computations."""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from btc_bot.news.macro.fred import FredObservation, FredSeriesResult, compute_rate_subscore
from btc_bot.news.macro.gdelt import GdeltEvent, GdeltFetchResult, compute_geopolitical_subscore
from btc_bot.news.macro.calendar import CalendarResult, UpcomingEvent, compute_event_risk_subscore
from btc_bot.news.macro.etf_flows import EtfFlowResult, EtfFlowRow, compute_etf_flow_subscore


NOW = datetime.now(timezone.utc)


# ── FRED rates sub-score ───────────────────────────────────────────────────────

def _fred_result(series_id: str, values: list[float], ok: bool = True) -> FredSeriesResult:
    obs = [FredObservation(date=f"2026-01-{i+1:02d}", value=v) for i, v in enumerate(values)]
    return FredSeriesResult(series_id=series_id, observations=obs, fetched_at=NOW, ok=ok)


def test_rates_subscore_neutral_no_change():
    series = {
        "DGS10": _fred_result("DGS10", [4.0] * 15),
        "DFF": _fred_result("DFF", [5.0, 5.0]),
        "WALCL": _fred_result("WALCL", [7_500_000.0] * 5),
        "T10YIE": _fred_result("T10YIE", [2.5] * 5),
    }
    score, snapshot = compute_rate_subscore(series)
    assert score == pytest.approx(0.0, abs=0.02)


def test_rates_subscore_hawkish_negative():
    # 10y yield rises 0.5pp over 10 days → bearish for BTC
    values = [4.0] * 5 + [4.5] * 5 + [4.5]
    series = {
        "DGS10": _fred_result("DGS10", values),
        "DFF": _fred_result("DFF", [5.0, 5.0]),
        "WALCL": _fred_result("WALCL", [7_500_000.0] * 5),
        "T10YIE": _fred_result("T10YIE", [2.5] * 5),
    }
    score, snapshot = compute_rate_subscore(series)
    assert score < 0.0
    assert -0.25 <= score <= 0.0


def test_rates_subscore_dovish_positive():
    # Fed cuts (DFF drops): bullish for BTC
    series = {
        "DGS10": _fred_result("DGS10", [4.0] * 15),
        "DFF": _fred_result("DFF", [5.5, 4.5]),   # -1pp cut
        "WALCL": _fred_result("WALCL", [7_500_000.0] * 5),
        "T10YIE": _fred_result("T10YIE", [2.5] * 5),
    }
    score, _ = compute_rate_subscore(series)
    assert score > 0.0


def test_rates_subscore_capped_at_bounds():
    # Extreme move should not exceed bounds
    values = [3.0] + [6.0] * 14
    series = {
        "DGS10": _fred_result("DGS10", values),
        "DFF": _fred_result("DFF", [3.0, 6.0]),
        "WALCL": _fred_result("WALCL", [8_000_000.0, 6_000_000.0, 6_000_000.0, 6_000_000.0, 6_000_000.0]),
        "T10YIE": _fred_result("T10YIE", [2.5] * 5),
    }
    score, _ = compute_rate_subscore(series)
    assert -0.25 <= score <= 0.25


def test_rates_subscore_failed_series_returns_zero():
    series = {
        "DGS10": _fred_result("DGS10", [], ok=False),
        "DFF": _fred_result("DFF", [], ok=False),
        "WALCL": _fred_result("WALCL", [], ok=False),
        "T10YIE": _fred_result("T10YIE", [], ok=False),
    }
    score, _ = compute_rate_subscore(series)
    assert score == 0.0


# ── GDELT geopolitical sub-score ──────────────────────────────────────────────

def _gdelt_event(goldstein: float, mentions: int = 50) -> GdeltEvent:
    return GdeltEvent(
        event_id="1", date_str="20260101",
        actor1_country="USA", actor2_country="IRN",
        event_root_code=18,
        goldstein_scale=goldstein,
        num_mentions=mentions,
        source_url="https://example.com",
    )


def test_geopolitical_subscore_no_events():
    result = GdeltFetchResult(events=[], fetched_at=NOW, ok=True)
    score, summary = compute_geopolitical_subscore(result)
    assert score == 0.0


def test_geopolitical_subscore_fetch_failed():
    result = GdeltFetchResult(events=[], fetched_at=NOW, ok=False, error="timeout")
    score, summary = compute_geopolitical_subscore(result)
    assert score == 0.0


def test_geopolitical_subscore_severe_conflict():
    events = [_gdelt_event(-9.0, mentions=200), _gdelt_event(-8.0, mentions=150)]
    result = GdeltFetchResult(events=events, fetched_at=NOW, ok=True)
    score, summary = compute_geopolitical_subscore(result)
    assert score < -0.05
    assert -0.30 <= score <= 0.05


def test_geopolitical_subscore_capped():
    # Even extreme events should not go below -0.30
    events = [_gdelt_event(-10.0, mentions=10000) for _ in range(100)]
    result = GdeltFetchResult(events=events, fetched_at=NOW, ok=True)
    score, _ = compute_geopolitical_subscore(result)
    assert score >= -0.30


# ── Calendar event risk sub-score ─────────────────────────────────────────────

def test_event_risk_no_events():
    result = CalendarResult(events=[], fetched_at=NOW, ok=True)
    score, _ = compute_event_risk_subscore(result)
    assert score == 0.0


def test_event_risk_far_away():
    event = UpcomingEvent(name="BLS_RELEASE", date_str="2026-06-01", hours_away=72, source="bls")
    result = CalendarResult(events=[event], fetched_at=NOW, ok=True)
    score, _ = compute_event_risk_subscore(result)
    assert score == 0.0


def test_event_risk_imminent():
    event = UpcomingEvent(name="BLS_RELEASE", date_str="2026-05-28", hours_away=6, source="bls")
    result = CalendarResult(events=[event], fetched_at=NOW, ok=True)
    score, _ = compute_event_risk_subscore(result)
    assert score < -0.10
    assert score >= -0.20


def test_event_risk_at_48h_boundary():
    event = UpcomingEvent(name="BLS_RELEASE", date_str="2026-05-28", hours_away=48, source="bls")
    result = CalendarResult(events=[event], fetched_at=NOW, ok=True)
    score, _ = compute_event_risk_subscore(result)
    assert score == pytest.approx(-0.05, abs=0.01)


# ── ETF flow sub-score ────────────────────────────────────────────────────────

def _etf_rows(flows: list[float]) -> list[EtfFlowRow]:
    return [EtfFlowRow(date_str=f"2026-01-{i+1:02d}", net_flow_m=f) for i, f in enumerate(flows)]


def test_etf_subscore_fetch_failed():
    result = EtfFlowResult(rows=[], fetched_at=NOW, ok=False, error="timeout")
    score, summary, penalty = compute_etf_flow_subscore(result)
    assert score == 0.0
    assert penalty == 0.15


def test_etf_subscore_neutral_stable():
    flows = [100.0] * 30
    result = EtfFlowResult(rows=_etf_rows(flows), fetched_at=NOW, ok=True)
    score, summary, penalty = compute_etf_flow_subscore(result)
    assert score == pytest.approx(0.0, abs=0.02)
    assert penalty == 0.0


def test_etf_subscore_large_inflow():
    # Last day spikes above average
    flows = [50.0] * 29 + [500.0]
    result = EtfFlowResult(rows=_etf_rows(flows), fetched_at=NOW, ok=True)
    score, summary, penalty = compute_etf_flow_subscore(result)
    assert score > 0.05
    assert score <= 0.20
    assert penalty == 0.0


def test_etf_subscore_large_outflow():
    flows = [50.0] * 29 + [-400.0]
    result = EtfFlowResult(rows=_etf_rows(flows), fetched_at=NOW, ok=True)
    score, summary, penalty = compute_etf_flow_subscore(result)
    assert score < -0.05
    assert score >= -0.20
