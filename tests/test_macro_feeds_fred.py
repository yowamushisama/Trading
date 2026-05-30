"""Unit tests for FRED client parsing logic (no HTTP calls)."""

from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

import pytest

from btc_bot.news.macro.fred import (
    FredClient,
    FredObservation,
    FredSeriesResult,
    compute_rate_subscore,
)

NOW = datetime.now(timezone.utc)


class TestFredClientInit:
    def test_raises_without_api_key(self):
        with pytest.raises(ValueError, match="FRED_API_KEY"):
            FredClient("")

    def test_accepts_valid_key(self):
        client = FredClient("abc123")
        assert client._api_key == "abc123"


class TestFredClientParsing:
    def test_fetch_series_parses_observations(self):
        mock_response = MagicMock()
        mock_response.json.return_value = {
            "observations": [
                {"date": "2026-01-01", "value": "4.25"},
                {"date": "2026-01-02", "value": "4.30"},
                {"date": "2026-01-03", "value": "."},   # missing — should be skipped
            ]
        }
        mock_response.raise_for_status = MagicMock()

        client = FredClient("key")
        with patch("btc_bot.news.macro.fred.requests.get", return_value=mock_response):
            result = client.fetch_series("DGS10", days=10)

        assert result.ok is True
        assert len(result.observations) == 2
        assert result.observations[0].value == 4.25
        assert result.observations[1].value == 4.30

    def test_fetch_series_handles_http_error(self):
        with patch("btc_bot.news.macro.fred.requests.get", side_effect=Exception("timeout")):
            client = FredClient("key")
            result = client.fetch_series("DGS10", days=10)

        assert result.ok is False
        assert result.observations == []
        assert "timeout" in result.error


class TestRateSubScoreBounds:
    def _series(self, sid: str, values: list[float]) -> FredSeriesResult:
        obs = [FredObservation(date=f"2026-01-{i+1:02d}", value=v) for i, v in enumerate(values)]
        return FredSeriesResult(series_id=sid, observations=obs, fetched_at=NOW, ok=True)

    def test_score_within_bounds_always(self):
        for delta in [-3.0, -1.0, 0.0, 1.0, 3.0]:
            values = [4.0] + [4.0 + delta] * 14
            series = {
                "DGS10": self._series("DGS10", values),
                "DFF": self._series("DFF", [5.0, 5.0 + delta]),
                "WALCL": self._series("WALCL", [7e6] * 5),
                "T10YIE": self._series("T10YIE", [2.5] * 5),
            }
            score, _ = compute_rate_subscore(series)
            assert -0.25 <= score <= 0.25, f"Out of bounds for delta={delta}: score={score}"
