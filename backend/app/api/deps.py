"""FastAPI dependencies. This is the only place in api/ that touches database sessions: routers receive services."""

from __future__ import annotations

from collections.abc import AsyncIterator

from fastapi import Depends, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.ratelimit import RateLimiter
from app.config import Settings
from app.errors import Unauthorized
from app.providers import Providers
from app.schemas import api as s
from app.services.ask import AskService
from app.services.auth import AuthService
from app.services.documents import DocumentService
from app.services.evaluation import EvaluationService
from app.services.fulltext import FullTextService
from app.services.workspaces import WorkspaceService

bearer = HTTPBearer(auto_error=False, scheme_name="bearerAuth", bearerFormat="JWT")


def get_settings(request: Request) -> Settings:
    settings: Settings = request.app.state.settings
    return settings


def get_providers(request: Request) -> Providers:
    providers: Providers = request.app.state.providers
    return providers


async def get_session(request: Request) -> AsyncIterator[AsyncSession]:
    async with request.app.state.sessionmaker() as session:
        yield session


def auth_service(session: AsyncSession = Depends(get_session), settings: Settings = Depends(get_settings)) -> AuthService:
    return AuthService(session, settings)


async def current_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer), auth: AuthService = Depends(auth_service)
) -> s.User:
    if credentials is None:
        raise Unauthorized("Missing bearer token")
    return await auth.user_from_token(credentials.credentials)


def workspace_service(
    session: AsyncSession = Depends(get_session), providers: Providers = Depends(get_providers)
) -> WorkspaceService:
    return WorkspaceService(session, providers.blobs)


def document_service(
    session: AsyncSession = Depends(get_session),
    settings: Settings = Depends(get_settings),
    providers: Providers = Depends(get_providers),
) -> DocumentService:
    return DocumentService(session, settings, providers.blobs)


def ask_service(
    session: AsyncSession = Depends(get_session),
    settings: Settings = Depends(get_settings),
    providers: Providers = Depends(get_providers),
) -> AskService:
    return AskService(session, settings, providers)


def evaluation_service(
    session: AsyncSession = Depends(get_session),
    settings: Settings = Depends(get_settings),
    providers: Providers = Depends(get_providers),
) -> EvaluationService:
    return EvaluationService(session, settings, providers)


def fulltext_service(
    session: AsyncSession = Depends(get_session),
    settings: Settings = Depends(get_settings),
    providers: Providers = Depends(get_providers),
) -> FullTextService:
    return FullTextService(session, settings, providers)


def ask_limiter(request: Request) -> RateLimiter:
    limiter: RateLimiter = request.app.state.ask_limiter
    return limiter


def auth_limiter(request: Request) -> RateLimiter:
    limiter: RateLimiter = request.app.state.auth_limiter
    return limiter


def client_key(request: Request) -> str:
    """Rate-limit key. X-Forwarded-For is only honoured when TRUST_PROXY_HEADERS=true (we run behind Caddy);
    otherwise any client could dodge the limit by sending a fake header."""
    if request.app.state.settings.trust_proxy_headers:
        forwarded = request.headers.get("x-forwarded-for", "").split(",")[0].strip()
        if forwarded:
            return forwarded
    return request.client.host if request.client else "unknown"
