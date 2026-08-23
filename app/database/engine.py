"""Async SQLAlchemy engine and session factory.

One datastore holds the corpus, the vectors, the cases and the audit trail
(ADR-005). A command timeout is set deliberately: it is what forces retention to
delete in batches, since one unbounded ``DELETE`` against a backlog would time
out, roll back, and remove nothing while appearing enabled.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from app.config.settings import Settings

__all__ = ["build_engine", "build_session_factory", "session_scope"]


def build_engine(settings: Settings) -> AsyncEngine:
    connect_args: dict[str, object] = {}
    if settings.database_url.startswith("postgresql+asyncpg"):
        connect_args["command_timeout"] = settings.database_command_timeout_seconds
    return create_async_engine(
        settings.database_url,
        pool_pre_ping=True,
        pool_size=10,
        max_overflow=5,
        connect_args=connect_args,
    )


def build_session_factory(engine: AsyncEngine) -> async_sessionmaker[AsyncSession]:
    return async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)


@asynccontextmanager
async def session_scope(
    factory: async_sessionmaker[AsyncSession],
) -> AsyncIterator[AsyncSession]:
    """One transaction. Commits on success, rolls back on any exception."""
    async with factory() as session:
        try:
            yield session
        except Exception:
            await session.rollback()
            raise
        else:
            await session.commit()
