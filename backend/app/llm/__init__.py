from __future__ import annotations

from app.config import Settings
from app.llm.base import GenerationRequest, LLMProvider, Usage
from app.llm.fake import FakeProvider


def build_llm(settings: Settings) -> LLMProvider:
    """The INTERNAL lane's model: the only one that may read company documents."""
    if settings.llm_provider == "anthropic":
        from app.llm.anthropic_provider import AnthropicProvider

        return AnthropicProvider(settings)
    if settings.llm_provider == "local":
        from app.llm.local_provider import LocalProvider

        return LocalProvider(settings)
    return FakeProvider()


def build_public_llm(settings: Settings) -> LLMProvider | None:
    """The PUBLIC lane's model. It is only ever given text from the public internet and a question the egress
    guard cleared (see services/pipeline.py: `choose_llm`)."""
    if settings.public_llm_provider == "anthropic":
        from app.llm.anthropic_provider import AnthropicProvider

        return AnthropicProvider(settings, proxy_url=settings.egress_proxy_url)
    if settings.public_llm_provider == "fake":
        return FakeProvider()
    return None


__all__ = ["FakeProvider", "GenerationRequest", "LLMProvider", "Usage", "build_llm", "build_public_llm"]
