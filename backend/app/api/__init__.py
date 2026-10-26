from fastapi import APIRouter

from app.api import (
    routes_annotations,
    routes_ask,
    routes_audit,
    routes_auth,
    routes_dashboard,
    routes_documents,
    routes_evaluation,
    routes_fulltext,
    routes_inbox,
    routes_learning,
    routes_oidc,
    routes_research,
    routes_workspaces,
)

api_router = APIRouter()
for module in (
    routes_auth,
    routes_oidc,
    routes_workspaces,
    routes_documents,
    routes_ask,
    routes_research,
    routes_evaluation,
    routes_annotations,
    routes_inbox,
    routes_fulltext,
    routes_learning,
    routes_audit,
    routes_dashboard,
):
    api_router.include_router(module.router)

__all__ = ["api_router"]
