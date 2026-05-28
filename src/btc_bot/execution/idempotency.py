"""Client order ID generation — idempotent, never reused."""

from __future__ import annotations

import uuid


def make_client_order_id(strategy: str, intent: str | None = None) -> str:
    """Generate a unique client order ID.

    Format: {strategy}-{intent}-{uuid4_hex[:16]}
    Max 36 chars for Binance compatibility.
    """
    base = f"{strategy[:10]}"
    if intent:
        base += f"-{intent[:8]}"
    uid = uuid.uuid4().hex[:12]
    return f"{base}-{uid}"[:36]


def make_list_client_id(strategy: str) -> str:
    return make_client_order_id(strategy, "list")
