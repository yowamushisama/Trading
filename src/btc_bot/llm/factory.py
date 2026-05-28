"""LLM provider factory — selects from config, returns None if provider=none."""

from __future__ import annotations

from btc_bot.config import LLMProvider, Settings
from btc_bot.llm.base import LLMProvider as LLMProviderProtocol


def create_llm_provider(settings: Settings) -> LLMProviderProtocol | None:
    match settings.llm_provider:
        case LLMProvider.anthropic:
            if not settings.anthropic_api_key:
                raise ValueError("ANTHROPIC_API_KEY not set")
            from btc_bot.llm.anthropic_provider import AnthropicProvider
            return AnthropicProvider(settings.anthropic_api_key, settings.llm_model)
        case LLMProvider.openai:
            if not settings.openai_api_key:
                raise ValueError("OPENAI_API_KEY not set")
            from btc_bot.llm.openai_provider import OpenAIProvider
            return OpenAIProvider(settings.openai_api_key, settings.llm_model)
        case LLMProvider.groq:
            if not settings.groq_api_key:
                raise ValueError("GROQ_API_KEY not set")
            from btc_bot.llm.groq_provider import GroqProvider
            return GroqProvider(settings.groq_api_key, settings.llm_model)
        case _:
            return None
