"""Fee and slippage calculations."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class FeeEstimate:
    fee_per_side_pct: float
    slippage_buffer_pct: float

    @property
    def round_trip_pct(self) -> float:
        return self.fee_per_side_pct * 2

    @property
    def total_cost_pct(self) -> float:
        """Round-trip fees plus slippage buffer on both sides."""
        return self.round_trip_pct + self.slippage_buffer_pct * 2

    def minimum_move_pct(self, rr: float) -> float:
        """Minimum price move required to be worth trading at given R:R.
        The stop distance must cover fees + slippage, and target must
        also cover fees + slippage plus produce the required R.
        """
        # Entry cost + stop-side cost + target-side cost
        # A trade is viable if: (target - entry) > total_cost + (entry - stop)
        # Simplified: expected_move > total_cost (fees cover entry+exit)
        return self.total_cost_pct

    def is_viable(self, entry: float, stop: float, target: float) -> tuple[bool, str]:
        if entry <= 0 or stop <= 0 or target <= 0:
            return False, "Invalid price (zero or negative)"
        stop_distance_pct = abs(entry - stop) / entry
        move_to_target_pct = abs(target - entry) / entry
        min_move = self.total_cost_pct
        if move_to_target_pct <= min_move:
            return (
                False,
                f"Expected move {move_to_target_pct:.4%} ≤ min required {min_move:.4%} "
                f"(fees {self.round_trip_pct:.4%} + slippage {self.slippage_buffer_pct * 2:.4%})",
            )
        if stop_distance_pct < 0.001:
            return False, f"Stop too tight: {stop_distance_pct:.4%} < 0.1%"
        return True, "ok"
