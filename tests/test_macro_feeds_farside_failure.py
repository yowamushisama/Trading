"""Tests that Farside ETF flow failures degrade confidence gracefully."""

from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import patch

import pytest

from btc_bot.news.macro.etf_flows import (
    EtfFlowResult,
    EtfFlowRow,
    compute_etf_flow_subscore,
    fetch_farside_btc_etf_flows,
)

NOW = datetime.now(timezone.utc)


class TestFarsideFetchFailure:
    def test_http_exception_returns_ok_false(self):
        with patch("btc_bot.news.macro.etf_flows.requests.get", side_effect=Exception("timeout")):
            result = fetch_farside_btc_etf_flows()
        assert result.ok is False
        assert result.rows == []
        assert "timeout" in result.error

    def test_failed_fetch_gives_zero_score_and_confidence_penalty(self):
        result = EtfFlowResult(rows=[], fetched_at=NOW, ok=False, error="timeout")
        score, summary, penalty = compute_etf_flow_subscore(result)
        assert score == 0.0
        assert penalty == pytest.approx(0.15)
        assert summary["fetch_ok"] is False

    def test_empty_rows_ok_true_gives_zero_and_no_penalty(self):
        # Fetched successfully but no data rows
        result = EtfFlowResult(rows=[], fetched_at=NOW, ok=False)  # ok=False from no rows
        score, summary, penalty = compute_etf_flow_subscore(result)
        assert score == 0.0
        assert penalty == 0.15

    def test_score_stays_within_bounds_with_valid_rows(self):
        # Large but reasonable flows — score must stay in [-0.20, +0.20]
        rows = [EtfFlowRow(date_str=f"2026-01-{i+1:02d}", net_flow_m=50.0 + i * 5) for i in range(30)]
        result = EtfFlowResult(rows=rows, fetched_at=NOW, ok=True)
        score, _, penalty = compute_etf_flow_subscore(result)
        assert -0.20 <= score <= 0.20
        assert penalty == 0.0


class TestFarsideParsing:
    def test_parse_date_formats(self):
        from btc_bot.news.macro.etf_flows import _parse_date
        assert _parse_date("15 Jan 2026") == "2026-01-15"
        assert _parse_date("2026-01-15") == "2026-01-15"
        assert _parse_date("01/15/2026") == "2026-01-15"
        assert _parse_date("gibberish") is None
