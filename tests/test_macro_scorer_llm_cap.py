"""Tests for LLM sub-score hard cap and staleness rules."""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch

import pytest

from btc_bot.news.macro_scorer import LLM_SUBSCORE_CAP, MacroScorer, SubScores


def _make_scorer(llm_response: str = "") -> tuple[MacroScorer, MagicMock]:
    llm = MagicMock()
    llm.complete.return_value = llm_response

    scorer = MacroScorer(fred_api_key="test_key", llm_provider=llm, llm_model="test-model")
    return scorer, llm


def _mock_all_fetches(monkeypatch, llm_score: float = 0.0):
    """Patch all external fetches so tests run offline."""
    from btc_bot.news.macro import fred as fred_mod
    from btc_bot.news.macro import gdelt as gdelt_mod
    from btc_bot.news.macro import calendar as cal_mod
    from btc_bot.news.macro import etf_flows as etf_mod
    from btc_bot.news.macro import feeds as feeds_mod

    now = datetime.now(timezone.utc)

    monkeypatch.setattr(fred_mod, "FredClient", lambda *a, **kw: MagicMock(
        fetch_all_rate_series=lambda **kw2: {
            "DGS10": MagicMock(ok=False, observations=[], error="mocked"),
            "DFF": MagicMock(ok=False, observations=[], error="mocked"),
            "WALCL": MagicMock(ok=False, observations=[], error="mocked"),
            "T10YIE": MagicMock(ok=False, observations=[], error="mocked"),
        }
    ))
    monkeypatch.setattr(gdelt_mod, "fetch_gdelt_events", lambda **kw: gdelt_mod.GdeltFetchResult(
        events=[], fetched_at=now, ok=True
    ))
    monkeypatch.setattr(cal_mod, "fetch_official_calendar", lambda **kw: cal_mod.CalendarResult(
        events=[], fetched_at=now, ok=True
    ))
    monkeypatch.setattr(etf_mod, "fetch_farside_btc_etf_flows", lambda: etf_mod.EtfFlowResult(
        rows=[], fetched_at=now, ok=False, error="mocked"
    ))
    monkeypatch.setattr(feeds_mod, "fetch_macro_feeds", lambda: [])


class TestLLMSubScoreCap:
    def test_llm_score_above_cap_is_clamped(self, monkeypatch):
        _mock_all_fetches(monkeypatch)
        llm = MagicMock()
        llm.complete.return_value = json.dumps({"score": 0.99, "summary": "test", "drivers": [], "caveats": ""})
        scorer = MacroScorer(fred_api_key="k", llm_provider=llm, llm_model="m")
        result = scorer.compute(session=None)
        assert result.subscores.llm_narrative <= LLM_SUBSCORE_CAP

    def test_llm_score_below_negative_cap_is_clamped(self, monkeypatch):
        _mock_all_fetches(monkeypatch)
        llm = MagicMock()
        llm.complete.return_value = json.dumps({"score": -0.99, "summary": "test", "drivers": [], "caveats": ""})
        scorer = MacroScorer(fred_api_key="k", llm_provider=llm, llm_model="m")
        result = scorer.compute(session=None)
        assert result.subscores.llm_narrative >= -LLM_SUBSCORE_CAP

    def test_llm_failure_does_not_crash(self, monkeypatch):
        _mock_all_fetches(monkeypatch)
        llm = MagicMock()
        llm.complete.side_effect = Exception("network error")
        scorer = MacroScorer(fred_api_key="k", llm_provider=llm, llm_model="m")
        result = scorer.compute(session=None)
        assert result.subscores.llm_narrative == 0.0

    def test_llm_invalid_json_does_not_crash(self, monkeypatch):
        _mock_all_fetches(monkeypatch)
        llm = MagicMock()
        llm.complete.return_value = "not valid json !!!"
        scorer = MacroScorer(fred_api_key="k", llm_provider=llm, llm_model="m")
        result = scorer.compute(session=None)
        assert result.subscores.llm_narrative == 0.0

    def test_no_llm_gives_zero_narrative(self, monkeypatch):
        _mock_all_fetches(monkeypatch)
        scorer = MacroScorer(fred_api_key="k", llm_provider=None, llm_model="")
        result = scorer.compute(session=None)
        assert result.subscores.llm_narrative == 0.0

    def test_final_score_clamped_to_minus_one_plus_one(self, monkeypatch):
        _mock_all_fetches(monkeypatch)
        scorer = MacroScorer(fred_api_key="k", llm_provider=None)
        result = scorer.compute(session=None)
        assert -1.0 <= result.final_score <= 1.0

    def test_direction_derived_from_score(self, monkeypatch):
        _mock_all_fetches(monkeypatch)
        llm = MagicMock()
        llm.complete.return_value = json.dumps({"score": 0.10, "summary": "test", "drivers": [], "caveats": ""})
        scorer = MacroScorer(fred_api_key="k", llm_provider=llm, llm_model="m")
        result = scorer.compute(session=None)
        # Direction is derived from final_score sign, not from LLM
        if result.final_score >= 0.15:
            assert result.direction == "bullish"
        elif result.final_score <= -0.15:
            assert result.direction == "bearish"
        else:
            assert result.direction == "neutral"

    def test_confidence_between_zero_and_one(self, monkeypatch):
        _mock_all_fetches(monkeypatch)
        scorer = MacroScorer(fred_api_key="k", llm_provider=None)
        result = scorer.compute(session=None)
        assert 0.0 <= result.confidence <= 1.0


class TestSubScoresDataclass:
    def test_total_sums_all_fields(self):
        ss = SubScores(rates=0.1, event_risk=-0.05, geopolitical=-0.10,
                       etf_flow=0.05, crypto_news=0.02, llm_narrative=0.03)
        assert ss.total() == pytest.approx(0.05, abs=1e-9)
