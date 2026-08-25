"""The audit schema, asserted the way R-16 says it should be.

R-16 (audit tampering, **Critical**) has recorded its mitigation since Phase 0 as
"append-only grants; retention deletes by `created_at` and nothing else, **asserted
against the compiled SQL**". This file is that assertion. Until Phase 24 there was no
audit table, so there was nothing to assert and the row had been describing an
intention.

These tests need no database. The empirical proof - that PostgreSQL actually refuses an
UPDATE, a DELETE and a TRUNCATE - lives in
`tests/integration/test_audit_append_only.py`, because it can only be made against a
real server. Both are needed: the integration test proves it works *here*, and this one
proves the migration still *says so* on a machine with no database at all.
"""

from __future__ import annotations

import importlib.util
import re
from pathlib import Path
from types import ModuleType

import pytest
from sqlalchemy import String, Text

from app.audit.models import (
    APPEND_ONLY_TABLES,
    AuditEventRow,
    CaseState,
    HumanReviewAction,
    HumanReviewEventRow,
)
from app.database.base import Base

pytestmark = [pytest.mark.unit, pytest.mark.security]

REPO = Path(__file__).resolve().parents[2]
MIGRATION = REPO / "migrations/versions/0005_case_lifecycle_and_audit.py"


def migration_source() -> str:
    return MIGRATION.read_text(encoding="utf-8")


def migration_module() -> ModuleType:
    """Load the revision by path - its name starts with a digit, so `import` cannot.

    Loading it means the trigger assertions run against the statements that will
    actually be executed rather than against the f-string that generates them. A
    source-text assertion would have passed on a generator that produced nothing.
    """
    spec = importlib.util.spec_from_file_location("_migration_0005", MIGRATION)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


# --------------------------------------------------------------------------- 1
# Append-only, in the compiled SQL
# ---------------------------------------------------------------------------


def test_update_delete_and_truncate_are_revoked_on_every_append_only_table() -> None:
    source = migration_source()
    for table in APPEND_ONLY_TABLES:
        assert f"ON {table} FROM %I" in source, f"{table} has no REVOKE"
    assert "REVOKE UPDATE, DELETE, TRUNCATE, REFERENCES, TRIGGER" in source, (
        "the revocation no longer covers all five. TRUNCATE is not optional: it "
        "empties the table in one statement, which is a more complete erasure than "
        "the DELETE this control exists to prevent."
    )


def test_a_refusing_trigger_exists_because_grants_do_not_bind_the_owner() -> None:
    """**The load-bearing test of this file.**

    The first version of this migration revoked UPDATE and DELETE and stopped there.
    The grants were applied, appeared correctly in `information_schema`, and were
    inert: PostgreSQL does not enforce grants against a table's owner, and the
    application user owns its own schema. UPDATE, DELETE and TRUNCATE all still
    succeeded.

    A trigger binds the owner. That is why it is the mechanism and the grants are
    defence in depth.
    """
    module = migration_module()
    assert "medauth_refuse_audit_mutation" in module.REFUSE_FUNCTION_SQL
    assert "RAISE EXCEPTION" in module.REFUSE_FUNCTION_SQL

    statements = list(module.APPEND_ONLY_TRIGGERS)
    assert statements, "no trigger statements are generated at all"
    for table in APPEND_ONLY_TABLES:
        assert any(
            f"CREATE TRIGGER {table}_append_only " in s
            and f"BEFORE UPDATE OR DELETE ON {table} " in s
            for s in statements
        ), f"{table} has no UPDATE/DELETE trigger"
        # FOR EACH ROW never fires on TRUNCATE, so a statement-level trigger is the
        # only thing that catches it. Measured, not assumed - the first version had
        # only the row-level one and TRUNCATE went straight through.
        assert any(
            f"CREATE TRIGGER {table}_no_truncate " in s and f"BEFORE TRUNCATE ON {table} " in s
            for s in statements
        ), f"{table} has no TRUNCATE trigger"
    assert all("EXECUTE FUNCTION medauth_refuse_audit_mutation()" in s for s in statements)


def test_the_migration_and_the_orm_agree_on_which_tables_are_append_only() -> None:
    """Two hand-kept lists drift. This is the test instead of that."""
    declared = re.search(r"^APPEND_ONLY_TABLES = \(([^)]*)\)", migration_source(), re.M | re.S)
    assert declared, "APPEND_ONLY_TABLES has moved in the migration"
    names = tuple(re.findall(r'"([a-z_]+)"', declared.group(1)))
    assert names == APPEND_ONLY_TABLES


def test_retention_deletes_by_created_at_and_by_nothing_else() -> None:
    """A purge that can be aimed at particular rows is the attack R-16 names."""
    source = migration_source()
    function = source[source.index("CREATE OR REPLACE FUNCTION purge_audit_before") :]
    function = function[: function.index('"""')]

    assert "purge_audit_before(before timestamptz)" in function, (
        "the retention function takes something other than a single timestamp"
    )
    deletes = re.findall(r"DELETE FROM (\w+) WHERE ([^;]+);", function)
    assert deletes, "no DELETE found in the retention function"
    for table, predicate in deletes:
        assert table in APPEND_ONLY_TABLES
        assert predicate.strip() == "created_at < before", (
            f"retention deletes from {table} on `{predicate.strip()}` - it may only "
            "ever filter on created_at"
        )


