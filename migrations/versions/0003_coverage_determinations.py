"""Coverage determinations: temporal honesty, layer separation, link provenance.

Revision ID: 0003_coverage_determinations
Revises: 0002_policy_corpus

Three groups of changes, all in service of one rule: **the absence of a fact must
produce no decision, never a default fact.**

**1. An effective date may be unknown, and unknown must not mean "always".** The
CMS Coverage API publishes prose where a date belongs - "This is a longstanding
national coverage determination. The effective date of this version has not been
posted." was returned for 14 of 24 NCD records sampled during Phase 5 planning.
`effective_date` becomes nullable, but the schema is **not** weakened: a CHECK ties
nullability to `temporal_status`, so a `DATED` row still cannot have a NULL date and
an undated row cannot carry an end date. Existing regulation rows backfill as
`DATED` through the column default, so there is no data migration.

`window_derivation` records whether a window was published or inferred, because
presenting a derived end date to a reviewer as though CMS posted it is the same
class of error as a sentinel date. `effective_date_source` keeps the raw published
string, so the reason a version is unresolvable lives in the row.

**2. A regulation must never silently become a coverage determination.** ADR-022
made that non-negotiable and it was a Python convention; here it becomes a database
constraint.

**3. A code link records on whose authority it exists.** No link in this corpus is
authoritative - 42 CFR enumerates no procedure codes, and the NCD record carries no
procedure-code field at all. The column exists so a future source that *does* supply
linkage is distinguishable from the judgement calls made here.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0003_coverage_determinations"
down_revision = "0002_policy_corpus"
branch_labels = None
depends_on = None

#: Ties nullability to the status, so relaxing NOT NULL does not relax the schema.
TEMPORAL_CHECK = (
    "(temporal_status = 'DATED' AND effective_date IS NOT NULL) "
    "OR (temporal_status <> 'DATED' AND effective_date IS NULL AND end_date IS NULL)"
)


def upgrade() -> None:
    # ---------------------------------------------------------- 1. temporal
    op.add_column(
        "policy_versions",
        sa.Column(
            "temporal_status",
            sa.String(16),
            nullable=False,
            server_default="DATED",
        ),
    )
    op.add_column(
        "policy_versions",
        sa.Column(
            "window_derivation",
            sa.String(24),
            nullable=False,
            server_default="POSTED",
        ),
    )
    op.add_column(
        "policy_versions",
        sa.Column(
            "effective_date_source",
            sa.Text(),
            nullable=False,
            server_default="",
        ),
    )
    op.alter_column("policy_versions", "effective_date", nullable=True)

    # The existing constraint compares two dates; one of them can now be NULL, and
    # `NULL >= date` is NULL rather than false - so the comparison would silently
    # stop being enforced. Restated to make the NULL case explicit.
    op.drop_constraint("end_date_after_effective", "policy_versions", type_="check")
    op.create_check_constraint(
        "end_date_after_effective",
        "policy_versions",
        "end_date IS NULL OR effective_date IS NULL OR end_date >= effective_date",
    )
    op.create_check_constraint(
        "temporal_status_matches_dates", "policy_versions", TEMPORAL_CHECK
    )

    # ------------------------------------------------- 2. layer separation
    op.add_column(
        "policy_documents",
        sa.Column("retirement_date_raw", sa.Text(), nullable=False, server_default=""),
    )
    op.create_check_constraint(
        "document_type_is_known",
        "policy_documents",
        "document_type IN ('REGULATION', 'NCD', 'LCD', 'ARTICLE')",
    )

    # -------------------------------------------------- 3. link provenance
    op.add_column(
        "policy_code_links",
        sa.Column(
            "link_provenance",
            sa.String(24),
            nullable=False,
            server_default="HUMAN_CURATED",
        ),
    )


def downgrade() -> None:
    op.drop_column("policy_code_links", "link_provenance")
    op.drop_constraint("document_type_is_known", "policy_documents", type_="check")
    op.drop_column("policy_documents", "retirement_date_raw")

    op.drop_constraint("temporal_status_matches_dates", "policy_versions", type_="check")
    # Undated rows cannot exist in the 0002 schema, so they are dropped rather
    # than given a date. Inventing one to satisfy NOT NULL is precisely the
    # sentinel this migration exists to remove.
    op.execute("DELETE FROM policy_versions WHERE effective_date IS NULL")
    op.alter_column("policy_versions", "effective_date", nullable=False)
    op.drop_constraint("end_date_after_effective", "policy_versions", type_="check")
    op.create_check_constraint(
        "end_date_after_effective",
        "policy_versions",
        "end_date IS NULL OR end_date >= effective_date",
    )
    op.drop_column("policy_versions", "effective_date_source")
    op.drop_column("policy_versions", "window_derivation")
    op.drop_column("policy_versions", "temporal_status")
