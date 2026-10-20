"""Password hashing and JWTs."""

from __future__ import annotations

import asyncio
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


def decode_token(settings: Settings, token: str) -> uuid.UUID:
    try:
        payload = jwt.decode(token, settings.jwt_secret, algorithms=[ALGORITHM], options={"require": ["exp", "sub"]})
        return uuid.UUID(payload["sub"])
    except (jwt.PyJWTError, ValueError) as exc:
        raise Unauthorized("Invalid or expired token") from exc
