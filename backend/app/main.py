"""FastAPI application factory."""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager
from typing import Any

from fastapi import FastAPI, Request, Response
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.openapi.utils import get_openapi
from fastapi.responses import JSONResponse
from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.api import api_router, routes_ops
from app.api.ratelimit import RateLimiter
from app.config import Settings, get_settings
from app.db import make_engine, make_sessionmaker
from app.errors import AppError
from app.observability import HTTP_REQUESTS, setup_tracing
from app.providers import Providers, build_providers
from app.schemas import api as api_schemas

log = logging.getLogger("citesure.api")

SECURITY_HEADERS = {
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
    "Referrer-Policy": "no-referrer",
    "Permissions-Policy": "geolocation=(), microphone=(), camera=()",
}


def create_app(
    settings: Settings | None = None,
    *,
    providers: Providers | None = None,
    engine: AsyncEngine | None = None,
) -> FastAPI:
    settings = settings or get_settings()
    settings.assert_safe_for_prod()
    if settings.jwt_secret.startswith("dev-only"):
        log.warning(
            "Running with the built-in development JWT secret: anyone can forge tokens. Set JWT_SECRET (and ENV=prod)."
        )
    setup_tracing(settings)
    owns_engine = engine is None

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        app.state.engine = engine or make_engine(settings.database_url)
        sessionmaker: async_sessionmaker = make_sessionmaker(app.state.engine)  # type: ignore[type-arg]
        app.state.sessionmaker = sessionmaker
        app.state.providers = providers or build_providers(settings)
        yield
        if providers is None and app.state.providers.research is not None:
            await app.state.providers.research.aclose()
        if owns_engine:
            await app.state.engine.dispose()

    app = FastAPI(
        title="CiteSure API",
        version="1.0.0",
        lifespan=lifespan,
        separate_input_output_schemas=False,  # one schema per model, like openapi.yaml
        docs_url="/docs" if settings.env != "prod" else None,
        redoc_url=None,
    )
    app.state.settings = settings
    app.state.ask_limiter = RateLimiter(settings.rate_limit_ask_per_min)
    app.state.auth_limiter = RateLimiter(settings.rate_limit_auth_per_min)

    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origin_list,  # explicit origins only, never "*"
        allow_credentials=False,
        allow_methods=["GET", "POST", "PATCH", "DELETE"],
        allow_headers=["Authorization", "Content-Type"],
    )

    @app.middleware("http")
    async def add_security_headers(request: Request, call_next: Callable[[Request], Awaitable[Response]]) -> Response:
        response = await call_next(request)
        for name, value in SECURITY_HEADERS.items():
            response.headers.setdefault(name, value)
        HTTP_REQUESTS.labels(method=request.method, status=str(response.status_code)).inc()
        return response

    @app.exception_handler(AppError)
    async def app_error_handler(_: Request, exc: AppError) -> JSONResponse:
        return JSONResponse({"code": exc.code, "detail": exc.detail}, status_code=exc.status_code)

    @app.exception_handler(RequestValidationError)
    async def validation_handler(_: Request, exc: RequestValidationError) -> JSONResponse:
        # Field paths and messages only: never echo the submitted values back (they may contain document text).
        detail = "; ".join(f"{'.'.join(str(p) for p in e['loc'] if p != 'body')}: {e['msg']}" for e in exc.errors()[:5])
        return JSONResponse({"code": "invalid_input", "detail": detail}, status_code=422)

    @app.exception_handler(StarletteHTTPException)
    async def http_handler(_: Request, exc: StarletteHTTPException) -> JSONResponse:
        return JSONResponse({"code": "http_error", "detail": str(exc.detail)}, status_code=exc.status_code)

    @app.exception_handler(Exception)
    async def unhandled_handler(request: Request, exc: Exception) -> JSONResponse:
        log.exception("unhandled error method=%s path=%s", request.method, request.url.path)  # no bodies, no question text
        return JSONResponse({"code": "internal_error", "detail": "Something went wrong"}, status_code=500)

    app.include_router(api_router, prefix="/api/v1")
    app.include_router(routes_ops.router)
    app.openapi = lambda: _openapi_with_documented_models(app)  # type: ignore[method-assign]
    return app


def _openapi_with_documented_models(app: FastAPI) -> dict[str, Any]:
    """FastAPI only emits schemas that some route returns. The error body and the SSE event are part of the public
    contract (openapi.yaml) but are not route response models, so they are added here."""
    if app.openapi_schema:
        return app.openapi_schema
    schema = get_openapi(title=app.title, version=app.version, routes=app.routes)
    schemas = schema.setdefault("components", {}).setdefault("schemas", {})
    for model in (api_schemas.Error, api_schemas.StreamEvent):
        json_schema = model.model_json_schema(ref_template="#/components/schemas/{model}")
        schemas.update(json_schema.pop("$defs", {}))
        schemas.setdefault(model.__name__, json_schema)
    app.openapi_schema = schema
    return schema


def app_factory() -> FastAPI:
    """uvicorn entry point: `uvicorn app.main:app_factory --factory`."""
    return create_app()
