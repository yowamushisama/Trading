"""Unit tests for GDELT event parsing and subscore computation (no HTTP calls)."""

from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import patch

import pytest

from btc_bot.news.macro.gdelt import (
    GdeltEvent,
    GdeltFetchResult,
    G7_COUNTRY_CODES,
    CONFLICT_ROOT_CODES,
    GOLDSTEIN_THRESHOLD,
    compute_geopolitical_subscore,
    _parse_events_from_csv,
)

NOW = datetime.now(timezone.utc)


def _make_csv_row(
    event_id: str = "1",
    sql_date: str = "20260101",
    actor1: str = "USA",
    actor2: str = "IRN",
    root_code: int = 18,
    goldstein: float = -8.0,
    mentions: int = 100,
    source_url: str = "https://example.com",
) -> str:
    # Build a tab-separated row with the correct column count (58 columns)
    row = [""] * 58
    row[0] = event_id
    row[1] = sql_date
    row[7] = actor1
    row[17] = actor2
    row[28] = str(root_code)
    row[30] = str(goldstein)
    row[31] = str(mentions)
    row[57] = source_url
    return "\t".join(row)


class TestGdeltCsvParsing:
    def test_parses_valid_conflict_event(self):
        csv_text = _make_csv_row()
        events = _parse_events_from_csv(csv_text)
        assert len(events) == 1
        assert events[0].actor1_country == "USA"
        assert events[0].goldstein_scale == -8.0
        assert events[0].num_mentions == 100

    def test_skips_non_conflict_root_code(self):
        csv_text = _make_csv_row(root_code=5)
        events = _parse_events_from_csv(csv_text)
        assert events == []

    def test_skips_high_goldstein(self):
        csv_text = _make_csv_row(goldstein=-3.0)  # above threshold
        events = _parse_events_from_csv(csv_text)
        assert events == []

    def test_skips_non_g7_actors(self):
        csv_text = _make_csv_row(actor1="CUB", actor2="VEN")
        events = _parse_events_from_csv(csv_text)
        assert events == []

    def test_parses_g7_actor2(self):
        csv_text = _make_csv_row(actor1="PRK", actor2="GBR")
        events = _parse_events_from_csv(csv_text)
        assert len(events) == 1

    def test_empty_csv_returns_empty(self):
        events = _parse_events_from_csv("")
        assert events == []

    def test_short_row_skipped(self):
        events = _parse_events_from_csv("1\t2\t3")
        assert events == []


class TestGdeltSubScore:
    def test_no_events_returns_zero(self):
        result = GdeltFetchResult(events=[], fetched_at=NOW, ok=True)
        score, _ = compute_geopolitical_subscore(result)
        assert score == 0.0

    def test_score_within_bounds(self):
        for n in [1, 5, 50, 200]:
            events = [
                GdeltEvent("1", "20260101", "USA", "IRN", 18, -9.0, 500, "")
                for _ in range(n)
            ]
            result = GdeltFetchResult(events=events, fetched_at=NOW, ok=True)
            score, _ = compute_geopolitical_subscore(result)
            assert -0.30 <= score <= 0.05

    def test_failed_fetch_returns_zero(self):
        result = GdeltFetchResult(events=[], fetched_at=NOW, ok=False, error="timeout")
        score, _ = compute_geopolitical_subscore(result)
        assert score == 0.0
