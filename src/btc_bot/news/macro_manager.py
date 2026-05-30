"""MacroNewsManager — background thread that computes the daily macro score.

Computes once per day at MACRO_NEWS_COMPUTE_HOUR_UTC (default 00:00 UTC).
On boot, loads the latest score from DB; recomputes immediately if stale
(older than MACRO_SCORE_STALE_HOURS).

Phase 1: observe-only. current_score is readable by runners for logging
but is NOT wired into risk/engine.py or sizing.
"""

from __future__ import annotations

import threading
from datetime import datetime, timezone
from typing import Optional

from loguru import logger

from btc_bot.news.macro_scorer import MacroScoreResult, MacroScorer


class MacroNewsManager:
    def __init__(
        self,
        fred_api_key: str,
        session_factory=None,
        compute_hour_utc: int = 0,
        stale_hours: int = 30,
        llm_provider=None,
        llm_model: str = "",
    ) -> None:
        self._scorer = MacroScorer(
            fred_api_key=fred_api_key,
            llm_provider=llm_provider,
            llm_model=llm_model,
        )
        self._session = session_factory
        self._compute_hour = compute_hour_utc
        self._stale_hours = stale_hours
        self._current_score: Optional[MacroScoreResult] = None
        self._stop = threading.Event()
        self._thread: Optional[threading.Thread] = None

    @property
    def current_score(self) -> Optional[MacroScoreResult]:
        return self._current_score

    def is_stale(self) -> bool:
        if self._current_score is None:
            return True
        age_h = (datetime.now(timezone.utc) - self._current_score.computed_at_utc).total_seconds() / 3600
        return age_h > self._stale_hours

    def start(self) -> None:
        # Try to load last score from DB before starting the thread
        self._load_from_db()

        if self.is_stale():
            logger.info("MacroNewsManager: no recent score — computing immediately on start")
            self._compute_and_store()

        self._stop.clear()
        self._thread = threading.Thread(target=self._run, daemon=True, name="MacroNewsManager")
        self._thread.start()
        logger.info("MacroNewsManager started")

    def stop(self) -> None:
        self._stop.set()

    def _run(self) -> None:
        while not self._stop.is_set():
            now = datetime.now(timezone.utc)
            # Wake at the next compute hour
            next_wake = self._seconds_until_next_compute(now)
            if self._stop.wait(timeout=next_wake):
                break
            if not self._stop.is_set():
                self._compute_and_store()

    def _compute_and_store(self) -> None:
        try:
            result = self._scorer.compute(session=self._session)
            self._current_score = result
            logger.info(
                f"MacroNewsManager: new score computed "
                f"score={result.final_score:+.3f} ({result.direction}) "
                f"confidence={result.confidence:.2f} "
                f"drivers={result.drivers[:3]}"
            )
        except Exception as e:
            logger.error(f"MacroNewsManager compute failed: {e}")

    def _load_from_db(self) -> None:
        if self._session is None:
            return
        try:
            from btc_bot.storage.repos import get_latest_macro_score
            with self._session() as s:
                row = get_latest_macro_score(s)
            if row is not None:
                from btc_bot.news.macro_scorer import SubScores
                self._current_score = MacroScoreResult(
                    computed_at_utc=row.computed_at_utc,
                    final_score=float(row.final_score),
                    direction=row.direction,
                    confidence=float(row.confidence),
                    subscores=SubScores(**row.subscores) if isinstance(row.subscores, dict) else SubScores(),
                    drivers=row.drivers or [],
                    rates_snapshot=row.rates_snapshot or {},
                    top_headlines=row.top_headlines or [],
                    gdelt_summary=row.gdelt_summary or {},
                    etf_summary=row.etf_summary or {},
                    calendar_summary=row.calendar_summary or {},
                    llm_provider=row.llm_provider or "",
                    llm_model=row.llm_model or "",
                    llm_prompt_hash=row.llm_prompt_hash or "",
                    llm_raw_response=row.llm_raw_response or "",
                    score_schema_version=row.score_schema_version,
                )
                logger.info(
                    f"MacroNewsManager: loaded score from DB "
                    f"computed_at={row.computed_at_utc.isoformat()} "
                    f"score={float(row.final_score):+.3f}"
                )
        except Exception as e:
            logger.debug(f"MacroNewsManager DB load failed (non-fatal): {e}")

    def _seconds_until_next_compute(self, now: datetime) -> float:
        """Seconds until the next daily compute hour."""
        target = now.replace(hour=self._compute_hour, minute=0, second=0, microsecond=0)
        from datetime import timedelta
        if target <= now:
            target += timedelta(days=1)
        return max(60.0, (target - now).total_seconds())
