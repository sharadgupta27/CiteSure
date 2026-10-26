from __future__ import annotations

from fastapi import APIRouter, Depends, Request

from app.api.deps import auth_limiter, auth_service, client_key, current_user, get_settings
from app.api.ratelimit import RateLimiter
from app.config import Settings
from app.schemas import admin as a
from app.schemas import api as s
from app.services.auth import AuthService

router = APIRouter(tags=["auth"])


@router.post("/auth/register", operation_id="registerUser", status_code=201, response_model=s.TokenResponse)
async def register(
    body: s.RegisterRequest,
    request: Request,
    auth: AuthService = Depends(auth_service),
    limiter: RateLimiter = Depends(auth_limiter),
) -> s.TokenResponse:
    limiter.check(f"register:{client_key(request)}")
    return await auth.register(body.email, body.password)


@router.post("/auth/login", operation_id="loginUser", response_model=s.TokenResponse)
async def login(
    body: s.LoginRequest,
    request: Request,
    auth: AuthService = Depends(auth_service),
    limiter: RateLimiter = Depends(auth_limiter),
) -> s.TokenResponse:
    limiter.check(f"login:{client_key(request)}")
    return await auth.login(body.email, body.password)


@router.get("/auth/me", operation_id="getMe", response_model=s.User)
async def me(user: s.User = Depends(current_user)) -> s.User:
    return user


@router.get("/auth/config", operation_id="getAuthConfig", response_model=a.AuthConfig)
async def auth_config(settings: Settings = Depends(get_settings)) -> a.AuthConfig:
    """What the login page may offer. Public, and reveals nothing but which buttons to show."""
    return a.AuthConfig(
        password_login=not settings.oidc_only,
        registration=not settings.oidc_only,
        oidc_enabled=settings.oidc_enabled,
        oidc_provider_name=settings.oidc_provider_name if settings.oidc_enabled else None,
    )
