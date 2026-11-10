"""OpenAI's hosted models over the `/chat/completions` protocol, with strict JSON-schema structured output.

Plain httpx, no SDK: the protocol is the one the local provider already speaks, so both share one client
(`ChatCompletionsProvider`) and the only differences are the address, the key and the proxy.

Like Anthropic, this is a HOSTED model. In private mode it may only be the public lane's model: config refuses
LLM_PROVIDER=openai at boot, and services/pipeline.py `choose_llm` never hands it company text.
"""

from __future__ import annotations

import httpx

from app.config import Settings
from app.llm.local_provider import ChatCompletionsProvider


class OpenAIProvider(ChatCompletionsProvider):
    hosted = True
    _label = "OpenAI model"
    _length_limit_param = "max_completion_tokens"  # "max_tokens" is deprecated for OpenAI's chat completions

    def __init__(self, settings: Settings, proxy_url: str = "", transport: httpx.AsyncBaseTransport | None = None) -> None:
        if not settings.openai_api_key:
            raise RuntimeError("OPENAI_API_KEY is required for the OpenAI provider")
        self.answer_model = settings.openai_answer_model
        self.verify_model = settings.openai_verify_model
        self._url = settings.openai_base_url.rstrip("/") + "/chat/completions"
        self._answer_tokens = settings.max_answer_tokens
        self._verify_tokens = settings.max_verify_tokens
        # With a proxy, ignore ambient proxy variables so the allow-list proxy is the only way out.
        self._client = httpx.AsyncClient(
            timeout=60.0,
            headers={"Authorization": f"Bearer {settings.openai_api_key}"},
            proxy=proxy_url or None,
            trust_env=not proxy_url,
            transport=transport,
        )
