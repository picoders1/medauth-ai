"""Alembic environment.

The database URL comes from ``MEDAUTH_DATABASE_URL`` rather than ``alembic.ini``,
so the schema and the application can never disagree about which database they
mean. The schema is versioned and never auto-created.
"""

from __future__ import annotations

import asyncio
from logging.config import fileConfig

from alembic import context
from sqlalchemy import pool
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import async_engine_from_config

from app.audit import models as _audit_models  # noqa: F401  - registers the tables
from app.config.settings import get_settings
from app.database.base import Base
from app.policy import models as _policy_models  # noqa: F401  - registers the tables

config = context.config
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

config.set_main_option("sqlalchemy.url", get_settings().database_url)

# Importing the model modules above registers their tables on this metadata.
# Autogenerate is a drafting aid only; migrations are written and reviewed by hand,
# because a schema change here is a change to what the audit trail can record.
target_metadata = Base.metadata


def run_migrations_offline() -> None:
    context.configure(
        url=config.get_main_option("sqlalchemy.url"),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()


def _run(connection: Connection) -> None:
    context.configure(connection=connection, target_metadata=target_metadata)
    with context.begin_transaction():
        context.run_migrations()


async def run_migrations_online() -> None:
    engine = async_engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    async with engine.connect() as connection:
        await connection.run_sync(_run)
    await engine.dispose()


if context.is_offline_mode():
    run_migrations_offline()
else:
    asyncio.run(run_migrations_online())
