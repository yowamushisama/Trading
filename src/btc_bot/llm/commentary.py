"""LLM commentary — daily summaries, signal explanations, regime narration.

LLM is read-only. No order tools, no risk overrides.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from loguru import logger

from btc_bot.llm.base import COMMENTARY_SYSTEM_PROMPT

if TYPE_CHECKING:
    from btc_bot.llm.base import LLMProvider


class Commentary:
    def __init__(self, provider: "LLMProvider | None") -> None:
        self.provider = provider

    def _complete(self, user_prompt: str, max_tokens: int = 512) -> str:
        if self.provider is None:
            return "[LLM disabled]"
        try:
            return self.provider.complete(COMMENTARY_SYSTEM_PROMPT, user_prompt, max_tokens=max_tokens)
        except Exception as e:
            logger.warning(f"LLM commentary failed: {e}")
            return f"[LLM error: {e}]"

    def explain_signal(
        self,
        strategy: str,
        signal_allowed: bool,
        reject_reason: str,
        entry: float,
        stop: float,
        target: float,
        regime: str,
        rsi: float | None = None,
    ) -> str:
        status = "ALLOWED" if signal_allowed else f"REJECTED ({reject_reason})"
        prompt = (
            f"A {strategy} strategy signal was {status}.\n"
            f"Entry: ${entry:.2f}, Stop: ${stop:.2f}, Target: ${target:.2f}\n"
            f"Market regime: {regime}\n"
            f"{'RSI: ' + str(rsi) if rsi else ''}\n\n"
            f"Explain in 2-3 sentences why this outcome makes sense given the market conditions."
        )
        return self._complete(prompt)

    def daily_summary(
        self,
        date_str: str,
        trades: int,
        wins: int,
        losses: int,
        pnl_usdt: float,
        starting_equity: float,
        regime: str,
        top_news: list[str],
    ) -> str:
        news_text = "\n".join(f"- {n}" for n in top_news[:5]) or "No significant news."
        prompt = (
            f"Daily trading summary for {date_str}:\n"
            f"Trades: {trades} ({wins}W/{losses}L)\n"
            f"P&L: ${pnl_usdt:+.2f} ({pnl_usdt / starting_equity:+.2%} of equity)\n"
            f"Market regime: {regime}\n"
            f"Top news:\n{news_text}\n\n"
            f"Provide a concise 3-sentence summary covering: "
            f"performance context, market regime, and key news impact."
        )
        return self._complete(prompt, max_tokens=300)

    def classify_regime(self, btc_price: float, ema200: float, atr_pct: float, adx: float) -> str:
        prompt = (
            f"BTC market data: price=${btc_price:.0f}, EMA200=${ema200:.0f}, "
            f"ATR%={atr_pct:.2%}, ADX={adx:.1f}.\n"
            f"In one sentence, describe the current market regime for a BTC swing trader."
        )
        return self._complete(prompt, max_tokens=100)
