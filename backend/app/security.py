"""Password hashing and JWTs."""

from __future__ import annotations

import asyncio
import hashlib
import hmac
import uuid
from datetime import UTC, datetime, timedelta

import bcrypt
import jwt

from app.config import Settings
from app.errors import Unauthorized

ALGORITHM = "HS256"
# A valid hash of a random password: verifying against it takes as long as a real check, so login timing does
# not reveal whether an email address is registered.
_DUMMY_HASH = bcrypt.hashpw(b"not-a-real-password", bcrypt.gensalt(rounds=12)).decode()


async def hash_password(password: str) -> str:
    return (await asyncio.to_thread(bcrypt.hashpw, password.encode()[:72], bcrypt.gensalt(rounds=12))).decode()


async def verify_password(password: str, password_hash: str | None) -> bool:
    return (
        await asyncio.to_thread(bcrypt.checkpw, password.encode()[:72], (password_hash or _DUMMY_HASH).encode())
        and password_hash is not None
    )


def create_token(settings: Settings, user_id: uuid.UUID) -> str:
    now = datetime.now(UTC)
    payload = {"sub": str(user_id), "iat": now, "exp": now + timedelta(minutes=settings.jwt_expire_minutes)}
    return jwt.encode(payload, settings.jwt_secret, algorithm=ALGORITHM)


FILE_LINK_AUDIENCE = "citesure:file-link"


def _file_link_key(settings: Settings) -> str:
    # A key derived for this one purpose: a download token can never verify as a login token, nor the other way round,
    # even though both come from JWT_SECRET.
    return hmac.new(settings.jwt_secret.encode(), b"citesure file-link v1", hashlib.sha256).hexdigest()


def create_file_link_token(settings: Settings, user_id: uuid.UUID, document_id: uuid.UUID) -> tuple[str, datetime]:
    now = datetime.now(UTC)
    expires = now + timedelta(seconds=settings.file_link_ttl_seconds)
    payload = {"sub": str(user_id), "doc": str(document_id), "aud": FILE_LINK_AUDIENCE, "iat": now, "exp": expires}
    return jwt.encode(payload, _file_link_key(settings), algorithm=ALGORITHM), expires


def decode_file_link_token(settings: Settings, token: str) -> tuple[uuid.UUID, uuid.UUID]:
    """(user id, document id) of a valid, unexpired download link."""
    try:
        payload = jwt.decode(
            token,
            _file_link_key(settings),
            algorithms=[ALGORITHM],
            audience=FILE_LINK_AUDIENCE,
            options={"require": ["exp", "sub", "doc", "aud"]},
        )
        return uuid.UUID(payload["sub"]), uuid.UUID(payload["doc"])
    except (jwt.PyJWTError, ValueError) as exc:
        raise Unauthorized("Invalid or expired download link") from exc


def decode_token(settings: Settings, token: str) -> uuid.UUID:
    try:
        payload = jwt.decode(token, settings.jwt_secret, algorithms=[ALGORITHM], options={"require": ["exp", "sub"]})
        return uuid.UUID(payload["sub"])
    except (jwt.PyJWTError, ValueError) as exc:
        raise Unauthorized("Invalid or expired token") from exc
