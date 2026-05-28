"""Position sizing — quantity determined from risk budget and stop distance.
Never from emotion or fixed quantity.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class ExchangeFilters:
    """Parsed Binance symbol filters relevant to sizing."""
    step_size: float        # LOT_SIZE stepSize (qty granularity)
    min_qty: float          # LOT_SIZE minQty
    max_qty: float          # LOT_SIZE maxQty
    tick_size: float        # PRICE_FILTER tickSize
    min_price: float        # PRICE_FILTER minPrice
    max_price: float        # PRICE_FILTER maxPrice
    min_notional: float     # MIN_NOTIONAL or NOTIONAL minNotional
    max_notional: float = float("inf")

    @classmethod
    def from_exchange_info(cls, filters: list[dict[str, Any]]) -> "ExchangeFilters":
        """Parse raw filters list from Binance exchangeInfo."""
        step_size = 0.000001
        min_qty = 0.0
        max_qty = float("inf")
        tick_size = 0.01
        min_price = 0.0
        max_price = float("inf")
        min_notional = 10.0
        max_notional = float("inf")

        for f in filters:
            ft = f.get("filterType", "")
            if ft == "LOT_SIZE":
                step_size = float(f["stepSize"])
                min_qty = float(f["minQty"])
                max_qty = float(f["maxQty"])
            elif ft == "PRICE_FILTER":
                tick_size = float(f["tickSize"])
                min_price = float(f["minPrice"])
                max_price = float(f["maxPrice"])
            elif ft in ("MIN_NOTIONAL", "NOTIONAL"):
                min_notional = float(f.get("minNotional", f.get("minVal", 10.0)))
                if "maxNotional" in f:
                    max_notional = float(f["maxNotional"])

        return cls(
            step_size=step_size,
            min_qty=min_qty,
            max_qty=max_qty,
            tick_size=tick_size,
            min_price=min_price,
            max_price=max_price,
            min_notional=min_notional,
            max_notional=max_notional,
        )

    @classmethod
    def default_btcusdt(cls) -> "ExchangeFilters":
        """Fallback when exchange info is unavailable (backtest mode)."""
        return cls(
            step_size=0.00001,
            min_qty=0.00001,
            max_qty=9000.0,
            tick_size=0.01,
            min_price=0.01,
            max_price=1_000_000.0,
            min_notional=5.0,
        )


def round_step(value: float, step: float) -> float:
    """Round down to the nearest step size."""
    if step <= 0:
        return value
    precision = max(0, round(-math.log10(step)))
    return round(math.floor(value / step) * step, precision)


def round_tick(value: float, tick: float) -> float:
    """Round price to the nearest tick size."""
    if tick <= 0:
        return value
    precision = max(0, round(-math.log10(tick)))
    return round(round(value / tick) * tick, precision)


@dataclass
class SizingResult:
    qty: float
    notional: float
    risk_usdt: float
    risk_pct: float
    ok: bool
    reason: str = "ok"


def calculate_position_size(
    equity: float,
    entry: float,
    stop: float,
    risk_pct: float,
    filters: ExchangeFilters,
    max_pct: float = 0.005,
) -> SizingResult:
    """Compute position size from risk budget and ATR-based stop distance.

    qty = floor((equity * risk_pct) / |entry - stop|, stepSize)
    Then validate against exchange filters.
    """
    if equity <= 0:
        return SizingResult(0, 0, 0, 0, False, "Equity must be positive")
    if entry <= 0 or stop <= 0:
        return SizingResult(0, 0, 0, 0, False, "Invalid prices")
    if stop >= entry:
        return SizingResult(0, 0, 0, 0, False, "Stop must be below entry for long")

    stop_distance = entry - stop
    if stop_distance / entry < 0.001:
        return SizingResult(0, 0, 0, 0, False, "Stop distance < 0.1% of entry")

    risk_budget = equity * risk_pct
    raw_qty = risk_budget / stop_distance
    qty = round_step(raw_qty, filters.step_size)

    if qty <= 0:
        return SizingResult(0, 0, 0, 0, False, "Computed qty rounds to zero")

    notional = qty * entry
    actual_risk_pct = (qty * stop_distance) / equity

    # Exchange filter validations
    if qty < filters.min_qty:
        return SizingResult(
            qty, notional, qty * stop_distance, actual_risk_pct,
            False, f"qty {qty} < minQty {filters.min_qty}"
        )
    if qty > filters.max_qty:
        return SizingResult(
            qty, notional, qty * stop_distance, actual_risk_pct,
            False, f"qty {qty} > maxQty {filters.max_qty}"
        )
    if notional < filters.min_notional:
        return SizingResult(
            qty, notional, qty * stop_distance, actual_risk_pct,
            False,
            f"Notional {notional:.2f} < minNotional {filters.min_notional} "
            f"at allowed risk {risk_pct:.4%}. Either equity too small or stop too wide.",
        )
    if notional > filters.max_notional:
        return SizingResult(
            qty, notional, qty * stop_distance, actual_risk_pct,
            False, f"Notional {notional:.2f} > maxNotional {filters.max_notional}"
        )

    # Hard cap: actual risk must not exceed risk_pct
    if actual_risk_pct > max_pct:
        return SizingResult(
            qty, notional, qty * stop_distance, actual_risk_pct,
            False,
            f"Actual risk {actual_risk_pct:.4%} exceeds hard cap {max_pct:.4%}",
        )

    return SizingResult(
        qty=qty,
        notional=notional,
        risk_usdt=qty * stop_distance,
        risk_pct=actual_risk_pct,
        ok=True,
    )
