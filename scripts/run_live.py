"""Live trading runner — refuses to start without both safety flags.

Usage:
    py -3.11 scripts/run_live.py

Required in .env:
    MODE=live
    LIVE_TRADING_ENABLED=true
    I_UNDERSTAND_LIVE_TRADING_RISK=true
    LIVE_API_KEY=<real key>
    LIVE_API_SECRET=<real secret>
    BINANCE_TESTNET=false
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from btc_bot.utils.logging import setup_logging


def main():
    # Import and validate config first — will raise if flags not set
    try:
        from btc_bot.config import Mode, get_settings
        settings = get_settings()
    except Exception as e:
        print(f"\n[BLOCKED] Live trading refused: {e}\n")
        sys.exit(1)

    setup_logging(settings.log_level, settings.log_file)

    if settings.mode != Mode.live:
        print(f"\n[BLOCKED] MODE={settings.mode.value}, expected MODE=live\n")
        sys.exit(1)

    if settings.binance_testnet:
        print("\n[WARNING] BINANCE_TESTNET=true is set — orders will go to testnet, not mainnet.\n")

    # Import live runner here to avoid loading exchange dependencies in backtest mode
    from btc_bot.live.runner import LiveRunner
    runner = LiveRunner(settings)
    runner.run()


if __name__ == "__main__":
    main()
