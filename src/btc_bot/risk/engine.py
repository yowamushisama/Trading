"""
RiskEngine: single evaluation entry point.
All 12 gates run in order; first reject short-circuits with logged reason.
Hard rules are in code — martingale, averaging down, widening stops, and
removing stops are structurally impossible here.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from loguru import logger

from btc_bot.risk.account import AccountLimits, AccountState, check_account_limits
from btc_bot.risk.fees import FeeEstimate
from btc_bot.risk.kill_switch import KillSwitchState
from btc_bot.risk.sizing import ExchangeFilters, SizingResult, calculate_position_size
from btc_bot.utils.halt import is_halted


@dataclass(frozen=True)
class Signal:
    strategy: str
    symbol: str
    side: Literal["long", "short"]
    entry: float
    stop: float
    target: float
    timeframe: str
    reason: str = ""


@dataclass
class Decision:
    allowed: bool
    reason: str
    sizing: SizingResult | None = None

    @classmethod
    def reject(cls, reason: str) -> "Decision":
        logger.warning(f"Trade REJECTED: {reason}")
        return cls(allowed=False, reason=reason)

    @classmethod
    def allow(cls, reason: str, sizing: SizingResult) -> "Decision":
        logger.info(f"Trade ALLOWED: {reason} | qty={sizing.qty} notional={sizing.notional:.2f}")
        return cls(allowed=True, reason=reason, sizing=sizing)


class RiskEngine:
    def __init__(
        self,
        account_limits: AccountLimits,
        fee_estimate: FeeEstimate,
        kill_switch: KillSwitchState,
        halt_file_path: str = "./HALT",
        news_pause_active: bool = False,
    ) -> None:
        self.account_limits = account_limits
        self.fee_estimate = fee_estimate
        self.kill_switch = kill_switch
        self.halt_file_path = halt_file_path
        self.news_pause_active = news_pause_active

    def evaluate(
        self,
        signal: Signal,
        account: AccountState,
        filters: ExchangeFilters,
        risk_pct: float,
    ) -> Decision:
        # ── Gate 1: Halt file / env var ───────────────────────────
        if is_halted(self.halt_file_path):
            return Decision.reject("Manual halt active (HALT file or env var)")

        # ── Gate 2: Kill switch ───────────────────────────────────
        if self.kill_switch.active:
            return Decision.reject(
                f"Kill switch active: {self.kill_switch.reason} — {self.kill_switch.detail}"
            )

        # ── Gate 3: Short trades blocked on Spot ──────────────────
        if signal.side == "short":
            return Decision.reject("Short trades are disabled in Spot mode")

        # ── Gate 4: News pause ────────────────────────────────────
        if self.news_pause_active:
            return Decision.reject("News pause active — high-impact-negative event detected")

        # ── Gate 5–9: Account-level limits ────────────────────────
        ok, reason = check_account_limits(account, self.account_limits)
        if not ok:
            return Decision.reject(reason)

        # ── Gate 10: Per-trade risk cap ───────────────────────────
        if risk_pct > self.account_limits.daily_loss_cap_pct:
            return Decision.reject(
                f"risk_pct {risk_pct:.4%} > daily_loss_cap "
                f"{self.account_limits.daily_loss_cap_pct:.4%}"
            )

        # ── Gate 11: Stop must exist and be valid ─────────────────
        if signal.stop is None or signal.stop <= 0:
            return Decision.reject("Stop-loss missing or zero")
        stop_dist_pct = abs(signal.entry - signal.stop) / signal.entry
        if stop_dist_pct < 0.001:
            return Decision.reject(f"Stop distance {stop_dist_pct:.4%} < 0.1%")

        # ── Gate 12: R:R ──────────────────────────────────────────
        stop_dist = signal.entry - signal.stop
        target_dist = signal.target - signal.entry
        if stop_dist <= 0:
            return Decision.reject("Stop must be below entry for long")
        rr = target_dist / stop_dist
        if rr < self.account_limits.min_rr:
            return Decision.reject(
                f"R:R {rr:.2f} < minimum {self.account_limits.min_rr:.2f}"
            )

        # ── Gate 13: Fee + slippage viability ─────────────────────
        viable, fee_reason = self.fee_estimate.is_viable(
            signal.entry, signal.stop, signal.target
        )
        if not viable:
            return Decision.reject(f"Fee/slippage: {fee_reason}")

        # ── Gate 14: Exchange filter + sizing ─────────────────────
        sizing = calculate_position_size(
            equity=account.equity,
            entry=signal.entry,
            stop=signal.stop,
            risk_pct=risk_pct,
            filters=filters,
        )
        if not sizing.ok:
            return Decision.reject(f"Sizing: {sizing.reason}")

        return Decision.allow("All gates passed", sizing)
