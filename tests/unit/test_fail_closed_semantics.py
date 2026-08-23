"""The Phase 5 safety invariant: unverified policy semantics cannot adjudicate.

    NO_DECISION_WITH_UNVERIFIED_POLICY_SEMANTICS

    For every `criteria`, `guardrail`, `resolution` and `as_of`, and every
    `semantics` whose `logic is None` or whose status is `REVIEW_REQUIRED`:

        decide(...).outcome not in {APPROVE_RECOMMENDED, DENY_RECOMMENDED}

**Naming trap, stated because it is easy to get wrong.** `Outcome.NO_DECISION`
already exists and means something else - an unverifiable citation stopped the case
(rule 3). The invariant's name uses "no decision" in the English sense: no
*adjudication*. Never implement it as `outcome is Outcome.NO_DECISION`; assert on
the set. The invariant deliberately permits `NEEDS_INFO` from rule 1 (no applicable
policy is never a denial) and `NO_DECISION` from rule 3.

**Why the tests here are paired.** Quantifying over generated inputs and asserting
"never approves or denies" passes trivially if the generated space contains no input
that *would* have adjudicated. So every input is decided twice - once unverified,
once attested - and the attested run is the control that proves the space is real.
"""

from __future__ import annotations

import inspect
from itertools import product

import pytest

from app.core.types import CriterionKind, ResolutionStatus, Verdict
from app.decision.logic import All, Leaf, LogicForm, PolicyLogic
from app.decision.models import DecisionRule, Outcome
from app.decision.semantics import (
    PRODUCTION_ORIGINS,
    Attestation,
    PolicySemantics,
    SemanticsOrigin,
    SemanticsStatus,
)
from app.decision.table import (
    CriterionOutcome,
    GuardrailState,
    ResolutionState,
    decide,
)
from tests.support import TEST_ATTESTATION, attested_assumption

pytestmark = [pytest.mark.unit, pytest.mark.security]

ADJUDICATIONS = frozenset({Outcome.APPROVE_RECOMMENDED, Outcome.DENY_RECOMMENDED})
R = CriterionKind.REQUIRED
X = CriterionKind.EXCLUSION


def _space() -> list[tuple[tuple[CriterionOutcome, ...], GuardrailState, ResolutionState]]:
    """Every input up to 2 required + 2 exclusion criteria, all states.

    The same generator shape as the Phase 4 equivalence check, so the space is
    already known to be rich enough to reach every row of the table.
    """
    cells = [(v, e) for v in Verdict for e in (True, False)]
    inputs = []
    for n_req in range(3):
        for n_exc in range(3):
            for req in product(cells, repeat=n_req):
                for exc in product(cells, repeat=n_exc):
                    criteria = tuple(
                        CriterionOutcome(f"R{i}", R, v, e) for i, (v, e) in enumerate(req)
                    ) + tuple(CriterionOutcome(f"X{i}", X, v, e) for i, (v, e) in enumerate(exc))
                    for guardrail in GuardrailState:
                        for status in ResolutionStatus:
                            inputs.append((criteria, guardrail, ResolutionState(status, 1)))
    return inputs


# ---------------------------------------------------------------------------
# The invariant, paired
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "unverified",
    [
        pytest.param(lambda _c: PolicySemantics.unconsulted(), id="nobody-consulted-the-inventory"),
        pytest.param(
            lambda _c: PolicySemantics.review_required(policy_id="p", policy_version="v"),
            id="corpus-unreviewed",
        ),
        pytest.param(
            lambda _c: PolicySemantics.no_criteria(policy_id="p", policy_version="v"),
            id="nothing-transcribed",
        ),
    ],
)
def test_unverified_semantics_never_adjudicate(unverified) -> None:  # type: ignore[no-untyped-def]
    """The safety claim, plus the two clauses that stop it being vacuous.

    1. **The invariant.** Unverified semantics never approve and never deny.
    2. **Positive control.** The same space, attested, must reach BOTH
       `APPROVE_RECOMMENDED` and `DENY_RECOMMENDED` - otherwise clause 1 would be
       a statement about a space that never adjudicates at all.
    3. **Anti-vacuity.** Wherever the attested run adjudicates, the unverified run's
       rule must be one of the two semantics rules. This proves the *new gate*
       stopped the case. Without it, an implementation that fired rule 1 on
       everything would satisfy clauses 1 and 2 and prove nothing.
    """
    approvals = denials = gated = 0

    for criteria, guardrail, resolution in _space():
        blocked = decide(criteria, guardrail, resolution, unverified(criteria))
        control = decide(criteria, guardrail, resolution, attested_assumption(criteria))

        # 1
        assert blocked.outcome not in ADJUDICATIONS, (
            f"unverified semantics produced {blocked.outcome.value} for "
            f"{criteria} / {guardrail.value} / {resolution.status.value}"
        )

        if control.outcome is Outcome.APPROVE_RECOMMENDED:
            approvals += 1
        elif control.outcome is Outcome.DENY_RECOMMENDED:
            denials += 1
        else:
            continue

        # 3
        assert blocked.rule in {
            DecisionRule.POLICY_SEMANTICS_UNRESOLVED,
            DecisionRule.POLICY_SEMANTICS_UNVERIFIED,
        }, (
            f"the attested run adjudicated ({control.outcome.value}) but the "
            f"unverified run was stopped by rule {blocked.rule.name}, not by the "
            "semantics gate"
        )
        gated += 1

    # 2
    assert approvals > 0, "the generated space never approves; clause 1 proves nothing"
    assert denials > 0, "the generated space never denies; clause 1 proves nothing"
    assert gated == approvals + denials


