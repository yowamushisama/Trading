"""RSS feed ingestor for crypto news sources."""

from __future__ import annotations

import ssl
from dataclasses import dataclass
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime

from loguru import logger

RSS_FEEDS = {
    "coindesk": "https://www.coindesk.com/arc/outboundfeeds/rss/",
    "theblock": "https://www.theblock.co/rss.xml",
    "bitcoinmagazine": "https://bitcoinmagazine.com/.rss/full/",
    "decrypt": "https://decrypt.co/feed",
}


@dataclass
class RawNewsItem:
    source: str
    url: str
    title: str
    body: str
    published_at: datetime | None


def fetch_rss_items(source: str, feed_url: str) -> list[RawNewsItem]:
    try:
        import feedparser
        feed = feedparser.parse(feed_url)
        items = []
        for entry in feed.entries[:20]:
            pub = None
            if hasattr(entry, "published"):
                try:
                    pub = parsedate_to_datetime(entry.published).astimezone(timezone.utc)
                except Exception:
                    pass
            items.append(
                RawNewsItem(
                    source=source,
                    url=entry.get("link", ""),
                    title=entry.get("title", ""),
                    body=entry.get("summary", ""),
                    published_at=pub,
                )
            )
        return items
    except Exception as e:
        logger.warning(f"RSS fetch failed for {source}: {e}")
        return []


def fetch_all_feeds() -> list[RawNewsItem]:
    items = []
    for source, url in RSS_FEEDS.items():
        items.extend(fetch_rss_items(source, url))
    return items
