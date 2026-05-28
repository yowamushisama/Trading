"""Backtest runner script.

Usage:
    py -3.11 scripts/run_backtest.py --strategy scalper --from 2023-01-01 --to 2025-01-01
    py -3.11 scripts/run_backtest.py --strategy scalper --walk-forward
    py -3.11 scripts/run_backtest.py --strategy scalper --stress
"""

from __future__ import annotations

import argparse
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from loguru import logger

from btc_bot.backtest.metrics import BacktestMetrics
from btc_bot.backtest.runner import BacktestConfig, BacktestRunner
from btc_bot.backtest.walk_forward import run_walk_forward
from btc_bot.data.candles import detect_gaps, deduplicate, validate_ohlcv
from btc_bot.data.rest import fetch_candles_ccxt
from btc_bot.strategy.scalper import ScalperStrategy
from btc_bot.strategy.swing import SwingStrategy
from btc_bot.utils.logging import setup_logging


def parse_args():
    p = argparse.ArgumentParser()
    p.add_argument("--strategy", choices=["scalper", "swing"], default="scalper")
    p.add_argument("--from", dest="from_date", default="2023-01-01")
    p.add_argument("--to", dest="to_date", default="2025-01-01")
    p.add_argument("--stress", action="store_true")
    p.add_argument("--walk-forward", action="store_true")
    p.add_argument("--equity", type=float, default=10_000.0)
    return p.parse_args()


def fetch(symbol: str, tf: str, since: datetime, until: datetime):
    logger.info(f"Fetching {symbol} {tf} {since.date()} → {until.date()}")
    df = fetch_candles_ccxt("binance", symbol, tf, since, until, pause_ms=200)
    df = deduplicate(df)
    df = validate_ohlcv(df)
    gaps = detect_gaps(df, tf)
    if gaps:
        logger.warning(f"{tf}: {len(gaps)} gaps detected")
    return df


def main():
    setup_logging()
    args = parse_args()

    since = datetime.fromisoformat(args.from_date).replace(tzinfo=timezone.utc)
    until = datetime.fromisoformat(args.to_date).replace(tzinfo=timezone.utc)

    symbol = "BTC/USDT"
    strategy_name = args.strategy

    if strategy_name == "scalper":
        strategy = ScalperStrategy()
        exec_tf, confirm_tf, regime_tf = "5m", "15m", "1h"
    else:
        strategy = SwingStrategy()
        exec_tf, confirm_tf, regime_tf = "4h", "1d", "1w"

    exec_df = fetch(symbol, exec_tf, since, until)
    confirm_df = fetch(symbol, confirm_tf, since, until)
    regime_df = fetch(symbol, regime_tf, since, until)

    config = BacktestConfig(initial_equity=args.equity)

    if args.walk_forward:
        logger.info("Running walk-forward test...")
        result = run_walk_forward(strategy, exec_df, confirm_df, regime_df, config)
        logger.info(f"Walk-forward avg OOS PF: {result.avg_oos_pf:.2f}")
        logger.info(f"Passes (all OOS PF > 1.0): {result.passes}")
        for start, end, m in result.windows:
            logger.info(f"  {start.date()} → {end.date()}: {m.summary()}")
        return

    runner = BacktestRunner(strategy, config, exec_df, confirm_df, regime_df)
    metrics = runner.run(stress=args.stress)
    label = "STRESS" if args.stress else "BASE"
    logger.info(f"\n{'=' * 60}")
    logger.info(f"  {strategy_name.upper()} BACKTEST [{label}]")
    logger.info(f"{'=' * 60}")
    logger.info(f"  {metrics.summary()}")
    logger.info(f"{'=' * 60}")

    passed, failures = metrics.passes_stress_test()
    if passed:
        logger.info("✓ Stress test PASSED — strategy eligible for paper trading.")
    else:
        logger.error(f"✗ Stress test FAILED: {', '.join(failures)}")
        sys.exit(1)


if __name__ == "__main__":
    main()