def test_the_two_failure_causes_produce_different_rules() -> None:
    """A corpus problem and a wiring problem must be distinguishable in the audit.

    `REVIEW_REQUIRED` means a human must read the regulation (OD-19).
    `POLICY_SEMANTICS_UNKNOWN` means an engineer must fix the caller. Collapsing
    them into one generic UNKNOWN would make a misconfigured deployment look
    exactly like an honestly-unreviewed corpus.
    """
    criteria = (CriterionOutcome("a", R, Verdict.SATISFIED, True),)
    resolved = ResolutionState(ResolutionStatus.RESOLVED, 1)

    corpus = decide(
        criteria,
        GuardrailState.PASSED,
        resolved,
        PolicySemantics.review_required(policy_id="p", policy_version="v"),
    )
    wiring = decide(criteria, GuardrailState.PASSED, resolved, PolicySemantics.unconsulted())

    assert corpus.rule is DecisionRule.POLICY_SEMANTICS_UNRESOLVED
    assert wiring.rule is DecisionRule.POLICY_SEMANTICS_UNVERIFIED
    assert corpus.rule is not wiring.rule
    assert corpus.outcome is wiring.outcome is Outcome.HUMAN_REVIEW


def test_the_recommendation_records_what_was_known_and_who_said_so() -> None:
    """An outcome that cannot say which semantics produced it is not auditable."""
    criteria = (CriterionOutcome("a", R, Verdict.SATISFIED, True),)
    resolved = ResolutionState(ResolutionStatus.RESOLVED, 1)

    attested = decide(criteria, GuardrailState.PASSED, resolved, attested_assumption(criteria))
    assert attested.policy_semantics is SemanticsStatus.ASSUMED_CONJUNCTION
    assert attested.semantics_origin is SemanticsOrigin.POLICY_LOGIC_INVENTORY

    blocked = decide(criteria, GuardrailState.PASSED, resolved, PolicySemantics.unconsulted())
    assert blocked.policy_semantics is SemanticsStatus.POLICY_SEMANTICS_UNKNOWN
    assert blocked.semantics_origin is SemanticsOrigin.UNCONSULTED


# ---------------------------------------------------------------------------
# Mutations the paired test cannot catch
# ---------------------------------------------------------------------------


def test_semantics_has_no_default() -> None:
    """Giving `semantics` a default would reinstate R-59 invisibly.

    The paired test above cannot catch this: a default that supplies an attested
    conjunction makes every unverified call verified, and the test would then be
    comparing the control against itself and passing. Only the signature shows it.
    """
    parameter = inspect.signature(decide).parameters["semantics"]
    assert parameter.default is inspect.Parameter.empty, (
        "decide(semantics=...) acquired a default. A caller who supplies nothing "
        "must get a TypeError, not an assumption."
    )
    assert parameter.kind is inspect.Parameter.POSITIONAL_OR_KEYWORD


def test_decide_no_longer_accepts_a_bare_policy_logic() -> None:
    """The `logic=` parameter is gone, not deprecated.

    A bare `PolicyLogic` carries no attestation, so accepting one would be a
    second route to executing an unattested assumption.
    """
    assert "logic" not in inspect.signature(decide).parameters


