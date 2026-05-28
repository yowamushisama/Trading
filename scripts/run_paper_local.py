"""Paper trading runner (paper_local mode).

Usage:
    py -3.11 scripts/run_paper_local.py

Requires DATABASE_URL in .env (or backtest mode for no DB).
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from btc_bot.config import Mode, get_settings
from btc_bot.paper.runner import PaperRunner
from btc_bot.utils.logging import setup_logging


def main():
    settings = get_settings()
    setup_logging(settings.log_level, settings.log_file)

    if settings.mode not in (Mode.paper_local, Mode.paper_testnet):
        print(f"Mode is {settings.mode.value}. Set MODE=paper_local in .env to run paper trading.")
        sys.exit(1)

    runner = PaperRunner(settings)
    runner.run()


if __name__ == "__main__":
    main()
