"""The case lifecycle, and an audit trail that is append-only by grant.

Revision ID: 0005_case_lifecycle_and_audit
Revises: 0004_link_review_and_identity

R-16 (audit tampering, Critical) has recorded its mitigation since Phase 0 as "append-only
grants; retention deletes by `created_at` and nothing else, asserted against the compiled
SQL". There was no audit table, so there were no grants and nothing to assert. This is
that row becoming true.

## Two mechanisms, because one of them does not work here

**A trigger, which binds today.** `REVOKE` was the original plan and R-16's stated
mitigation, and inspecting the live database after applying it showed UPDATE, DELETE and
TRUNCATE all still succeeding. PostgreSQL does not enforce grants against a table's
**owner**, and this deployment's application user owns its own schema. The grants were
correct, present in `information_schema`, and inert.

So the enforcement is a `BEFORE UPDATE OR DELETE` trigger that raises. Triggers apply to
the owner, which is what makes this the mechanism rather than the decoration.

**Grants, which bind when a deployment separates roles.** Kept as defence in depth for
any installation that runs the application as a non-owner. Harmless where they are
inert, and correct where they are not.

**Residual, stated:** a superuser can `ALTER TABLE ... DISABLE TRIGGER` or drop it.
Nothing inside the database stops a deliberate administrator, and no schema can. The
claim this earns is narrow and true - *no application code path can mutate the trail* -
and it is the claim `docs/architecture/audit-trail.md` makes.

## The grants

`REVOKE UPDATE, DELETE ON audit_events, human_review_events` from the application role.
A future ORM call that tries to mutate an audit row fails in PostgreSQL rather than in a
review, which is the difference between a property and an intention.

The role is read from `MEDAUTH_APP_DB_ROLE`, defaulting to the connection's own role.
`DO $$` guards the whole block so a deployment where the migration runs as a role that
cannot GRANT still upgrades - it logs a warning instead of failing. That trade is
deliberate and stated: a schema that will not install because of a permissions detail is
a schema nobody installs, and the test suite asserts the revocation text is present
whether or not a given database applied it.

## Retention

`purge_audit_before(timestamptz)` takes one argument and has one predicate. There is no
overload that accepts a case id, a reviewer or an outcome, because a purge that can be
aimed at particular rows is a mechanism for erasing the record of one recommendation -
which is precisely the attack R-16 names.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0005_case_lifecycle_and_audit"
down_revision = "0004_link_review_and_identity"
branch_labels = None
depends_on = None

#: Kept in step with `app.audit.models.APPEND_ONLY_TABLES` by a test, rather than by
#: two people remembering.
APPEND_ONLY_TABLES = ("audit_events", "human_review_events")

REVOKE_SQL = """
DO $$
DECLARE
    app_role text := coalesce(current_setting('medauth.app_role', true), current_user);
BEGIN
    -- INSERT and SELECT, and nothing else. The audit trail grows or it does nothing.
    --
    -- TRUNCATE is revoked alongside DELETE and it is not a formality: the first
    -- version of this migration revoked only UPDATE and DELETE, and an inspection of
    -- the live grants showed TRUNCATE still present. It empties the table in one
    -- statement, which is a more complete erasure than the DELETE this row exists to
    -- prevent. REFERENCES and TRIGGER go too - both are routes to a cascade or a
    -- rewrite that the application role has no reason to hold.
    EXECUTE format(
        'REVOKE UPDATE, DELETE, TRUNCATE, REFERENCES, TRIGGER ON audit_events FROM %I',
        app_role);
    EXECUTE format(
        'REVOKE UPDATE, DELETE, TRUNCATE, REFERENCES, TRIGGER ON human_review_events FROM %I',
        app_role);
    EXECUTE format('GRANT INSERT, SELECT ON audit_events TO %I', app_role);
    EXECUTE format('GRANT INSERT, SELECT ON human_review_events TO %I', app_role);
EXCEPTION WHEN insufficient_privilege OR undefined_object THEN
    -- A deployment whose migration role cannot GRANT still upgrades. The revocation
    -- is then an operator task, and docs/architecture/audit-trail.md says so rather
    -- than the schema pretending it happened.
    RAISE WARNING 'MEDAUTH: could not apply append-only grants; apply them manually';
