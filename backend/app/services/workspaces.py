"""Workspaces, members, groups and collections (everything an admin manages except documents)."""

from __future__ import annotations

import uuid

from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.errors import Conflict, Forbidden, InvalidInput, NotFound
from app.repositories import asks as asks_repo
from app.repositories import collections as collections_repo
from app.repositories import documents as documents_repo
from app.repositories import users as users_repo
from app.repositories import workspaces as workspaces_repo
from app.schemas import api as s
from app.services import acl
from app.storage.base import BlobStore


class WorkspaceService:
    def __init__(self, session: AsyncSession, blobs: BlobStore) -> None:
        self.session = session
        self.blobs = blobs

    # --- workspaces and members -------------------------------------------------------------
    async def list_workspaces(self, user_id: uuid.UUID) -> list[s.Workspace]:
        rows = await workspaces_repo.list_for_user(self.session, user_id)
        return [s.Workspace(id=w.id, name=w.name, role=role, created_at=w.created_at) for w, role in rows]

    async def create_workspace(self, user_id: uuid.UUID, name: str) -> s.Workspace:
        ws = await workspaces_repo.create_workspace(self.session, name.strip())
        await workspaces_repo.add_membership(self.session, user_id, ws.id, "admin")
        await self.session.commit()
        return s.Workspace(id=ws.id, name=ws.name, role="admin", created_at=ws.created_at)

    async def list_members(self, user_id: uuid.UUID, workspace_id: uuid.UUID) -> list[s.Member]:
        await acl.require_admin(self.session, user_id, workspace_id)
        rows = await workspaces_repo.list_members(self.session, workspace_id)
        return [s.Member(user_id=i, email=e, role=r) for i, e, r in rows]

    async def add_member(self, user_id: uuid.UUID, workspace_id: uuid.UUID, email: str, role: str) -> s.Member:
        await acl.require_admin(self.session, user_id, workspace_id)
        user = await users_repo.get_by_email(self.session, email)
        if user is None:
            raise NotFound("No account with that email. Ask them to register first.")
        if await workspaces_repo.get_role(self.session, user.id, workspace_id):
            raise Conflict("That user is already a member")
        await workspaces_repo.add_membership(self.session, user.id, workspace_id, role)
        await self.session.commit()
        return s.Member(user_id=user.id, email=user.email, role=role)

    # --- groups -----------------------------------------------------------------------------
    async def list_groups(self, user_id: uuid.UUID, workspace_id: uuid.UUID) -> list[s.Group]:
        await acl.require_admin(self.session, user_id, workspace_id)
        rows = await workspaces_repo.list_groups(self.session, workspace_id)
        return [s.Group(id=g.id, workspace_id=g.workspace_id, name=g.name, member_ids=members) for g, members in rows]

    async def create_group(self, user_id: uuid.UUID, workspace_id: uuid.UUID, name: str) -> s.Group:
        await acl.require_admin(self.session, user_id, workspace_id)
        if await workspaces_repo.group_by_name(self.session, workspace_id, name.strip()):
            raise Conflict("A group with this name already exists")
        group = await workspaces_repo.create_group(self.session, workspace_id, name.strip())
        await self.session.commit()
        return s.Group(id=group.id, workspace_id=workspace_id, name=group.name, member_ids=[])

    async def add_group_member(self, user_id: uuid.UUID, group_id: uuid.UUID, email: str) -> s.Group:
        group = await workspaces_repo.get_group(self.session, group_id)
        if group is None:
            raise NotFound("Group not found")
        await acl.require_admin(self.session, user_id, group.workspace_id)
        user = await users_repo.get_by_email(self.session, email)
        if user is None or not await workspaces_repo.get_role(self.session, user.id, group.workspace_id):
            raise NotFound("That person is not a member of this workspace")
        await workspaces_repo.add_group_member(self.session, group_id, user.id)
        await self.session.commit()
        members = await workspaces_repo.group_member_ids(self.session, group_id)
        return s.Group(id=group.id, workspace_id=group.workspace_id, name=group.name, member_ids=members)

    # --- collections ------------------------------------------------------------------------
    async def list_collections(self, user_id: uuid.UUID, workspace_id: uuid.UUID) -> list[s.Collection]:
        context = await acl.context_for_workspace(self.session, user_id, workspace_id)
        allowed = set(context.allowed_collection_ids)
        rows = await collections_repo.list_with_groups(self.session, workspace_id)
        return [self._collection(c, groups) for c, groups in rows if c.id in allowed]

    async def create_collection(self, user_id: uuid.UUID, workspace_id: uuid.UUID, body: s.CollectionCreate) -> s.Collection:
        await acl.require_admin(self.session, user_id, workspace_id)
        await self._validate_groups(workspace_id, body.visibility, body.group_ids)
        try:
            collection = await collections_repo.create(self.session, workspace_id, body.name.strip(), body.visibility)
            await collections_repo.set_groups(
                self.session, collection.id, body.group_ids if body.visibility == "groups" else []
            )
            await self.session.commit()
        except IntegrityError as exc:
            await self.session.rollback()
            raise Conflict("A collection with this name already exists") from exc
        return self._collection(collection, body.group_ids if body.visibility == "groups" else [])

    async def update_collection(
        self, user_id: uuid.UUID, collection_id: uuid.UUID, body: s.CollectionUpdate
    ) -> s.Collection:
        collection = await self._admin_collection(user_id, collection_id)
        visibility = body.visibility or collection.visibility
        current_groups = await collections_repo.group_ids(self.session, collection_id)
        group_ids = body.group_ids if body.group_ids is not None else current_groups
        await self._validate_groups(collection.workspace_id, visibility, group_ids)
        if body.name:
            collection.name = body.name.strip()
        collection.visibility = visibility
        await collections_repo.set_groups(self.session, collection_id, group_ids if visibility == "groups" else [])
        try:
            await self.session.commit()
        except IntegrityError as exc:
            await self.session.rollback()
            raise Conflict("A collection with this name already exists") from exc
        return self._collection(collection, group_ids if visibility == "groups" else [])

    async def delete_collection(self, user_id: uuid.UUID, collection_id: uuid.UUID) -> None:
        await self._admin_collection(user_id, collection_id)
        keys = await collections_repo.blob_keys(self.session, collection_id)
        await asks_repo.scrub_deleted_chunks(
            self.session, await documents_repo.chunk_ids_for_collection_for_worker(self.session, collection_id)
        )
        await collections_repo.delete_collection(self.session, collection_id)  # chunks and documents cascade
        await self.session.commit()
        for key in keys:
            await self.blobs.delete(key)

    async def _admin_collection(self, user_id: uuid.UUID, collection_id: uuid.UUID):  # type: ignore[no-untyped-def]
        collection = await collections_repo.get(self.session, collection_id)
        if collection is None:
            raise NotFound("Collection not found")
        context = await acl.context_for_workspace(self.session, user_id, collection.workspace_id)
        if not context.is_admin:
            if collection_id in context.allowed_collection_ids:
                raise Forbidden("Only workspace admins can do this")
            raise NotFound("Collection not found")
        return collection

    async def _validate_groups(self, workspace_id: uuid.UUID, visibility: str, group_ids: list[uuid.UUID]) -> None:
        if visibility == "groups" and not group_ids:
            raise InvalidInput("A collection restricted to groups needs at least one group")
        if group_ids:
            valid = {g.id for g, _ in await workspaces_repo.list_groups(self.session, workspace_id)}
            if not set(group_ids) <= valid:  # a group from another workspace would grant access across workspaces
                raise InvalidInput("Unknown group")

    @staticmethod
    def _collection(collection, group_ids: list[uuid.UUID]) -> s.Collection:  # type: ignore[no-untyped-def]
        return s.Collection(
            id=collection.id,
            workspace_id=collection.workspace_id,
            name=collection.name,
            visibility=collection.visibility,
            group_ids=list(group_ids),
            created_at=collection.created_at,
        )
