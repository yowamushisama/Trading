"""News ingestion pipeline: fetch → deduplicate → tag → persist → check pause."""

from __future__ import annotations

import threading
import time
from datetime import datetime, timedelta, timezone

from loguru import logger
from sqlalchemy.orm import Session

from btc_bot.news.cryptopanic import fetch_cryptopanic
from btc_bot.news.rss import fetch_all_feeds
from btc_bot.news.tagger_keyword import tag_item
from btc_bot.storage.repos import get_recent_high_impact_news, upsert_news_item
from btc_bot.utils.time import utcnow


class NewsManager:
    """Polls feeds, tags items, persists to DB, exposes is_paused() for risk engine."""

    def __init__(
        self,
        session_factory,
        cryptopanic_token: str = "",
        poll_interval_seconds: int = 900,  # 15 min
        cooldown_minutes: int = 30,
        news_tagger: str = "keyword",
        llm_provider=None,
    ) -> None:
        self.session_factory = session_factory
        self.cryptopanic_token = cryptopanic_token
        self.poll_interval = poll_interval_seconds
        self.cooldown_minutes = cooldown_minutes
        self.news_tagger = news_tagger
        self.llm_provider = llm_provider
        self._pause_until: datetime | None = None
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    @property
    def is_paused(self) -> bool:
        if self._pause_until is None:
            return False
        return utcnow() < self._pause_until

    def start(self) -> None:
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, daemon=True, name="NewsManager")
        self._thread.start()
        logger.info("NewsManager started")

    def stop(self) -> None:
        self._stop.set()

    def _run(self) -> None:
        while not self._stop.is_set():
            try:
                self._poll_once()
            except Exception as e:
                logger.error(f"NewsManager poll error: {e}")
            self._stop.wait(timeout=self.poll_interval)

    def _poll_once(self) -> None:
        items: list = []
        items.extend(fetch_all_feeds())

        if self.cryptopanic_token:
            from btc_bot.news.rss import RawNewsItem as _RN
            cp_items = fetch_cryptopanic(self.cryptopanic_token)
            for cp in cp_items:
                items.append(type("_Item", (), {
                    "source": "cryptopanic",
                    "url": cp.url,
                    "title": cp.title,
                    "body": "",
                    "published_at": cp.published_at,
                })())

        new_count = high_impact_count = 0
        with self.session_factory() as session:
            for item in items:
                if not getattr(item, "url", ""):
                    continue

                tag_result = tag_item(item.title, getattr(item, "body", "") or "")

                # Optional LLM enrichment (advisory only — never overrides keyword tagger)
                if self.llm_provider and self.news_tagger == "llm":
                    try:
                        from btc_bot.llm.base import COMMENTARY_SYSTEM_PROMPT
                        prompt = (
                            f"Classify this crypto news headline. "
                            f"Reply with one of: regulatory|hack|exchange-outage|etf-flow|macro-event|neutral\n\n"
                            f"Title: {item.title}"
                        )
                        llm_tag = self.llm_provider.complete(COMMENTARY_SYSTEM_PROMPT, prompt, max_tokens=20)
                        llm_tag = llm_tag.strip().lower().split("\n")[0]
                        if llm_tag not in tag_result.tags:
                            tag_result.tags.append(f"llm:{llm_tag}")
                    except Exception as e:
                        logger.debug(f"LLM tagging failed: {e}")

                _, is_new = upsert_news_item(
                    session,
                    source=item.source,
                    url=item.url,
                    title=item.title,
                    body=getattr(item, "body", "") or "",
                    published_at=item.published_at,
                    tags=tag_result.tags,
                    sentiment_score=tag_result.sentiment,
                    tagger=self.news_tagger,
                )
                if is_new:
                    new_count += 1
                    if tag_result.is_high_impact_negative:
                        high_impact_count += 1
                        logger.warning(
                            f"HIGH-IMPACT-NEGATIVE news: {item.title[:80]} "
                            f"tags={tag_result.tags}"
                        )

        if high_impact_count > 0:
            self._pause_until = utcnow() + timedelta(minutes=self.cooldown_minutes)
            logger.warning(
                f"News pause activated until {self._pause_until.strftime('%H:%M:%S UTC')} "
                f"({self.cooldown_minutes}m cooldown)"
            )

        if new_count:
            logger.info(f"NewsManager: {new_count} new items, {high_impact_count} high-impact")

    def poll_now(self) -> None:
        """Force an immediate poll (call from main thread for testing)."""
        self._poll_once()
