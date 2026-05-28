"""Exchange filter cache — fetched from exchangeInfo on startup and every 6h."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from loguru import logger

from btc_bot.risk.sizing import ExchangeFilters


class FilterCache:
    def __init__(self, ttl_hours: int = 6) -> None:
        self._cache: dict[str, tuple[ExchangeFilters, datetime]] = {}
        self.ttl = timedelta(hours=ttl_hours)

    def get(self, symbol: str) -> ExchangeFilters | None:
        if symbol not in self._cache:
            return None
        filters, fetched_at = self._cache[symbol]
        if datetime.now(tz=timezone.utc) - fetched_at > self.ttl:
            logger.info(f"Filter cache stale for {symbol}, refetch needed")
            return None
        return filters

    def set(self, symbol: str, filters: ExchangeFilters) -> None:
        self._cache[symbol] = (filters, datetime.now(tz=timezone.utc))

    def validate_order(
        self,
        symbol: str,
        qty: float,
        price: float,
        current_price: float,
    ) -> tuple[bool, str]:
        """Validate qty/price against cached filters before submitting."""
        filters = self.get(symbol)
        if filters is None:
            return False, "Exchange filters not loaded — cannot validate order"

        if qty < filters.min_qty:
            return False, f"qty {qty} < minQty {filters.min_qty}"
        if qty > filters.max_qty:
            return False, f"qty {qty} > maxQty {filters.max_qty}"

        notional = qty * price
        if notional < filters.min_notional:
            return False, f"Notional {notional:.2f} < minNotional {filters.min_notional}"
        if notional > filters.max_notional:
            return False, f"Notional {notional:.2f} > maxNotional {filters.max_notional}"

        if price < filters.min_price or price > filters.max_price:
            return False, f"Price {price} out of [{filters.min_price}, {filters.max_price}]"

        # Percent-price check: reject if order price is wildly off from current
        if current_price > 0:
            deviation = abs(price - current_price) / current_price
            if deviation > 0.20:
                return False, f"Price {price} deviates {deviation:.1%} from current {current_price}"

        return True, "ok"
