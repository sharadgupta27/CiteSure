from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker, create_async_engine


def make_engine(database_url: str, *, echo: bool = False) -> AsyncEngine:
    # hide_parameters: SQLAlchemy error messages otherwise include the bound values, which for chunks are document text.
    return create_async_engine(
        database_url, echo=echo, pool_pre_ping=True, pool_size=10, max_overflow=10, hide_parameters=True
    )


def make_sessionmaker(engine: AsyncEngine) -> async_sessionmaker[AsyncSession]:
    return async_sessionmaker(engine, expire_on_commit=False)
