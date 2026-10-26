"""Settings. Every model name, threshold and provider switch comes from here (env vars)."""

from __future__ import annotations

import ipaddress
from functools import lru_cache
from typing import Literal
from urllib.parse import urlparse

from pydantic import Field, field_validator
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
    public_sources: str = "arxiv,crossref,openalex,europepmc,semanticscholar"  # + web
    public_results_per_source: int = Field(5, ge=1, le=20)
    public_top_k: int = Field(6, ge=1, le=20)
    public_timeout_s: float = Field(15.0, gt=0)
    public_max_bytes: int = Field(2_000_000, ge=10_000)
    public_user_agent: str = "CiteSure/1.0 (research assistant; +https://github.com/sharadgupta27/CiteSure)"
    contact_email: str = ""  # sent to Crossref/OpenAlex "polite pools" (faster, friendlier); optional
    web_search_model: str = ""  # defaults to ANSWER_MODEL; used only for URL discovery with the Anthropic web search tool
    web_search_max_uses: int = Field(3, ge=1, le=10)
    web_fetch_pages: int = Field(4, ge=1, le=10)

    # --- phase 2 settings (viewer + inbox): owned by the phase 2 agent; add fields under this line ---
    # Watched folder: <INBOX_ROOT>/<workspace folder>/<collection name>/<file>. Empty = the feature is off.
    inbox_root: str = ""
    inbox_poll_seconds: int = Field(30, ge=2, le=3600)
    inbox_settle_seconds: int = Field(5, ge=0, le=600)  # a file must be this old (mtime) so a half-copied file is never read
    inbox_max_file_mb: int = Field(20, ge=1, le=500)
    inbox_allowed_types: str = "pdf,docx,markdown"  # detected kinds (by magic bytes): pdf, docx, markdown, html

    # --- phase 3 settings (open-access full text): owned by the phase 3 agent; add fields under this line ---
    # On demand, a user can add the open-access PDF of a published paper to the public cache (docs/open-access-fulltext.md).
    fulltext_enabled: bool | None = None  # None follows PUBLIC_RESEARCH_ENABLED; False switches only this feature off
    fulltext_daily_fetches: int = Field(
        20, ge=0, le=1000
    )  # downloads per workspace per UTC day; 0 refuses every new download
    fulltext_max_bytes: int = Field(25_000_000, ge=100_000)  # one paper's PDF; a larger download is cut off and refused
    fulltext_max_pages: int = Field(150, ge=1, le=2000)  # a longer PDF is refused before it is parsed (parse-time bomb)
    fulltext_max_chunks: int = Field(800, ge=10, le=5000)  # bounds embedding work for one paper
    fulltext_cache_ttl_days: int = Field(30, ge=1, le=3650)  # after this a cached paper is ignored and fetched afresh
    fulltext_timeout_s: float = Field(60.0, gt=0)  # whole download, redirects included
    fulltext_parse_timeout_s: float = Field(60.0, gt=0)

    @field_validator("fulltext_enabled", mode="before")
    @classmethod
    def _blank_fulltext_flag_follows_the_public_lane(cls, value: object) -> object:
        """`FULLTEXT_ENABLED=` in a compose file or .env arrives as an empty string, which means 'not set'."""
        return None if isinstance(value, str) and not value.strip() else value

    @property
    def fulltext_on(self) -> bool:
        """Full text needs the public lane (it is fetched through the same egress guard and client)."""
        return self.public_research_enabled and self.fulltext_enabled is not False

    # --- phase 4 settings (learning layer): owned by the phase 4 agent; add fields under this line ---
    learning_reading_wpm: int = Field(200, ge=50, le=1000)  # reading speed behind the effort estimates
    learning_unit_minutes: int = Field(30, ge=5, le=240)  # a plan step aims at about this much reading
    learning_max_plan_documents: int = Field(12, ge=1, le=50)
    learning_max_plan_steps: int = Field(12, ge=1, le=40)  # one grounded generation per step, so this bounds the cost
    learning_summary_chunks: int = Field(12, ge=2, le=40)  # sections of one document the summary model reads
    learning_compare_chunks_per_doc: int = Field(3, ge=1, le=10)
    learning_generation_concurrency: int = Field(3, ge=1, le=10)  # parallel model calls while building a plan

    # --- phase 5 settings (audit, OIDC, vault, OCR): owned by the phase 5 agent; add fields under this line ---
    # Optional OIDC sign-in (Keycloak, Entra ID, Google...). Off by default; docs/oidc.md. The identity provider is
    # contacted directly (discovery, JWKS, token endpoint) and is NOT part of the public-research egress allow-list.
    oidc_enabled: bool = False
    oidc_issuer: str = (
        ""  # e.g. https://keycloak.example/realms/acme ; discovery is read from <issuer>/.well-known/openid-configuration
    )
    oidc_client_id: str = ""
    oidc_client_secret: str = ""  # empty = public client (PKCE only)
    oidc_redirect_uri: str = ""  # the API's callback, e.g. https://citesure.example/api/v1/auth/oidc/callback
    oidc_scopes: str = "openid email profile"
    oidc_groups_claim: str = "groups"  # id-token claim listing group names; only groups that already exist are mapped
    oidc_provider_name: str = "Single sign-on"  # label of the login button
    oidc_auto_create_users: bool = False  # create a local account on first login (otherwise it must already exist)
    oidc_require_email_verified: bool = True  # refuse ids whose provider does not vouch for the address
    oidc_only: bool = False  # true = password login and registration are switched off
    oidc_post_login_url: str = ""  # where the browser lands after login; default is the first CORS origin
    oidc_timeout_s: float = Field(10.0, gt=0)
    # Encrypted vault: AES-GCM envelope encryption of uploaded files at rest (docs/vault-and-ocr.md).
    vault_enabled: bool = False
    vault_key: str = ""  # base64 (or 64 hex chars) of 32 random bytes; prefer VAULT_KEY_FILE
    vault_key_file: str = ""  # path of a file holding the active key (Docker/Kubernetes secret)
    vault_key_id: str = "k1"  # stored with every object, so keys can be rotated
    vault_retired_keys_file: str = ""  # JSON {"key id": "base64 key"} of old keys that can still decrypt
    # Local OCR for scanned PDFs (PyMuPDF + Tesseract; nothing leaves the machine).
    ocr_enabled: bool = False
    ocr_languages: str = "eng"  # Tesseract language codes, e.g. "eng+deu"
    ocr_dpi: int = Field(300, ge=72, le=600)
    ocr_max_pages: int = Field(200, ge=1, le=2000)
    egress_mode: Literal["allowlist", "open"] = "allowlist"  # open = any public https host (needs web source)
    egress_allow_hosts: str = (
        "export.arxiv.org,api.crossref.org,api.openalex.org,www.ebi.ac.uk,api.semanticscholar.org,api.anthropic.com,"
        "arxiv.org,europepmc.org"  # the last two serve open-access PDFs (phase 3 full text)
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

    def assert_oidc_vault_consistent(self) -> None:
        """Phase 5 switches: refuse half-configured sign-in or an encryption vault that cannot find its key."""
        if self.oidc_only and not self.oidc_enabled:
            raise RuntimeError("OIDC_ONLY needs OIDC_ENABLED=true (otherwise nobody could sign in)")
        if self.oidc_enabled:
            missing = [
                name
                for name, value in (
                    ("OIDC_ISSUER", self.oidc_issuer),
                    ("OIDC_CLIENT_ID", self.oidc_client_id),
                    ("OIDC_REDIRECT_URI", self.oidc_redirect_uri),
                )
                if not value
            ]
            if missing:
                raise RuntimeError(f"OIDC_ENABLED needs {', '.join(missing)}")
            if not self.oidc_issuer.startswith("https://") and not is_private_url(self.oidc_issuer):
                raise RuntimeError("OIDC_ISSUER must be an https:// URL (plain http is only allowed on a private network)")
            if self.private_mode and not is_private_url(self.oidc_issuer):
                # Discovery, JWKS and token requests go straight to the provider, outside the egress allow-list,
                # so in private mode the provider has to live on this machine or the private network.
                raise RuntimeError("PRIVATE_MODE: OIDC_ISSUER must point at a provider on this machine or a private network")
        if self.vault_enabled and not (self.vault_key or self.vault_key_file):
            raise RuntimeError("VAULT_ENABLED needs VAULT_KEY or VAULT_KEY_FILE (the vault fails closed without a key)")

    def assert_private_mode_consistent(self) -> None:
        """The promise of private mode, checked at boot so a bad .env cannot silently break it:
        every component that reads company text runs on this machine or a private network."""
        self.assert_oidc_vault_consistent()
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
