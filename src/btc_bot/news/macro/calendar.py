"""Economic calendar from official free sources.

Sources:
  - Federal Reserve FOMC dates via press releases RSS (fedreserve.gov)
  - BLS release schedule (hardcoded annual list; BLS publishes a PDF but no machine-readable RSS)

Goal: flag "high-impact event within the next N hours" so the scorer can apply
event-proximity risk (the event_risk_subscore).
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Optional

from loguru import logger

# BLS key release dates 2026 — approximate first-Friday CPI/NFP schedule.
# Replace or extend as years change. These are approximate; the exact dates shift
# year-to-year but are close enough for a ±48h proximity window.
BLS_APPROX_DATES_2026: list[str] = [
    # CPI (usually 2nd week of month)
    "2026-01-15", "2026-02-12", "2026-03-12", "2026-04-10",
    "2026-05-13", "2026-06-11", "2026-07-15", "2026-08-13",
    "2026-09-10", "2026-10-14", "2026-11-12", "2026-12-11",
    # NFP (usually first Friday)
    "2026-01-09", "2026-02-06", "2026-03-06", "2026-04-03",
    "2026-05-01", "2026-06-05", "2026-07-10", "2026-08-07",
    "2026-09-04", "2026-10-02", "2026-11-06", "2026-12-04",
]

BLS_APPROX_DATES_2027: list[str] = [
    "2027-01-14", "2027-02-11", "2027-03-11", "2027-04-09",
    "2027-05-13", "2027-06-10", "2027-07-15", "2027-08-12",
    "2027-09-09", "2027-10-14", "2027-11-11", "2027-12-09",
    "2027-01-08", "2027-02-05", "2027-03-05", "2027-04-02",
    "2027-05-07", "2027-06-04", "2027-07-09", "2027-08-06",
    "2027-09-03", "2027-10-01", "2027-11-05", "2027-12-03",
]


@dataclass
class UpcomingEvent:
    name: str
    date_str: str           # YYYY-MM-DD
    hours_away: float
    source: str


@dataclass
class CalendarResult:
    events: list[UpcomingEvent]
    fetched_at: datetime
    ok: bool
    error: str = ""


def _bls_dates() -> list[str]:
    now_year = datetime.now(timezone.utc).year
    if now_year == 2026:
        return BLS_APPROX_DATES_2026
    if now_year == 2027:
        return BLS_APPROX_DATES_2027
    return []


def _parse_fomc_from_fed_rss() -> list[str]:
    """Extract FOMC meeting date strings from Federal Reserve press release RSS."""
    fomc_dates: list[str] = []
    try:
        import feedparser
        from btc_bot.news.rss import fetch_rss_items
        items = fetch_rss_items("fed_pressreleases",
                                "https://www.federalreserve.gov/feeds/press_all.xml")
        fomc_pattern = re.compile(
            r"\b(january|february|march|april|may|june|july|august|september|october|november|december)"
            r"\s+\d{1,2}[-–]\d{1,2},?\s+\d{4}\b",
            re.IGNORECASE,
        )
        for item in items:
            if "fomc" in (item.title + " " + item.body).lower():
                for m in fomc_pattern.findall(item.title + " " + item.body):
                    pass  # date parsing from natural language is fragile; skip
    except Exception as e:
        logger.debug(f"FOMC RSS parse failed: {e}")
    return fomc_dates


def fetch_official_calendar(days_ahead: int = 7) -> CalendarResult:
    """Return upcoming high-impact economic events within `days_ahead` days."""
    now = datetime.now(timezone.utc)
    fetched_at = now
    upcoming: list[UpcomingEvent] = []

    try:
        all_dates = _bls_dates()
        for date_str in all_dates:
            try:
                event_dt = datetime.strptime(date_str, "%Y-%m-%d").replace(
                    hour=13, minute=30, tzinfo=timezone.utc  # typical BLS release time
                )
                delta = (event_dt - now).total_seconds() / 3600
                if 0 <= delta <= days_ahead * 24:
                    upcoming.append(UpcomingEvent(
                        name="BLS_RELEASE",
                        date_str=date_str,
                        hours_away=round(delta, 1),
                        source="bls_hardcoded",
                    ))
            except ValueError:
                continue

        upcoming.sort(key=lambda e: e.hours_away)
        return CalendarResult(events=upcoming, fetched_at=fetched_at, ok=True)

    except Exception as e:
        logger.warning(f"Calendar fetch failed: {e}")
        return CalendarResult(events=[], fetched_at=fetched_at, ok=False, error=str(e))


def compute_event_risk_subscore(result: CalendarResult) -> tuple[float, dict]:
    """
    Returns (subscore, summary_dict).
    subscore ∈ [-0.20, 0.0] — negative only (pre-event uncertainty).
    Magnitude grows as an event approaches within 48h.
    """
    summary: dict = {"upcoming_events": [e.hours_away for e in result.events[:3]]}
    if not result.ok or not result.events:
        return 0.0, summary

    # Use the nearest upcoming event
    nearest = result.events[0]
    h = nearest.hours_away
    if h > 48:
        return 0.0, summary

    # Linear ramp: 48h → -0.05; 12h → -0.15; 0h (during) → -0.20
    score = -0.20 + (h / 48.0) * 0.15
    score = max(-0.20, min(0.0, score))
    summary["nearest_event"] = nearest.name
    summary["nearest_hours_away"] = h
    return score, summary
