"""Encrypted vault: AES-256-GCM envelope encryption around any BlobStore (local volume or S3).

Every object gets its own random 32-byte data key (DEK) that encrypts the file. The DEK is wrapped with a master key that
is named by an id stored in the object, so a master key can be rotated by re-wrapping 48 bytes per object instead of
re-encrypting every file. This protects files at rest (a stolen disk, volume snapshot or bucket); it does not protect
against someone who can run the API, because that process holds the master key (docs/vault-and-ocr.md).

Object layout (all integers are single bytes):

    "CSVAULT" | version | kid length | kid | wrap nonce (12) | wrapped DEK (32 + 16 tag) | data nonce (12) | ciphertext + tag

Both ciphertexts are authenticated against the blob key, and the wrap also against the key id, so an object copied under
another name, or with its key id edited, fails instead of decrypting. The data AAD deliberately excludes the key id and the
wrapped DEK: a rotation rewrites those without touching the (large) ciphertext.

It fails closed. A malformed key, an unknown key id, a wrong key or any change to a stored object raises VaultError;
nothing is ever returned unless it authenticated. Objects without the magic prefix are older uploads from before the vault
was switched on and are returned as they are (and encrypted by `python -m app.storage.rotate`).

Key material never appears in logs, exceptions or reprs. Error details are generic on purpose: they reach HTTP clients.
"""

from __future__ import annotations

import asyncio
import base64
import binascii
import hmac
import json
import logging
import os
import re
from collections.abc import Mapping
from pathlib import Path
from typing import Literal

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from app.config import Settings
from app.errors import AppError
from app.storage.base import BlobStore

log = logging.getLogger(__name__)

MAGIC = b"CSVAULT"
VERSION = 1
_NONCE_LEN = 12
_KEY_LEN = 32
_TAG_LEN = 16
_WRAPPED_LEN = _KEY_LEN + _TAG_LEN
_KEY_ID = re.compile(r"^[A-Za-z0-9._-]{1,64}$")
_HEX_KEY = re.compile(r"^[0-9a-fA-F]{64}$")
_GENERIC = "The stored file could not be read"

RewrapResult = Literal["encrypted", "rewrapped", "current"]


class VaultError(AppError):
    """The vault could not produce trustworthy plaintext. Mapped to 500; the detail never says why or shows key data."""

    code = "vault_error"

    def __init__(self, detail: str = _GENERIC) -> None:
        super().__init__(detail)


def _fail(blob_key: str, reason: str) -> VaultError:
    # The reason is one of our own fixed strings (never data from the object or a key), so it is safe to log.
    log.error("vault refused an object blob=%s reason=%s", blob_key, reason)
    return VaultError()


def parse_key(raw: str) -> bytes:
    """A 32-byte key written as 64 hex characters or as base64 (standard or URL-safe)."""
    text = raw.strip()
    if _HEX_KEY.match(text):
        return bytes.fromhex(text)
    try:
        padded = text + "=" * (-len(text) % 4)
        key = base64.b64decode(padded.replace("-", "+").replace("_", "/"), validate=True)
    except (binascii.Error, ValueError):
        key = b""
    if len(key) != _KEY_LEN:
        # Never echo the value: even a malformed key is probably a real one with a typo.
        raise VaultError("A vault key must be 32 random bytes written as base64 or 64 hex characters") from None
    return key


def check_key_id(key_id: str) -> str:
    if not _KEY_ID.match(key_id):
        raise VaultError("A vault key id must be 1-64 characters from A-Z a-z 0-9 . _ -")
    return key_id


class KeyRing:
    """The active master key plus retired keys that may still decrypt old objects."""

    def __init__(self, active_id: str, keys: Mapping[str, bytes]) -> None:
        check_key_id(active_id)
        if active_id not in keys:
            raise VaultError("The active vault key is missing")
        for kid, key in keys.items():
            check_key_id(kid)
            if len(key) != _KEY_LEN:
                raise VaultError("A vault key must be 32 bytes")
        self._active_id = active_id
        self._keys = dict(keys)

    @property
    def active_id(self) -> str:
        return self._active_id

    def get(self, key_id: str) -> bytes | None:
        return self._keys.get(key_id)

    def __repr__(self) -> str:
        return f"KeyRing(active={self._active_id!r}, ids={sorted(self._keys)!r})"

    __str__ = __repr__


def _read_text(path: str, what: str) -> str:
    try:
        return Path(path).read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        raise VaultError(f"{what} cannot be read") from None


def load_keyring(settings: Settings) -> KeyRing:
    """Build the key ring from settings, or raise: the app must not start with a vault it cannot open."""
    raw = _read_text(settings.vault_key_file, "VAULT_KEY_FILE") if settings.vault_key_file else settings.vault_key
    if not raw.strip():
        raise VaultError("VAULT_ENABLED is true but no key is set (VAULT_KEY or VAULT_KEY_FILE)")
    active_id = check_key_id(settings.vault_key_id)
    active = parse_key(raw)
    keys = {active_id: active}
    if settings.vault_retired_keys_file:
        try:
            retired = json.loads(_read_text(settings.vault_retired_keys_file, "VAULT_RETIRED_KEYS_FILE"))
        except ValueError:
            raise VaultError("VAULT_RETIRED_KEYS_FILE is not valid JSON") from None
        if not isinstance(retired, dict) or not all(isinstance(v, str) for v in retired.values()):
            raise VaultError('VAULT_RETIRED_KEYS_FILE must be a JSON object like {"k0": "<key>"}')
        for kid, value in retired.items():
            key = parse_key(value)
            if kid == active_id and not hmac.compare_digest(key, active):
                raise VaultError("VAULT_KEY_ID is also listed as a retired key with a different value")
            keys[check_key_id(kid)] = key
    return KeyRing(active_id, keys)


