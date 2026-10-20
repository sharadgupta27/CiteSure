from __future__ import annotations

from app.config import Settings
from app.llm.base import GenerationRequest, LLMProvider, Usage
from app.llm.fake import FakeProvider


def build_llm(settings: Settings) -> LLMProvider:
    if settings.llm_provider == "anthropic":
        from app.llm.anthropic_provider import AnthropicProvider

        return AnthropicProvider(settings)
    return FakeProvider()


__all__ = ["FakeProvider", "GenerationRequest", "LLMProvider", "Usage", "build_llm"]
