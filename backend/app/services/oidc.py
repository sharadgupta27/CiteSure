"""Optional OpenID Connect sign-in: authorization-code flow with PKCE, handled entirely by the backend.

The browser is only redirected. The backend keeps the one-time secrets (state, nonce, PKCE verifier) in a short-lived
signed cookie, exchanges the code for tokens itself, and accepts the ID token only after checking its signature
against the provider's JWKS and its issuer, audience, expiry and nonce. Only asymmetric algorithms are accepted, so
the "alg: none" and "HS256 with the public key" tricks do not apply.

Discovery, JWKS and token requests go straight to the identity provider. They are NOT part of the public-research
egress allow-list (`app/egress`), which exists to control what company text may leave; nothing from the documents is
ever sent here. In private mode the provider must be on this machine or a private network (config.py checks it).
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import secrets
import time
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlencode

import httpx
import jwt
from jwt import PyJWKSet

from app.config import Settings, is_private_url
from app.errors import AppError

ALLOWED_ALGORITHMS = ["RS256", "RS384", "RS512", "PS256", "PS384", "PS512", "ES256", "ES384", "ES512"]
FLOW_TTL_S = 600
FLOW_TYPE = "oidc_flow"
_METADATA_TTL_S = 3600
_JWKS_TTL_S = 3600
_LEEWAY_S = 60


class OidcError(AppError):
    """Sign-in failed. `reason` is a short code for the browser redirect and the audit log; the detail is generic."""

    status_code = 401
    code = "oidc_failed"

    def __init__(self, reason: str, detail: str = "Single sign-on failed") -> None:
        super().__init__(detail)
        self.reason = reason


@dataclass(frozen=True)
class ProviderMetadata:
    issuer: str
    authorization_endpoint: str
    token_endpoint: str
    jwks_uri: str


@dataclass(frozen=True)
class OidcClaims:
    issuer: str
    subject: str
    email: str | None
    email_verified: bool
    groups: list[str]
    raw: dict[str, Any]


def _b64url(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


def pkce_challenge(verifier: str) -> str:
    return _b64url(hashlib.sha256(verifier.encode()).digest())


def _lookup(claims: dict[str, Any], path: str) -> Any:
    """`groups`, or a dotted path such as `realm_access.roles` (Keycloak realm roles)."""
    if path in claims:
        return claims[path]
    value: Any = claims
    for part in path.split("."):
        if not isinstance(value, dict) or part not in value:
            return None
        value = value[part]
    return value


def extract_groups(claims: dict[str, Any], path: str) -> list[str]:
    value = _lookup(claims, path) if path else None
    items = [value] if isinstance(value, str) else value if isinstance(value, list) else []
    names = {item.strip().lstrip("/") for item in items if isinstance(item, str)}  # Keycloak paths look like "/hr"
    return sorted(n for n in names if n)[:200]


class OidcClient:
    def __init__(self, settings: Settings, http: httpx.AsyncClient | None = None) -> None:
        self.settings = settings
        self.issuer = settings.oidc_issuer.rstrip("/")
        self._http = http or httpx.AsyncClient(timeout=settings.oidc_timeout_s, follow_redirects=False)
        self._owns_http = http is None
        self._metadata: tuple[float, ProviderMetadata] | None = None
        self._jwks: tuple[float, PyJWKSet] | None = None

    async def aclose(self) -> None:
        if self._owns_http:
            await self._http.aclose()

    # --- provider documents -----------------------------------------------------------------
    async def metadata(self) -> ProviderMetadata:
        now = time.monotonic()
        if self._metadata and now - self._metadata[0] < _METADATA_TTL_S:
            return self._metadata[1]
        document = await self._get_json(f"{self.issuer}/.well-known/openid-configuration")
        meta = ProviderMetadata(
            issuer=str(document.get("issuer", "")).rstrip("/"),
            authorization_endpoint=str(document.get("authorization_endpoint", "")),
            token_endpoint=str(document.get("token_endpoint", "")),
            jwks_uri=str(document.get("jwks_uri", "")),
        )
        if meta.issuer != self.issuer:
            raise OidcError("bad_metadata", "The identity provider reported a different issuer")
        methods = document.get("code_challenge_methods_supported")
        if methods is not None and "S256" not in methods:
            raise OidcError("bad_metadata", "The identity provider does not support PKCE (S256)")
        for url in (meta.authorization_endpoint, meta.token_endpoint, meta.jwks_uri):
            if not (url.startswith("https://") or (url.startswith("http://") and is_private_url(url))):
                raise OidcError("bad_metadata", "The identity provider returned an insecure endpoint")
        self._metadata = (now, meta)
        return meta

    async def _jwk_set(self, *, refresh: bool = False) -> PyJWKSet:
        now = time.monotonic()
        if not refresh and self._jwks and now - self._jwks[0] < _JWKS_TTL_S:
            return self._jwks[1]
        document = await self._get_json((await self.metadata()).jwks_uri)
        try:
            keys = PyJWKSet.from_dict(document)
        except Exception as exc:
            raise OidcError("bad_jwks") from exc
        self._jwks = (now, keys)
        return keys

    async def _get_json(self, url: str) -> dict[str, Any]:
        try:
            response = await self._http.get(url)
            response.raise_for_status()
            data = response.json()
        except (httpx.HTTPError, ValueError) as exc:
            raise OidcError("provider_unreachable", "The identity provider could not be reached") from exc
        if not isinstance(data, dict):
            raise OidcError("bad_metadata")
        return data

    # --- the flow ---------------------------------------------------------------------------
    def new_flow(self) -> tuple[str, str, str]:
        """Fresh (state, nonce, verifier). The verifier never leaves the server except inside the signed cookie."""
        return secrets.token_urlsafe(24), secrets.token_urlsafe(24), secrets.token_urlsafe(48)

    def flow_cookie(self, state: str, nonce: str, verifier: str) -> str:
        now = int(time.time())
        payload = {
            "typ": FLOW_TYPE,
            "state": state,
            "nonce": nonce,
            "verifier": verifier,
            "iat": now,
            "exp": now + FLOW_TTL_S,
        }
        return jwt.encode(payload, self.settings.jwt_secret, algorithm="HS256")

    def read_flow_cookie(self, cookie: str | None) -> dict[str, str]:
        if not cookie:
            raise OidcError("no_flow", "The sign-in attempt expired. Start again.")
        try:
            data = jwt.decode(cookie, self.settings.jwt_secret, algorithms=["HS256"], options={"require": ["exp", "typ"]})
        except jwt.PyJWTError as exc:
            raise OidcError("no_flow", "The sign-in attempt expired. Start again.") from exc
        if data.get("typ") != FLOW_TYPE:
            raise OidcError("no_flow", "The sign-in attempt expired. Start again.")
        return {k: str(data[k]) for k in ("state", "nonce", "verifier")}

    async def authorization_url(self, state: str, nonce: str, verifier: str) -> str:
        meta = await self.metadata()
        query = {
            "response_type": "code",
            "client_id": self.settings.oidc_client_id,
            "redirect_uri": self.settings.oidc_redirect_uri,
            "scope": self.settings.oidc_scopes,
            "state": state,
            "nonce": nonce,
            "code_challenge": pkce_challenge(verifier),
            "code_challenge_method": "S256",
        }
        separator = "&" if "?" in meta.authorization_endpoint else "?"
        return f"{meta.authorization_endpoint}{separator}{urlencode(query)}"

    async def complete(self, code: str, state: str, cookie: str | None) -> OidcClaims:
        flow = self.read_flow_cookie(cookie)
        if not hmac.compare_digest(flow["state"], state):
            raise OidcError("bad_state", "The sign-in attempt does not match this browser. Start again.")
        id_token = await self._exchange(code, flow["verifier"])
        claims = await self.verify_id_token(id_token, flow["nonce"])
        email = claims.get("email")
        verified = claims.get("email_verified")
        return OidcClaims(
            issuer=self.issuer,
            subject=str(claims["sub"]),
            email=email.strip().lower() if isinstance(email, str) and email.strip() else None,
            email_verified=verified is True or (isinstance(verified, str) and verified.lower() == "true"),
            groups=extract_groups(claims, self.settings.oidc_groups_claim),
            raw=claims,
        )

    async def _exchange(self, code: str, verifier: str) -> str:
        meta = await self.metadata()
        form = {
            "grant_type": "authorization_code",
            "code": code,
            "redirect_uri": self.settings.oidc_redirect_uri,
            "client_id": self.settings.oidc_client_id,
            "code_verifier": verifier,
        }
        if self.settings.oidc_client_secret:
            form["client_secret"] = self.settings.oidc_client_secret
        try:
            response = await self._http.post(meta.token_endpoint, data=form, headers={"Accept": "application/json"})
            payload = response.json()
        except (httpx.HTTPError, ValueError) as exc:
            raise OidcError("token_exchange_failed") from exc
        # The provider's error body is not echoed: it can contain request details.
        id_token = payload.get("id_token") if response.is_success and isinstance(payload, dict) else None
        if not isinstance(id_token, str) or not id_token:
            raise OidcError("token_exchange_failed")
        return id_token

    async def verify_id_token(self, id_token: str, nonce: str) -> dict[str, Any]:
        try:
            header = jwt.get_unverified_header(id_token)
        except jwt.PyJWTError as exc:
            raise OidcError("bad_id_token") from exc
        algorithm = header.get("alg")
        if algorithm not in ALLOWED_ALGORITHMS:
            raise OidcError("bad_id_token")
        key = await self._signing_key(header.get("kid"))
        try:
            claims: dict[str, Any] = jwt.decode(
                id_token,
                key,
                algorithms=[algorithm],
                audience=self.settings.oidc_client_id,
                issuer=self.issuer,
                leeway=_LEEWAY_S,
                options={"require": ["exp", "iat", "iss", "aud", "sub"]},
            )
        except jwt.PyJWTError as exc:
            raise OidcError("bad_id_token") from exc
        audience = claims["aud"]
        if isinstance(audience, list) and len(audience) > 1 and claims.get("azp") != self.settings.oidc_client_id:
            raise OidcError("bad_id_token")
        token_nonce = claims.get("nonce")
        if not isinstance(token_nonce, str) or not hmac.compare_digest(token_nonce, nonce):
            raise OidcError("bad_nonce")
        return claims

    async def _signing_key(self, kid: str | None) -> Any:
        for refresh in (False, True):  # a rotated key shows up after one refetch
            keys = (await self._jwk_set(refresh=refresh)).keys
            matches = [k for k in keys if kid is None or k.key_id == kid]
            if matches and (kid is not None or len(keys) == 1):
                return matches[0].key
        raise OidcError("bad_id_token")
