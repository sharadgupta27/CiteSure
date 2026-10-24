"""Settings. Every model name, threshold and provider switch comes from here (env vars)."""

from __future__ import annotations

import ipaddress
from functools import lru_cache
from typing import Literal
from urllib.parse import urlparse

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

EMBEDDING_DIM = 384  # fixed per migration; changing it needs a new migration + reindex
# Synthetic users created by the evaluator use this reserved domain. They are hidden from member and group lists.
SYSTEM_EMAIL_DOMAIN = "citesure.invalid"


_PRIVATE_SUFFIXES = (".internal", ".local", ".lan", ".localdomain", ".home.arpa")
_PRIVATE_HOSTS = frozenset({"localhost", "host.docker.internal", "gateway.docker.internal"})


def is_private_url(url: str) -> bool:
    """True when the URL's host is this machine, a private/link-local address, or a bare service name such as
    `ollama` (Docker/Kubernetes DNS). A dotted public name is not private even if it happens to resolve locally."""
    host = (urlparse(url).hostname or "").lower()
    if not host:
        return False
    if host in _PRIVATE_HOSTS or host.endswith(_PRIVATE_SUFFIXES):
        return True
    try:
        address = ipaddress.ip_address(host)
    except ValueError:
        return "." not in host
    return address.is_private or address.is_loopback or address.is_link_local


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    env: Literal["dev", "test", "prod"] = "dev"
    database_url: str = "postgresql+asyncpg://citesure:citesure@localhost:5432/citesure"
    jwt_secret: str = "dev-only-secret-change-me-dev-only-secret-0000"  # noqa: S105  (development default, rejected in prod)
    jwt_expire_minutes: int = 480
    cors_origins: str = "http://localhost:5173"

    # Providers. `llm_provider` is the INTERNAL lane: it is the only model that may read company documents.
    llm_provider: Literal["fake", "anthropic", "local"] = "fake"
    anthropic_api_key: str = ""
    answer_model: str = "claude-sonnet-5-5"
    verify_model: str = "claude-haiku-5-5"
    embedding_provider: Literal["fake", "fastembed", "voyage"] = "fake"
    embedding_model: str = "BAAI/bge-small-en-v1.5"
    voyage_api_key: str = ""
    reranker: Literal["cross-encoder", "lexical", "none"] = "lexical"
    rerank_enabled: bool = True

    # Local model server for the internal lane (any OpenAI-compatible endpoint: Ollama, vLLM, llama.cpp, LM Studio).
    # It must live on this machine or a private network: private mode refuses a public address.
    local_llm_base_url: str = "http://localhost:11434/v1"
    local_answer_model: str = "llama3.2:3b"
    local_verify_model: str = "llama3.2:3b"
    local_llm_timeout_s: float = Field(180.0, gt=0)

    # Private mode: company documents never reach a hosted model or the public internet (docs/private-deployment.md).
    private_mode: bool = False

    # Public research lane: published papers and web pages, reached only through the egress guard.
    public_research_enabled: bool = False
    default_scope: Literal["internal", "public", "both"] = "internal"
    public_llm_provider: Literal["none", "fake", "anthropic"] = "none"  # may read PUBLIC text only
    public_sources: str = "arxiv,crossref,openalex,europepmc"  # + semanticscholar, web
    public_results_per_source: int = Field(5, ge=1, le=20)
    public_top_k: int = Field(6, ge=1, le=20)
    public_timeout_s: float = Field(15.0, gt=0)
    public_max_bytes: int = Field(2_000_000, ge=10_000)
    public_user_agent: str = "CiteSure/1.0 (research assistant; +https://github.com/sharadgupta27/CiteSure)"
    contact_email: str = ""  # sent to Crossref/OpenAlex "polite pools" (faster, friendlier); optional
    web_search_model: str = ""  # defaults to ANSWER_MODEL; used only for URL discovery with the Anthropic web search tool
    web_search_max_uses: int = Field(3, ge=1, le=10)
    web_fetch_pages: int = Field(4, ge=1, le=10)
    egress_mode: Literal["allowlist", "open"] = "allowlist"  # open = any public https host (needs web source)
    egress_allow_hosts: str = (
        "export.arxiv.org,api.crossref.org,api.openalex.org,www.ebi.ac.uk,api.semanticscholar.org,api.anthropic.com"
    )
    egress_proxy_url: str = ""  # e.g. http://egress-proxy:3128 ; required in prod private mode
    egress_deny_terms: str = ""  # comma separated project names, customers, code names that must never leave
    egress_allow_terms: str = ""  # terms exempt from the document-title check (generic titles such as "Handbook")
    egress_canaries: str = ""  # comma separated canary strings; any outbound text containing one is blocked
    egress_overlap_words: int = Field(6, ge=3, le=20)  # a run of this many words copied from a document blocks
    egress_max_query_chars: int = Field(300, ge=40, le=2000)
    egress_block_internal_titles: bool | None = None  # None = on in private mode, off otherwise

    # Retrieval and verification
    candidate_k: int = Field(30, ge=1, le=100)
    top_k: int = Field(6, ge=1, le=20)
    quote_match_min: float = Field(0.9, ge=0.0, le=1.0)
    min_quote_chars: int = 12
    max_answer_tokens: int = 4096
    max_verify_tokens: int = 2048
    chunk_tokens: int = 400
    chunk_overlap: float = Field(0.15, ge=0.0, le=0.5)
    pii_redact: bool = False

    # Estimated prices in USD per million tokens (Sonnet 5.5 / Haiku 5.5 list prices). Override for your contract.
    price_in_answer: float = 2.0
    price_out_answer: float = 10.0
    price_in_verify: float = 0.10
    price_out_verify: float = 0.50

    # Storage and uploads
    storage_backend: Literal["local", "s3"] = "local"
    storage_path: str = "./uploads"
    s3_bucket: str = ""
    max_upload_mb: int = 20
    uploads_enabled: bool = True

    # Limits
    rate_limit_ask_per_min: int = 30
    rate_limit_auth_per_min: int = 20
    trust_proxy_headers: bool = False

    # Observability
    otel_exporter_otlp_endpoint: str = ""

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]

    @property
    def max_upload_bytes(self) -> int:
        return self.max_upload_mb * 1024 * 1024

    @staticmethod
    def _csv(value: str) -> list[str]:
        return [item.strip() for item in value.split(",") if item.strip()]

    @property
    def public_source_list(self) -> list[str]:
        return [s.lower() for s in self._csv(self.public_sources)]

    @property
    def egress_allow_host_list(self) -> list[str]:
        return [h.lower() for h in self._csv(self.egress_allow_hosts)]

    @property
    def deny_term_list(self) -> list[str]:
        return self._csv(self.egress_deny_terms)

    @property
    def allow_term_list(self) -> list[str]:
        return [t.lower() for t in self._csv(self.egress_allow_terms)]

    @property
    def canary_list(self) -> list[str]:
        return self._csv(self.egress_canaries)

    @property
    def block_internal_titles(self) -> bool:
        return self.private_mode if self.egress_block_internal_titles is None else self.egress_block_internal_titles

    def assert_safe_for_prod(self) -> None:
        """Called at startup. Refuses to boot a prod server with development defaults."""
        if self.env == "prod" and (self.jwt_secret.startswith("dev-only") or len(self.jwt_secret) < 32):
            raise RuntimeError("JWT_SECRET must be a random string of at least 32 characters in prod")
        if self.env == "prod" and "*" in self.cors_origin_list:
            raise RuntimeError("CORS_ORIGINS must list explicit origins in prod")
        self.assert_private_mode_consistent()

    def assert_private_mode_consistent(self) -> None:
        """The promise of private mode, checked at boot so a bad .env cannot silently break it:
        every component that reads company text runs on this machine or a private network."""
        if self.public_llm_provider != "none" and not self.public_research_enabled:
            raise RuntimeError("PUBLIC_LLM_PROVIDER needs PUBLIC_RESEARCH_ENABLED=true")
        if self.default_scope != "internal" and not self.public_research_enabled:
            raise RuntimeError("DEFAULT_SCOPE other than 'internal' needs PUBLIC_RESEARCH_ENABLED=true")
        if self.egress_mode == "open" and "web" not in self.public_source_list:
            raise RuntimeError("EGRESS_MODE=open is only for the 'web' source; add it to PUBLIC_SOURCES or use allowlist")
        if "web" in self.public_source_list and self.egress_mode != "open":
            raise RuntimeError("The 'web' source reads arbitrary pages: set EGRESS_MODE=open (the allow-list refuses them)")
        if "web" in self.public_source_list and self.public_llm_provider != "anthropic":
            raise RuntimeError("The 'web' source finds pages with Claude's web search: set PUBLIC_LLM_PROVIDER=anthropic")
        if not self.private_mode:
            return
        if self.llm_provider == "anthropic":
            raise RuntimeError("PRIVATE_MODE: LLM_PROVIDER=anthropic would send company text to a hosted model; use 'local'")
        if self.embedding_provider == "voyage":
            raise RuntimeError(
                "PRIVATE_MODE: EMBEDDING_PROVIDER=voyage would send company text to a hosted API; use fastembed"
            )
        if self.llm_provider == "local" and not is_private_url(self.local_llm_base_url):
            raise RuntimeError("PRIVATE_MODE: LOCAL_LLM_BASE_URL must point at this machine or a private network")
        if self.public_research_enabled and self.env == "prod" and not self.egress_proxy_url:
            raise RuntimeError(
                "PRIVATE_MODE in prod: set EGRESS_PROXY_URL so all outbound traffic passes the allow-list proxy"
            )


@lru_cache
def get_settings() -> Settings:
    return Settings()
