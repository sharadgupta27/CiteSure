"""The encrypted vault: round trips, rotation, legacy objects, and every way an object can be wrong (all fail closed)."""

from __future__ import annotations

import base64
import json
import logging
import os
from pathlib import Path

import pytest

from app.config import Settings
from app.errors import AppError
from app.storage.base import BlobStore, LocalBlobStore, build_blob_store
from app.storage.rotate import rotate_all
from app.storage.vault import MAGIC, KeyRing, VaultBlobStore, VaultError, load_keyring, parse_key

KEY_A = os.urandom(32)
KEY_B = os.urandom(32)


def b64(key: bytes) -> str:
    return base64.b64encode(key).decode()


class MemoryStore:
    """An in-memory BlobStore, so the vault is proven to work around the protocol and not around one backend."""

    def __init__(self) -> None:
        self.objects: dict[str, bytes] = {}

    async def put(self, key: str, data: bytes) -> None:
        self.objects[key] = data

    async def get(self, key: str) -> bytes:
        if key not in self.objects:
            raise FileNotFoundError(key)
        return self.objects[key]

    async def delete(self, key: str) -> None:
        self.objects.pop(key, None)


def vault(inner: BlobStore, key: bytes = KEY_A, key_id: str = "k1", **retired: bytes) -> VaultBlobStore:
    return VaultBlobStore(inner, KeyRing(key_id, {key_id: key, **retired}))


@pytest.fixture(params=["memory", "local"])
def inner(request: pytest.FixtureRequest, tmp_path: Path) -> BlobStore:
    return MemoryStore() if request.param == "memory" else LocalBlobStore(tmp_path / "blobs")


async def raw(store: BlobStore, key: str) -> bytes:
    return await store.get(key)


# --- round trip ------------------------------------------------------------------------------
async def test_round_trip_and_the_stored_object_is_not_plaintext(inner: BlobStore) -> None:
    store = vault(inner)
    secret = b"Salary bands: the CEO earns 9 million."
    await store.put("docs/a.pdf", secret)

    stored = await raw(inner, "docs/a.pdf")
    assert stored.startswith(MAGIC)
    assert secret not in stored and b"CEO" not in stored
    assert await store.get("docs/a.pdf") == secret


async def test_same_content_encrypts_differently_each_time() -> None:
    inner = MemoryStore()
    store = vault(inner)
    await store.put("a", b"same")
    await store.put("b", b"same")
    assert inner.objects["a"] != inner.objects["b"]


async def test_empty_and_large_payloads() -> None:
    inner = MemoryStore()
    store = vault(inner)
    await store.put("empty", b"")
    assert await store.get("empty") == b""
    big = os.urandom(5 * 1024 * 1024)
    await store.put("big", big)
    assert await store.get("big") == big


async def test_delete_removes_the_object(inner: BlobStore) -> None:
    store = vault(inner)
    await store.put("x", b"data")
    await store.delete("x")
    with pytest.raises(FileNotFoundError):
        await store.get("x")


# --- keys and rotation -----------------------------------------------------------------------
async def test_the_key_id_is_stored_in_the_object() -> None:
    inner = MemoryStore()
    await vault(inner, key_id="prod-2026").put("a", b"data")
    assert b"prod-2026" in inner.objects["a"][: len(MAGIC) + 2 + len("prod-2026")]


async def test_a_rotated_store_still_reads_old_objects_through_retired_keys() -> None:
    inner = MemoryStore()
    await vault(inner, KEY_A, "k1").put("old", b"written under k1")

    rotated = vault(inner, KEY_B, "k2", k1=KEY_A)
    assert await rotated.get("old") == b"written under k1"
    await rotated.put("new", b"written under k2")
    assert await rotated.get("new") == b"written under k2"


async def test_a_store_without_the_retired_key_refuses_old_objects() -> None:
    inner = MemoryStore()
    await vault(inner, KEY_A, "k1").put("old", b"data")
    with pytest.raises(VaultError):
        await vault(inner, KEY_B, "k2").get("old")


async def test_rewrap_moves_the_data_key_without_touching_the_ciphertext() -> None:
    inner = MemoryStore()
    await vault(inner, KEY_A, "k1").put("doc", b"payload" * 1000)
    before = inner.objects["doc"]

    rotated = vault(inner, KEY_B, "k2", k1=KEY_A)
    assert await rotated.rewrap("doc") == "rewrapped"
    after = inner.objects["doc"]
    assert after != before and after[-1000:] == before[-1000:]  # same ciphertext tail
    assert await rotated.rewrap("doc") == "current"
    # k1 is no longer needed once everything is rewrapped
    assert await vault(inner, KEY_B, "k2").get("doc") == b"payload" * 1000


async def test_rewrap_encrypts_legacy_objects() -> None:
    inner = MemoryStore()
    inner.objects["legacy"] = b"uploaded before the vault"
    store = vault(inner)
    assert await store.rewrap("legacy") == "encrypted"
    assert inner.objects["legacy"].startswith(MAGIC)
    assert await store.get("legacy") == b"uploaded before the vault"


