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

from app.core.identity import PolicyType
from app.database.base import Base, utc_now_column, uuid_pk

__all__ = [
    "EMBEDDING_DIMENSION",
    "DocumentType",
    "LinkProvenance",
    "LinkReviewStatus",
    "LinkType",
    "PolicyChunk",
    "PolicyCodeLink",
    "PolicyDocument",
    "PolicyScope",
    "PolicyVersion",
    "TemporalStatus",
    "WindowDerivation",
]

#: Fixed at migration time. `bge-base-en-v1.5` emits 768. Changing the encoder to a
#: different width is a migration plus a full re-embed, never a silent truncation -
#: ingest asserts the measured dimension against this value and refuses to write.
EMBEDDING_DIMENSION = 768


#: Alias. The vocabulary moved to `app.core.identity` in Phase 6, because policy
#: type is part of a policy's IDENTITY and `app.decision` may not import
#: `app.policy`. Kept under the old name so every existing call site and every
#: stored `document_type` string keeps working - the members and values are the
#: same objects, not a parallel enum that could drift.
DocumentType = PolicyType


class TemporalStatus(StrEnum):
    """Whether this version's effective date is known.

    Introduced for NCDs, where the CMS Coverage API publishes prose where a date
    belongs - "This is a longstanding national coverage determination. The
    effective date of this version has not been posted." was returned for 14 of 24
    records sampled during Phase 5 planning.

    An `UNDATED` version is stored, indexed and retrievable by id, and is
    **unreachable by date of service**. That is the fail-closed reading: the
    absence of a fact produces no decision, never a default fact. Encoding the
    unknown as `date.min` would have converted "we do not know when this took
    effect" into "it has always been in effect" - the widest-applicability
    direction, and one that would print a fabricated date to a reviewer.
    """

    DATED = "DATED"
    UNDATED = "UNDATED"

    #: The source published something date-shaped that cannot be trusted as a
    #: version window - two versions claiming the same effective date, or an end
    #: date preceding its own start. Treated exactly like UNDATED for resolution;
    #: kept distinct so the corpus records *which* kind of problem the source has.
    AMBIGUOUS = "AMBIGUOUS"

    @property
    def is_resolvable(self) -> bool:
        return self is TemporalStatus.DATED


class WindowDerivation(StrEnum):
    """Where a version's [effective, end] window came from.

    Exists so `ResolvedVersion.why` can tell a reviewer that an end date was
    *derived* rather than published. Presenting a derived fact as a published one
    is the same class of error as a sentinel date, one field over.
    """

    #: Both dates as the source published them.
    POSTED = "POSTED"

    #: End inferred from the next version's effective date. Ends may be inferred
    #: because inferring one NARROWS applicability; starts are never inferred,
    #: because inferring one widens it.
    DERIVED_FROM_SEQUENCE = "DERIVED_FROM_SEQUENCE"

    #: End taken from a document-level retirement date. It may close a window; it
    #: may never open one.
    POSTED_RETIREMENT = "POSTED_RETIREMENT"


class PolicyScope(StrEnum):
    NATIONAL = "NATIONAL"
    JURISDICTIONAL = "JURISDICTIONAL"