@pytest.mark.parametrize(
    ("factory", "kwargs"),
    [
        ("declared", {"logic": None, "attestation": TEST_ATTESTATION}),
        ("assumed", {"logic": None, "attestation": TEST_ATTESTATION}),
    ],
)
def test_an_executable_status_without_a_tree_is_demoted(
    factory: str, kwargs: dict[str, object]
) -> None:
    """Claiming an executable status without the tree it needs cannot succeed."""
    semantics = getattr(PolicySemantics, factory)(policy_id="p", policy_version="v", **kwargs)
    assert semantics.status is SemanticsStatus.POLICY_SEMANTICS_UNKNOWN
    assert semantics.logic is None
    assert semantics.notes


def test_an_unattested_assumption_is_demoted() -> None:
    """The mutation the paired test cannot see.

    Weakening the constructor so an unattested `ASSUMED_CONJUNCTION` survives would
    leave the paired test green - every value it builds is attested - while
    restoring exactly the behaviour R-59 was about: a conjunction executing because
    someone constructed one, not because the inventory said so.
    """
    logic = PolicyLogic(
        policy_id="p",
        policy_version="v",
        requirements=All((Leaf("a"),)),
        form=LogicForm.ASSUMED_CONJUNCTION,
    )
    semantics = PolicySemantics.assumed(
        policy_id="p", policy_version="v", logic=logic, attestation=None
    )
    assert semantics.status is SemanticsStatus.POLICY_SEMANTICS_UNKNOWN
    assert not semantics.is_executable
    assert any("attestation" in note for note in semantics.notes)


def test_a_status_that_disagrees_with_its_tree_is_demoted() -> None:
    """`DECLARED` with an assumed tree is a claim the tree does not support."""
    assumed_tree = PolicyLogic(
        policy_id="p",
        policy_version="v",
        requirements=All((Leaf("a"),)),
        form=LogicForm.ASSUMED_CONJUNCTION,
    )
    semantics = PolicySemantics.declared(
        policy_id="p", policy_version="v", logic=assumed_tree, attestation=TEST_ATTESTATION
    )
    assert semantics.status is SemanticsStatus.POLICY_SEMANTICS_UNKNOWN


def test_review_required_discards_any_tree_it_is_handed() -> None:
    """Holding a tree beside a verdict that says "do not run this" invites running it."""
    semantics = PolicySemantics.review_required(policy_id="p", policy_version="v")
    assert semantics.logic is None
    assert not semantics.is_executable


# ---------------------------------------------------------------------------
# Vocabulary alignment
# ---------------------------------------------------------------------------


def test_the_status_vocabulary_matches_the_logic_inventory() -> None:
    """A classification the inventory can emit must have a status here.

    Otherwise `semantics_for()` falls through to `unconsulted` for a form the
    inventory considers meaningful - safe, but silently so, and the gap would only
    show up as every case for that policy routing to a human for the wrong reason.
    """
    inventory_forms = {form.value for form in LogicForm}
    statuses = {status.value for status in SemanticsStatus}
    assert inventory_forms <= statuses, (
        f"LogicForm members with no SemanticsStatus: {sorted(inventory_forms - statuses)}"
    )
    assert statuses - inventory_forms == {"POLICY_SEMANTICS_UNKNOWN"}


def test_only_two_origins_are_admissible_in_production() -> None:
    assert PRODUCTION_ORIGINS == {
        SemanticsOrigin.POLICY_LOGIC_INVENTORY,
        SemanticsOrigin.DECLARED_LOGIC_FILE,
    }
    assert SemanticsOrigin.GOLD_V1_REPLAY not in PRODUCTION_ORIGINS
    assert SemanticsOrigin.UNCONSULTED not in PRODUCTION_ORIGINS


def test_only_declared_and_assumed_are_executable_statuses() -> None:
    executable = {s for s in SemanticsStatus if s.is_executable}
    assert executable == {
        SemanticsStatus.DECLARED,
        SemanticsStatus.ASSUMED_CONJUNCTION,
    }


def test_an_attestation_is_required_to_be_executable() -> None:
    """`is_executable` needs both halves; either alone has been wrong before."""
    logic = PolicyLogic(
        policy_id="p",
        policy_version="v",
        requirements=All((Leaf("a"),)),
        form=LogicForm.ASSUMED_CONJUNCTION,
    )
    good = PolicySemantics.assumed(
        policy_id="p", policy_version="v", logic=logic, attestation=TEST_ATTESTATION
    )
    assert good.is_executable

    # A status that permits execution but carries no tree.
    hollow = PolicySemantics(
        policy_id="p",
        policy_version="v",
        status=SemanticsStatus.DECLARED,
        logic=None,
        attestation=Attestation("x", "y", SemanticsOrigin.DECLARED_LOGIC_FILE),
    )
    assert not hollow.is_executable
