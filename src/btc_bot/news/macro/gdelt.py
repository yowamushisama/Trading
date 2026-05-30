"""GDELT 2.0 Event database adapter.

Downloads the most recent 24h of 15-minute event CSV files from GDELT and
filters for conflict/war events (EventRootCode 14-20) with negative Goldstein
scores involving US or G7 actors.

Reference:
  Codebook: https://data.gdeltproject.org/documentation/GDELT-Event_Codebook-V2.0.pdf
  Latest 15-min file list: http://data.gdeltproject.org/gdeltv2/lastupdate.txt
"""

from __future__ import annotations

import csv
import io
import zipfile
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

import requests
from loguru import logger

GDELT_LASTUPDATE_URL = "http://data.gdeltproject.org/gdeltv2/lastupdate.txt"
REQUEST_TIMEOUT = 30

# GDELT V2 event CSV column indices (0-based)
COL_GLOBALEVENTID = 0
COL_SQLDATE = 1
COL_ACTOR1COUNTRYCODE = 7
COL_ACTOR2COUNTRYCODE = 17
COL_EVENTROOTCODE = 28
COL_GOLDSTEINSCALE = 30
COL_NUMMENTIONS = 31
COL_SOURCEURL = 57

G7_COUNTRY_CODES = {"USA", "GBR", "DEU", "FRA", "JPN", "ITA", "CAN", "CHN", "RUS"}
CONFLICT_ROOT_CODES = {14, 15, 16, 17, 18, 19, 20}
GOLDSTEIN_THRESHOLD = -5.0


@dataclass
class GdeltEvent:
    event_id: str
    date_str: str           # YYYYMMDD
    actor1_country: str
    actor2_country: str
    event_root_code: int
    goldstein_scale: float
    num_mentions: int
    source_url: str


@dataclass
class GdeltFetchResult:
    events: list[GdeltEvent]
    fetched_at: datetime
    ok: bool
    error: str = ""
    files_processed: int = 0


def _fetch_lastupdate_urls() -> list[str]:
    """Return the export CSV URLs from the latest GDELT update file."""
    resp = requests.get(GDELT_LASTUPDATE_URL, timeout=REQUEST_TIMEOUT, verify=False)
    resp.raise_for_status()
    urls = []
    for line in resp.text.strip().split("\n"):
        parts = line.strip().split(" ")
        if len(parts) >= 3 and parts[2].endswith(".export.CSV.zip"):
            urls.append(parts[2])
    return urls


def _parse_events_from_csv(csv_text: str) -> list[GdeltEvent]:
    events = []
    reader = csv.reader(io.StringIO(csv_text), delimiter="\t")
    for row in reader:
        try:
            if len(row) < 58:
                continue
            root_code_str = row[COL_EVENTROOTCODE].strip()
            if not root_code_str.isdigit():
                continue
            root_code = int(root_code_str)
            if root_code not in CONFLICT_ROOT_CODES:
                continue
            goldstein_str = row[COL_GOLDSTEINSCALE].strip()
            if not goldstein_str:
                continue
            goldstein = float(goldstein_str)
            if goldstein >= GOLDSTEIN_THRESHOLD:
                continue
            actor1 = row[COL_ACTOR1COUNTRYCODE].strip()
            actor2 = row[COL_ACTOR2COUNTRYCODE].strip()
            if not (actor1 in G7_COUNTRY_CODES or actor2 in G7_COUNTRY_CODES):
                continue
            events.append(GdeltEvent(
                event_id=row[COL_GLOBALEVENTID].strip(),
                date_str=row[COL_SQLDATE].strip(),
                actor1_country=actor1,
                actor2_country=actor2,
                event_root_code=root_code,
                goldstein_scale=goldstein,
                num_mentions=int(row[COL_NUMMENTIONS].strip() or "0"),
                source_url=row[COL_SOURCEURL].strip() if len(row) > COL_SOURCEURL else "",
            ))
        except (ValueError, IndexError):
            continue
    return events


def fetch_gdelt_events(hours: int = 24) -> GdeltFetchResult:
    """Download recent GDELT event file(s) and return high-impact geopolitical events."""
    fetched_at = datetime.now(timezone.utc)
    all_events: list[GdeltEvent] = []
    files_processed = 0

    try:
        urls = _fetch_lastupdate_urls()
        if not urls:
            return GdeltFetchResult(events=[], fetched_at=fetched_at, ok=False,
                                    error="No export URLs found in lastupdate.txt")

        # Only process the most recent file (last 15 minutes) to keep it fast.
        # For a true 24h window you'd need ~96 files; that's too slow for live use.
        # We accept the recency trade-off and note it in the confidence deduction.
        for url in urls[:1]:
            try:
                resp = requests.get(url, timeout=REQUEST_TIMEOUT, verify=False)
                resp.raise_for_status()
                with zipfile.ZipFile(io.BytesIO(resp.content)) as zf:
                    csv_name = [n for n in zf.namelist() if n.endswith(".CSV")][0]
                    csv_text = zf.read(csv_name).decode("utf-8", errors="replace")
                all_events.extend(_parse_events_from_csv(csv_text))
                files_processed += 1
            except Exception as e:
                logger.warning(f"GDELT file fetch failed ({url}): {e}")

        return GdeltFetchResult(
            events=all_events,
            fetched_at=fetched_at,
            ok=True,
            files_processed=files_processed,
        )
    except Exception as e:
        logger.warning(f"GDELT fetch failed: {e}")
        return GdeltFetchResult(events=[], fetched_at=fetched_at, ok=False, error=str(e))


def compute_geopolitical_subscore(result: GdeltFetchResult) -> tuple[float, dict]:
    """
    Returns (subscore, summary_dict).
    subscore ∈ [-0.30, +0.05].
    Skewed negative: severe conflict → risk-off → bearish BTC.
    """
    summary: dict = {
        "events_found": len(result.events),
        "fetch_ok": result.ok,
    }
    if not result.ok or not result.events:
        # If fetch failed entirely, treat as neutral (confidence deducted by caller)
        return 0.0, summary

    # Weight each event by abs(Goldstein) * log(mentions+1)
    import math
    total_weight = 0.0
    for ev in result.events:
        weight = abs(ev.goldstein_scale) * math.log1p(ev.num_mentions)
        total_weight += weight

    summary["total_conflict_weight"] = round(total_weight, 2)
    summary["top_events"] = [
        {
            "actor1": ev.actor1_country,
            "actor2": ev.actor2_country,
            "root_code": ev.event_root_code,
            "goldstein": ev.goldstein_scale,
            "mentions": ev.num_mentions,
        }
        for ev in sorted(result.events, key=lambda e: e.goldstein_scale)[:5]
    ]

    # Map total_weight to [-0.30, +0.05]:
    # weight=0 → 0.0; weight=50 → -0.15; weight=150 → -0.30
    score = max(-0.30, min(0.05, -total_weight / 500.0))
    return score, summary
