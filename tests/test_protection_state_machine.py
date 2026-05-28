"""Tests for the OTOCO/OCO protection state machine."""

from __future__ import annotations

import time
from datetime import datetime, timedelta, timezone

import pytest
from btc_bot.risk.protection import ProtectionState, ProtectionStatus


class TestProtectionStateMachine:
    def test_initial_state_is_pending_entry(self):
        p = ProtectionStatus()
        assert p.state == ProtectionState.pending_entry

    def test_entry_fill_transitions_to_awaiting(self):
        p = ProtectionStatus()
        p.on_entry_filled()
        assert p.state == ProtectionState.awaiting_protection
        assert p.entry_fill_time is not None

    def test_protection_confirmed_transitions_to_protected(self):
        p = ProtectionStatus()
        p.on_entry_filled()
        p.on_protection_confirmed()
        assert p.state == ProtectionState.protected
        assert p.protection_confirmed_time is not None

    def test_no_timeout_when_protected(self):
        p = ProtectionStatus()
        p.on_entry_filled()
        p.on_protection_confirmed()
        assert not p.needs_emergency_flatten(timeout_seconds=5)

    def test_seconds_unprotected_grows(self):
        p = ProtectionStatus()
        p.on_entry_filled()
        # Manually backdate the entry fill time
        p.entry_fill_time = datetime.now(tz=timezone.utc) - timedelta(seconds=10)
        elapsed = p.seconds_unprotected()
        assert elapsed is not None and elapsed >= 10

    def test_timeout_triggers_emergency(self):
        p = ProtectionStatus()
        p.on_entry_filled()
        p.entry_fill_time = datetime.now(tz=timezone.utc) - timedelta(seconds=6)
        assert p.needs_emergency_flatten(timeout_seconds=5)

    def test_no_timeout_before_deadline(self):
        p = ProtectionStatus()
        p.on_entry_filled()
        p.entry_fill_time = datetime.now(tz=timezone.utc) - timedelta(seconds=3)
        assert not p.needs_emergency_flatten(timeout_seconds=5)

    def test_seconds_unprotected_none_when_not_awaiting(self):
        p = ProtectionStatus()
        assert p.seconds_unprotected() is None
        p.on_entry_filled()
        p.on_protection_confirmed()
        assert p.seconds_unprotected() is None

    def test_emergency_flatten_sets_state(self):
        p = ProtectionStatus()
        p.on_entry_filled()
        p.trigger_emergency("test timeout")
        assert p.state == ProtectionState.flat_emergency
        assert p.emergency_reason == "test timeout"

    def test_on_closed(self):
        p = ProtectionStatus()
        p.on_entry_filled()
        p.on_protection_confirmed()
        p.on_closed()
        assert p.state == ProtectionState.closed
