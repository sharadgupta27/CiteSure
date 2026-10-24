from fastapi import APIRouter

from app.api import (
    routes_ask,
    routes_auth,
    routes_documents,
    routes_evaluation,
    routes_research,
    routes_workspaces,
)

api_router = APIRouter()
for module in (routes_auth, routes_workspaces, routes_documents, routes_ask, routes_research, routes_evaluation):
    api_router.include_router(module.router)

__all__ = ["api_router"]
