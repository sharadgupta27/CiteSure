"""Settings. Every model name, threshold and provider switch comes from here (env vars)."""

from __future__ import annotations

from functools import lru_cache
from typing import Literal

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

EMBEDDING_DIM = 384  # fixed per migration; changing it needs a new migration + reindex
# Synthetic users created by the evaluator use this reserved domain. They are hidden from member and group lists.
SYSTEM_EMAIL_DOMAIN = "citesure.invalid"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    env: Literal["dev", "test", "prod"] = "dev"
    database_url: str = "postgresql+asyncpg://citesure:citesure@localhost:5432/citesure"
    jwt_secret: str = "dev-only-secret-change-me-dev-only-secret-0000"  # noqa: S105  (development default, rejected in prod)
    jwt_expire_minutes: int = 480
    cors_origins: str = "http://localhost:5173"

    # Providers
    llm_provider: Literal["fake", "anthropic"] = "fake"
    anthropic_api_key: str = ""
    answer_model: str = "claude-sonnet-5-5"
    verify_model: str = "claude-haiku-5-5"
    embedding_provider: Literal["fake", "fastembed", "voyage"] = "fake"
    embedding_model: str = "BAAI/bge-small-en-v1.5"
    voyage_api_key: str = ""
    reranker: Literal["cross-encoder", "lexical", "none"] = "lexical"
    rerank_enabled: bool = True

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

    def assert_safe_for_prod(self) -> None:
        """Called at startup. Refuses to boot a prod server with development defaults."""
        if self.env == "prod" and (self.jwt_secret.startswith("dev-only") or len(self.jwt_secret) < 32):
            raise RuntimeError("JWT_SECRET must be a random string of at least 32 characters in prod")
        if self.env == "prod" and "*" in self.cors_origin_list:
            raise RuntimeError("CORS_ORIGINS must list explicit origins in prod")


@lru_cache
def get_settings() -> Settings:
    return Settings()
