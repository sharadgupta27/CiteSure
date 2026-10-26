from __future__ import annotations

import secrets
import uuid

from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings
from app.errors import Conflict, Forbidden, Unauthorized
from app.repositories import oidc as oidc_repo
from app.repositories import users as users_repo
from app.schemas import api as s
from app.security import create_token, decode_token, hash_password, verify_password
from app.services import audit
from app.services.oidc import OidcClaims, OidcError


class AuthService:
    def __init__(self, session: AsyncSession, settings: Settings) -> None:
        self.session = session
        self.settings = settings

    def _require_password_login(self) -> None:
        if self.settings.oidc_only:
            raise Forbidden("Password sign-in is turned off on this server. Use single sign-on.")

    async def register(self, email: str, password: str) -> s.TokenResponse:
        self._require_password_login()
        if await users_repo.get_by_email(self.session, email):
            raise Conflict("An account with this email already exists")
        try:
            user = await users_repo.create_user(self.session, email, await hash_password(password))
            await self.session.commit()
        except IntegrityError as exc:  # two simultaneous registrations
            await self.session.rollback()
            raise Conflict("An account with this email already exists") from exc
        await audit.record(self.session, user, audit.REGISTER)
        return self._token_response(user)

    async def login(self, email: str, password: str) -> s.TokenResponse:
        self._require_password_login()
        user = await users_repo.get_by_email(self.session, email)
        ok = await verify_password(password, user.password_hash if user else None)
        if user is None or not ok:
            # An address that is not an account is stored as a hash only: people sometimes type a password there.
            await audit.record(
                self.session,
                user,
                audit.LOGIN_FAILED,
                metadata={"known_account": user is not None, **({} if user else {"email_sha256": audit.sha256_hex(email)})},
            )
            raise Unauthorized("Wrong email or password")
        await audit.record(self.session, user, audit.LOGIN, metadata={"method": "password"})
        return self._token_response(user)

    async def login_oidc(self, claims: OidcClaims) -> s.TokenResponse:
        """Map a verified identity to a local user: by the provider's subject, else by verified e-mail address."""
        identity = await oidc_repo.get_identity(self.session, claims.issuer, claims.subject)
        created = False
        if identity is not None:
            user = await users_repo.get_by_id(self.session, identity.user_id)
            if user is None:  # cannot happen (cascade), but never log in "nobody"
                raise OidcError("no_account", "No account is linked to this identity")
            oidc_repo.touch(identity)
        else:
            if not claims.email:
                raise OidcError("no_email", "The identity provider did not release an e-mail address")
            if self.settings.oidc_require_email_verified and not claims.email_verified:
                raise OidcError("email_unverified", "The identity provider has not verified your e-mail address")
            user = await users_repo.get_by_email(self.session, claims.email)
            if user is None:
                if not self.settings.oidc_auto_create_users:
                    raise OidcError("no_account", "There is no CiteSure account for this e-mail address. Ask an admin.")
                # Nobody knows this password, so the account can only be entered through the provider.
                user = await users_repo.create_user(
                    self.session, claims.email, await hash_password(secrets.token_urlsafe(32))
                )
                created = True
            await oidc_repo.add_identity(self.session, user.id, claims.issuer, claims.subject)
        granted, revoked = await self._sync_groups(user.id, claims.groups)
        try:
            await self.session.commit()
        except IntegrityError as exc:  # two first logins at once
            await self.session.rollback()
            raise OidcError("conflict", "Please try signing in again") from exc
        await audit.record(
            self.session,
            user,
            audit.OIDC_LOGIN,
            metadata={"new_account": created, "groups_granted": granted, "groups_revoked": revoked},
        )
        return self._token_response(user)

    async def _sync_groups(self, user_id: uuid.UUID, names: list[str]) -> tuple[int, int]:
        """Make the user's provider-granted groups match the claim, for groups that already exist. Groups are never
        created from a claim, and memberships an admin added by hand are never removed."""
        wanted = {g.id for g in await oidc_repo.groups_named(self.session, user_id, names)}
        before = await oidc_repo.granted_group_ids(self.session, user_id)
        added = 0
        for group_id in wanted - before:
            added += int(await oidc_repo.grant(self.session, user_id, group_id))
        stale = before - wanted
        await oidc_repo.revoke(self.session, user_id, stale)
        return added, len(stale)

    async def record_oidc_failure(self, reason: str) -> None:
        await audit.record(self.session, None, audit.OIDC_FAILED, metadata={"reason": reason})

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
