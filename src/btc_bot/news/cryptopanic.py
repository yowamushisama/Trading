"""CryptoPanic free-tier client. Budget: 60 requests/day."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone

import httpx
from loguru import logger

BASE_URL = "https://cryptopanic.com/api/v1/posts/"


@dataclass
class CryptoPanicItem:
    url: str
    title: str
    published_at: datetime | None
    votes_negative: int
    votes_positive: int


def fetch_cryptopanic(token: str, currency: str = "BTC", limit: int = 20) -> list[CryptoPanicItem]:
    if not token:
        return []
    try:
        resp = httpx.get(
            BASE_URL,
            params={"auth_token": token, "currencies": currency, "public": "true"},
            timeout=10,
            verify=False,  # Windows SSL workaround
        )
        resp.raise_for_status()
        data = resp.json()
        items = []
        for post in data.get("results", [])[:limit]:
            pub = None
            if post.get("published_at"):
                try:
                    pub = datetime.fromisoformat(
                        post["published_at"].replace("Z", "+00:00")
                    ).astimezone(timezone.utc)
                except Exception:
                    pass
            votes = post.get("votes", {})
            items.append(
                CryptoPanicItem(
                    url=post.get("url", ""),
                    title=post.get("title", ""),
                    published_at=pub,
                    votes_negative=votes.get("negative", 0),
                    votes_positive=votes.get("positive", 0),
                )
            )
        return items
    except Exception as e:
        logger.warning(f"CryptoPanic fetch failed: {e}")
        return []
