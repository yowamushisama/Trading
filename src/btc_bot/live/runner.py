"""Live trading runner. Only reached after double-flag validation in config."""

from __future__ import annotations

import time
from dataclasses import replace
from datetime import datetime, timedelta, timezone

from loguru import logger

from btc_bot.config import Settings
from btc_bot.data.rest import fetch_candles_ccxt
from btc_bot.exchange.binance_spot import BinanceSpotAdapter
from btc_bot.execution.idempotency import make_list_client_id
from btc_bot.execution.order_manager import ManagedOrder, OrderManager
from btc_bot.risk.account import AccountLimits, AccountState, record_trade_result
from btc_bot.risk.engine import RiskEngine
from btc_bot.risk.fees import FeeEstimate
from btc_bot.risk.kill_switch import KillSwitchState
from btc_bot.strategy.scalper import ScalperStrategy
from btc_bot.strategy.swing import SwingStrategy
from btc_bot.utils.halt import is_halted
from btc_bot.utils.time import utcnow

# First 30 days of live trading: enforce 10% size cap in code (not config)
LIVE_RAMP_UP_PCT = 0.10
LIVE_RAMP_UP_DAYS = 30


class LiveRunner:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.kill_switch = KillSwitchState()
        self.adapter = BinanceSpotAdapter(
            api_key=settings.api_key,
            api_secret=settings.api_secret,
            testnet=settings.binance_testnet,
        )
        self.limits = AccountLimits(
            daily_loss_cap_pct=settings.daily_loss_cap_pct,
            weekly_loss_cap_pct=settings.weekly_loss_cap_pct,
            max_consec_losses=settings.max_consec_losses,
            cooldown_hours=settings.consec_loss_cooldown_hours,
            max_open_positions=settings.max_open_positions,
            min_rr=settings.min_rr,
        )
        self.engine = RiskEngine(
            account_limits=self.limits,
            fee_estimate=FeeEstimate(
                fee_per_side_pct=settings.fee_per_side_pct,
                slippage_buffer_pct=settings.slippage_buffer_pct,
            ),
            kill_switch=self.kill_switch,
            halt_file_path=settings.halt_file_path,
        )
        self.order_manager = OrderManager(
            adapter=self.adapter,
            kill_switch=self.kill_switch,
            protection_timeout_seconds=settings.protection_timeout_seconds,
        )
        self.strategies = []
        if "scalper" in settings.strategies_list:
            self.strategies.append(ScalperStrategy(
                atr_stop_k=settings.atr_stop_k, min_rr=settings.min_rr
            ))
        if "swing" in settings.strategies_list:
            self.strategies.append(SwingStrategy(
                atr_stop_k=settings.atr_stop_k, min_rr=settings.min_rr
            ))
        self._started_at = utcnow()

    def _is_ramp_up(self) -> bool:
        return (utcnow() - self._started_at).days < LIVE_RAMP_UP_DAYS

    def _get_account_state(self) -> AccountState:
        usdt = self.adapter.get_balance("USDT")
        equity = usdt.free + usdt.locked
        return AccountState(
            equity=equity,
            starting_equity_today=equity,
            starting_equity_week=equity,
            today=utcnow().date(),
        )

    def _emergency_flatten(self) -> None:
        logger.critical("EMERGENCY FLATTEN — closing all positions at market")
        try:
            btc = self.adapter.get_balance("BTC")
            if btc.free > 0:
                from btc_bot.execution.idempotency import make_client_order_id
                self.adapter.place_market_order(
                    symbol=self.settings.symbol.replace("/", ""),
                    side="SELL",
                    qty=btc.free,
                    client_order_id=make_client_order_id("emergency", "flatten"),
                )
        except Exception as e:
            logger.critical(f"Emergency flatten FAILED: {e}")

    def run(self) -> None:
        logger.warning(
            f"LIVE TRADING ACTIVE — testnet={self.settings.binance_testnet} "
            f"ramp_up={self._is_ramp_up()}"
        )

        filters = self.adapter.get_exchange_filters(self.settings.symbol)

        while True:
            # ── Halt check (every iteration) ──────────────────────
            if is_halted(self.settings.halt_file_path):
                logger.warning("HALT detected — stopping live runner.")
                break
            if self.kill_switch.active:
                logger.critical(f"Kill switch: {self.kill_switch.reason}. STOPPED.")
                break

            # ── Protection timeout check ───────────────────────────
            self.order_manager.check_protection_timeout(self._emergency_flatten)

            try:
                account = self._get_account_state()
                risk_pct = self.settings.risk_per_trade_pct
                if self._is_ramp_up():
                    risk_pct *= LIVE_RAMP_UP_PCT

                now = utcnow()
                for strategy in self.strategies:
                    if strategy.name == "scalper":
                        exec_df = fetch_candles_ccxt(
                            "binance", self.settings.symbol, "5m", now - timedelta(hours=24)
                        )
                        confirm_df = fetch_candles_ccxt(
                            "binance", self.settings.symbol, "15m", now - timedelta(days=7)
                        )
                        regime_df = fetch_candles_ccxt(
                            "binance", self.settings.symbol, "1h", now - timedelta(days=60)
                        )
                    else:
                        exec_df = fetch_candles_ccxt(
                            "binance", self.settings.symbol, "4h", now - timedelta(days=180)
                        )
                        confirm_df = fetch_candles_ccxt(
                            "binance", self.settings.symbol, "1d", now - timedelta(days=365)
                        )
                        regime_df = fetch_candles_ccxt(
                            "binance", self.settings.symbol, "1w", now - timedelta(days=1000)
                        )

                    signal = strategy.on_candles(exec_df, confirm_df, regime_df)
                    if signal is None:
                        continue

                    decision = self.engine.evaluate(signal, account, filters, risk_pct)
                    if not decision.allowed:
                        logger.info(f"[{strategy.name}] REJECTED: {decision.reason}")
                        continue

                    logger.info(
                        f"[{strategy.name}] SIGNAL ALLOWED: entry={signal.entry:.2f} "
                        f"stop={signal.stop:.2f} target={signal.target:.2f} "
                        f"qty={decision.sizing.qty}"
                    )

                    list_id = make_list_client_id(strategy.name)
                    result = self.adapter.place_otoco_order(
                        symbol=self.settings.symbol,
                        entry_side="BUY",
                        entry_qty=decision.sizing.qty,
                        entry_price=signal.entry,
                        stop_price=signal.stop,
                        take_profit_price=signal.target,
                        list_client_id=list_id,
                    )
                    if result:
                        self.order_manager.protection.on_entry_filled()
                        logger.info(f"OTOCO order placed: {list_id}")

            except Exception as e:
                self.kill_switch.record_api_error()
                logger.error(f"Live loop error: {e}")

            time.sleep(30)