def test_retention_restores_the_trigger_it_suspends() -> None:
    """It disables the guard to do its one legitimate job. It must put it back, and
    on the failure path too - otherwise one bad purge leaves the trail mutable."""
    source = migration_source()
    function = source[source.index("CREATE OR REPLACE FUNCTION purge_audit_before") :]
    function = function[: function.index('"""')]
    for table in APPEND_ONLY_TABLES:
        assert function.count(f"DISABLE TRIGGER {table}_append_only") == 1
        # Once on the happy path, once in the EXCEPTION handler.
        assert function.count(f"ENABLE TRIGGER {table}_append_only") == 2, (
            f"{table}'s trigger is not restored on both the success and failure paths"
        )
    assert "EXCEPTION WHEN OTHERS THEN" in function
    assert "RAISE;" in function, "the handler swallows the error instead of re-raising"


# --------------------------------------------------------------------------- 2
# No column can hold clinical text (R-17)
# ---------------------------------------------------------------------------


def test_no_audit_column_can_hold_free_text() -> None:
    """R-17: "schema-level assertion that no column holds a prompt or completion".

    `audit_events` is identifiers, enums, counts and one JSONB payload. An unbounded
    `Text` column is where a note ends up when somebody needs "somewhere to put it",
    so there is not one.
    """
    table = Base.metadata.tables[AuditEventRow.__tablename__]
    offenders = [c.name for c in table.columns if isinstance(c.type, Text)]
    assert not offenders, (
        f"audit_events has unbounded text columns {offenders}; clinical narrative "
        "ends up wherever there is room for it"
    )
    # Every string column is length-bounded, which also bounds what can be smuggled.
    for column in table.columns:
        if isinstance(column.type, String):
            assert column.type.length, f"{column.name} is an unbounded String"
            assert column.type.length <= 64, f"{column.name} is wide enough for prose"


def test_the_only_reviewer_free_text_is_the_reviewer_s_own_rationale() -> None:
    """`rationale` and `reviewer_qualification` are unbounded on purpose - a person
    writing about their own decision and their own credentials. Everything else on the
    review event is bounded."""
    table = Base.metadata.tables[HumanReviewEventRow.__tablename__]
    unbounded = {c.name for c in table.columns if isinstance(c.type, Text)}
    assert unbounded == {"rationale", "reviewer_qualification"}


# --------------------------------------------------------------------------- 3
# The vocabulary says what it means
# ---------------------------------------------------------------------------


def test_an_override_is_its_own_action_not_a_flag() -> None:
    """So "how often do reviewers disagree" is countable without parsing anything."""
    assert HumanReviewAction.OVERRIDE in set(HumanReviewAction)
    assert {a.value for a in HumanReviewAction} == {
        "APPROVE",
        "DENY",
        "REQUEST_INFO",
        "OVERRIDE",
    }


def test_a_recommendation_is_not_a_disposition() -> None:
    """`ASSESSED` and `REVIEWED` are different states. A system whose engine output
    was its final state would be making determinations, which this one does not."""
    assert CaseState.ASSESSED != CaseState.REVIEWED
    assert {s.value for s in CaseState} >= {"ASSESSED", "AWAITING_REVIEW", "REVIEWED"}


def test_a_denial_or_override_requires_a_rationale_in_the_database() -> None:
    """Enforced in the schema because the API is not the only writer a deployment
    might ever have."""
    table = Base.metadata.tables[HumanReviewEventRow.__tablename__]
    clauses = [
        str(c.sqltext)  # type: ignore[attr-defined]
        for c in table.constraints
        if type(c).__name__ == "CheckConstraint"
    ]
    assert any("DENY" in c and "OVERRIDE" in c and "rationale" in c for c in clauses), (
        "nothing stops a denial being recorded with no reason given"
    )


def test_a_review_event_cannot_outlive_the_recommendation_it_judged() -> None:
    """RESTRICT, not CASCADE. Deleting a recommendation that a human ruled on would
    remove the thing the decision was about and leave the decision standing."""
    table = Base.metadata.tables[HumanReviewEventRow.__tablename__]
    foreign_keys = [fk for fk in table.foreign_keys if "case_recommendations" in str(fk.column)]
    assert foreign_keys, "the review event no longer references a recommendation"
    assert all(fk.ondelete == "RESTRICT" for fk in foreign_keys)


def test_confidence_is_uncalibrated_by_default() -> None:
    """A numeric score would be read as a probability by every consumer, and this
    project has not earned one."""
    table = Base.metadata.tables["case_recommendations"]
    assert table.columns["confidence_state"].default.arg == "UNCALIBRATED"  # type: ignore[union-attr]
