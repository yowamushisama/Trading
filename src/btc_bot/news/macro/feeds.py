"""Macro RSS feeds: Reuters, AP, Federal Reserve, US Treasury wire services."""

from __future__ import annotations

from btc_bot.news.rss import RawNewsItem, fetch_rss_items

MACRO_RSS_FEEDS: dict[str, str] = {
    "reuters_top": "https://feeds.reuters.com/reuters/topNews",
    "ap_top": "https://feeds.apnews.com/apnews/apf-topnews",
    "fed_pressreleases": "https://www.federalreserve.gov/feeds/press_all.xml",
    "us_treasury": "https://home.treasury.gov/system/files/rss-feeds/press-release.xml",
}


def fetch_macro_feeds() -> list[RawNewsItem]:
    """Fetch all macro wire RSS feeds, deduplicated by URL."""
    seen: set[str] = set()
    items: list[RawNewsItem] = []
    for source, url in MACRO_RSS_FEEDS.items():
        for item in fetch_rss_items(source, url):
            if item.url and item.url not in seen:
                seen.add(item.url)
                items.append(item)
    return items