class LinkProvenance(StrEnum):
    """On what authority a code is linked to a policy version.

    The three levels are not a quality scale, they are three different *kinds of
    claim*, and only the first is a claim about the source rather than about us.

    No link in this corpus is `SOURCE_STATED`, and none can be from the present
    sources: 42 CFR enumerates no procedure codes, and the CMS Coverage API's NCD
    record carries no procedure-code field at all - 19 fields, none of them codes,
    verified by live probe. The member exists so that a future source which *does*
    supply linkage is distinguishable from the judgement calls made here.
    """

    #: The source document itself states the relationship. Authoritative.
    SOURCE_STATED = "SOURCE_STATED"

    #: A person judged the code falls within the policy's subject matter.
    #: **Not authoritative until reviewed** - see `LinkReviewStatus`.
    HUMAN_CURATED = "HUMAN_CURATED"

    #: The relationship rests on resemblance rather than on a judgement about the
    #: text. **Must not enter production decision logic**, because applicability
    #: from similarity is precisely what ADR-004 exists to prevent.
    ENGINEERING_INFERRED = "ENGINEERING_INFERRED"

    @property
    def is_authoritative(self) -> bool:
        """Only the source speaking for itself is authoritative."""
        return self is LinkProvenance.SOURCE_STATED

    @property
    def admissible_in_production(self) -> bool:
        """Whether a link of this provenance may establish applicability.

        `HUMAN_CURATED` is admissible and *not* authoritative - those are different
        questions. Excluding it would leave the corpus with no resolvable link at
        all, which would be disabling the system rather than making it safer.
        `ENGINEERING_INFERRED` is excluded outright.
        """
        return self is not LinkProvenance.ENGINEERING_INFERRED


class LinkReviewStatus(StrEnum):
    """Whether a qualified reviewer has confirmed a curated link.

    Separate from provenance because they answer different questions: provenance is
    *who made this claim*, review status is *has anyone checked it*. A
    `HUMAN_CURATED` link that a reviewer has VERIFIED is still not
    `SOURCE_STATED` - review confirms a judgement, it does not turn it into a
    statement by the source.
    """

    PENDING = "PENDING"
    IN_REVIEW = "IN_REVIEW"
    VERIFIED = "VERIFIED"
    REJECTED = "REJECTED"
    INTERPRETATION_REQUIRED = "INTERPRETATION_REQUIRED"


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
    __table_args__ = (
        UniqueConstraint("policy_id", "document_type"),
        # A regulation must never silently become a coverage determination. This
        # is a database property rather than a Python convention because ADR-022's
        # non-negotiable is that the two layers cannot blur.
        CheckConstraint(
            "document_type IN ('REGULATION', 'NCD', 'LCD', 'ARTICLE')",
            name="document_type_is_known",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(PgUUID(as_uuid=True), primary_key=True, default=uuid_pk)
    policy_id: Mapped[str] = mapped_column(String(64), nullable=False)
    document_type: Mapped[DocumentType] = mapped_column(String(16), nullable=False)
    title: Mapped[str] = mapped_column(Text, nullable=False)
    source_url: Mapped[str] = mapped_column(Text, nullable=False)
    source_authority: Mapped[str] = mapped_column(String(128), nullable=False, default="CMS")
    contractor: Mapped[str | None] = mapped_column(String(128), nullable=True)
    #: A document-level retirement string as published. NOT a version window: for
    #: NCD 30.4 the CMS API returns the same `effective_end_date` on every version
    #: and it PRECEDES their effective dates, so treating it as one would be
    #: manufacturing an interval the source does not establish.
    retirement_date_raw: Mapped[str] = mapped_column(Text, nullable=False, default="")
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
    #: NULL only when `temporal_status` is not DATED - the CHECK constraint ties
    #: the two together, so a DATED row still cannot have a NULL date.
    effective_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    temporal_status: Mapped[str] = mapped_column(
        String(16), nullable=False, default=TemporalStatus.DATED.value
    )
    window_derivation: Mapped[str] = mapped_column(
        String(24), nullable=False, default=WindowDerivation.POSTED.value
    )
    #: The raw string the source published where a date belongs, kept verbatim so
    #: the reason a version is unresolvable lives in the row rather than in a
    #: comment.
    effective_date_source: Mapped[str] = mapped_column(Text, nullable=False, default="")
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
    #: Not part of the key: the same link may be re-curated with better evidence
    #: without becoming a different link.
    link_provenance: Mapped[str] = mapped_column(
        String(24), nullable=False, default=LinkProvenance.HUMAN_CURATED.value
    )
    #: Whether a qualified reviewer has confirmed this link. Distinct from
    #: provenance: review confirms a judgement, it does not make it authoritative.
    link_review_status: Mapped[str] = mapped_column(
        String(24), nullable=False, default=LinkReviewStatus.PENDING.value
    )

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
