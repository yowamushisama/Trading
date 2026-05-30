"""BTC spot ETF flow scraper — Farside Investors.

IMPORTANT: Farside has no documented stable API. This adapter scrapes the HTML
table at https://farside.co.uk/etf/ and is fragile by design. If it breaks,
the etf_flow_subscore returns 0.0 and confidence is reduced by 0.15. A fallback
provider (CSV upload, CoinGlass, etc.) can replace this adapter without changing
the scorer interface.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Optional

import requests
from loguru import logger

FARSIDE_URL = "https://farside.co.uk/etf/"
REQUEST_TIMEOUT = 20


@dataclass
class EtfFlowRow:
    date_str: str   # YYYY-MM-DD
    net_flow_m: float  # USD millions, positive = inflow


@dataclass
class EtfFlowResult:
    rows: list[EtfFlowRow]   # most recent ≤ 30 rows
    fetched_at: datetime
    ok: bool
    error: str = ""


def fetch_farside_btc_etf_flows() -> EtfFlowResult:
    """Scrape Farside BTC ETF daily net flow table. Returns failure gracefully."""
    fetched_at = datetime.now(timezone.utc)
    try:
        resp = requests.get(FARSIDE_URL, timeout=REQUEST_TIMEOUT, verify=False,
                            headers={"User-Agent": "Mozilla/5.0 (research bot)"})
        resp.raise_for_status()
        rows = _parse_flow_table(resp.text)
        return EtfFlowResult(rows=rows, fetched_at=fetched_at, ok=True)
    except Exception as e:
        logger.warning(f"Farside ETF flow fetch failed (non-fatal): {e}")
        return EtfFlowResult(rows=[], fetched_at=fetched_at, ok=False, error=str(e))


def _parse_flow_table(html: str) -> list[EtfFlowRow]:
    """
    Parse the net-flow total column from Farside's HTML table.
    Farside format varies; we look for rows with a date pattern and a numeric total.
    """
    rows: list[EtfFlowRow] = []
    date_pattern = re.compile(r"\b(\d{1,2}\s+\w+\s+\d{4}|\d{4}-\d{2}-\d{2}|\d{2}/\d{2}/\d{4})\b")
    number_pattern = re.compile(r"-?\d[\d,]*\.?\d*")

    # Try to find table rows with a date and a numeric total
    # Look for <tr> rows containing both a date and numbers
    row_pattern = re.compile(r"<tr[^>]*>(.*?)</tr>", re.IGNORECASE | re.DOTALL)
    cell_pattern = re.compile(r"<t[dh][^>]*>(.*?)</t[dh]>", re.IGNORECASE | re.DOTALL)
    tag_strip = re.compile(r"<[^>]+>")

    for row_match in row_pattern.finditer(html):
        cells = [tag_strip.sub("", c.group(1)).strip()
                 for c in cell_pattern.finditer(row_match.group(1))]
        if len(cells) < 3:
            continue

        # First cell should be a date
        date_str = _parse_date(cells[0])
        if not date_str:
            continue

        # Last numeric cell is typically the total
        total_str = None
        for cell in reversed(cells[1:]):
            clean = cell.replace(",", "").replace("(", "-").replace(")", "")
            if number_pattern.fullmatch(clean.strip()):
                total_str = clean.strip()
                break

        if total_str is not None:
            try:
                rows.append(EtfFlowRow(date_str=date_str, net_flow_m=float(total_str)))
            except ValueError:
                continue

    # Return most recent 30 rows, chronologically ascending
    rows = rows[-30:]
    return rows


def _parse_date(raw: str) -> Optional[str]:
    """Try to normalise a date string to YYYY-MM-DD."""
    raw = raw.strip()
    for fmt in ("%d %b %Y", "%d %B %Y", "%Y-%m-%d", "%m/%d/%Y", "%d/%m/%Y"):
        try:
            return datetime.strptime(raw, fmt).strftime("%Y-%m-%d")
        except ValueError:
            continue
    return None


def compute_etf_flow_subscore(result: EtfFlowResult) -> tuple[float, dict, float]:
    """
    Returns (subscore, summary_dict, confidence_penalty).
    subscore ∈ [-0.20, +0.20].
    confidence_penalty: 0.15 if fetch failed, else 0.0.
    """
    summary: dict = {"fetch_ok": result.ok, "rows_available": len(result.rows)}

    if not result.ok or not result.rows:
        return 0.0, summary, 0.15  # non-fatal; reduce confidence

    flows = [r.net_flow_m for r in result.rows]
    latest = flows[-1]
    rolling_mean = sum(flows) / len(flows)
    rolling_std = (sum((f - rolling_mean) ** 2 for f in flows) / len(flows)) ** 0.5

    summary["latest_flow_m"] = latest
    summary["rolling_mean_m"] = round(rolling_mean, 2)
    summary["days"] = len(flows)

    if rolling_std < 1e-6:
        return 0.0, summary, 0.0

    z = (latest - rolling_mean) / rolling_std
    summary["z_score"] = round(z, 3)

    # Cap z at ±2 sigma → map to ±0.20
    score = max(-0.20, min(0.20, z * 0.10))
    return score, summary, 0.0
