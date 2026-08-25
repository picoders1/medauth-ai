"""Every constraint a migration creates must exist in the ORM metadata too.

Closure audit, R-105. `uv run alembic check` - which CLAUDE.md lists in the standard
verification set - was failing at `ded0e9b` and had been for some time:

    remove_constraint(CheckConstraint(name='ck_policy_versions_temporal_status_matches_dates'))

Migration `0003_coverage_determinations` creates that constraint. `PolicyVersion`
never declared it. The database therefore held a rule the model did not know about,
and the metadata read as though the rule should not be there - so the next
`alembic revision --autogenerate` would have emitted a migration **dropping** it.

The rule being dropped is not a formality. It ties nullability to `temporal_status`,
which is the database-level half of "an undated NCD version is stored and never
resolvable". Without it, an `UNDATED` row may carry dates, and "we do not know when
this took effect" becomes a date somebody can query against - the exact conversion
`app/policy/models.py` and `app/policy/temporal.py` exist to prevent.

A drop like that arrives inside a generated migration that looks like housekeeping.
This test makes it arrive as a failure instead.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

from app.database.base import Base
from app.policy import models as _policy_models  # noqa: F401 - registers the tables

pytestmark = pytest.mark.unit

REPO = Path(__file__).resolve().parents[2]
MIGRATIONS = REPO / "migrations" / "versions"


def constraints_created_by_migrations() -> dict[str, str]:
    """`{constraint_name: migration_filename}` for every `create_check_constraint`.

    Parsed, not listed. A hand-maintained list is a list that stops matching the
    migrations the moment somebody adds one, which is the case this test is for.
    """
    created: dict[str, str] = {}
    for migration in sorted(MIGRATIONS.glob("*.py")):
        tree = ast.parse(migration.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Attribute)
                and node.func.attr == "create_check_constraint"
                and node.args
                and isinstance(node.args[0], ast.Constant)
            ):
                created[str(node.args[0].value)] = migration.name
    return created


def declares_check_constraint(name: str) -> bool:
    """Whether any table declares a CheckConstraint by this name.

    Matched by suffix, because the metadata naming convention renders
    `temporal_status_matches_dates` as `ck_policy_versions_temporal_status_matches_dates`
    while the migration names it bare. Comparing the two vocabularies literally is how
    a test concludes a constraint is missing when it is merely spelled by a convention.
    """
    for table in Base.metadata.tables.values():
        for constraint in table.constraints:
            if type(constraint).__name__ != "CheckConstraint" or not constraint.name:
                continue
            declared = str(constraint.name)
            if declared == name or declared.endswith(f"_{name}"):
                return True
    return False


def check_constraint_clause(table: str, name: str) -> str | None:
    """The SQL text of one named CheckConstraint, or None if it is not declared."""
    for constraint in Base.metadata.tables[table].constraints:
        if type(constraint).__name__ != "CheckConstraint" or not constraint.name:
            continue
        declared = str(constraint.name)
        if declared == name or declared.endswith(f"_{name}"):
            return str(constraint.sqltext)  # type: ignore[attr-defined]
    return None


def test_the_detector_finds_the_migrations_it_is_supposed_to() -> None:
    """Non-vacuity. An empty parse would make every assertion below trivially true,
    and this file's whole subject is a check that passed while finding nothing."""
    created = constraints_created_by_migrations()
    assert created, "no create_check_constraint call was found in any migration"
    assert "temporal_status_matches_dates" in created


def test_every_migration_check_constraint_is_declared_in_the_model() -> None:
    missing = {
        name: migration
        for name, migration in constraints_created_by_migrations().items()
        if not declares_check_constraint(name)
    }
    assert not missing, (
        f"these constraints exist in the database and not in the ORM metadata: "
        f"{missing}. `alembic check` reports each as a constraint to REMOVE, so the "
        "next --autogenerate emits a migration dropping it."
    )


def test_the_temporal_constraint_still_ties_nullability_to_the_status() -> None:
    """The specific rule, not merely a name.

    A constraint present under the right name but weakened to `1 = 1` would pass the
    test above. This asserts the clause still says what it has to say.
    """
    clause = check_constraint_clause("policy_versions", "temporal_status_matches_dates")
    assert clause, "policy_versions no longer declares temporal_status_matches_dates"
    assert "temporal_status = 'DATED'" in clause
    assert "effective_date IS NOT NULL" in clause
    # The UNDATED branch is the load-bearing half: no start date AND no end date.
    assert "effective_date IS NULL AND end_date IS NULL" in clause


def test_the_model_and_the_migration_spell_the_rule_identically() -> None:
    """Two spellings of one rule agree until they do not.

    The migration holds the text in a module-level `TEMPORAL_CHECK`; the model holds
    it inline. Comparing them here means a future edit to either one that does not
    edit the other fails a test rather than producing a database whose constraint and
    whose ORM disagree about the same column.
    """
    migration = (MIGRATIONS / "0003_coverage_determinations.py").read_text(encoding="utf-8")
    tree = ast.parse(migration)
    literal: str | None = None
    for node in ast.walk(tree):
        if (
            isinstance(node, ast.Assign)
            and any(isinstance(t, ast.Name) and t.id == "TEMPORAL_CHECK" for t in node.targets)
            and isinstance(node.value, ast.Constant)
        ):
            literal = str(node.value.value)
    assert literal, "TEMPORAL_CHECK has moved or is no longer a plain string literal"

    declared = check_constraint_clause("policy_versions", "temporal_status_matches_dates")
    assert declared, "policy_versions no longer declares temporal_status_matches_dates"
    normalise = " ".join(literal.split())
    assert normalise == " ".join(declared.split()), (
        "the migration and the model state the temporal rule differently:\n"
        f"  migration: {normalise}\n"
        f"  model:     {' '.join(declared.split())}"
    )
