"""Optional OIDC sign-in (disabled unless OIDC_ENABLED=true). docs/oidc.md.

Both routes are browser navigations, not API calls: /login redirects to the identity provider and /callback redirects
back to the web app with either a CiteSure token or a short error code in the URL *fragment* (a fragment is never sent
to a server, a proxy log or a Referer header)."""

from __future__ import annotations

import re
from urllib.parse import quote

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import RedirectResponse

from app.api.deps import auth_limiter, auth_service, client_key, get_settings
from app.api.ratelimit import RateLimiter
from app.config import Settings
from app.errors import AppError, NotFound
from app.services.auth import AuthService
from app.services.oidc import FLOW_TTL_S, OidcClient, OidcError

router = APIRouter(tags=["auth"])

COOKIE = "citesure_oidc"
COOKIE_PATH = "/api/v1/auth/oidc"
_CODE = re.compile(r"[^a-z0-9_]+")


def oidc_client(request: Request, settings: Settings = Depends(get_settings)) -> OidcClient:
    if not settings.oidc_enabled:
        raise NotFound("Single sign-on is not enabled")
    client: OidcClient | None = getattr(request.app.state, "oidc", None)
    if client is None:  # built once, so the provider's metadata and keys are cached between sign-ins
        client = request.app.state.oidc = OidcClient(settings)
    return client


def _app_url(settings: Settings, fragment: str) -> str:
    base = (settings.oidc_post_login_url or (settings.cors_origin_list[0] if settings.cors_origin_list else "")).rstrip("/")
    return f"{base}/#{fragment}"


def _redirect(settings: Settings, fragment: str) -> RedirectResponse:
    response = RedirectResponse(_app_url(settings, fragment), status_code=302)
    response.headers["Cache-Control"] = "no-store"
    response.delete_cookie(COOKIE, path=COOKIE_PATH)
    return response


@router.get("/auth/oidc/login", operation_id="oidcLogin", status_code=302, response_class=RedirectResponse)
async def oidc_login(
    request: Request,
    settings: Settings = Depends(get_settings),
    client: OidcClient = Depends(oidc_client),
    limiter: RateLimiter = Depends(auth_limiter),
) -> RedirectResponse:
    limiter.check(f"oidc:{client_key(request)}")
    state, nonce, verifier = client.new_flow()
    url = await client.authorization_url(state, nonce, verifier)
    response = RedirectResponse(url, status_code=302)
    response.headers["Cache-Control"] = "no-store"
    response.set_cookie(
        COOKIE,
        client.flow_cookie(state, nonce, verifier),
        max_age=FLOW_TTL_S,
        path=COOKIE_PATH,
        httponly=True,
        secure=settings.oidc_redirect_uri.startswith("https://"),
        samesite="lax",  # the provider redirects back with a top-level GET, which Lax allows
    )
    return response


@router.get("/auth/oidc/callback", operation_id="oidcCallback", status_code=302, response_class=RedirectResponse)
async def oidc_callback(
    request: Request,
    code: str | None = Query(None, max_length=4096),
    state: str | None = Query(None, max_length=512),
    error: str | None = Query(None, max_length=100),
    settings: Settings = Depends(get_settings),
    client: OidcClient = Depends(oidc_client),
    auth: AuthService = Depends(auth_service),
    limiter: RateLimiter = Depends(auth_limiter),
) -> RedirectResponse:
    limiter.check(f"oidc:{client_key(request)}")
    try:
        if error:
            raise OidcError("provider_" + _CODE.sub("_", error.lower())[:40], "The identity provider refused the sign-in")
        if not code or not state:
            raise OidcError("bad_request", "The sign-in response is incomplete")
        claims = await client.complete(code, state, request.cookies.get(COOKIE))
        token = await auth.login_oidc(claims)
    except OidcError as exc:
        await auth.record_oidc_failure(exc.reason)
        return _redirect(settings, f"oidc_error={quote(exc.reason)}")
    except AppError as exc:  # e.g. a rate limit or conflict raised by the service
        await auth.record_oidc_failure(exc.code)
        return _redirect(settings, f"oidc_error={quote(exc.code)}")
    return _redirect(settings, f"oidc_token={quote(token.access_token)}")