def is_encrypted(blob: bytes) -> bool:
    return blob.startswith(MAGIC)


def _wrap_aad(key_id: str, blob_key: str) -> bytes:
    return MAGIC + bytes([VERSION]) + b"wrap\0" + key_id.encode() + b"\0" + blob_key.encode()


def _data_aad(blob_key: str) -> bytes:
    return MAGIC + bytes([VERSION]) + b"data\0" + blob_key.encode()


def _wrap(ring: KeyRing, blob_key: str, dek: bytes) -> bytes:
    """The header part of an object up to and including the wrapped data key."""
    key_id = ring.active_id
    master = ring.get(key_id)
    assert master is not None  # the constructor guarantees it
    nonce = os.urandom(_NONCE_LEN)
    wrapped = AESGCM(master).encrypt(nonce, dek, _wrap_aad(key_id, blob_key))
    return MAGIC + bytes([VERSION, len(key_id)]) + key_id.encode() + nonce + wrapped


class _Parsed:
    """An object split into its parts. Slicing only; nothing is trusted until a tag verifies."""

    def __init__(self, blob_key: str, blob: bytes) -> None:
        fixed = len(MAGIC) + 2
        if len(blob) < fixed:
            raise _fail(blob_key, "truncated header")
        if blob[len(MAGIC)] != VERSION:
            raise _fail(blob_key, "unsupported version")
        kid_len = blob[len(MAGIC) + 1]
        start = fixed + kid_len
        end = start + _NONCE_LEN + _WRAPPED_LEN + _NONCE_LEN
        if kid_len == 0 or len(blob) < end + _TAG_LEN:
            raise _fail(blob_key, "truncated object")
        try:
            self.key_id = check_key_id(blob[fixed:start].decode("ascii"))
        except (UnicodeDecodeError, VaultError):
            raise _fail(blob_key, "bad key id") from None
        self.wrap_nonce = blob[start : start + _NONCE_LEN]
        self.wrapped = blob[start + _NONCE_LEN : start + _NONCE_LEN + _WRAPPED_LEN]
        self.data_part = blob[end - _NONCE_LEN :]  # data nonce + ciphertext, kept together for rewrap


def _unwrap(ring: KeyRing, blob_key: str, parsed: _Parsed) -> bytes:
    master = ring.get(parsed.key_id)
    if master is None:
        raise _fail(blob_key, f"unknown key id {parsed.key_id}")
    try:
        return AESGCM(master).decrypt(parsed.wrap_nonce, parsed.wrapped, _wrap_aad(parsed.key_id, blob_key))
    except InvalidTag:
        raise _fail(blob_key, "data key did not authenticate (wrong key, edited or swapped object)") from None


def seal(ring: KeyRing, blob_key: str, data: bytes) -> bytes:
    dek = AESGCM.generate_key(bit_length=256)
    nonce = os.urandom(_NONCE_LEN)
    return _wrap(ring, blob_key, dek) + nonce + AESGCM(dek).encrypt(nonce, data, _data_aad(blob_key))


def open_sealed(ring: KeyRing, blob_key: str, blob: bytes) -> bytes:
    parsed = _Parsed(blob_key, blob)
    dek = _unwrap(ring, blob_key, parsed)
    nonce, ciphertext = parsed.data_part[:_NONCE_LEN], parsed.data_part[_NONCE_LEN:]
    try:
        return AESGCM(dek).decrypt(nonce, ciphertext, _data_aad(blob_key))
    except InvalidTag:
        raise _fail(blob_key, "ciphertext did not authenticate (edited, truncated or swapped object)") from None


def rewrap_sealed(ring: KeyRing, blob_key: str, blob: bytes) -> bytes | None:
    """The object with its data key wrapped by the active master key, or None when it already is."""
    parsed = _Parsed(blob_key, blob)
    if parsed.key_id == ring.active_id:
        # Still check the wrap, so "current" never hides an object that would fail to open.
        _unwrap(ring, blob_key, parsed)
        return None
    dek = _unwrap(ring, blob_key, parsed)
    return _wrap(ring, blob_key, dek) + parsed.data_part


class VaultBlobStore:
    """A BlobStore that encrypts on put and decrypts on get. Same protocol, so nothing above storage/ changes."""

    def __init__(self, inner: BlobStore, ring: KeyRing, *, allow_plaintext: bool = True) -> None:
        self._inner = inner
        self._ring = ring
        # Old uploads are plain. Turning this off (after rotate has encrypted everything) also rejects a plain file
        # slipped in where an encrypted one should be.
        self._allow_plaintext = allow_plaintext

    @property
    def key_id(self) -> str:
        return self._ring.active_id

    async def put(self, key: str, data: bytes) -> None:
        await self._inner.put(key, await asyncio.to_thread(seal, self._ring, key, data))

    async def get(self, key: str) -> bytes:
        blob = await self._inner.get(key)
        if not is_encrypted(blob):
            if not self._allow_plaintext:
                raise _fail(key, "object is not encrypted")
            return blob
        return await asyncio.to_thread(open_sealed, self._ring, key, blob)

    async def delete(self, key: str) -> None:
        await self._inner.delete(key)

    async def rewrap(self, key: str) -> RewrapResult:
        """Bring one object up to the active key: encrypt a legacy object, re-wrap one under an old key, or do nothing."""
        blob = await self._inner.get(key)
        if not is_encrypted(blob):
            await self.put(key, blob)
            return "encrypted"
        updated = await asyncio.to_thread(rewrap_sealed, self._ring, key, blob)
        if updated is None:
            return "current"
        await self._inner.put(key, updated)
        return "rewrapped"
