"""A fake OpenID Connect provider for tests: httpx.MockTransport plus a locally generated RSA key.
Nothing here touches the network."""

from __future__ import annotations

import json
import time
import uuid
from typing import Any
from urllib.parse import parse_qs

import httpx
import jwt
from cryptography.hazmat.primitives.asymmetric import rsa
from jwt.algorithms import RSAAlgorithm

ISSUER = "https://idp.test/realms/acme"
CLIENT_ID = "citesure"
REDIRECT = "https://citesure.test/api/v1/auth/oidc/callback"


def make_key() -> rsa.RSAPrivateKey:
    return rsa.generate_private_key(public_exponent=65537, key_size=2048)


class MockIdp:
    def __init__(self, key: rsa.RSAPrivateKey | None = None, kid: str = "key-1") -> None:
        self.key = key or make_key()
        self.kid = kid
        self.issuer = ISSUER
        self.metadata_issuer = ISSUER
        self.claims: dict[str, Any] = {}  # merged into the next ID token
        self.drop: set[str] = set()  # claims to leave out
        self.sign_with: Any = None  # override the signing key
        self.algorithm = "RS256"
        self.requests: list[httpx.Request] = []
        self.token_requests: list[dict[str, str]] = []
        self.expected_verifier_challenge: str | None = None
        self.nonce_override: str | None = None
        self.token_status = 200
        self.last_nonce: str | None = None
        self.subject = f"subject-{uuid.uuid4().hex[:8]}"  # unique, so one test's identity link never leaks into another

    # --- documents ----------------------------------------------------------------------
    def jwks(self) -> dict[str, Any]:
        jwk = json.loads(RSAAlgorithm.to_jwk(self.key.public_key()))
        return {"keys": [{**jwk, "kid": self.kid, "use": "sig", "alg": "RS256"}]}

    def id_token(self, nonce: str) -> str:
        now = int(time.time())
        claims: dict[str, Any] = {
            "iss": self.issuer,
            "aud": CLIENT_ID,
            "sub": self.subject,
            "iat": now,
            "exp": now + 300,
            "nonce": self.nonce_override or nonce,
            "email": "alice@acme.example",
            "email_verified": True,
            "groups": [],
            **self.claims,
        }
        for name in self.drop:
            claims.pop(name, None)
        return jwt.encode(claims, self.sign_with or self.key, algorithm=self.algorithm, headers={"kid": self.kid})

    # --- transport ----------------------------------------------------------------------
    def handler(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        assert request.url.host == "idp.test", f"unexpected host {request.url.host}"
        path = request.url.path
        if path.endswith("/.well-known/openid-configuration"):
            return httpx.Response(
                200,
                json={
                    "issuer": self.metadata_issuer,
                    "authorization_endpoint": "https://idp.test/realms/acme/protocol/openid-connect/auth",
                    "token_endpoint": "https://idp.test/realms/acme/protocol/openid-connect/token",
                    "jwks_uri": "https://idp.test/realms/acme/protocol/openid-connect/certs",
                    "code_challenge_methods_supported": ["S256"],
                },
            )
        if path.endswith("/certs"):
            return httpx.Response(200, json=self.jwks())
        if path.endswith("/token"):
            form = {k: v[0] for k, v in parse_qs(request.content.decode()).items()}
            self.token_requests.append(form)
            if self.token_status != 200:
                return httpx.Response(
                    self.token_status, json={"error": "invalid_grant", "error_description": "secret detail"}
                )
            return httpx.Response(200, json={"access_token": "opaque", "id_token": self.id_token(self.last_nonce or "")})
        return httpx.Response(404)

    def client(self) -> httpx.AsyncClient:
        return httpx.AsyncClient(transport=httpx.MockTransport(self.handler))
