"""A tiny authenticated HTTP client for the CiteSure API, used by the MCP server (and unit-tested with a mock transport).

The client logs in as a *service user* with an email and password from the environment. Everything it can see is
decided by the server's ACL for that user: the agent never gets more access than the account it runs as.
"""

from __future__ import annotations

import os
from typing import Any

import httpx


class CiteSureError(Exception):
    """An API error with a message that is safe to show to the agent (no tokens, no stack traces)."""


class CiteSureClient:
    def __init__(self, base_url: str, email: str, password: str, *, transport: httpx.AsyncBaseTransport | None = None) -> None:
        self._email = email
        self._password = password
        self._token: str | None = None
        self._http = httpx.AsyncClient(base_url=base_url.rstrip("/") + "/api/v1", timeout=60, transport=transport)

    @classmethod
    def from_env(cls) -> CiteSureClient:
        password = os.environ.get("CITESURE_MCP_PASSWORD", "")
        if not password:
            raise CiteSureError("Set CITESURE_MCP_PASSWORD (the service user's password) in the MCP server environment.")
        return cls(
            os.environ.get("CITESURE_URL", "http://localhost:8000"),
            os.environ.get("CITESURE_MCP_EMAIL", "agent@acme.example"),
            password,
        )

    async def _login(self) -> None:
        response = await self._http.post("/auth/login", json={"email": self._email, "password": self._password})
        if response.status_code != 200:
            raise CiteSureError("The service user could not log in. Check CITESURE_MCP_EMAIL and CITESURE_MCP_PASSWORD.")
        self._token = response.json()["access_token"]

    async def request(self, method: str, path: str, **kwargs: Any) -> Any:
        if self._token is None:
            await self._login()
        for attempt in range(2):
            response = await self._http.request(method, path, headers={"Authorization": f"Bearer {self._token}"}, **kwargs)
            if response.status_code == 401 and attempt == 0:  # the token expired: log in again once
                await self._login()
                continue
            break
        if response.status_code >= 400:
            detail = ""
            try:
                detail = response.json().get("detail", "")
            except ValueError:
                pass
            raise CiteSureError(f"{method} {path} failed with HTTP {response.status_code}: {detail or 'no details'}")
        return response.json() if response.content else None

    async def default_workspace_id(self) -> str:
        configured = os.environ.get("CITESURE_WORKSPACE_ID")
        if configured:
            return configured
        workspaces = await self.request("GET", "/workspaces")
        if not workspaces:
            raise CiteSureError("The service user is not a member of any workspace.")
        return str(workspaces[0]["id"])

    async def aclose(self) -> None:
        await self._http.aclose()
