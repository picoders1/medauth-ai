"""Policy corpus: documents, versions, the resolution index, and chunks.

Implements data-architecture.md section 3.1 verbatim.

Two design points are enforced here in the database rather than in application
code, because a constraint that lives only in Python is a suggestion:

* ``end_date >= effective_date`` - a version cannot end before it begins, so a
  malformed temporal range cannot be stored and then quietly mis-resolve.
* ``policy_code_links`` has a composite primary key over
  (version, code, code_system, link_type). Applicability is a set of rows, and
  duplicate rows would silently double-count a policy during conflict detection.

The HNSW index is created without a populated table, which is correct: pgvector
builds it incrementally, and Phase 1 ingests in the thousands of chunks.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from pgvector.sqlalchemy import Vector

revision: str = "0002_policy_corpus"
down_revision: str | None = "0001_enable_pgvector"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

EMBEDDING_DIMENSION = 768


def upgrade() -> None:
    op.create_table(
        "policy_documents",
        sa.Column("id", sa.UUID(as_uuid=True), nullable=False),
        sa.Column("policy_id", sa.String(64), nullable=False),
        sa.Column("document_type", sa.String(16), nullable=False),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("source_url", sa.Text(), nullable=False),
        sa.Column("source_authority", sa.String(128), nullable=False, server_default="CMS"),
        sa.Column("contractor", sa.String(128), nullable=True),
        sa.Column("first_seen_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id", name="pk_policy_documents"),
        sa.UniqueConstraint(
            "policy_id", "document_type", name="uq_policy_documents_policy_id_document_type"
        ),
    )

    op.create_table(
        "policy_versions",
        sa.Column("id", sa.UUID(as_uuid=True), nullable=False),
        sa.Column("document_id", sa.UUID(as_uuid=True), nullable=False),
        sa.Column("revision_id", sa.String(64), nullable=False),
        sa.Column("scope", sa.String(16), nullable=False),
        sa.Column("jurisdiction", sa.String(32), nullable=True),
        sa.Column("effective_date", sa.Date(), nullable=False),
        sa.Column("end_date", sa.Date(), nullable=True),
        sa.Column("revision_date", sa.Date(), nullable=True),
        sa.Column("superseded_by", sa.UUID(as_uuid=True), nullable=True),
        sa.Column("content_sha256", sa.String(64), nullable=False),
        sa.Column("ingested_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id", name="pk_policy_versions"),
        sa.ForeignKeyConstraint(
            ["document_id"],
            ["policy_documents.id"],
            name="fk_policy_versions_document_id_policy_documents",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["superseded_by"],
            ["policy_versions.id"],
            name="fk_policy_versions_superseded_by_policy_versions",
            ondelete="SET NULL",
        ),
        sa.UniqueConstraint(
            "document_id", "revision_id", name="uq_policy_versions_document_id_revision_id"
        ),
        # A version that ends before it begins cannot be stored.
        sa.CheckConstraint(
            "end_date IS NULL OR end_date >= effective_date",
            name="end_date_after_effective",
        ),
    )
    op.create_index(
        "ix_policy_versions_temporal", "policy_versions", ["effective_date", "end_date"]
    )
    op.create_index(
        "ix_policy_versions_jurisdiction", "policy_versions", ["scope", "jurisdiction"]
    )

    op.create_table(
        "policy_code_links",
        sa.Column("policy_version_id", sa.UUID(as_uuid=True), nullable=False),
        sa.Column("code", sa.String(16), nullable=False),
        sa.Column("code_system", sa.String(16), nullable=False),
        sa.Column("link_type", sa.String(24), nullable=False),
        sa.PrimaryKeyConstraint(
            "policy_version_id", "code", "code_system", "link_type", name="pk_policy_code_links"
        ),
        sa.ForeignKeyConstraint(
            ["policy_version_id"],
            ["policy_versions.id"],
            name="fk_policy_code_links_policy_version_id_policy_versions",
            ondelete="CASCADE",
        ),
    )
    # Resolution reads this first: given a procedure code, which versions list it?
    op.create_index("ix_policy_code_links_code", "policy_code_links", ["code", "code_system"])

    op.create_table(
        "policy_chunks",
        sa.Column("id", sa.UUID(as_uuid=True), nullable=False),
        sa.Column("policy_version_id", sa.UUID(as_uuid=True), nullable=False),
        sa.Column("section_path", sa.Text(), nullable=False),
        sa.Column("ordinal", sa.Integer(), nullable=False),
        sa.Column("page_from", sa.Integer(), nullable=False),
        sa.Column("page_to", sa.Integer(), nullable=False),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("text_sha256", sa.String(64), nullable=False),
        sa.Column("token_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("embedding", Vector(EMBEDDING_DIMENSION), nullable=True),
        sa.PrimaryKeyConstraint("id", name="pk_policy_chunks"),
        sa.ForeignKeyConstraint(
            ["policy_version_id"],
            ["policy_versions.id"],
            name="fk_policy_chunks_policy_version_id_policy_versions",
            ondelete="CASCADE",
        ),
        sa.UniqueConstraint(
            "policy_version_id", "ordinal", name="uq_policy_chunks_policy_version_id_ordinal"
        ),
        sa.CheckConstraint("page_to >= page_from", name="page_range_ordered"),
    )
    # The scoping filter: every search is restricted to resolved versions (ADR-004).
    op.create_index("ix_policy_chunks_version", "policy_chunks", ["policy_version_id"])
    op.create_index(
        "ix_policy_chunks_embedding_hnsw",
        "policy_chunks",
        ["embedding"],
        postgresql_using="hnsw",
        postgresql_ops={"embedding": "vector_cosine_ops"},
    )


def downgrade() -> None:
    op.drop_table("policy_chunks")
    op.drop_table("policy_code_links")
    op.drop_table("policy_versions")
    op.drop_table("policy_documents")
