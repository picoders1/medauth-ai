"""Declarative base and shared column conventions."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from sqlalchemy import DateTime, MetaData
from sqlalchemy.orm import DeclarativeBase, mapped_column

__all__ = ["NAMING_CONVENTION", "Base", "utc_now_column", "uuid_pk"]

#: Deterministic constraint names, so Alembic autogenerate produces stable
#: migrations instead of database-assigned identifiers that differ per install.
NAMING_CONVENTION = {
    "ix": "ix_%(table_name)s_%(column_0_N_name)s",
    "uq": "uq_%(table_name)s_%(column_0_N_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}


class Base(DeclarativeBase):
    metadata = MetaData(naming_convention=NAMING_CONVENTION)


def uuid_pk() -> uuid.UUID:
    return uuid.uuid4()


def utc_now_column() -> datetime:
    return datetime.now(UTC)


UTCDateTime = DateTime(timezone=True)

# Re-exported for model modules; keeps the tz=True decision in one place.
_ = mapped_column
