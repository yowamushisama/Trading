"""Paper trading runner (paper_local mode).

Fetches live BTC candles via REST, runs strategy + risk pipeline,
simulates fills via PaperLocalAdapter, persists everything to Supabase.
"""

from __future__ import annotations

import hashlib
import json
import time
from dataclasses import replace
from datetime import datetime, timedelta, timezone

from loguru import logger

from btc_bot.config import Settings
from btc_bot.data.candles import deduplicate, detect_gaps, validate_ohlcv
from btc_bot.data.rest import fetch_candles_ccxt
from btc_bot.exchange.paper_local import PaperLocalAdapter
from btc_bot.execution.idempotency import make_client_order_id, make_list_client_id
from btc_bot.llm.commentary import Commentary
from btc_bot.llm.factory import create_llm_provider
from btc_bot.news.ingest import NewsManager
from btc_bot.risk.account import AccountLimits, AccountState, record_trade_result
from btc_bot.risk.engine import RiskEngine
from btc_bot.risk.fees import FeeEstimate
from btc_bot.risk.kill_switch import KillSwitchState
from btc_bot.storage import db as _db
from btc_bot.storage.repos import (
    log_risk_event,
    open_trade,
    save_signal,
    set_state,
    start_strategy_run,
    end_strategy_run,
    upsert_daily_performance,
)
from btc_bot.strategy.scalper import ScalperStrategy
from btc_bot.strategy.swing import SwingStrategy
from btc_bot.utils.halt import is_halted
from btc_bot.utils.time import utcnow


def _config_hash(settings: Settings) -> str:
    data = {
        "risk_pct": settings.risk_per_trade_pct,
        "atr_k": settings.atr_stop_k,
        "min_rr": settings.min_rr,
        "strategies": settings.strategies_list,
    }
    return hashlib.md5(json.dumps(data, sort_keys=True).encode()).hexdigest()[:16]


