"""Authenticated reviewer identity on review events. OD-43.

Revision ID: 0006_reviewer_identity
Revises: 0005_case_lifecycle_and_audit

`human_review_events.reviewer_id` recorded who **claimed** to decide: it arrived in the
request body, and the API key identified the integrating system rather than the person.
This adds the authenticated identity beside it.

## Existing rows are not rewritten

`identity_model` defaults to `LEGACY_CALLER_SUPPLIED` for every row that already exists,
and new rows are written `AUTHENTICATED_HUMAN`. Nothing back-fills a principal onto a
historical event, because there was no authenticated principal at the time and inventing
one would make the old records look like evidence they are not.

A reader can therefore tell, per row, how much the identity on it is worth - which is
strictly more useful than a uniform column that quietly means two different things.

## The append-only guarantee is untouched

Adding nullable columns does not require rewriting rows, so no trigger is suspended and
no grant changes. The triggers from 0005 remain in force throughout.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

#: 22 characters. `alembic_version.version_num` is varchar(32), and
#: "0006_authenticated_reviewer_identity" is 36 - the upgrade failed on the version
#: row itself, after the DDL had already run.
revision = "0006_reviewer_identity"
down_revision = "0005_case_lifecycle_and_audit"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "human_review_events",
        # NOT NULL with a server default, so every historical row is explicitly
        # labelled rather than left NULL and interpreted later by whoever reads it.
        sa.Column(
            "identity_model",
            sa.String(24),
            nullable=False,
            server_default="LEGACY_CALLER_SUPPLIED",
        ),
    )
    op.add_column(
        "human_review_events",
        sa.Column("principal_id", sa.String(128), nullable=True),
    )
    op.add_column(
        "human_review_events",
        sa.Column("principal_type", sa.String(16), nullable=True),
    )
    op.add_column(
        "human_review_events",
        sa.Column("authentication_method", sa.String(16), nullable=True),
    )
    op.add_column(
        "human_review_events",
        sa.Column("identity_issuer", sa.Text(), nullable=True),
    )

    # An AUTHENTICATED_HUMAN row without a principal is the failure this whole
    # migration exists to prevent, so the database refuses it. Legacy rows are exempt
    # by naming the model rather than by being old.
    op.create_check_constraint(
        "authenticated_review_names_its_principal",
        "human_review_events",
        "identity_model <> 'AUTHENTICATED_HUMAN' "
        "OR (principal_id IS NOT NULL AND principal_type = 'HUMAN' "
        "AND authentication_method IS NOT NULL)",
    )

    op.create_index(
        "ix_human_review_events_principal_id",
        "human_review_events",
        ["principal_id"],
    )


def downgrade() -> None:
    op.drop_index("ix_human_review_events_principal_id", "human_review_events")
    op.drop_constraint(
        "ck_human_review_events_authenticated_review_names_its_principal",
        "human_review_events",
        type_="check",
    )
    for column in (
        "identity_issuer",
        "authentication_method",
        "principal_type",
        "principal_id",
        "identity_model",
    ):
        op.drop_column("human_review_events", column)
