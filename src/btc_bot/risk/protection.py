"""OTOCO / OCO protective order state machine.

States: PENDING_ENTRY → AWAITING_PROTECTION → PROTECTED → CLOSED
If AWAITING_PROTECTION exceeds protection_timeout_seconds,
the bot must immediately flatten at market and raise a risk_event.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum


class ProtectionState(str, Enum):
    pending_entry = "PENDING_ENTRY"
    awaiting_protection = "AWAITING_PROTECTION"
    protected = "PROTECTED"
    closed = "CLOSED"
    flat_emergency = "FLAT_EMERGENCY"


@dataclass
class ProtectionStatus:
    state: ProtectionState = ProtectionState.pending_entry
    entry_fill_time: datetime | None = None
    protection_confirmed_time: datetime | None = None
    emergency_reason: str = ""

    def on_entry_filled(self) -> None:
        self.state = ProtectionState.awaiting_protection
        self.entry_fill_time = datetime.now(tz=timezone.utc)

    def on_protection_confirmed(self) -> None:
        self.state = ProtectionState.protected
        self.protection_confirmed_time = datetime.now(tz=timezone.utc)

    def on_closed(self) -> None:
        self.state = ProtectionState.closed

    def seconds_unprotected(self) -> float | None:
        """Seconds since entry fill with no protection confirmed. None if not in that state."""
        if self.state != ProtectionState.awaiting_protection:
            return None
        if self.entry_fill_time is None:
            return None
        return (datetime.now(tz=timezone.utc) - self.entry_fill_time).total_seconds()

    def needs_emergency_flatten(self, timeout_seconds: float) -> bool:
        elapsed = self.seconds_unprotected()
        return elapsed is not None and elapsed >= timeout_seconds

    def trigger_emergency(self, reason: str = "protection timeout") -> None:
        self.state = ProtectionState.flat_emergency
        self.emergency_reason = reason
