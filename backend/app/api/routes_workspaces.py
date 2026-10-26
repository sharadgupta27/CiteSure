from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, Response

from app.api.deps import current_user, workspace_service
from app.api.deps_admin import audit_log
from app.schemas import api as s
from app.services import audit as audit_actions
from app.services.audit import AuditLog
from app.services.workspaces import WorkspaceService

router = APIRouter()


@router.get("/workspaces", tags=["workspaces"], operation_id="listWorkspaces", response_model=list[s.Workspace])
async def list_workspaces(
    user: s.User = Depends(current_user), svc: WorkspaceService = Depends(workspace_service)
) -> list[s.Workspace]:
    return await svc.list_workspaces(user.id)


@router.post("/workspaces", tags=["workspaces"], operation_id="createWorkspace", status_code=201, response_model=s.Workspace)
async def create_workspace(
    body: s.WorkspaceCreate,
    user: s.User = Depends(current_user),
    svc: WorkspaceService = Depends(workspace_service),
    audit: AuditLog = Depends(audit_log),
) -> s.Workspace:
    ws = await svc.create_workspace(user.id, body.name)
    await audit.record(user, audit_actions.WORKSPACE_CREATE, f"workspace:{ws.id}", ws.id)
    return ws


@router.get(
    "/workspaces/{workspace_id}/members", tags=["workspaces"], operation_id="listMembers", response_model=list[s.Member]
)
async def list_members(
    workspace_id: uuid.UUID, user: s.User = Depends(current_user), svc: WorkspaceService = Depends(workspace_service)
) -> list[s.Member]:
    return await svc.list_members(user.id, workspace_id)


@router.post(
    "/workspaces/{workspace_id}/members",
    tags=["workspaces"],
    operation_id="addMember",
    status_code=201,
    response_model=s.Member,
)
async def add_member(
    workspace_id: uuid.UUID,
    body: s.MemberAdd,
    user: s.User = Depends(current_user),
    svc: WorkspaceService = Depends(workspace_service),
    audit: AuditLog = Depends(audit_log),
) -> s.Member:
    member = await svc.add_member(user.id, workspace_id, body.email, body.role)
    await audit.record(user, audit_actions.MEMBER_ADD, f"user:{member.user_id}", workspace_id, {"role": member.role})
    return member


@router.get(
    "/workspaces/{workspace_id}/groups", tags=["workspaces"], operation_id="listGroups", response_model=list[s.Group]
)
async def list_groups(
    workspace_id: uuid.UUID, user: s.User = Depends(current_user), svc: WorkspaceService = Depends(workspace_service)
) -> list[s.Group]:
    return await svc.list_groups(user.id, workspace_id)


@router.post(
    "/workspaces/{workspace_id}/groups",
    tags=["workspaces"],
    operation_id="createGroup",
    status_code=201,
    response_model=s.Group,
)
async def create_group(
    workspace_id: uuid.UUID,
    body: s.GroupCreate,
    user: s.User = Depends(current_user),
    svc: WorkspaceService = Depends(workspace_service),
    audit: AuditLog = Depends(audit_log),
) -> s.Group:
    group = await svc.create_group(user.id, workspace_id, body.name)
    await audit.record(user, audit_actions.GROUP_CREATE, f"group:{group.id}", workspace_id)
    return group


@router.post("/groups/{group_id}/members", tags=["workspaces"], operation_id="addGroupMember", response_model=s.Group)
async def add_group_member(
    group_id: uuid.UUID,
    body: s.GroupMemberAdd,
    user: s.User = Depends(current_user),
    svc: WorkspaceService = Depends(workspace_service),
    audit: AuditLog = Depends(audit_log),
) -> s.Group:
    group = await svc.add_group_member(user.id, group_id, body.email)
    await audit.record(
        user,
        audit_actions.GROUP_MEMBER_ADD,
        f"group:{group_id}",
        group.workspace_id,
        {"member_email_sha256": audit_actions.sha256_hex(body.email), "members": len(group.member_ids)},
    )
    return group


@router.get(
    "/workspaces/{workspace_id}/collections",
    tags=["collections"],
    operation_id="listCollections",
    response_model=list[s.Collection],
)
async def list_collections(
    workspace_id: uuid.UUID, user: s.User = Depends(current_user), svc: WorkspaceService = Depends(workspace_service)
) -> list[s.Collection]:
    return await svc.list_collections(user.id, workspace_id)


@router.post(
    "/workspaces/{workspace_id}/collections",
    tags=["collections"],
    operation_id="createCollection",
    status_code=201,
    response_model=s.Collection,
)
async def create_collection(
    workspace_id: uuid.UUID,
    body: s.CollectionCreate,
    user: s.User = Depends(current_user),
    svc: WorkspaceService = Depends(workspace_service),
    audit: AuditLog = Depends(audit_log),
) -> s.Collection:
    collection = await svc.create_collection(user.id, workspace_id, body)
    await audit.record(
        user,
        audit_actions.COLLECTION_CREATE,
        f"collection:{collection.id}",
        workspace_id,
        {"visibility": collection.visibility, "groups": len(collection.group_ids)},
    )
    return collection


@router.patch(
    "/collections/{collection_id}", tags=["collections"], operation_id="updateCollection", response_model=s.Collection
)
async def update_collection(
    collection_id: uuid.UUID,
    body: s.CollectionUpdate,
    user: s.User = Depends(current_user),
    svc: WorkspaceService = Depends(workspace_service),
    audit: AuditLog = Depends(audit_log),
) -> s.Collection:
    collection = await svc.update_collection(user.id, collection_id, body)
    await audit.record(
        user,
        audit_actions.COLLECTION_UPDATE,
        f"collection:{collection_id}",
        collection.workspace_id,
        {"visibility": collection.visibility, "groups": len(collection.group_ids), "renamed": body.name is not None},
    )
    return collection


@router.delete("/collections/{collection_id}", tags=["collections"], operation_id="deleteCollection", status_code=204)
async def delete_collection(
    collection_id: uuid.UUID,
    user: s.User = Depends(current_user),
    svc: WorkspaceService = Depends(workspace_service),
    audit: AuditLog = Depends(audit_log),
) -> Response:
    workspace_id = await audit.workspace_of("collection", collection_id)  # the row is gone after the delete
    await svc.delete_collection(user.id, collection_id)
    await audit.record(user, audit_actions.COLLECTION_DELETE, f"collection:{collection_id}", workspace_id)
    return Response(status_code=204)