async def test_rotate_all_counts_every_outcome_and_survives_bad_objects() -> None:
    inner = MemoryStore()
    await vault(inner, KEY_A, "k1").put("old", b"1")
    inner.objects["plain"] = b"2"
    await vault(inner, KEY_B, "k2").put("current", b"3")
    await vault(inner, KEY_A, "k1").put("lost-key", b"4")
    inner.objects["lost-key"] = inner.objects["lost-key"].replace(b"k1", b"k9")

    store = vault(inner, KEY_B, "k2", k1=KEY_A)
    counts = await rotate_all(store, ["old", "plain", "current", "lost-key", "gone"])
    assert dict(counts) == {"rewrapped": 1, "encrypted": 1, "current": 1, "failed": 1, "missing": 1}


# --- legacy objects --------------------------------------------------------------------------
async def test_legacy_plaintext_is_returned_as_it_is(inner: BlobStore) -> None:
    await inner.put("legacy.pdf", b"%PDF-1.4 old upload")
    assert await vault(inner).get("legacy.pdf") == b"%PDF-1.4 old upload"


async def test_plaintext_can_be_refused_once_everything_is_encrypted() -> None:
    inner = MemoryStore()
    inner.objects["a"] = b"swapped in plaintext"
    strict = VaultBlobStore(inner, KeyRing("k1", {"k1": KEY_A}), allow_plaintext=False)
    with pytest.raises(VaultError):
        await strict.get("a")


# --- everything that must fail closed --------------------------------------------------------
async def test_wrong_key_fails() -> None:
    inner = MemoryStore()
    await vault(inner, KEY_A, "k1").put("a", b"data")
    with pytest.raises(VaultError):
        await vault(inner, KEY_B, "k1").get("a")  # right id, wrong key


async def test_every_single_byte_flip_is_detected() -> None:
    inner = MemoryStore()
    store = vault(inner)
    await store.put("a", b"x" * 64)
    good = inner.objects["a"]
    for index in range(len(good)):
        tampered = bytearray(good)
        tampered[index] ^= 0x01
        inner.objects["a"] = bytes(tampered)
        # A flipped magic byte makes it look like a legacy plaintext object, which the strict store refuses.
        with pytest.raises(VaultError):
            await VaultBlobStore(inner, KeyRing("k1", {"k1": KEY_A}), allow_plaintext=False).get("a")
        if index >= len(MAGIC):  # with the magic intact even the permissive store must fail
            with pytest.raises(VaultError):
                await store.get("a")


async def test_truncated_objects_fail_at_every_length() -> None:
    inner = MemoryStore()
    store = vault(inner)
    await store.put("a", b"hello world")
    good = inner.objects["a"]
    for length in range(len(MAGIC), len(good)):
        inner.objects["a"] = good[:length]
        with pytest.raises(VaultError):
            await store.get("a")


async def test_appended_bytes_fail() -> None:
    inner = MemoryStore()
    store = vault(inner)
    await store.put("a", b"hello")
    inner.objects["a"] += b"\x00"
    with pytest.raises(VaultError):
        await store.get("a")


async def test_an_object_served_under_another_key_fails() -> None:
    inner = MemoryStore()
    store = vault(inner)
    await store.put("collection-1/secret.pdf", b"secret")
    await store.put("collection-2/other.pdf", b"other")
    inner.objects["collection-2/other.pdf"] = inner.objects["collection-1/secret.pdf"]
    with pytest.raises(VaultError):
        await store.get("collection-2/other.pdf")


async def test_an_edited_key_id_fails() -> None:
    inner = MemoryStore()
    await vault(inner, KEY_A, "k1").put("a", b"data")
    inner.objects["a"] = inner.objects["a"].replace(b"k1", b"k2")
    with pytest.raises(VaultError):
        await vault(inner, KEY_A, "k2").get("a")  # the id is authenticated, not just looked up


async def test_a_future_version_is_refused() -> None:
    inner = MemoryStore()
    store = vault(inner)
    await store.put("a", b"data")
    blob = bytearray(inner.objects["a"])
    blob[len(MAGIC)] = 9
    inner.objects["a"] = bytes(blob)
    with pytest.raises(VaultError):
        await store.get("a")


def test_vault_error_is_a_500_with_a_generic_message() -> None:
    assert issubclass(VaultError, AppError)
    assert VaultError.status_code == 500
    assert VaultError().detail == "The stored file could not be read"


# --- key sources -----------------------------------------------------------------------------
def settings(**overrides: object) -> Settings:
    return Settings(_env_file=None, vault_enabled=True, **overrides)  # type: ignore[arg-type]


def test_parse_key_accepts_base64_urlsafe_base64_and_hex() -> None:
    assert parse_key(b64(KEY_A)) == KEY_A
    assert parse_key("  " + b64(KEY_A) + "\n") == KEY_A
    assert parse_key(base64.urlsafe_b64encode(KEY_A).decode()) == KEY_A
    assert parse_key(KEY_A.hex()) == KEY_A
    assert parse_key(KEY_A.hex().upper()) == KEY_A


