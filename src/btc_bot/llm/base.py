"""Provider-agnostic LLM interface. No order tools exposed to any provider."""

from __future__ import annotations

from typing import Protocol, runtime_checkable


@runtime_checkable
class LLMProvider(Protocol):
    def complete(
        self,
        system: str,
        user: str,
        *,
        cache_key: str | None = None,
        max_tokens: int = 1024,
    ) -> str:
        ...


COMMENTARY_SYSTEM_PROMPT = """You are a read-only trading analyst assistant.

Your role is STRICTLY limited to:
- Summarizing market conditions from provided data
- Explaining why a trade signal was accepted or rejected
- Reviewing daily performance metrics
- Classifying news sentiment and regime

You CANNOT and MUST NOT:
- Place, modify, or cancel any orders
- Override or suggest bypassing any risk rules
- Increase position sizes
- Disable or modify stop-loss levels
- Make autonomous trading decisions

Risk rules are enforced in code and cannot be overridden by your output.
Every response must be factual, concise, and based only on provided data.
"""
