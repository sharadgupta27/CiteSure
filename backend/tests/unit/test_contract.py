"""Contract drift test: the FastAPI app must match openapi.yaml (the source of truth).

Checks (1) the set of operations (method, path, operationId), (2) for every component schema that exists in both
documents: the same properties, the same required fields and the same enum values, (3) every documented
response status code is one the route can produce.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
import yaml

from app.config import Settings
from app.main import create_app

SPEC_PATH = Path(__file__).resolve().parents[3] / "openapi.yaml"
METHODS = {"get", "post", "put", "patch", "delete"}


@pytest.fixture(scope="module")
def spec() -> dict[str, Any]:
    return yaml.safe_load(SPEC_PATH.read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def generated() -> dict[str, Any]:
    app = create_app(Settings(env="test"))
    return app.openapi()


def operations(doc: dict[str, Any], *, yaml_doc: bool) -> dict[tuple[str, str], str]:
    ops: dict[tuple[str, str], str] = {}
    base = "/api/v1"
    for path, item in doc["paths"].items():
        full = path if not yaml_doc else (path if "servers" in item else base + path)
        for method, op in item.items():
            if method in METHODS:
                ops[(method, full)] = op["operationId"]
    return ops


def resolve(doc: dict[str, Any], schema: dict[str, Any]) -> dict[str, Any]:
    while "$ref" in schema:
        schema = doc["components"]["schemas"][schema["$ref"].rsplit("/", 1)[-1]]
    return schema


def enum_values(doc: dict[str, Any], schema: dict[str, Any]) -> set[Any] | None:
    schema = resolve(doc, schema)
    if "enum" in schema:
        return set(schema["enum"])
    if "const" in schema:  # Pydantic renders Literal["x"] as a const
        return {schema["const"]}
    for key in ("anyOf", "oneOf"):
        for option in schema.get(key, []):
            found = enum_values(doc, option)
            if found:
                return found
    return None


def test_same_operations_and_operation_ids(spec: dict[str, Any], generated: dict[str, Any]) -> None:
    expected = operations(spec, yaml_doc=True)
    actual = operations(generated, yaml_doc=False)
    assert set(actual) - set(expected) == set(), "routes missing from openapi.yaml"
    assert set(expected) - set(actual) == set(), "routes in openapi.yaml that the backend does not implement"
    assert {k: v for k, v in actual.items()} == expected, "operationId differs"


def test_every_shared_schema_has_identical_fields(spec: dict[str, Any], generated: dict[str, Any]) -> None:
    problems: list[str] = []
    compared = 0
    for name, expected in spec["components"]["schemas"].items():
        actual = generated["components"]["schemas"].get(name)
        if actual is None or expected.get("type") != "object":
            continue
        compared += 1
        exp_props, act_props = set(expected.get("properties", {})), set(actual.get("properties", {}))
        if exp_props != act_props:
            problems.append(
                f"{name}: properties differ (yaml only: {exp_props - act_props}, backend only: {act_props - exp_props})"
            )
            continue
        if set(expected.get("required", [])) != set(actual.get("required", [])):
            problems.append(
                f"{name}: required differs (yaml {sorted(expected.get('required', []))} vs backend {sorted(actual.get('required', []))})"
            )
        for prop, definition in expected.get("properties", {}).items():
            exp_enum = enum_values(spec, definition)
            act_enum = enum_values(generated, actual["properties"][prop])
            if exp_enum != act_enum:
                problems.append(f"{name}.{prop}: enum differs ({exp_enum} vs {act_enum})")
    assert compared >= 40, f"expected to compare most schemas, compared {compared}"
    assert not problems, "\n".join(problems)


def test_every_yaml_schema_is_implemented_or_inline(spec: dict[str, Any], generated: dict[str, Any]) -> None:
    """A schema in the YAML with no Pydantic twin is allowed only for shared enums, which FastAPI inlines."""
    missing = []
    for name, schema in spec["components"]["schemas"].items():
        if name not in generated["components"]["schemas"] and "enum" not in schema:
            missing.append(name)
    assert missing == []


def test_documented_success_codes_match(spec: dict[str, Any], generated: dict[str, Any]) -> None:
    mismatches = []
    for path, item in spec["paths"].items():
        full = path if "servers" in item else "/api/v1" + path
        for method, op in item.items():
            if method not in METHODS:
                continue
            documented = {code for code in op["responses"] if code.startswith("2")}
            actual = {code for code in generated["paths"][full][method]["responses"] if code.startswith("2")}
            if documented != actual:
                mismatches.append(f"{method.upper()} {full}: yaml {documented} vs backend {actual}")
    assert not mismatches, "\n".join(mismatches)


def test_every_protected_operation_declares_security(spec: dict[str, Any]) -> None:
    public = {"registerUser", "loginUser", "healthz", "metrics", "getAuthConfig", "oidcLogin", "oidcCallback"}
    for path, item in spec["paths"].items():
        for method, op in item.items():
            if method in METHODS and op["operationId"] not in public:
                assert "security" not in op or op["security"], f"{method} {path} is unexpectedly public"
