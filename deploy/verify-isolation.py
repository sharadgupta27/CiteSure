"""Proves, from inside the running API container, the claims of the private stack. Run it with:

    deploy/verify-isolation.sh          (Linux, macOS, Git Bash)
    deploy/verify-isolation.ps1         (Windows PowerShell)

It does not read company data. Exit code 0 = every check passed (skipped checks do not fail the run).
"""

from __future__ import annotations

import os
import socket
import sys

import httpx

PROXY = os.environ.get("EGRESS_PROXY_URL", "")
MODE = os.environ.get("EGRESS_MODE", "allowlist")
results: list[tuple[str, str, str]] = []


def record(name: str, ok: bool | None, detail: str = "") -> None:
    results.append((name, "PASS" if ok else "SKIP" if ok is None else "FAIL", detail))


def direct_connection_fails() -> None:
    for host in ("1.1.1.1", "8.8.8.8"):
        try:
            socket.create_connection((host, 443), timeout=5).close()
        except OSError:
            continue
        return record("no direct route to the internet", False, f"connected straight to {host}")
    try:
        socket.getaddrinfo("example.com", 443)
        return record("no direct route to the internet", False, "the container can resolve public names itself")
    except OSError:
        pass
    record("no direct route to the internet", True, "raw sockets and DNS fail")


def via_proxy(url: str) -> tuple[int | None, str]:
    try:
        with httpx.Client(proxy=PROXY, timeout=20, trust_env=False) as client:
            return client.get(url).status_code, ""
    except httpx.ProxyError as exc:
        return None, f"refused by the proxy ({exc})"
    except httpx.HTTPError as exc:
        return None, type(exc).__name__


def proxy_checks() -> None:
    if not PROXY:
        return record("egress proxy configured", False, "EGRESS_PROXY_URL is empty")
    record("egress proxy configured", True, PROXY)
    status, why = via_proxy("https://export.arxiv.org/api/query?search_query=all:attention&max_results=1")
    record("allow-listed host reachable through the proxy", True if status == 200 else None, f"status={status} {why}".strip())
    status, why = via_proxy("https://example.com/")
    if MODE == "allowlist":
        record("host outside the allow-list refused", status is None, f"status={status} {why}".strip())
    else:
        record("open mode reaches public pages", True if status == 200 else None, f"status={status} {why}".strip())
    for private in ("https://169.254.169.254/latest/meta-data/", "https://10.0.0.1/", "https://192.168.1.1/"):
        status, why = via_proxy(private)
        record(f"private address refused ({private.split('/')[2]})", status is None, f"status={status} {why}".strip())


def local_model_reachable() -> None:
    base = os.environ.get("LOCAL_LLM_BASE_URL", "")
    if os.environ.get("LLM_PROVIDER") != "local" or not base:
        return record("local model server reachable", None, "LLM_PROVIDER is not 'local'")
    try:
        with httpx.Client(timeout=10, trust_env=False) as client:
            names = [m.get("id") for m in client.get(base.rstrip("/") + "/models").json().get("data", [])]
    except (httpx.HTTPError, ValueError) as exc:
        return record("local model server reachable", False, type(exc).__name__)
    wanted = os.environ.get("LOCAL_ANSWER_MODEL", "")
    record("local model server reachable", True, f"{len(names)} model(s) installed")
    record("answer model downloaded", wanted in names if names else False, wanted)


def settings_consistent() -> None:
    sys.path.insert(0, "/srv/citesure/backend")
    from app.config import Settings

    try:
        settings = Settings()
        settings.assert_safe_for_prod()
    except RuntimeError as exc:
        return record("private-mode settings consistent", False, str(exc))
    record("private-mode settings consistent", settings.private_mode, f"private_mode={settings.private_mode}")


if __name__ == "__main__":
    direct_connection_fails()
    proxy_checks()
    local_model_reachable()
    settings_consistent()
    width = max(len(name) for name, _, _ in results)
    for name, status, detail in results:
        print(f"{status:4}  {name:{width}}  {detail}")
    failed = [name for name, status, _ in results if status == "FAIL"]
    print("\nALL CHECKS PASSED" if not failed else f"\nFAILED: {', '.join(failed)}")
    sys.exit(1 if failed else 0)
