"""Kill switch: trips on abnormal conditions and prevents any further trading."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum

from loguru import logger


class KillReason(str, Enum):
    manual_halt = "manual_halt"
    volatility_spike = "volatility_spike"
    api_errors = "api_errors"
    missing_candles = "missing_candles"
    order_rejections = "order_rejections"
    position_mismatch = "position_mismatch"


@dataclass
class KillSwitchState:
    active: bool = False
    reason: KillReason | None = None
    detail: str = ""
    tripped_at: datetime | None = None

    # Internal counters (reset on trip)
    api_error_count: int = 0
    api_error_window_start: datetime | None = None
    consecutive_order_rejects: int = 0
    missing_candle_count: int = 0

    # Thresholds
    api_error_limit: int = 3
    api_error_window_seconds: int = 60
    order_reject_limit: int = 3
    missing_candle_limit: int = 2
    atr_spike_multiplier: float = 4.0  # current ATR > N * 30d median → spike

    def trip(self, reason: KillReason, detail: str = "") -> None:
        self.active = True
        self.reason = reason
        self.detail = detail
        self.tripped_at = datetime.now(tz=timezone.utc)
        logger.critical(
            f"KILL SWITCH TRIPPED: {reason.value} — {detail}"
        )

    def reset(self) -> None:
        """Manual reset only — requires explicit call, never automatic."""
        logger.warning("Kill switch reset manually")
        self.active = False
        self.reason = None
        self.detail = ""
        self.tripped_at = None
        self.api_error_count = 0
        self.api_error_window_start = None
        self.consecutive_order_rejects = 0
        self.missing_candle_count = 0

    def record_api_error(self) -> None:
        now = datetime.now(tz=timezone.utc)
        if self.api_error_window_start is None:
            self.api_error_window_start = now
            self.api_error_count = 1
        else:
            elapsed = (now - self.api_error_window_start).total_seconds()
            if elapsed > self.api_error_window_seconds:
                self.api_error_window_start = now
                self.api_error_count = 1
            else:
                self.api_error_count += 1
                if self.api_error_count >= self.api_error_limit:
                    self.trip(
                        KillReason.api_errors,
                        f"{self.api_error_count} errors in {elapsed:.0f}s",
                    )

    def record_order_rejection(self) -> None:
        self.consecutive_order_rejects += 1
        if self.consecutive_order_rejects >= self.order_reject_limit:
            self.trip(
                KillReason.order_rejections,
                f"{self.consecutive_order_rejects} consecutive order rejections",
            )

    def record_order_success(self) -> None:
        self.consecutive_order_rejects = 0

    def record_missing_candle(self) -> None:
        self.missing_candle_count += 1
        if self.missing_candle_count >= self.missing_candle_limit:
            self.trip(
                KillReason.missing_candles,
                f"{self.missing_candle_count} missing candles detected",
            )

    def check_volatility(self, current_atr: float, median_atr_30d: float) -> None:
        if median_atr_30d > 0 and current_atr > self.atr_spike_multiplier * median_atr_30d:
            self.trip(
                KillReason.volatility_spike,
                f"ATR {current_atr:.2f} > {self.atr_spike_multiplier}× median {median_atr_30d:.2f}",
            )

    def check_position_mismatch(
        self, local_qty: float, exchange_qty: float, tolerance: float = 0.0001
    ) -> None:
        if abs(local_qty - exchange_qty) > tolerance:
            self.trip(
                KillReason.position_mismatch,
                f"Local qty {local_qty} ≠ exchange qty {exchange_qty}",
            )
