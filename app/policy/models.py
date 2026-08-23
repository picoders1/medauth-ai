"""ORM for the policy corpus - the schema in data-architecture.md section 3.1.

Four tables, and the interesting one is ``policy_code_links``. It is deliberately a
plain table with a plain index rather than anything clever, because applicability
must be reproducible, explainable to a reviewer in one sentence, and diffable when
the corpus is refreshed. **It is the whole of policy resolution** (ADR-004).

``policy_versions`` carries the temporal columns that make "which version was in
force on the date of service" answerable. A version is never edited on refresh; a
new one is added, so a case adjudicated last month still resolves to the text that
adjudicated it.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime
from enum import StrEnum

from pgvector.sqlalchemy import Vector
from sqlalchemy import (
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import UUID as PgUUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database.base import Base, utc_now_column, uuid_pk

__all__ = [
    "EMBEDDING_DIMENSION",
    "DocumentType",
    "LinkType",
    "PolicyChunk",
    "PolicyCodeLink",
    "PolicyDocument",
    "PolicyScope",
    "PolicyVersion",
]

#: Fixed at migration time. `bge-base-en-v1.5` emits 768. Changing the encoder to a
#: different width is a migration plus a full re-embed, never a silent truncation -
#: ingest asserts the measured dimension against this value and refuses to write.
EMBEDDING_DIMENSION = 768


class DocumentType(StrEnum):
    """Where a document sits in the Medicare coverage hierarchy.

    The layers are distinct sources of authority and must not be conflated:
    statute, then REGULATION (42 CFR), then NCD (national), then LCD (local, by
    contractor), with ARTICLE attached to an LCD. A regulation labelled as an NCD
    would misstate both its authority and its scope.
    """

    REGULATION = "REGULATION"
    NCD = "NCD"
    LCD = "LCD"
    ARTICLE = "ARTICLE"


class PolicyScope(StrEnum):
    NATIONAL = "NATIONAL"
    JURISDICTIONAL = "JURISDICTIONAL"


class LinkType(StrEnum):
    """Why a code appears in a policy version.

    The distinction is load-bearing for resolution: a procedure code establishes
    *applicability*, a diagnosis code *supports* it, and an excluded code means the
    policy applies and speaks against coverage. Collapsing them would make
    "this policy applies" and "this policy is satisfied" the same question.
    """

    COVERED_PROCEDURE = "COVERED_PROCEDURE"
    SUPPORTING_DIAGNOSIS = "SUPPORTING_DIAGNOSIS"
    EXCLUDED = "EXCLUDED"


class PolicyDocument(Base):
    """A policy as an identity, independent of any particular revision."""

    __tablename__ = "policy_documents"
    __table_args__ = (UniqueConstraint("policy_id", "document_type"),)

    id: Mapped[uuid.UUID] = mapped_column(PgUUID(as_uuid=True), primary_key=True, default=uuid_pk)
    policy_id: Mapped[str] = mapped_column(String(64), nullable=False)
    document_type: Mapped[DocumentType] = mapped_column(String(16), nullable=False)
    title: Mapped[str] = mapped_column(Text, nullable=False)
    source_url: Mapped[str] = mapped_column(Text, nullable=False)
    source_authority: Mapped[str] = mapped_column(String(128), nullable=False, default="CMS")
    contractor: Mapped[str | None] = mapped_column(String(128), nullable=True)
    first_seen_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utc_now_column
    )

    versions: Mapped[list[PolicyVersion]] = relationship(
        back_populates="document", cascade="all, delete-orphan"
    )


class PolicyVersion(Base):
    """One revision of a policy, with the dates that make it temporally locatable."""

    __tablename__ = "policy_versions"
    __table_args__ = (
        UniqueConstraint("document_id", "revision_id"),
        CheckConstraint(
            "end_date IS NULL OR end_date >= effective_date", name="end_date_after_effective"
        ),
        # Resolution filters on these three together, in this order.
        Index("ix_policy_versions_temporal", "effective_date", "end_date"),
        Index("ix_policy_versions_jurisdiction", "scope", "jurisdiction"),
    )

    id: Mapped[uuid.UUID] = mapped_column(PgUUID(as_uuid=True), primary_key=True, default=uuid_pk)
    document_id: Mapped[uuid.UUID] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("policy_documents.id", ondelete="CASCADE"), nullable=False
    )
    revision_id: Mapped[str] = mapped_column(String(64), nullable=False)
    scope: Mapped[PolicyScope] = mapped_column(String(16), nullable=False)
    jurisdiction: Mapped[str | None] = mapped_column(String(32), nullable=True)

    #: Selection is by date of service, never "latest". `end_date IS NULL` means
    #: currently in force - not "most recent".
    effective_date: Mapped[date] = mapped_column(Date, nullable=False)
    end_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    revision_date: Mapped[date | None] = mapped_column(Date, nullable=True)

    superseded_by: Mapped[uuid.UUID | None] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("policy_versions.id", ondelete="SET NULL"), nullable=True
    )
    content_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    ingested_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utc_now_column
    )

    document: Mapped[PolicyDocument] = relationship(back_populates="versions")
    code_links: Mapped[list[PolicyCodeLink]] = relationship(
        back_populates="version", cascade="all, delete-orphan"
    )
    chunks: Mapped[list[PolicyChunk]] = relationship(
        back_populates="version", cascade="all, delete-orphan"
    )


class PolicyCodeLink(Base):
    """THE RESOLUTION INDEX. Applicability is these rows, and nothing else."""

    __tablename__ = "policy_code_links"
    __table_args__ = (
        # Resolution reads this first: given a procedure code, which versions list it?
        Index("ix_policy_code_links_code", "code", "code_system"),
    )

    policy_version_id: Mapped[uuid.UUID] = mapped_column(
        PgUUID(as_uuid=True),
        ForeignKey("policy_versions.id", ondelete="CASCADE"),
        primary_key=True,
    )
    code: Mapped[str] = mapped_column(String(16), primary_key=True)
    code_system: Mapped[str] = mapped_column(String(16), primary_key=True)
    link_type: Mapped[LinkType] = mapped_column(String(24), primary_key=True)

    version: Mapped[PolicyVersion] = relationship(back_populates="code_links")


class PolicyChunk(Base):
    """A section-bounded passage, with the provenance a citation needs."""

    __tablename__ = "policy_chunks"
    __table_args__ = (
        UniqueConstraint("policy_version_id", "ordinal"),
        CheckConstraint("page_to >= page_from", name="page_range_ordered"),
        # The scoping filter. Every search is restricted to resolved versions, so
        # this index is on the hot path of every retrieval (ADR-004).
        Index("ix_policy_chunks_version", "policy_version_id"),
        Index(
            "ix_policy_chunks_embedding_hnsw",
            "embedding",
            postgresql_using="hnsw",
            postgresql_ops={"embedding": "vector_cosine_ops"},
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(PgUUID(as_uuid=True), primary_key=True, default=uuid_pk)
    policy_version_id: Mapped[uuid.UUID] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("policy_versions.id", ondelete="CASCADE"), nullable=False
    )
    section_path: Mapped[str] = mapped_column(Text, nullable=False)
    ordinal: Mapped[int] = mapped_column(Integer, nullable=False)
    page_from: Mapped[int] = mapped_column(Integer, nullable=False)
    page_to: Mapped[int] = mapped_column(Integer, nullable=False)
    text: Mapped[str] = mapped_column(Text, nullable=False)

    #: Tamper and drift detection. A historical citation can be re-validated against
    #: the chunk it named; a hash mismatch is a poisoning signal rather than a
    #: silent behaviour change (threat T-06).
    text_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    token_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    embedding: Mapped[list[float] | None] = mapped_column(
        Vector(EMBEDDING_DIMENSION), nullable=True
    )

    version: Mapped[PolicyVersion] = relationship(back_populates="chunks")
