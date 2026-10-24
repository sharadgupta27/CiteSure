"""The only HTTP gateway to the public internet.

Every connector fetches through `EgressClient.get`. It enforces, in code, what the proxy enforces on the network:
HTTPS only, a host allow-list (or, for the optional web source, any PUBLIC host), no private or loopback addresses
(SSRF), a response size cap, a timeout, and a bounded number of re-validated redirects. Each request is counted and
logged by destination and a short fingerprint of the query, never the query text.
"""

from __future__ import annotations

import asyncio
import hashlib
import ipaddress
import logging
import socket
from dataclasses import dataclass
from typing import Literal
from urllib.parse import urljoin, urlparse

import httpx

from app.observability import EGRESS_REQUESTS

log = logging.getLogger("citesure.egress")

MAX_REDIRECTS = 3


class EgressDenied(Exception):
    """The request was refused before it left. `reason` is a code (not_allowed, private_address, ...), never a URL."""

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


@dataclass(frozen=True)
class EgressResponse:
    url: str
    status: int
    content: bytes
    content_type: str


def fingerprint(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:10]


def _is_public_ip(address: str) -> bool:
    ip = ipaddress.ip_address(address)
    return not (
        ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_multicast or ip.is_reserved or ip.is_unspecified
    )


class EgressClient:
    def __init__(
        self,
        *,
        mode: Literal["allowlist", "open"],
        allow_hosts: list[str],
        user_agent: str,
        timeout_s: float,
        max_bytes: int,
        proxy_url: str = "",
        transport: httpx.AsyncBaseTransport | None = None,
        check_dns: bool | None = None,
    ) -> None:
        self.mode = mode
        self._allow = {h.lower() for h in allow_hosts}
        self._max_bytes = max_bytes
        # Behind the proxy the container usually has no DNS for the outside world; the proxy refuses private
        # destinations itself. Without a proxy we resolve and check here.
        self._check_dns = (not proxy_url) if check_dns is None else check_dns
        self._client = httpx.AsyncClient(
            timeout=timeout_s,
            headers={"User-Agent": user_agent, "Accept": "*/*"},
            proxy=proxy_url or None,
            transport=transport,
            follow_redirects=False,  # redirects are followed by hand so every hop is validated
            trust_env=False,  # only the proxy configured above, never ambient HTTP(S)_PROXY settings
        )

    async def aclose(self) -> None:
        await self._client.aclose()

    def host_allowed(self, host: str) -> bool:
        host = host.lower()
        return host in self._allow or any(host.endswith("." + allowed) for allowed in self._allow)

    async def _validate(self, url: str) -> None:
        parts = urlparse(url)
        host = (parts.hostname or "").lower()
        if parts.scheme != "https" or not host:
            raise EgressDenied("https_only")
        if parts.username or parts.password:
            raise EgressDenied("credentials_in_url")
        try:
            literal = ipaddress.ip_address(host)
        except ValueError:
            literal = None
        if literal is not None and not _is_public_ip(str(literal)):
            raise EgressDenied("private_address")
        if self.mode == "allowlist" and not self.host_allowed(host):
            raise EgressDenied("not_allowed")
        if host in ("localhost",) or host.endswith((".internal", ".local", ".lan")):
            raise EgressDenied("private_address")
        if self._check_dns and literal is None:
            await self._check_resolves_public(host, parts.port or 443)

    @staticmethod
    async def _check_resolves_public(host: str, port: int) -> None:
        loop = asyncio.get_running_loop()
        try:
            infos = await loop.getaddrinfo(host, port, type=socket.SOCK_STREAM)
        except OSError as exc:
            raise EgressDenied("dns_failed") from exc
        if not infos or not all(_is_public_ip(str(info[4][0])) for info in infos):
            raise EgressDenied("private_address")

    async def get(
        self, destination: str, url: str, *, params: dict[str, str] | None = None, fingerprint_of: str = ""
    ) -> EgressResponse:
        """GET `url`. `destination` labels the metrics (arxiv, web, ...). Raises EgressDenied or httpx errors."""
        tag = fingerprint(fingerprint_of) if fingerprint_of else "-"
        try:
            response = await self._get_following(url, params)
        except EgressDenied as exc:
            EGRESS_REQUESTS.labels(destination=destination, outcome=f"denied:{exc.reason}").inc()
            log.warning("egress denied destination=%s reason=%s q=%s", destination, exc.reason, tag)
            raise
        except (httpx.HTTPError, OSError) as exc:
            EGRESS_REQUESTS.labels(destination=destination, outcome="error").inc()
            log.warning("egress error destination=%s type=%s q=%s", destination, type(exc).__name__, tag)
            raise
        EGRESS_REQUESTS.labels(destination=destination, outcome=f"http_{response.status}").inc()
        log.info(
            "egress ok destination=%s status=%s bytes=%d q=%s", destination, response.status, len(response.content), tag
        )
        return response

    async def _get_following(self, url: str, params: dict[str, str] | None) -> EgressResponse:
        current = url
        for hop in range(MAX_REDIRECTS + 1):
            await self._validate(current)
            async with self._client.stream("GET", current, params=params if hop == 0 else None) as response:
                if response.is_redirect and (location := response.headers.get("location")):
                    current = urljoin(str(response.url), location)
                    continue
                body = bytearray()
                async for chunk in response.aiter_bytes():
                    body.extend(chunk)
                    if len(body) > self._max_bytes:
                        raise EgressDenied("response_too_large")
                return EgressResponse(
                    url=str(response.url),
                    status=response.status_code,
                    content=bytes(body),
                    content_type=response.headers.get("content-type", "").split(";")[0].strip().lower(),
                )
        raise EgressDenied("too_many_redirects")
