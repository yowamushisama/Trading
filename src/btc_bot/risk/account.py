"""Account-level risk state: daily/weekly loss caps, consecutive-loss cooldown."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone


@dataclass
class AccountState:
    equity: float                          # current total equity in USDT
    starting_equity_today: float           # equity at start of trading day
    starting_equity_week: float            # equity at start of trading week
    realized_pnl_today: float = 0.0        # realised PnL today (can be negative)
    realized_pnl_week: float = 0.0
    open_positions: int = 0
    consecutive_losses: int = 0
    cooldown_until: datetime | None = None
    today: date = field(default_factory=lambda: date.today())


@dataclass(frozen=True)
class AccountLimits:
    daily_loss_cap_pct: float       # e.g. 0.015
    weekly_loss_cap_pct: float      # e.g. 0.04
    max_consec_losses: int          # e.g. 3
    cooldown_hours: int             # e.g. 4
    max_open_positions: int         # e.g. 1
    min_rr: float = 1.5             # minimum reward:risk ratio
    max_risk_per_trade_pct: float = 0.005  # hard per-trade risk ceiling


def check_account_limits(
    state: AccountState, limits: AccountLimits
) -> tuple[bool, str]:
    """Return (allowed, reason). Called before any new entry is considered."""
    now = datetime.now(tz=timezone.utc)

    # Cooldown
    if state.cooldown_until is not None and now < state.cooldown_until:
        remaining = int((state.cooldown_until - now).total_seconds() / 60)
        return False, f"Consecutive-loss cooldown active — {remaining}m remaining"

    # Consecutive loss hard block (guards against cooldown_until not being set)
    if state.consecutive_losses >= limits.max_consec_losses:
        return False, (
            f"Consecutive loss limit reached ({state.consecutive_losses}/"
            f"{limits.max_consec_losses}) — cooldown required before next entry"
        )

    # Max open positions
    if state.open_positions >= limits.max_open_positions:
        return False, f"Max open positions ({limits.max_open_positions}) reached"

    # Daily loss cap
    daily_loss_pct = -state.realized_pnl_today / state.starting_equity_today
    if daily_loss_pct >= limits.daily_loss_cap_pct:
        return (
            False,
            f"Daily loss cap hit: {daily_loss_pct:.2%} ≥ {limits.daily_loss_cap_pct:.2%}",
        )

    # Weekly loss cap
    weekly_loss_pct = -state.realized_pnl_week / state.starting_equity_week
    if weekly_loss_pct >= limits.weekly_loss_cap_pct:
        return (
            False,
            f"Weekly loss cap hit: {weekly_loss_pct:.2%} ≥ {limits.weekly_loss_cap_pct:.2%}",
        )

    return True, "ok"


def record_trade_result(
    state: AccountState, pnl: float, limits: AccountLimits
) -> AccountState:
    """Update state after a trade closes. Returns updated state."""
    from dataclasses import replace
    state = replace(
        state,
        realized_pnl_today=state.realized_pnl_today + pnl,
        realized_pnl_week=state.realized_pnl_week + pnl,
        equity=state.equity + pnl,
    )

    if pnl < 0:
        new_consec = state.consecutive_losses + 1
        cooldown_until = state.cooldown_until
        if new_consec >= limits.max_consec_losses:
            cooldown_until = datetime.now(tz=timezone.utc) + timedelta(
                hours=limits.cooldown_hours
            )
        state = replace(
            state,
            consecutive_losses=new_consec,
            cooldown_until=cooldown_until,
        )
    else:
        state = replace(state, consecutive_losses=0, cooldown_until=None)

    return state