class PaperRunner:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings

        # DB
        _db.init_db(settings.database_url)
        self._session = _db.get_session

        # Exchange sim
        self.adapter = PaperLocalAdapter(
            initial_usdt=10_000.0,
            fee_per_side_pct=settings.fee_per_side_pct,
        )
        self.kill_switch = KillSwitchState()

        # Account
        self.account = AccountState(
            equity=10_000.0,
            starting_equity_today=10_000.0,
            starting_equity_week=10_000.0,
            today=utcnow().date(),
        )
        self.limits = AccountLimits(
            daily_loss_cap_pct=settings.daily_loss_cap_pct,
            weekly_loss_cap_pct=settings.weekly_loss_cap_pct,
            max_consec_losses=settings.max_consec_losses,
            cooldown_hours=settings.consec_loss_cooldown_hours,
            max_open_positions=settings.max_open_positions,
            min_rr=settings.min_rr,
        )

        # LLM (optional)
        llm = create_llm_provider(settings)
        self.commentary = Commentary(llm)

        # News manager
        self.news_manager = NewsManager(
            session_factory=self._session,
            cryptopanic_token=settings.cryptopanic_token,
            cooldown_minutes=settings.news_cooldown_minutes,
            news_tagger=settings.news_tagger.value,
            llm_provider=llm,
        )

        # Risk engine
        self.engine = RiskEngine(
            account_limits=self.limits,
            fee_estimate=FeeEstimate(
                fee_per_side_pct=settings.fee_per_side_pct,
                slippage_buffer_pct=settings.slippage_buffer_pct,
            ),
            kill_switch=self.kill_switch,
            halt_file_path=settings.halt_file_path,
        )

        # Strategies (swing wins when both signal)
        self.strategies = []
        if "scalper" in settings.strategies_list:
            self.strategies.append(ScalperStrategy(
                atr_stop_k=settings.atr_stop_k, min_rr=settings.min_rr
            ))
        if "swing" in settings.strategies_list:
            self.strategies.append(SwingStrategy(
                atr_stop_k=settings.atr_stop_k, min_rr=settings.min_rr
            ))

        self._daily_stats: dict = {"trades": 0, "wins": 0, "losses": 0, "pnl": 0.0}
        self._run_ids: dict[str, int] = {}

    def run(self) -> None:
        logger.info(f"Paper trading started (paper_local) — strategies: {self.settings.strategies_list}")

        # Start news manager
        self.news_manager.start()

        # Register strategy runs in DB
        with self._session() as s:
            ch = _config_hash(self.settings)
            for strat in self.strategies:
                run = start_strategy_run(s, strat.name, "paper_local", ch)
                s.flush()
                self._run_ids[strat.name] = run.id

        filters = self.adapter.get_exchange_filters(self.settings.symbol)

        try:
            while True:
                if is_halted(self.settings.halt_file_path):
                    logger.warning("HALT detected — stopping paper runner.")
                    break
                if self.kill_switch.active:
                    logger.critical(f"Kill switch: {self.kill_switch.reason}. Stopping.")
                    self._write_risk_event("kill_switch_active", "critical",
                                           {"reason": self.kill_switch.reason.value})
                    break

                # Update risk engine with current news pause state
                self.engine.news_pause_active = self.news_manager.is_paused

                try:
                    self._loop_tick(filters)
                except Exception as e:
                    self.kill_switch.record_api_error()
                    logger.error(f"Loop error: {e}")

                time.sleep(30)
        finally:
            self.news_manager.stop()
            self._finalize_runs()

    def _loop_tick(self, filters) -> None:
        now = utcnow()
        signals = []

        for strategy in self.strategies:
            try:
                exec_df, confirm_df, regime_df = self._fetch_candles(strategy.name, now)
                if exec_df is None:
                    continue

                signal = strategy.on_candles(exec_df, confirm_df, regime_df)

                if signal is not None:
                    decision = self.engine.evaluate(
                        signal, self.account, filters, self.settings.risk_per_trade_pct
                    )
                    self._persist_signal(signal, decision)
                    if decision.allowed:
                        signals.append((strategy, signal, decision))
                        # LLM explanation (async log)
                        logger.info(
                            self.commentary.explain_signal(
                                strategy.name, True, "",
                                signal.entry, signal.stop, signal.target,
                                "regime", None,
                            )
                        )

            except Exception as e:
                logger.error(f"Strategy {strategy.name} error: {e}")

        # Execute highest-priority signal (swing > scalper)
        if signals and self.account.open_positions == 0:
            # Prefer swing over scalper
            chosen = next((s for s in signals if s[0].name == "swing"), signals[0])
            strategy, signal, decision = chosen
            self._execute_paper_trade(strategy.name, signal, decision, filters)

    def _fetch_candles(self, strategy_name: str, now):
        try:
            if strategy_name == "scalper":
                exec_df = fetch_candles_ccxt("binance", self.settings.symbol, "5m",
                                             now - timedelta(hours=24))
                confirm_df = fetch_candles_ccxt("binance", self.settings.symbol, "15m",
                                                now - timedelta(days=7))
                regime_df = fetch_candles_ccxt("binance", self.settings.symbol, "1h",
                                               now - timedelta(days=60))
            else:
                exec_df = fetch_candles_ccxt("binance", self.settings.symbol, "4h",
                                             now - timedelta(days=180))
                confirm_df = fetch_candles_ccxt("binance", self.settings.symbol, "1d",
                                                now - timedelta(days=365))
                regime_df = fetch_candles_ccxt("binance", self.settings.symbol, "1w",
                                               now - timedelta(days=1000))

            # Gap check
            exec_tf = "5m" if strategy_name == "scalper" else "4h"
            gaps = detect_gaps(exec_df, exec_tf)
            if len(gaps) > 2:
                self.kill_switch.record_missing_candle()
                logger.warning(f"{strategy_name}: {len(gaps)} candle gaps detected")
            else:
                self.kill_switch.missing_candle_count = 0

            return exec_df, confirm_df, regime_df
        except Exception as e:
            self.kill_switch.record_api_error()
            logger.error(f"Candle fetch error ({strategy_name}): {e}")
            return None, None, None

    def _execute_paper_trade(self, strategy_name, signal, decision, filters) -> None:
        list_id = make_list_client_id(strategy_name)
        self.adapter.place_otoco_order(
            symbol=self.settings.symbol,
            entry_side="BUY",
            entry_qty=decision.sizing.qty,
            entry_price=signal.entry,
            stop_price=signal.stop,
            take_profit_price=signal.target,
            list_client_id=list_id,
        )
        self.account = replace(self.account, open_positions=1)

        # Persist to DB
        with self._session() as s:
            from btc_bot.storage.repos import create_order, create_order_list
            from btc_bot.utils.time import utcnow as _now

            ol = create_order_list(s, list_id, "OTOCO")
            s.flush()
            entry_order = create_order(
                s, list_id + "-entry", self.settings.symbol, "BUY", "LIMIT_OTOCO",
                decision.sizing.qty, signal.entry, parent_list_id=ol.id,
            )
            s.flush()

            trade = open_trade(
                s, strategy_name, self.settings.symbol,
                entry_order.id, decision.sizing.qty, signal.entry,
            )
            set_state(s, "open_trade", {
                "trade_id": trade.id,
                "strategy": strategy_name,
                "entry": signal.entry,
                "stop": signal.stop,
                "target": signal.target,
                "qty": decision.sizing.qty,
            })

        logger.info(
            f"[PAPER] {strategy_name} BUY {decision.sizing.qty} BTC @ {signal.entry:.2f} "
            f"| SL={signal.stop:.2f} TP={signal.target:.2f} | list={list_id}"
        )

    def _persist_signal(self, signal, decision) -> None:
        with self._session() as s:
            save_signal(
                s,
                strategy=signal.strategy,
                symbol=signal.symbol,
                timeframe=signal.timeframe,
                side=signal.side,
                entry=signal.entry,
                stop=signal.stop,
                target=signal.target,
                accepted=decision.allowed,
                reason=signal.reason,
                reject_reason=decision.reason if not decision.allowed else "",
            )

    def _write_risk_event(self, kind: str, severity: str, payload: dict) -> None:
        try:
            with self._session() as s:
                log_risk_event(s, kind, severity, payload)
        except Exception as e:
            logger.error(f"Failed to write risk event: {e}")

    def _finalize_runs(self) -> None:
        with self._session() as s:
            for strat_name, run_id in self._run_ids.items():
                from btc_bot.storage.models import StrategyRun
                run = s.query(StrategyRun).filter_by(id=run_id).first()
                if run:
                    end_strategy_run(s, run, {"daily_stats": self._daily_stats})
