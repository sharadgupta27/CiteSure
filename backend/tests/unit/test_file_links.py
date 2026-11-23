"""Signed download links: bound to one user and one document, short-lived, and never interchangeable with a login."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import jwt
import pytest

from app.config import Settings
from app.errors import Unauthorized
from app.security import (
    ALGORITHM,
    FILE_LINK_AUDIENCE,
    _file_link_key,
    create_file_link_token,
    create_token,
    decode_file_link_token,
    decode_token,
)

SETTINGS = Settings(jwt_secret="unit-test-secret-" + "x" * 40, file_link_ttl_seconds=60)
USER, DOC = uuid.uuid4(), uuid.uuid4()


def test_round_trip_names_the_user_and_the_document() -> None:
    token, expires = create_file_link_token(SETTINGS, USER, DOC)
    assert decode_file_link_token(SETTINGS, token) == (USER, DOC)
    assert timedelta(seconds=55) < expires - datetime.now(UTC) <= timedelta(seconds=60)


def test_an_expired_link_is_rejected() -> None:
    past = datetime.now(UTC) - timedelta(seconds=5)
    payload = {"sub": str(USER), "doc": str(DOC), "aud": FILE_LINK_AUDIENCE, "iat": past, "exp": past}
    token = jwt.encode(payload, _file_link_key(SETTINGS), algorithm=ALGORITHM)
    with pytest.raises(Unauthorized):
        decode_file_link_token(SETTINGS, token)


def test_a_link_signed_with_another_secret_is_rejected() -> None:
    other = Settings(jwt_secret="another-secret-" + "y" * 40)
    token, _ = create_file_link_token(other, USER, DOC)
    with pytest.raises(Unauthorized):
        decode_file_link_token(SETTINGS, token)


def test_a_login_token_is_not_a_download_link() -> None:
    with pytest.raises(Unauthorized):
        decode_file_link_token(SETTINGS, create_token(SETTINGS, USER))


def test_a_download_link_is_not_a_login_token() -> None:
    token, _ = create_file_link_token(SETTINGS, USER, DOC)
    with pytest.raises(Unauthorized):
        decode_token(SETTINGS, token)


def test_the_lifetime_is_bounded() -> None:
    with pytest.raises(ValueError):
        Settings(file_link_ttl_seconds=3600)