@pytest.mark.parametrize(
    "bad",
    ["", "short", b64(os.urandom(16)), b64(os.urandom(33)), "!" * 44, "z" * 64, os.urandom(32).hex()[:-1]],
)
def test_malformed_keys_are_rejected_without_echoing_them(bad: str) -> None:
    with pytest.raises(VaultError) as caught:
        parse_key(bad)
    if bad:
        assert bad not in str(caught.value) and bad not in repr(caught.value)


def test_key_from_env_value_and_from_file(tmp_path: Path) -> None:
    assert load_keyring(settings(vault_key=b64(KEY_A))).get("k1") == KEY_A
    key_file = tmp_path / "vault.key"
    key_file.write_text(KEY_B.hex() + "\n", encoding="utf-8")
    ring = load_keyring(settings(vault_key_file=str(key_file), vault_key_id="file-key"))
    assert ring.get("file-key") == KEY_B and ring.active_id == "file-key"


def test_the_key_file_wins_over_the_inline_value(tmp_path: Path) -> None:
    key_file = tmp_path / "vault.key"
    key_file.write_text(b64(KEY_B), encoding="utf-8")
    assert load_keyring(settings(vault_key=b64(KEY_A), vault_key_file=str(key_file))).get("k1") == KEY_B


def test_retired_keys_file(tmp_path: Path) -> None:
    retired = tmp_path / "retired.json"
    retired.write_text(json.dumps({"k0": b64(KEY_A), "k_old": KEY_B.hex()}), encoding="utf-8")
    ring = load_keyring(settings(vault_key=b64(os.urandom(32)), vault_key_id="k2", vault_retired_keys_file=str(retired)))
    assert ring.get("k0") == KEY_A and ring.get("k_old") == KEY_B and ring.active_id == "k2"


@pytest.mark.parametrize(
    "content", ["not json", "[1, 2]", '{"k0": 5}', '{"k0": "tooshort"}', '{"bad id!": "' + b64(KEY_A) + '"}']
)
def test_a_broken_retired_keys_file_stops_startup(tmp_path: Path, content: str) -> None:
    retired = tmp_path / "retired.json"
    retired.write_text(content, encoding="utf-8")
    with pytest.raises(VaultError):
        load_keyring(settings(vault_key=b64(KEY_A), vault_retired_keys_file=str(retired)))


def test_a_retired_entry_may_not_redefine_the_active_key_id(tmp_path: Path) -> None:
    retired = tmp_path / "retired.json"
    retired.write_text(json.dumps({"k1": b64(KEY_B)}), encoding="utf-8")
    with pytest.raises(VaultError):
        load_keyring(settings(vault_key=b64(KEY_A), vault_retired_keys_file=str(retired)))


def test_missing_key_or_unreadable_files_fail_at_build_time(tmp_path: Path) -> None:
    with pytest.raises(VaultError):
        load_keyring(settings())
    with pytest.raises(VaultError):
        load_keyring(settings(vault_key_file=str(tmp_path / "nope.key")))
    with pytest.raises(VaultError):
        load_keyring(settings(vault_key=b64(KEY_A), vault_retired_keys_file=str(tmp_path / "nope.json")))
    with pytest.raises(VaultError):
        load_keyring(settings(vault_key=b64(KEY_A), vault_key_id="has space"))


def test_build_blob_store_wraps_only_when_the_vault_is_on(tmp_path: Path) -> None:
    plain = build_blob_store(Settings(_env_file=None, storage_path=str(tmp_path / "a")))
    assert isinstance(plain, LocalBlobStore)
    wrapped = build_blob_store(settings(storage_path=str(tmp_path / "b"), vault_key=b64(KEY_A)))
    assert isinstance(wrapped, VaultBlobStore)
    with pytest.raises(VaultError):
        build_blob_store(settings(storage_path=str(tmp_path / "c")))


# --- key material never leaks ----------------------------------------------------------------
async def test_keys_never_appear_in_reprs_messages_or_logs(caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level(logging.DEBUG)
    needles = [b64(KEY_A), KEY_A.hex(), repr(KEY_A), b64(KEY_B), KEY_B.hex()]
    inner = MemoryStore()
    store = vault(inner, KEY_A, "k1")
    await store.put("a", b"data")
    inner.objects["a"] = inner.objects["a"][:-1] + b"\x00"
    messages: list[str] = []
    for reader in (store, vault(inner, KEY_B, "k1"), vault(inner, KEY_B, "k2")):
        with pytest.raises(VaultError) as caught:
            await reader.get("a")
        messages += [str(caught.value), repr(caught.value), caught.value.detail]
    ring = KeyRing("k1", {"k1": KEY_A})
    with pytest.raises(VaultError) as bad_key:
        parse_key(b64(KEY_A)[:-4])
    messages += [repr(ring), str(ring), repr(store), str(bad_key.value)]
    messages += [record.getMessage() + str(record.args) for record in caplog.records]
    assert caplog.records  # the failures were logged...
    for text in messages:  # ...without any key
        for needle in needles:
            assert needle not in text
    assert not any(byte_needle in text.encode() for text in messages for byte_needle in (KEY_A, KEY_B))
