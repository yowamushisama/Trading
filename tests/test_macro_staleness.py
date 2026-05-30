"""Tests for MacroNewsManager staleness detection."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock

import pytest

from btc_bot.news.macro_manager import MacroNewsManager
from btc_bot.news.macro_scorer import MacroScoreResult, SubScores


def _make_score(hours_old: float = 0.0) -> MacroScoreResult:
    computed_at = datetime.now(timezone.utc) - timedelta(hours=hours_old)
    return MacroScoreResult(
        computed_at_utc=computed_at,
        final_score=-0.10,
        direction="bearish",
        confidence=0.8,
        subscores=SubScores(),
        drivers=[],
        rates_snapshot={},
        top_headlines=[],
        gdelt_summary={},
        etf_summary={},
        calendar_summary={},
        llm_provider="",
        llm_model="",
        llm_prompt_hash="",
        llm_raw_response="",
    )


def _make_manager(stale_hours: int = 30) -> MacroNewsManager:
    return MacroNewsManager(
        fred_api_key="test_key",
        session_factory=None,
        stale_hours=stale_hours,
    )


class TestStaleness:
    def test_no_score_is_stale(self):
        mgr = _make_manager()
        assert mgr.is_stale() is True

    def test_fresh_score_not_stale(self):
        mgr = _make_manager(stale_hours=30)
        mgr._current_score = _make_score(hours_old=1.0)
        assert mgr.is_stale() is False

    def test_score_exactly_at_threshold_not_stale(self):
        mgr = _make_manager(stale_hours=30)
        mgr._current_score = _make_score(hours_old=29.9)
        assert mgr.is_stale() is False

    def test_score_past_threshold_is_stale(self):
        mgr = _make_manager(stale_hours=30)
        mgr._current_score = _make_score(hours_old=31.0)
        assert mgr.is_stale() is True

    def test_seconds_until_next_compute_positive(self):
        mgr = _make_manager()
        now = datetime.now(timezone.utc)
        secs = mgr._seconds_until_next_compute(now)
        assert secs > 0
        assert secs <= 86400 + 60  # at most one day + margin

    def test_current_score_initially_none(self):
        mgr = _make_manager()
        assert mgr.current_score is None
