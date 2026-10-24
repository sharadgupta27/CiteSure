"""The egress client is the only way out. These tests use a mock transport, so nothing touches the network."""

from __future__ import annotations

import httpx
import pytest

from app.egress.client import EgressClient, EgressDenied, fingerprint


def client(handler: httpx.MockTransport | None = None, **kwargs: object) -> EgressClient:
    defaults: dict[str, object] = {
        "mode": "allowlist",
        "allow_hosts": ["export.arxiv.org", "api.crossref.org"],
        "user_agent": "test-agent",
        "timeout_s": 5.0,
        "max_bytes": 1000,
        "check_dns": False,
        "transport": handler or httpx.MockTransport(lambda request: httpx.Response(200, content=b"ok")),
    }
    return EgressClient(**{**defaults, **kwargs})  # type: ignore[arg-type]


async def test_allowed_host_is_fetched_with_params_and_user_agent() -> None:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200, content=b"<feed/>", headers={"content-type": "application/atom+xml; charset=utf-8"})

    response = await client(httpx.MockTransport(handler)).get(
        "arxiv", "https://export.arxiv.org/api/query", params={"search_query": "all:attention"}
    )
    assert response.status == 200 and response.content_type == "application/atom+xml"
    assert seen[0].url.params["search_query"] == "all:attention"
    assert seen[0].headers["user-agent"] == "test-agent"


@pytest.mark.parametrize(
    ("url", "reason"),
    [
        ("https://evil.example.com/x", "not_allowed"),
        ("http://export.arxiv.org/api/query", "https_only"),
        ("https://user:pw@export.arxiv.org/x", "credentials_in_url"),
        ("https://127.0.0.1/x", "private_address"),
        ("https://192.168.1.10/x", "private_address"),
        ("https://[::1]/x", "private_address"),
        ("file:///etc/passwd", "https_only"),
    ],
)
async def test_forbidden_destinations_are_refused_before_sending(url: str, reason: str) -> None:
    calls: list[httpx.Request] = []
    transport = httpx.MockTransport(lambda request: calls.append(request) or httpx.Response(200))
    with pytest.raises(EgressDenied) as caught:
        await client(transport).get("test", url)
    assert caught.value.reason == reason
    assert calls == []  # nothing left the process


async def test_subdomains_of_an_allowed_host_are_allowed_but_lookalikes_are_not() -> None:
    c = client()
    assert (await c.get("t", "https://eu.api.crossref.org/works")).status == 200
    with pytest.raises(EgressDenied):
        await c.get("t", "https://api.crossref.org.evil.com/works")


async def test_open_mode_allows_any_public_host_but_still_refuses_private_ones() -> None:
    c = client(mode="open")
    assert (await c.get("web", "https://example.org/paper")).status == 200
    for private in ("https://10.0.0.5/admin", "https://localhost/admin", "https://db.internal/x"):
        with pytest.raises(EgressDenied) as caught:
            await c.get("web", private)
        assert caught.value.reason == "private_address"


async def test_a_redirect_to_a_forbidden_host_is_refused() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.host == "export.arxiv.org":
            return httpx.Response(302, headers={"location": "https://169.254.169.254/latest/meta-data"})
        return httpx.Response(200)

    with pytest.raises(EgressDenied) as caught:
        await client(httpx.MockTransport(handler)).get("t", "https://export.arxiv.org/x")
    assert caught.value.reason == "private_address"


async def test_redirects_between_allowed_hosts_are_followed_up_to_a_limit() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/start":
            return httpx.Response(301, headers={"location": "https://api.crossref.org/final"})
        return httpx.Response(200, content=b"done")

    response = await client(httpx.MockTransport(handler)).get("t", "https://export.arxiv.org/start")
    assert response.content == b"done" and response.url.endswith("/final")

    loop = httpx.MockTransport(lambda request: httpx.Response(302, headers={"location": str(request.url)}))
    with pytest.raises(EgressDenied) as caught:
        await client(loop).get("t", "https://export.arxiv.org/loop")
    assert caught.value.reason == "too_many_redirects"


async def test_oversized_responses_are_cut_off() -> None:
    big = httpx.MockTransport(lambda request: httpx.Response(200, content=b"x" * 5000))
    with pytest.raises(EgressDenied) as caught:
        await client(big, max_bytes=1000).get("t", "https://export.arxiv.org/big")
    assert caught.value.reason == "response_too_large"


async def test_logs_carry_a_fingerprint_not_the_query(caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level("INFO")
    await client().get("arxiv", "https://export.arxiv.org/api/query", fingerprint_of="secret keywords here")
    assert fingerprint("secret keywords here") in caplog.text
    assert "secret keywords" not in caplog.text
