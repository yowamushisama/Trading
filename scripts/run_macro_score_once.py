"""One-shot macro score computation for manual testing and validation.

Usage:
    set PYTHONPATH=src
    py -3.11 scripts/run_macro_score_once.py

Fetches all macro sources, computes and persists a score, then prints the
full result as JSON so you can inspect it before paper trading.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))


def main() -> None:
    from btc_bot.config import get_settings
    from btc_bot.news.macro_scorer import MacroScorer
    from btc_bot.storage import db as _db

    settings = get_settings()

    if not settings.macro_news_enabled:
        print(
            "MACRO_NEWS_ENABLED is false in your .env.\n"
            "Set it to true and provide FRED_API_KEY to run this script."
        )
        sys.exit(1)

    _db.init_db(settings.database_url)

    from btc_bot.llm.factory import create_llm_provider
    llm = create_llm_provider(settings)

    scorer = MacroScorer(
        fred_api_key=settings.fred_api_key,
        llm_provider=llm,
        llm_model=settings.llm_model,
    )

    print("Computing macro score (this may take 15-30s)...")
    result = scorer.compute(session=_db.get_session)

    output = {
        "computed_at_utc": result.computed_at_utc.isoformat(),
        "final_score": result.final_score,
        "direction": result.direction,
        "confidence": result.confidence,
        "subscores": {
            "rates": result.subscores.rates,
            "event_risk": result.subscores.event_risk,
            "geopolitical": result.subscores.geopolitical,
            "etf_flow": result.subscores.etf_flow,
            "crypto_news": result.subscores.crypto_news,
            "llm_narrative": result.subscores.llm_narrative,
        },
        "drivers": result.drivers,
        "rates_snapshot": result.rates_snapshot,
        "gdelt_summary": result.gdelt_summary,
        "etf_summary": result.etf_summary,
        "calendar_summary": result.calendar_summary,
        "llm_provider": result.llm_provider,
        "llm_model": result.llm_model,
        "llm_prompt_hash": result.llm_prompt_hash,
    }
    print(json.dumps(output, indent=2))
    print("\nScore persisted to DB. Use check_db.py to verify.")


if __name__ == "__main__":
    main()
