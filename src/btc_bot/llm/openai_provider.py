"""OpenAI provider."""

from __future__ import annotations


class OpenAIProvider:
    def __init__(self, api_key: str, model: str = "gpt-4o") -> None:
        from openai import OpenAI
        self._client = OpenAI(api_key=api_key)
        self.model = model

    def complete(
        self,
        system: str,
        user: str,
        *,
        cache_key: str | None = None,
        max_tokens: int = 1024,
    ) -> str:
        response = self._client.chat.completions.create(
            model=self.model,
            max_tokens=max_tokens,
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
        )
        return response.choices[0].message.content or ""
