"""Anthropic Claude provider with prompt caching."""

from __future__ import annotations

from btc_bot.llm.base import COMMENTARY_SYSTEM_PROMPT


class AnthropicProvider:
    def __init__(self, api_key: str, model: str = "claude-opus-4-7") -> None:
        import anthropic
        self._client = anthropic.Anthropic(api_key=api_key)
        self.model = model

    def complete(
        self,
        system: str,
        user: str,
        *,
        cache_key: str | None = None,
        max_tokens: int = 1024,
    ) -> str:
        import anthropic
        messages = [{"role": "user", "content": user}]
        system_blocks = [
            {
                "type": "text",
                "text": system,
                "cache_control": {"type": "ephemeral"},
            }
        ]
        response = self._client.messages.create(
            model=self.model,
            max_tokens=max_tokens,
            system=system_blocks,
            messages=messages,
        )
        return response.content[0].text
