"""The private stack's promises live in YAML and a proxy config. These tests fail when a change quietly breaks one:
a service that reads company text gaining a route to the internet, a published database port, or an allow-list that
no longer matches what the application believes it may reach."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
import yaml

from app.config import Settings

ROOT = Path(__file__).resolve().parents[3]
INTERNAL_ONLY = {"db", "migrate", "api", "worker", "frontend", "ollama"}  # these read or store company text
ENTRY = {"egress-proxy", "caddy"}  # allowed to touch the internet-facing network


@pytest.fixture(scope="module")
def compose() -> dict[str, Any]:
    return yaml.safe_load((ROOT / "docker-compose.private.yml").read_text(encoding="utf-8"))


def networks_of(service: dict[str, Any]) -> set[str]:
    declared = service.get("networks", [])
    return set(declared)  # a list of names, or a mapping whose keys are the names


def test_the_internal_network_has_no_route_out(compose: dict[str, Any]) -> None:
    assert compose["networks"]["internal"]["internal"] is True
    assert not compose["networks"]["edge"].get("internal", False)


def test_services_that_touch_company_text_are_on_the_internal_network_only(compose: dict[str, Any]) -> None:
    for name in INTERNAL_ONLY:
        assert networks_of(compose["services"][name]) == {"internal"}, f"{name} must not join the edge network"


def test_only_the_proxy_and_the_front_door_join_the_edge_network(compose: dict[str, Any]) -> None:
    on_edge = {n for n, s in compose["services"].items() if "edge" in networks_of(s)}
    assert on_edge <= ENTRY | {"ollama-pull"}  # ollama-pull is a profile-gated one-off that downloads the model
    assert "egress-proxy" in on_edge
    assert compose["services"]["ollama-pull"]["profiles"] == ["setup"]  # never started by a plain `up`


def test_no_service_that_holds_data_publishes_a_port(compose: dict[str, Any]) -> None:
    for name in INTERNAL_ONLY | {"egress-proxy"}:
        assert "ports" not in compose["services"][name], f"{name} must not publish ports"


def test_published_ports_default_to_this_machine_only(compose: dict[str, Any]) -> None:
    for mapping in compose["services"]["caddy"]["ports"]:
        assert mapping.startswith("${BIND_ADDRESS:-127.0.0.1}:"), mapping


def test_the_stack_boots_in_private_mode_with_a_local_model_and_the_proxy(compose: dict[str, Any]) -> None:
    env = compose["x-backend-env"]
    assert env["PRIVATE_MODE"] == "true"
    assert env["LLM_PROVIDER"].startswith("${LLM_PROVIDER:-local}")
    assert env["LOCAL_LLM_BASE_URL"] == "http://ollama:11434/v1"
    assert env["EGRESS_PROXY_URL"] == "http://egress-proxy:3128"
    assert env["EMBEDDING_PROVIDER"].startswith("${EMBEDDING_PROVIDER:-fastembed}")
    assert "voyage" not in str(env).lower()


def test_the_default_environment_passes_the_applications_own_private_mode_check(compose: dict[str, Any]) -> None:
    Settings(
        env="prod",
        jwt_secret="x" * 40,
        private_mode=True,
        llm_provider="local",
        local_llm_base_url="http://ollama:11434/v1",
        embedding_provider="fastembed",
        public_research_enabled=True,
        egress_proxy_url="http://egress-proxy:3128",
    ).assert_safe_for_prod()


def proxy_hosts() -> set[str]:
    lines = (ROOT / "deploy" / "egress" / "allowlist.txt").read_text(encoding="utf-8").splitlines()
    return {line.strip() for line in lines if line.strip() and not line.startswith("#")}


def test_the_proxy_allow_list_matches_the_applications_default_hosts() -> None:
    assert proxy_hosts() == set(Settings(env="test").egress_allow_host_list)


@pytest.mark.parametrize("policy", ["squid-allowlist.conf", "squid-open.conf"])
def test_both_proxy_policies_refuse_private_destinations_and_non_https_ports(policy: str) -> None:
    text = (ROOT / "deploy" / "egress" / policy).read_text(encoding="utf-8")
    for needle in ("169.254.0.0/16", "10.0.0.0/8", "172.16.0.0/12", "192.168.0.0/16", "127.0.0.0/8", "fc00::/7"):
        assert needle in text
    assert text.index("http_access deny private_dst") < text.index("http_access allow")  # denies come first
    assert "acl Safe_ports port 443" in text and "port 80" not in text
    assert text.rstrip().count("http_access deny all") == 1


def test_only_the_allow_list_policy_names_hosts() -> None:
    assert "allowlist.txt" in (ROOT / "deploy" / "egress" / "squid-allowlist.conf").read_text(encoding="utf-8")
    assert "http_access allow all" in (ROOT / "deploy" / "egress" / "squid-open.conf").read_text(encoding="utf-8")


def test_the_env_example_documents_every_variable_the_compose_file_requires(compose: dict[str, Any]) -> None:
    example = (ROOT / ".env.private.example").read_text(encoding="utf-8")
    for required in (
        "POSTGRES_PASSWORD",
        "JWT_SECRET",
        "EGRESS_DENY_TERMS",
        "PUBLIC_LLM_PROVIDER",
        "ANTHROPIC_API_KEY",
        "BIND_ADDRESS",
    ):
        assert f"{required}=" in example
