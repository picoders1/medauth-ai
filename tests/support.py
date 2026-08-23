"""Shared test helpers for policy semantics.

`decide()` requires a `PolicySemantics`, and most tests are about the decision
table's *rows* rather than about where semantics come from. This module supplies
the stand-in, in one place, so the substitution is reviewable rather than repeated
nine times with slightly different wording.

Nothing here can execute in production. `attested_assumption` builds an
`Attestation` whose digest is a literal, and `app.policy.semantics_guard` refuses
any attestation whose digest does not match the inventory loaded at startup - so
these values behave like production semantics in a unit test and like a
misconfiguration anywhere it would matter.
"""

from __future__ import annotations

from app.decision.logic import LogicForm, PolicyLogic
from app.decision.semantics import (
    Attestation,
    PolicySemantics,
    SemanticsOrigin,
)
from app.decision.table import CriterionOutcome, assumed_conjunction

__all__ = ["TEST_ATTESTATION", "attested", "attested_assumption"]

#: Names itself, so a value that escapes into a report is self-describing. The
#: digest is deliberately not a real hash of anything.
TEST_ATTESTATION = Attestation(
    source="tests/support.py::TEST_ATTESTATION",
    sha256="0" * 64,
    origin=SemanticsOrigin.POLICY_LOGIC_INVENTORY,
)


def attested_assumption(
    criteria: tuple[CriterionOutcome, ...],
    *,
    policy_id: str = "test-policy",
    policy_version: str = "test-version",
) -> PolicySemantics:
    """An assumed conjunction the inventory is treated as having attested.

    Stands in for `logic_loader.semantics_for()` returning
    `ASSUMED_CONJUNCTION`. Before Phase 5 this was what `decide()` built for
    itself when no logic was passed; the tests that use it are unchanged in
    meaning, and the assumption they rest on is now written down.
    """
    return PolicySemantics.assumed(
        policy_id=policy_id,
        policy_version=policy_version,
        logic=assumed_conjunction(criteria, policy_id=policy_id, policy_version=policy_version),
        attestation=TEST_ATTESTATION,
    )


def attested(
    logic: PolicyLogic,
    *,
    policy_id: str = "test-policy",
    policy_version: str = "test-version",
) -> PolicySemantics:
    """Wrap an explicit `PolicyLogic` so it executes, matching on `form`.

    `REVIEW_REQUIRED` and `NO_CRITERIA` carry no tree by construction, so a test
    that wants those states gets them from the constructors directly rather than
    by wrapping a tree that would then be discarded.
    """
    if logic.form is LogicForm.DECLARED:
        return PolicySemantics.declared(
            policy_id=policy_id,
            policy_version=policy_version,
            logic=logic,
            attestation=TEST_ATTESTATION,
        )
    if logic.form is LogicForm.ASSUMED_CONJUNCTION:
        return PolicySemantics.assumed(
            policy_id=policy_id,
            policy_version=policy_version,
            logic=logic,
            attestation=TEST_ATTESTATION,
        )
    if logic.form is LogicForm.REVIEW_REQUIRED:
        return PolicySemantics.review_required(policy_id=policy_id, policy_version=policy_version)
    return PolicySemantics.no_criteria(policy_id=policy_id, policy_version=policy_version)
