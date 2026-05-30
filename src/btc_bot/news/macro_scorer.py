"""Macro news scorer — deterministic daily BTC macro signal.

Architecture
------------
Final score = clamp(sum of 6 bounded sub-scores, -1, 1).

  rates_subscore         [-0.25, +0.25]  FRED series
  event_risk_subscore    [-0.20,  0.00]  upcoming FOMC/CPI/NFP proximity
  geopolitical_subscore  [-0.30, +0.05]  GDELT conflict events
  etf_flow_subscore      [-0.20, +0.20]  Farside BTC ETF net flows
  crypto_news_subscore   [-0.15, +0.15]  existing keyword tagger on last 24h crypto news
  llm_narrative_subscore [-0.15, +0.15]  LLM contribution HARD CAPPED to ±0.15

The LLM's numeric sub-score is a tilt signal only; the LLM cannot move the
final score outside deterministic guardrails. Confidence is computed in Python
from input availability; the LLM does NOT set confidence.

Phase 1: compute + persist + log. NO effect on trades.
Phase 2 (future): enable sizing multiplier in risk/engine.py via MACRO_SIZING_ENABLED.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Optional

from loguru import logger

from btc_bot.llm.base import COMMENTARY_SYSTEM_PROMPT
from btc_bot.news.macro.calendar import CalendarResult, compute_event_risk_subscore, fetch_official_calendar
from btc_bot.news.macro.etf_flows import EtfFlowResult, compute_etf_flow_subscore, fetch_farside_btc_etf_flows
from btc_bot.news.macro.feeds import fetch_macro_feeds
from btc_bot.news.macro.fred import FredClient, compute_rate_subscore
from btc_bot.news.macro.gdelt import GdeltFetchResult, compute_geopolitical_subscore, fetch_gdelt_events

SCORE_SCHEMA_VERSION = 1
LLM_SUBSCORE_CAP = 0.15


@dataclass
class SubScores:
    rates: float = 0.0
    event_risk: float = 0.0
    geopolitical: float = 0.0
    etf_flow: float = 0.0
    crypto_news: float = 0.0
    llm_narrative: float = 0.0

    def total(self) -> float:
        return self.rates + self.event_risk + self.geopolitical + self.etf_flow + self.crypto_news + self.llm_narrative


@dataclass
class MacroScoreResult:
    computed_at_utc: datetime
    final_score: float           # clamped [-1, +1]
    direction: str               # "bearish" | "neutral" | "bullish"
    confidence: float            # [0, 1] — deterministic, not from LLM
    subscores: SubScores
    drivers: list[str]
    rates_snapshot: dict
    top_headlines: list[dict]
    gdelt_summary: dict
    etf_summary: dict
    calendar_summary: dict
    llm_provider: str
    llm_model: str
    llm_prompt_hash: str
    llm_raw_response: str
    score_schema_version: int = SCORE_SCHEMA_VERSION

    def to_log_dict(self) -> dict:
        return {
            "computed_at": self.computed_at_utc.isoformat(),
            "final_score": self.final_score,
            "direction": self.direction,
            "confidence": self.confidence,
            "subscores": {
                "rates": self.subscores.rates,
                "event_risk": self.subscores.event_risk,
                "geopolitical": self.subscores.geopolitical,
                "etf_flow": self.subscores.etf_flow,
                "crypto_news": self.subscores.crypto_news,
                "llm_narrative": self.subscores.llm_narrative,
            },
            "drivers": self.drivers,
        }


class MacroScorer:
    """Fetches all macro inputs and produces a MacroScoreResult."""

    def __init__(
        self,
        fred_api_key: str,
        llm_provider=None,
        llm_model: str = "",
    ) -> None:
        self._fred = FredClient(fred_api_key)
        self._llm = llm_provider
        self._llm_model = llm_model

    def compute(self, session=None) -> MacroScoreResult:
        """Fetch all sources and return the daily macro score."""
        computed_at = datetime.now(timezone.utc)
        confidence = 1.0
        drivers: list[str] = []
        inputs_payload: list[dict] = []

        # ── 1. FRED rates ─────────────────────────────────────────────────────
        fred_results = self._fred.fetch_all_rate_series(days=60)
        rates_score, rates_snapshot = compute_rate_subscore(fred_results)
        inputs_payload.append({
            "source": "fred",
            "fetched_at": computed_at.isoformat(),
            "ok": all(r.ok for r in fred_results.values()),
            "payload": {
                sid: {
                    "ok": r.ok,
                    "observations": [{"date": o.date, "value": o.value}
                                     for o in r.observations[-5:]] if r.ok else [],
                    "error": r.error,
                }
                for sid, r in fred_results.items()
            },
        })
        if not all(r.ok for r in fred_results.values()):
            confidence -= 0.10
            drivers.append("FRED partial failure — rates subscore may be incomplete")

        # ── 2. Economic calendar ──────────────────────────────────────────────
        cal_result = fetch_official_calendar(days_ahead=7)
        event_risk_score, cal_summary = compute_event_risk_subscore(cal_result)
        inputs_payload.append({
            "source": "calendar",
            "fetched_at": computed_at.isoformat(),
            "ok": cal_result.ok,
            "payload": cal_summary,
        })
        if cal_result.events and cal_result.events[0].hours_away < 48:
            drivers.append(
                f"High-impact event in {cal_result.events[0].hours_away:.0f}h "
                f"({cal_result.events[0].name})"
            )

        # ── 3. GDELT geopolitics ──────────────────────────────────────────────
        gdelt_result = fetch_gdelt_events(hours=24)
        geo_score, gdelt_summary = compute_geopolitical_subscore(gdelt_result)
        inputs_payload.append({
            "source": "gdelt",
            "fetched_at": computed_at.isoformat(),
            "ok": gdelt_result.ok,
            "payload": gdelt_summary,
        })
        if not gdelt_result.ok:
            confidence -= 0.10
            drivers.append("GDELT fetch failed — geopolitical sub-score is 0")
        elif gdelt_result.events:
            drivers.append(f"GDELT: {len(gdelt_result.events)} high-impact conflict events")

        # ── 4. ETF flows ──────────────────────────────────────────────────────
        etf_result = fetch_farside_btc_etf_flows()
        etf_score, etf_summary, etf_confidence_penalty = compute_etf_flow_subscore(etf_result)
        confidence -= etf_confidence_penalty
        inputs_payload.append({
            "source": "etf",
            "fetched_at": computed_at.isoformat(),
            "ok": etf_result.ok,
            "payload": etf_summary,
        })
        if etf_result.ok and abs(etf_score) > 0.08:
            direction_str = "inflow" if etf_score > 0 else "outflow"
            drivers.append(f"ETF flow {direction_str} (z={etf_summary.get('z_score', '?')})")

        # ── 5. Crypto news (reuse existing tagger) ────────────────────────────
        macro_feeds = fetch_macro_feeds()
        inputs_payload.append({
            "source": "rss",
            "fetched_at": computed_at.isoformat(),
            "ok": True,
            "payload": {
                "macro_headlines_count": len(macro_feeds),
                "headlines": [
                    {"title": it.title, "url": it.url,
                     "published_at": it.published_at.isoformat() if it.published_at else None}
                    for it in macro_feeds[:20]
                ],
            },
        })
        if len(macro_feeds) < 10:
            confidence -= 0.10
            drivers.append(f"Only {len(macro_feeds)} macro headlines fetched")

        crypto_score, crypto_headlines = _crypto_news_subscore(session)
        inputs_payload.append({
            "source": "cryptopanic",
            "fetched_at": computed_at.isoformat(),
            "ok": True,
            "payload": {"count": len(crypto_headlines)},
        })

        # ── 6. LLM narrative sub-score ────────────────────────────────────────
        llm_provider_name = ""
        llm_model_name = self._llm_model
        llm_raw = ""
        llm_score = 0.0
        llm_prompt = _build_llm_prompt(
            macro_feeds=macro_feeds,
            rates_snapshot=rates_snapshot,
            gdelt_summary=gdelt_summary,
            etf_summary=etf_summary,
            cal_summary=cal_summary,
        )
        llm_prompt_hash = hashlib.sha256(llm_prompt.encode()).hexdigest()[:16]

        if self._llm is not None:
            llm_provider_name = type(self._llm).__name__
            try:
                system = (
                    "You are a macro analyst. Your numeric score is capped at ±0.15 and used "
                    "only as a minor narrative tilt — deterministic code controls the final score. "
                    "Return ONLY valid JSON: {\"score\": <float -0.15 to 0.15>, \"summary\": \"...\", "
                    "\"drivers\": [\"...\"], \"caveats\": \"...\"}"
                )
                llm_raw = self._llm.complete(system, llm_prompt, max_tokens=400)
                parsed = json.loads(llm_raw.strip())
                raw_score = float(parsed.get("score", 0.0))
                llm_score = max(-LLM_SUBSCORE_CAP, min(LLM_SUBSCORE_CAP, raw_score))
                if parsed.get("drivers"):
                    drivers.extend(parsed["drivers"][:3])
            except Exception as e:
                logger.warning(f"LLM macro scoring failed (non-fatal): {e}")
                llm_score = 0.0
                confidence -= 0.05

        # ── Assemble final score ──────────────────────────────────────────────
        subscores = SubScores(
            rates=round(rates_score, 4),
            event_risk=round(event_risk_score, 4),
            geopolitical=round(geo_score, 4),
            etf_flow=round(etf_score, 4),
            crypto_news=round(crypto_score, 4),
            llm_narrative=round(llm_score, 4),
        )
        raw_total = subscores.total()
        final_score = round(max(-1.0, min(1.0, raw_total)), 4)

        if final_score >= 0.15:
            direction = "bullish"
        elif final_score <= -0.15:
            direction = "bearish"
        else:
            direction = "neutral"

        confidence = round(max(0.0, min(1.0, confidence)), 3)

        result = MacroScoreResult(
            computed_at_utc=computed_at,
            final_score=final_score,
            direction=direction,
            confidence=confidence,
            subscores=subscores,
            drivers=drivers[:10],
            rates_snapshot=rates_snapshot,
            top_headlines=[
                {"title": it.title, "url": it.url}
                for it in macro_feeds[:10]
            ],
            gdelt_summary=gdelt_summary,
            etf_summary=etf_summary,
            calendar_summary=cal_summary,
            llm_provider=llm_provider_name,
            llm_model=llm_model_name,
            llm_prompt_hash=llm_prompt_hash,
            llm_raw_response=llm_raw,
        )

        logger.info(
            f"MacroScorer: final_score={final_score:+.3f} ({direction}) "
            f"confidence={confidence:.2f} | "
            f"rates={subscores.rates:+.3f} "
            f"event_risk={subscores.event_risk:+.3f} "
            f"geo={subscores.geopolitical:+.3f} "
            f"etf={subscores.etf_flow:+.3f} "
            f"crypto={subscores.crypto_news:+.3f} "
            f"llm={subscores.llm_narrative:+.3f}"
        )

        # Persist to DB if session provided
        if session is not None:
            _persist_score(session, result, inputs_payload)

        return result


def _crypto_news_subscore(session=None) -> tuple[float, list]:
    """
    Read last-24h news_items from DB and compute a subscore via keyword tagger counts.
    Returns (subscore, headlines). Falls back to 0.0 if no DB session.
    """
    if session is None:
        return 0.0, []

    try:
        from datetime import timedelta
        from btc_bot.storage.repos import get_recent_high_impact_news
        from btc_bot.utils.time import utcnow

        cutoff = utcnow() - timedelta(hours=24)
        with session() as s:
            items = (
                s.query(__import__("btc_bot.storage.models", fromlist=["NewsItem"]).NewsItem)
                .filter(
                    __import__("btc_bot.storage.models", fromlist=["NewsItem"]).NewsItem.published_at >= cutoff
                )
                .limit(200)
                .all()
            )

        neg_count = sum(1 for it in items if it.sentiment_score and it.sentiment_score < -0.5)
        pos_count = sum(1 for it in items if it.sentiment_score and it.sentiment_score > 0.5)
        total = len(items)
        if total == 0:
            return 0.0, []

        # More negative items → negative score
        net = (pos_count - neg_count) / max(total, 1)
        score = max(-0.15, min(0.15, net * 0.30))
        return score, items[:10]
    except Exception as e:
        logger.debug(f"crypto_news_subscore DB query failed: {e}")
        return 0.0, []


def _build_llm_prompt(
    macro_feeds,
    rates_snapshot: dict,
    gdelt_summary: dict,
    etf_summary: dict,
    cal_summary: dict,
) -> str:
    headlines = "\n".join(
        f"- {it.title}" for it in macro_feeds[:20]
    ) or "No macro headlines available."

    return (
        f"Macro snapshot for BTC/USD signal analysis.\n\n"
        f"## US Rates\n{json.dumps(rates_snapshot, indent=2)}\n\n"
        f"## Upcoming Calendar Events\n{json.dumps(cal_summary, indent=2)}\n\n"
        f"## Geopolitical Events (GDELT)\n{json.dumps(gdelt_summary, indent=2)}\n\n"
        f"## BTC ETF Flows\n{json.dumps(etf_summary, indent=2)}\n\n"
        f"## Top Macro Headlines\n{headlines}\n\n"
        f"Score the macro environment for BTC. "
        f"Return JSON: {{\"score\": <float -0.15 to 0.15>, \"summary\": \"...\", "
        f"\"drivers\": [\"...\"], \"caveats\": \"...\"}}"
    )


def _persist_score(session, result: MacroScoreResult, inputs_payload: list[dict]) -> None:
    """Persist score and raw inputs to DB via repos."""
    try:
        from btc_bot.storage.repos import insert_macro_score, insert_macro_inputs
        with session() as s:
            score_id = insert_macro_score(s, result)
            insert_macro_inputs(s, score_id, inputs_payload)
    except Exception as e:
        logger.error(f"MacroScorer DB persist failed: {e}")
