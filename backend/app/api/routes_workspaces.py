from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, Response

from app.api.deps import current_user, workspace_service
from app.schemas import api as s
from app.services.workspaces import WorkspaceService

router = APIRouter()


@router.get("/workspaces", tags=["workspaces"], operation_id="listWorkspaces", response_model=list[s.Workspace])
async def list_workspaces(
    user: s.User = Depends(current_user), svc: WorkspaceService = Depends(workspace_service)
) -> list[s.Workspace]:
    return await svc.list_workspaces(user.id)


@router.post("/workspaces", tags=["workspaces"], operation_id="createWorkspace", status_code=201, response_model=s.Workspace)
async def create_workspace(
    body: s.WorkspaceCreate, user: s.User = Depends(current_user), svc: WorkspaceService = Depends(workspace_service)
) -> s.Workspace:
    return await svc.create_workspace(user.id, body.name)


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
) -> s.Member:
    return await svc.add_member(user.id, workspace_id, body.email, body.role)


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
) -> s.Group:
    return await svc.create_group(user.id, workspace_id, body.name)


@router.post("/groups/{group_id}/members", tags=["workspaces"], operation_id="addGroupMember", response_model=s.Group)
async def add_group_member(
    group_id: uuid.UUID,
    body: s.GroupMemberAdd,
    user: s.User = Depends(current_user),
    svc: WorkspaceService = Depends(workspace_service),
) -> s.Group:
    return await svc.add_group_member(user.id, group_id, body.email)


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
) -> s.Collection:
    return await svc.create_collection(user.id, workspace_id, body)


@router.patch(
    "/collections/{collection_id}", tags=["collections"], operation_id="updateCollection", response_model=s.Collection
)
async def update_collection(
    collection_id: uuid.UUID,
    body: s.CollectionUpdate,
    user: s.User = Depends(current_user),
    svc: WorkspaceService = Depends(workspace_service),
) -> s.Collection:
    return await svc.update_collection(user.id, collection_id, body)


@router.delete("/collections/{collection_id}", tags=["collections"], operation_id="deleteCollection", status_code=204)
async def delete_collection(
    collection_id: uuid.UUID, user: s.User = Depends(current_user), svc: WorkspaceService = Depends(workspace_service)
) -> Response:
    await svc.delete_collection(user.id, collection_id)
    return Response(status_code=204)
