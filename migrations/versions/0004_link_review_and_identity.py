"""Link review status, and a wider provenance vocabulary.

Revision ID: 0004_link_review_and_identity
Revises: 0003_coverage_determinations

Phase 6 separates two questions that `link_provenance` alone was answering at once:
*who made this claim* and *has anyone checked it*. A `HUMAN_CURATED` link that a
reviewer has verified is still not a statement by the source, so review status gets
its own column rather than a fourth provenance value.

The provenance vocabulary is also renamed to say what each value means as a claim:
`AUTHORITATIVE` -> `SOURCE_STATED` (the source itself states the relationship) and
`INFERRED` -> `ENGINEERING_INFERRED` (it rests on resemblance, and must not enter
production decision logic). Existing rows are migrated by value, not dropped.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0004_link_review_and_identity"
down_revision = "0003_coverage_determinations"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "policy_code_links",
        sa.Column(
            "link_review_status", sa.String(24), nullable=False, server_default="PENDING"
        ),
    )
    # Rename in place. A CHECK is deliberately NOT added: the vocabulary is
    # enforced by the enum at write time, and a constraint here would have to be
    # dropped and recreated on every future addition to it.
    op.execute("UPDATE policy_code_links SET link_provenance = 'SOURCE_STATED' "
               "WHERE link_provenance = 'AUTHORITATIVE'")
    op.execute("UPDATE policy_code_links SET link_provenance = 'ENGINEERING_INFERRED' "
               "WHERE link_provenance = 'INFERRED'")


def downgrade() -> None:
    op.execute("UPDATE policy_code_links SET link_provenance = 'AUTHORITATIVE' "
               "WHERE link_provenance = 'SOURCE_STATED'")
    op.execute("UPDATE policy_code_links SET link_provenance = 'INFERRED' "
               "WHERE link_provenance = 'ENGINEERING_INFERRED'")
    op.drop_column("policy_code_links", "link_review_status")