END $$;
"""

REFUSE_FUNCTION_SQL = """
CREATE OR REPLACE FUNCTION medauth_refuse_audit_mutation()
RETURNS trigger
LANGUAGE plpgsql
AS $$
BEGIN
    -- Reached only by UPDATE or DELETE. Retention uses purge_audit_before(), which
    -- suspends these triggers for the duration of its own single created_at predicate.
    RAISE EXCEPTION
        'audit trail is append-only: % on % is refused', TG_OP, TG_TABLE_NAME
        USING ERRCODE = 'insufficient_privilege';
END $$;
"""

#: One statement per entry - asyncpg prepares each execute() and refuses a multi-command
#: string, so a single blob here fails at migration time rather than at review time.
#:
#: TWO triggers per table, and the second is not redundant. A `FOR EACH ROW` trigger
#: fires per row, so it never fires on TRUNCATE (which removes rows without visiting
#: them) and never fires on a DELETE against an already-empty table. Testing the first
#: version showed exactly that: UPDATE and DELETE refused, TRUNCATE straight through.
#: `FOR EACH STATEMENT` on TRUNCATE is the only thing that catches it.
APPEND_ONLY_TRIGGERS = tuple(
    statement
    for table in APPEND_ONLY_TABLES
    for statement in (
        f"CREATE TRIGGER {table}_append_only "
        f"BEFORE UPDATE OR DELETE ON {table} "
        "FOR EACH ROW EXECUTE FUNCTION medauth_refuse_audit_mutation()",
        f"CREATE TRIGGER {table}_no_truncate "
        f"BEFORE TRUNCATE ON {table} "
        "FOR EACH STATEMENT EXECUTE FUNCTION medauth_refuse_audit_mutation()",
    )
)


RETENTION_SQL = """
CREATE OR REPLACE FUNCTION purge_audit_before(before timestamptz)
RETURNS integer
LANGUAGE plpgsql
AS $$
DECLARE
    removed integer;
BEGIN
    -- BY created_at AND BY NOTHING ELSE. There is deliberately no second parameter:
    -- a purge that can be aimed at a case id, a reviewer or an outcome is a mechanism
    -- for erasing the record of one particular recommendation (R-16).
    --
    -- The append-only trigger is suspended for exactly these two statements and
    -- restored unconditionally. Retention is the ONE legitimate deletion, and it is
    -- narrow by construction: the only value it can be given is a timestamp.
    ALTER TABLE audit_events DISABLE TRIGGER audit_events_append_only;
    ALTER TABLE human_review_events DISABLE TRIGGER human_review_events_append_only;
    BEGIN
        DELETE FROM audit_events WHERE created_at < before;
        GET DIAGNOSTICS removed = ROW_COUNT;
        DELETE FROM human_review_events WHERE created_at < before;
    EXCEPTION WHEN OTHERS THEN
        ALTER TABLE audit_events ENABLE TRIGGER audit_events_append_only;
        ALTER TABLE human_review_events ENABLE TRIGGER human_review_events_append_only;
        RAISE;
    END;
    ALTER TABLE audit_events ENABLE TRIGGER audit_events_append_only;
    ALTER TABLE human_review_events ENABLE TRIGGER human_review_events_append_only;
    RETURN removed;
