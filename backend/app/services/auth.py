from __future__ import annotations

from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings
from app.errors import Conflict, Unauthorized
from app.repositories import users as users_repo
from app.schemas import api as s
from app.security import create_token, decode_token, hash_password, verify_password


class AuthService:
    def __init__(self, session: AsyncSession, settings: Settings) -> None:
        self.session = session
        self.settings = settings

    async def register(self, email: str, password: str) -> s.TokenResponse:
        if await users_repo.get_by_email(self.session, email):
            raise Conflict("An account with this email already exists")
        try:
            user = await users_repo.create_user(self.session, email, await hash_password(password))
            await self.session.commit()
        except IntegrityError as exc:  # two simultaneous registrations
            await self.session.rollback()
            raise Conflict("An account with this email already exists") from exc
        return self._token_response(user)

    async def login(self, email: str, password: str) -> s.TokenResponse:
        user = await users_repo.get_by_email(self.session, email)
        ok = await verify_password(password, user.password_hash if user else None)
        if user is None or not ok:
            raise Unauthorized("Wrong email or password")
        return self._token_response(user)

    async def user_from_token(self, token: str) -> s.User:
        user = await users_repo.get_by_id(self.session, decode_token(self.settings, token))
        if user is None:
            raise Unauthorized("The account no longer exists")
        return s.User.model_validate(user)

    def _token_response(self, user: object) -> s.TokenResponse:
        user_schema = s.User.model_validate(user)
        return s.TokenResponse(
            access_token=create_token(self.settings, user_schema.id), token_type="bearer", user=user_schema
        )