END $$;
"""


def upgrade() -> None:
    op.create_table(
        "cases",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("case_id", sa.String(64), nullable=False),
        sa.Column("case_version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("state", sa.String(24), nullable=False, server_default="RECEIVED"),
        sa.Column("submitted_by", sa.String(64), nullable=False),
        sa.Column("input_sha256", sa.String(64), nullable=False),
        sa.Column("procedure_code", sa.String(16), nullable=False),
        sa.Column("code_system", sa.String(16), nullable=False),
        sa.Column("jurisdiction", sa.String(16), nullable=False),
        sa.Column("date_of_service", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_unique_constraint("uq_cases_case_id", "cases", ["case_id"])
    op.create_index("ix_cases_state_created_at", "cases", ["state", "created_at"])

    op.create_table(
        "case_recommendations",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("case_uuid", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("run_seq", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("outcome", sa.String(32)),
        sa.Column("decision_rule", sa.String(48)),
        sa.Column("abstention_reason", sa.String(48)),
        sa.Column("resolution_state", sa.String(32)),
        sa.Column("resolution_reason", sa.String(48)),
        sa.Column("policy_type", sa.String(16)),
        sa.Column("policy_id", sa.String(64)),
        sa.Column("policy_version", sa.String(64)),
        sa.Column("provider_failure_kind", sa.String(40)),
        sa.Column("provider_failure_attribution", sa.String(32)),
        sa.Column("model_id", sa.String(128)),
        sa.Column("model_calls", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("prompt_tokens", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("completion_tokens", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("latency_ms", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("confidence_state", sa.String(24), nullable=False, server_default="UNCALIBRATED"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["case_uuid"],
            ["cases.id"],
            name="fk_case_recommendations_case_uuid_cases",
            ondelete="CASCADE",
        ),
    )
    op.create_unique_constraint(
        "uq_case_recommendations_case_uuid_run_seq",
        "case_recommendations",
        ["case_uuid", "run_seq"],
    )
    op.create_check_constraint(
        "outcome_and_rule_agree",
        "case_recommendations",
        "(outcome IS NULL) = (decision_rule IS NULL)",
    )

    op.create_table(
        "audit_events",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("request_id", sa.String(64), nullable=False),
        sa.Column("case_id", sa.String(64), nullable=False),
        sa.Column("event", sa.String(48), nullable=False),
        sa.Column("stage", sa.String(32), nullable=False),
        sa.Column("outcome", sa.String(32)),
        sa.Column("abstention_reason", sa.String(48)),
        sa.Column("resolution_state", sa.String(32)),
        sa.Column("resolution_reason", sa.String(48)),
        sa.Column("contradiction_state", sa.String(32)),
        sa.Column("provider_failure_kind", sa.String(40)),
        sa.Column("payload", postgresql.JSONB(), nullable=False, server_default="{}"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_audit_events_case_id_created_at", "audit_events", ["case_id", "created_at"])
    op.create_index("ix_audit_events_created_at", "audit_events", ["created_at"])
    op.create_index("ix_audit_events_request_id", "audit_events", ["request_id"])

    op.create_table(
        "human_review_events",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("request_id", sa.String(64), nullable=False),
        sa.Column("case_id", sa.String(64), nullable=False),
        sa.Column("recommendation_id", postgresql.UUID(as_uuid=True)),
        sa.Column("reviewer_id", sa.String(64), nullable=False),
        sa.Column("reviewer_qualification", sa.Text(), nullable=False),
        sa.Column("action", sa.String(16), nullable=False),
        sa.Column("outcome", sa.String(24)),
        sa.Column("rationale", sa.Text()),
        sa.Column("recommended_outcome_at_review", sa.String(32)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["recommendation_id"],
            ["case_recommendations.id"],
            name="fk_human_review_events_recommendation_id_case_recommendations",
            # RESTRICT, not CASCADE. A recommendation with a human decision attached
            # must not be deletable - that would remove the thing the decision was
            # about while leaving the decision standing.
            ondelete="RESTRICT",
        ),
    )
    op.create_index(
        "ix_human_review_events_case_id_created_at",
        "human_review_events",
        ["case_id", "created_at"],
    )
    op.create_index("ix_human_review_events_created_at", "human_review_events", ["created_at"])
    op.create_check_constraint(
        "denial_and_override_require_a_rationale",
        "human_review_events",
        "action NOT IN ('DENY', 'OVERRIDE') OR (rationale IS NOT NULL AND length(rationale) > 0)",
    )

    op.execute(REVOKE_SQL)
    op.execute(REFUSE_FUNCTION_SQL)
    for statement in APPEND_ONLY_TRIGGERS:
        op.execute(statement)
    op.execute(RETENTION_SQL)


def downgrade() -> None:
    op.execute("DROP FUNCTION IF EXISTS purge_audit_before(timestamptz)")
    op.execute("DROP FUNCTION IF EXISTS medauth_refuse_audit_mutation() CASCADE")
    op.drop_table("human_review_events")
    op.drop_table("audit_events")
    op.drop_table("case_recommendations")
    op.drop_table("cases")
