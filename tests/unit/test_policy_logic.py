"""Truth tables for the policy logic, and the 410.32 regression that forced it.

Every connective is tested against its full Kleene table rather than against
sampled cases, because a three-valued connective has nine or twenty-seven rows and
there is no excuse for testing four of them. Where a test is not exhaustive by
construction it corrupts the implementation and asserts the corruption is caught.

The load-bearing test in this file is `test_the_mammography_exception_*`: it proves
the pre-Phase-4 conjunction produced a denial that 42 CFR 410.32(a)(1) contradicts,
and that the declared logic produces the policy-consistent result instead.
"""

from __future__ import annotations

import json
from datetime import date
from itertools import product
from pathlib import Path

import pytest

from app.core.types import CriterionKind, ResolutionStatus, Verdict
from app.decision.logic import (
    All,
    Any,
    AtLeast,
    Leaf,
    LogicForm,
    Not,
    PolicyLogic,
    PolicyTruth,
    Tri,
    Unless,
    When,
    evaluate,
    leaf_value,
)
from app.decision.models import DecisionRule, Outcome
from app.decision.table import (
    CriterionOutcome,
    GuardrailState,
    ResolutionState,
    assumed_conjunction,
    decide,
)
from app.policy.logic_loader import LogicSpecError, load_policy_logic_dir, parse_node
from tests.support import attested, attested_assumption

pytestmark = pytest.mark.unit

REPO = Path(__file__).resolve().parents[2]
LOGIC_DIR = REPO / "data/policy_logic"
INVENTORY = REPO / "data/criteria/inventory.jsonl"

T, F, U = Tri.TRUE, Tri.FALSE, Tri.UNKNOWN
R = CriterionKind.REQUIRED
X = CriterionKind.EXCLUSION
E = CriterionKind.EXCEPTION_CONDITION
RESOLVED = ResolutionState(status=ResolutionStatus.RESOLVED, version_count=1)


def _logic(node: object, **kw: object) -> PolicyLogic:
    return PolicyLogic(policy_id="test", policy_version="v1", requirements=node, **kw)


def _value(node: object, states: dict[str, Tri]) -> Tri:
    return evaluate(_logic(node), states).value


# ---------------------------------------------------------------------------
# Kleene connectives - exhaustive
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("a", "b", "expected"),
    [
        (T, T, T),
        (T, F, F),
        (T, U, U),
        (F, T, F),
        (F, F, F),
        (F, U, F),
        (U, T, U),
        (U, F, F),
        (U, U, U),
    ],
)
def test_all_is_kleene_conjunction(a: Tri, b: Tri, expected: Tri) -> None:
    """`ALL(FALSE, UNKNOWN) = FALSE` is the interesting row.

    A decisive failure stays decisive whatever else is unanswered. Whether the
    system should nonetheless hold the case is a separate question, answered in
    the recommendation layer, not here.
    """
    assert _value(All((Leaf("a"), Leaf("b"))), {"a": a, "b": b}) is expected


@pytest.mark.parametrize(
    ("a", "b", "expected"),
    [
        (T, T, T),
        (T, F, T),
        (T, U, T),
        (F, T, T),
        (F, F, F),
        (F, U, U),
        (U, T, T),
        (U, F, U),
        (U, U, U),
    ],
)
def test_any_is_kleene_disjunction(a: Tri, b: Tri, expected: Tri) -> None:
    """`ANY(TRUE, UNKNOWN) = TRUE` is why this module exists.

    An alternative pathway that already holds makes the unanswered question moot.
    Two-valued logic cannot say that without first guessing the unknown.
    """
    assert _value(Any((Leaf("a"), Leaf("b"))), {"a": a, "b": b}) is expected


@pytest.mark.parametrize(("a", "expected"), [(T, F), (F, T), (U, U)])
def test_not_leaves_unknown_alone(a: Tri, expected: Tri) -> None:
    assert _value(Not(Leaf("a")), {"a": a}) is expected


@pytest.mark.parametrize(
    ("n", "values", "expected"),
    [
        (2, (T, T, F), T),
        (2, (T, U, F), U),  # the unknown could still complete the count
        (2, (T, F, F), F),  # it cannot: only one can possibly hold
        (1, (U, F, F), U),
        (3, (T, T, T), T),
        (2, (U, U, F), U),
    ],
)
def test_at_least_counts_possible_completions(
    n: int, values: tuple[Tri, ...], expected: Tri
) -> None:
    """FALSE requires that even every unknown resolving TRUE would not reach `n`."""
    node = AtLeast(n, tuple(Leaf(c) for c in "abc"))
    assert _value(node, dict(zip("abc", values, strict=True))) is expected


def test_at_least_rejects_an_unsatisfiable_threshold() -> None:
    with pytest.raises(ValueError, match="unsatisfiable"):
        AtLeast(4, (Leaf("a"), Leaf("b")))


@pytest.mark.parametrize(
    ("rule", "exception", "expected"),
    [
        (T, T, T),
        (T, F, T),
        (T, U, T),
        (F, T, T),  # the exception carries it - the whole point
        (F, F, F),
        (F, U, U),
        (U, T, T),
        (U, F, U),
        (U, U, U),
    ],
)
def test_unless_matches_disjunction_exactly(rule: Tri, exception: Tri, expected: Tri) -> None:
    """`Unless` is a disjunction that remembers it was written as an exception.

    The truth table must be identical to `Any`, or the two spellings would mean
    different things and the inventory's readability would have cost correctness.
    """
    states = {"r": rule, "e": exception}
    assert _value(Unless(Leaf("r"), Leaf("e")), states) is expected
    assert _value(Any((Leaf("r"), Leaf("e"))), states) is expected


@pytest.mark.parametrize(
    ("condition", "body", "expected"),
    [
        (F, T, T),
        (F, F, T),
        (F, U, T),  # inapplicable rules cannot fail
        (T, T, T),
        (T, F, F),
        (T, U, U),
        (U, T, T),  # holds either way
        (U, F, U),
        (U, U, U),  # might not apply at all
    ],
)
def test_when_makes_inapplicable_rules_harmless(condition: Tri, body: Tri, expected: Tri) -> None:
    node = When(Leaf("c"), Leaf("b"))
    assert _value(node, {"c": condition, "b": body}) is expected


def test_nested_conditions_evaluate_compositionally() -> None:
    """A tree three deep, with each branch pinned independently."""
    node = All(
        (
            Unless(Leaf("a"), All((Leaf("b"), Leaf("c")))),
            Any((Leaf("d"), Not(Leaf("e")))),
        )
    )
    assert _value(node, {"a": F, "b": T, "c": T, "d": F, "e": F}) is T
    assert _value(node, {"a": F, "b": T, "c": F, "d": T, "e": T}) is F
    assert _value(node, {"a": F, "b": T, "c": U, "d": T, "e": T}) is U


def test_an_unreferenced_criterion_is_unknown_not_false() -> None:
    """A criterion nobody adjudicated is an open question, never a failed one."""
    result = evaluate(_logic(All((Leaf("a"), Leaf("absent")))), {"a": T})
    assert result.value is Tri.UNKNOWN
    assert "absent" in result.unknown_criteria


# ---------------------------------------------------------------------------
# leaf_value - the evidence asymmetry
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("kind", "verdict", "evidence", "expected"),
    [
        (R, Verdict.SATISFIED, True, T),
        (R, Verdict.SATISFIED, False, T),
        (R, Verdict.NOT_SATISFIED, True, F),
        (R, Verdict.NOT_SATISFIED, False, U),  # <- must not reach a denial
        (R, Verdict.INSUFFICIENT_EVIDENCE, True, U),
        (R, Verdict.NOT_APPLICABLE, False, T),
        (X, Verdict.SATISFIED, True, T),
        (X, Verdict.SATISFIED, False, U),  # <- must not reach a denial
        (X, Verdict.NOT_SATISFIED, False, F),
        (X, Verdict.INSUFFICIENT_EVIDENCE, True, U),
        (X, Verdict.NOT_APPLICABLE, False, F),
    ],
)
def test_the_denying_direction_always_requires_evidence(
    kind: CriterionKind, verdict: Verdict, evidence: bool, expected: Tri
) -> None:
    """Whichever truth value leads toward a denial needs evidence behind it.

    For a requirement that is FALSE; for an exclusion it is TRUE. The rule is one
    rule, applied in opposite directions, and both directions are pinned here so
    a future edit cannot quietly relax one of them.
    """
    assert leaf_value(verdict, has_valid_evidence=evidence, kind=kind) is expected


def test_every_verdict_and_kind_combination_is_total() -> None:
    """No input to `leaf_value` may fall through to an exception or None."""
    for kind, verdict, evidence in product(CriterionKind, Verdict, (True, False)):
        assert leaf_value(verdict, has_valid_evidence=evidence, kind=kind) in tuple(Tri)


# ---------------------------------------------------------------------------
# Temporal applicability
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("as_of", "applicable"),
    [
        (date(2025, 12, 31), False),
        (date(2026, 1, 1), True),
        (date(2026, 6, 1), True),
        (date(2026, 12, 31), True),
        (date(2027, 1, 1), False),
        (None, True),
    ],
)
def test_a_policy_outside_its_window_decides_nothing(as_of: date | None, applicable: bool) -> None:
    """Version selection is by date of service, never "latest" (ADR-004)."""
    logic = _logic(
        All((Leaf("a"),)),
        effective_from=date(2026, 1, 1),
        effective_to=date(2026, 12, 31),
    )
    result = evaluate(logic, {"a": T}, as_of=as_of)
    assert result.applicable is applicable
    if not applicable:
        assert result.truth is PolicyTruth.POLICY_INDETERMINATE


def test_an_out_of_window_policy_routes_to_a_human_not_a_denial() -> None:
    logic = _logic(All((Leaf("a"),)), effective_from=date(2026, 1, 1))
    outcomes = (CriterionOutcome("a", R, Verdict.NOT_SATISFIED, True),)
    got = decide(outcomes, GuardrailState.PASSED, RESOLVED, attested(logic), as_of=date(2025, 1, 1))
    assert got.outcome is Outcome.HUMAN_REVIEW


# ---------------------------------------------------------------------------
# The 410.32 mammography exception - the regression that forced this phase
# ---------------------------------------------------------------------------


P = "42_CFR_410_32_2026_08_13_"


@pytest.fixture(scope="module")
def mammography_logic() -> PolicyLogic:
    known = frozenset(
        json.loads(line)["criterion_id"]
        for line in INVENTORY.read_text(encoding="utf-8").splitlines()
        if line.strip()
    )
    return load_policy_logic_dir(LOGIC_DIR, known_criteria=known)[("42 CFR 410.32", "2026-08-13")]


def _case(
    *, ordering: Verdict, qualified: Verdict, mammogram: Verdict, evidence: bool = True
) -> tuple[CriterionOutcome, ...]:
    """The ordering requirement plus the two exception conditions.

    The other three requirements are held SATISFIED so the test isolates the
    exception; a case that failed elsewhere would deny for a reason that has
    nothing to do with what is being measured.
    """
    return (
        CriterionOutcome(P + "C01", R, ordering, evidence),
        CriterionOutcome(P + "C02", R, Verdict.SATISFIED, True),
        CriterionOutcome(P + "C03", R, Verdict.SATISFIED, True),
        CriterionOutcome(P + "C04", R, Verdict.SATISFIED, True),
        CriterionOutcome(P + "C05", E, qualified, evidence),
        CriterionOutcome(P + "C06", E, mammogram, evidence),
    )


def test_the_mammography_exception_was_decided_wrongly_before_phase_4(
    mammography_logic: PolicyLogic,
) -> None:
    """The load-bearing regression.

    42 CFR 410.32(a)(1): a physician qualified as an interpreting physician "may
    order a diagnostic mammogram based on the findings of a screening mammogram
    even though the physician does not treat the beneficiary."

    So this case - ordering physician does not treat the beneficiary, but is
    qualified and is ordering a diagnostic mammogram from screening findings - is
    permitted by the regulation. The universal conjunction denies it, because the
    ordering criterion is evidenced NOT_SATISFIED and a conjunction has no way to
    hear the word "even though".

    Both halves are asserted together deliberately. Asserting only the new result
    would leave no proof that the old logic was ever wrong, and the claim this
    phase rests on is precisely that it was.

    Phase 5 note: `old` used to be `decide()` with no logic argument - the silent
    default. That default is gone, so the wrong answer is now produced by an
    *explicitly attested* assumed conjunction. The regression claim is unchanged
    and arguably stronger: the denial is attributable to a named, reviewable
    assumption rather than to an unstated property of `table.py`.
    """
    case = _case(
        ordering=Verdict.NOT_SATISFIED,
        qualified=Verdict.SATISFIED,
        mammogram=Verdict.SATISFIED,
    )

    old = decide(case, GuardrailState.PASSED, RESOLVED, attested_assumption(case))
    assert old.outcome is Outcome.DENY_RECOMMENDED
    assert old.rule is DecisionRule.REQUIRED_NOT_SATISFIED

    new = decide(case, GuardrailState.PASSED, RESOLVED, attested(mammography_logic))
    assert new.outcome is Outcome.APPROVE_RECOMMENDED
    assert new.rule is DecisionRule.EXCEPTION_SATISFIED, (
        "an approval reached through an alternative pathway must say so; "
        "reporting ALL_REQUIRED_SATISFIED would misdescribe a case where a "
        "requirement demonstrably was not met"
    )


def test_the_ordinary_rule_still_governs_when_it_is_met(
    mammography_logic: PolicyLogic,
) -> None:
    """The exception must not become a second way to approve everything."""
    case = _case(
        ordering=Verdict.SATISFIED,
        qualified=Verdict.NOT_SATISFIED,
        mammogram=Verdict.NOT_SATISFIED,
    )
    got = decide(case, GuardrailState.PASSED, RESOLVED, attested(mammography_logic))
    assert got.outcome is Outcome.APPROVE_RECOMMENDED
    assert got.rule is DecisionRule.ALL_REQUIRED_SATISFIED


def test_a_failed_exception_leaves_the_denial_standing(
    mammography_logic: PolicyLogic,
) -> None:
    """Not every unmet requirement has a route around it.

    Ordering physician does not treat the beneficiary, and neither exception
    condition holds. The regulation gives no relief and the denial is correct -
    this is the case that proves the new logic did not simply stop denying.
    """
    case = _case(
        ordering=Verdict.NOT_SATISFIED,
        qualified=Verdict.NOT_SATISFIED,
        mammogram=Verdict.NOT_SATISFIED,
    )
    got = decide(case, GuardrailState.PASSED, RESOLVED, attested(mammography_logic))
    assert got.outcome is Outcome.DENY_RECOMMENDED
    assert got.rule is DecisionRule.REQUIRED_NOT_SATISFIED


def test_a_partial_exception_does_not_qualify(
    mammography_logic: PolicyLogic,
) -> None:
    """Both conditions must hold: a diagnostic mammogram ordered for some other
    reason, or ordered by an unqualified physician, is not within the exception."""
    for qualified, mammogram in (
        (Verdict.SATISFIED, Verdict.NOT_SATISFIED),
        (Verdict.NOT_SATISFIED, Verdict.SATISFIED),
    ):
        case = _case(ordering=Verdict.NOT_SATISFIED, qualified=qualified, mammogram=mammogram)
        got = decide(case, GuardrailState.PASSED, RESOLVED, attested(mammography_logic))
        assert got.outcome is Outcome.DENY_RECOMMENDED, (qualified, mammogram)


def test_an_unknown_exception_condition_holds_the_case(
    mammography_logic: PolicyLogic,
) -> None:
    """Nobody established whether the exception applies, so nobody may deny.

    The ordering requirement is evidenced NOT_SATISFIED, which under the old logic
    denied outright. It must not now, because a route around it may exist and the
    question was never asked.
    """
    case = _case(
        ordering=Verdict.NOT_SATISFIED,
        qualified=Verdict.INSUFFICIENT_EVIDENCE,
        mammogram=Verdict.SATISFIED,
    )
    got = decide(case, GuardrailState.PASSED, RESOLVED, attested(mammography_logic))
    assert got.outcome is Outcome.NEEDS_INFO
    assert got.rule is DecisionRule.INSUFFICIENT_EVIDENCE
    assert P + "C05" in got.missing_evidence


def test_a_satisfied_exception_survives_an_unknown_elsewhere_on_its_path(
    mammography_logic: PolicyLogic,
) -> None:
    """Kleene ANY(TRUE, UNKNOWN) = TRUE, at the recommendation layer.

    The ordering requirement is unanswered, but the exception pathway is fully
    established. Asking for the ordering facts anyway would be delay dressed as
    diligence: no answer could change the result.
    """
    case = _case(
        ordering=Verdict.INSUFFICIENT_EVIDENCE,
        qualified=Verdict.SATISFIED,
        mammogram=Verdict.SATISFIED,
    )
    got = decide(case, GuardrailState.PASSED, RESOLVED, attested(mammography_logic))
    assert got.outcome is Outcome.APPROVE_RECOMMENDED

    # And the universal conjunction would have held it.
    assert (
        decide(case, GuardrailState.PASSED, RESOLVED, attested_assumption(case)).outcome
        is Outcome.NEEDS_INFO
    )


def test_contradictory_facts_route_to_a_human_before_the_logic_runs(
    mammography_logic: PolicyLogic,
) -> None:
    """The system does not adjudicate its own inconsistency, exception or not."""
    case = _case(
        ordering=Verdict.NOT_SATISFIED,
        qualified=Verdict.SATISFIED,
        mammogram=Verdict.SATISFIED,
    )
    got = decide(case, GuardrailState.CONTRADICTION, RESOLVED, attested(mammography_logic))
    assert got.outcome is Outcome.HUMAN_REVIEW
    assert got.rule is DecisionRule.CONTRADICTORY_VERDICTS


def test_an_unevidenced_exception_cannot_rescue_a_denial(
    mammography_logic: PolicyLogic,
) -> None:
    """An exception asserted with nothing behind it holds the case; it never approves.

    This is the injection-shaped risk: if an unsupported SATISFIED on an exception
    condition could approve, the cheapest attack on this system would be to claim
    the exception. It cannot - without evidence the condition is UNKNOWN, and
    UNKNOWN on the only live pathway means NEEDS_INFO.
    """
    case = _case(
        ordering=Verdict.NOT_SATISFIED,
        qualified=Verdict.SATISFIED,
        mammogram=Verdict.SATISFIED,
        evidence=False,
    )
    got = decide(case, GuardrailState.PASSED, RESOLVED, attested(mammography_logic))
    assert got.outcome is Outcome.NEEDS_INFO


# ---------------------------------------------------------------------------
# Assumed conjunction and unresolved semantics
# ---------------------------------------------------------------------------


def test_an_undeclared_policy_gets_an_explicit_assumed_conjunction() -> None:
    """The old behaviour survives, but is now labelled instead of invisible."""
    criteria = (
        CriterionOutcome("a", R, Verdict.SATISFIED, True),
        CriterionOutcome("x", X, Verdict.NOT_SATISFIED, True),
    )
    logic = assumed_conjunction(criteria)
    assert logic.form is LogicForm.ASSUMED_CONJUNCTION
    assert logic.exclusions is not None


def test_exception_conditions_never_enter_an_assumed_conjunction() -> None:
    """Otherwise adding an exception condition would make cases *harder* to pass.

    An exception is an alternative route, not an extra hurdle. If it were folded
    into the default conjunction, transcribing one would silently start denying
    cases that previously approved.
    """
    criteria = (
        CriterionOutcome("a", R, Verdict.SATISFIED, True),
        CriterionOutcome("e", E, Verdict.NOT_SATISFIED, True),
    )
    got = decide(criteria, GuardrailState.PASSED, RESOLVED, attested_assumption(criteria))
    assert got.outcome is Outcome.APPROVE_RECOMMENDED


def test_unresolved_policy_semantics_never_produce_a_recommendation() -> None:
    """A policy whose logic nobody established cannot decide, in either direction.

    Guessing the shape of a rule is not a safer error than admitting it is
    unknown, so this fires before any denial and before any approval.

    Phase 5 note: this exercises the CORPUS failure - the inventory classifies the
    version REVIEW_REQUIRED because a human has not read it (OD-19). The RUNTIME
    failure, where nobody consulted the inventory at all, is a different cause with
    its own rule and lives in `tests/unit/test_fail_closed_semantics.py`. The tree
    passed here is discarded by `review_required()` on purpose: holding a tree
    beside a verdict that says "do not run this" invites someone to run it.
    """
    logic = _logic(All((Leaf("a"),)), form=LogicForm.REVIEW_REQUIRED)
    for verdict in (Verdict.SATISFIED, Verdict.NOT_SATISFIED):
        criteria = (CriterionOutcome("a", R, verdict, True),)
        got = decide(criteria, GuardrailState.PASSED, RESOLVED, attested(logic))
        assert got.outcome is Outcome.HUMAN_REVIEW
        assert got.rule is DecisionRule.POLICY_SEMANTICS_UNRESOLVED


def test_a_policy_stating_no_requirements_cannot_approve() -> None:
    """Vacuous truth would turn 42 CFR 411.15 into a universal approval.

    An exclusion overlay states nothing to satisfy. `ALL(())` is TRUE in every
    logic textbook, and here that would mean "nothing was required, so everything
    passes" - which is how an empty rule set becomes an approval engine.
    """
    logic = _logic(All(()), exclusions=Any((Leaf("x"),)))
    criteria = (CriterionOutcome("x", X, Verdict.NOT_SATISFIED, True),)
    got = decide(criteria, GuardrailState.PASSED, RESOLVED, attested(logic))
    assert got.outcome is Outcome.HUMAN_REVIEW
    assert got.rule is DecisionRule.UNCLASSIFIED


def test_an_established_exclusion_denies_even_when_requirements_hold() -> None:
    logic = _logic(All((Leaf("a"),)), exclusions=Any((Leaf("x"),)))
    criteria = (
        CriterionOutcome("a", R, Verdict.SATISFIED, True),
        CriterionOutcome("x", X, Verdict.SATISFIED, True),
    )
    got = decide(criteria, GuardrailState.PASSED, RESOLVED, attested(logic))
    assert got.outcome is Outcome.DENY_RECOMMENDED
    assert got.rule is DecisionRule.EXCLUSION_SATISFIED


# ---------------------------------------------------------------------------
# The loader refuses to guess
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("spec", "match"),
    [
        ({"leaf": ""}, "criterion id"),
        ({"all": []}, "non-empty"),
        ({"nonsense": []}, "unknown node type"),
        ({"all": [], "any": []}, "exactly one node key"),
        ({"unless": {"rule": {"leaf": "a"}}}, "unless"),
        ({"when": {"condition": {"leaf": "a"}}}, "when"),
        ("a string", "expected a mapping"),
    ],
)
def test_malformed_logic_raises_rather_than_defaulting(spec: object, match: str) -> None:
    """A typo must not silently degrade `unless` into `all`.

    That specific degradation would turn an alternative pathway back into an
    absolute requirement - reintroducing the exact defect this phase removed,
    with no error and no test failure to show for it.
    """
    with pytest.raises(LogicSpecError, match=match):
        parse_node(spec)


def test_a_dangling_criterion_reference_is_refused() -> None:
    """An unknown id evaluates to UNKNOWN, which would quietly make an exception
    pathway unreachable and the requirement absolute again. So it raises."""
    with pytest.raises(LogicSpecError, match="absent from the inventory"):
        load_policy_logic_dir(LOGIC_DIR, known_criteria=frozenset({"nothing"}))


def test_declared_logic_references_only_real_criteria() -> None:
    known = frozenset(
        json.loads(line)["criterion_id"]
        for line in INVENTORY.read_text(encoding="utf-8").splitlines()
        if line.strip()
    )
    loaded = load_policy_logic_dir(LOGIC_DIR, known_criteria=known)
    assert loaded, "no declared policy logic found"


def test_unresolved_semantics_are_recorded_not_silently_declared(
    mammography_logic: PolicyLogic,
) -> None:
    """Declaring the exception did not resolve the rest of 410.32.

    C03 depends on supervision levels that are not transcribed (R-51) and C04's
    applicability is conditional with nothing to condition on. Both are declared
    as plain conjuncts because that is what the engine already did - and both are
    written down as open questions rather than presented as settled.
    """
    assert mammography_logic.form is LogicForm.DECLARED
    notes = " ".join(mammography_logic.review_notes)
    assert "UNRESOLVED" in notes
    assert "C03" in notes and "C04" in notes


# ---------------------------------------------------------------------------
# What the rewrite changed, pinned
# ---------------------------------------------------------------------------


def _pre_phase4_decide(
    criteria: tuple[CriterionOutcome, ...],
    guardrail: GuardrailState,
    resolution: ResolutionState,
) -> tuple[Outcome, DecisionRule]:
    """The decision table exactly as it stood before Phase 4.

    Kept as a reference implementation rather than as a comment, so "the rewrite
    was behaviour-preserving except here" is a claim the suite checks on every run
    instead of one someone verified once.
    """
    required = [c for c in criteria if c.kind is CriterionKind.REQUIRED]
    exclusions = [c for c in criteria if c.kind is CriterionKind.EXCLUSION]

    if resolution.status is ResolutionStatus.NONE_APPLICABLE:
        return Outcome.NEEDS_INFO, DecisionRule.NO_APPLICABLE_POLICY
    if resolution.status is ResolutionStatus.CONFLICTING:
        return Outcome.HUMAN_REVIEW, DecisionRule.CONFLICTING_POLICY
    if guardrail is GuardrailState.INVALID_CITATION:
        return Outcome.NO_DECISION, DecisionRule.INVALID_CITATION
    if guardrail is GuardrailState.MODEL_PATH_FAILED:
        return Outcome.HUMAN_REVIEW, DecisionRule.MODEL_PATH_FAILED
    if guardrail is GuardrailState.CONTRADICTION:
        return Outcome.HUMAN_REVIEW, DecisionRule.CONTRADICTORY_VERDICTS
    if [c for c in required if c.verdict is Verdict.INSUFFICIENT_EVIDENCE]:
        return Outcome.NEEDS_INFO, DecisionRule.INSUFFICIENT_EVIDENCE
    if any(c.verdict is Verdict.SATISFIED and c.has_valid_evidence for c in exclusions):
        return Outcome.DENY_RECOMMENDED, DecisionRule.EXCLUSION_SATISFIED
    if [c for c in required if c.verdict is Verdict.NOT_SATISFIED and c.has_valid_evidence]:
        return Outcome.DENY_RECOMMENDED, DecisionRule.REQUIRED_NOT_SATISFIED
    if [c for c in required if c.verdict is Verdict.NOT_SATISFIED and not c.has_valid_evidence]:
        return Outcome.NEEDS_INFO, DecisionRule.INSUFFICIENT_EVIDENCE
    if required and all(c.verdict in (Verdict.SATISFIED, Verdict.NOT_APPLICABLE) for c in required):
        return Outcome.APPROVE_RECOMMENDED, DecisionRule.ALL_REQUIRED_SATISFIED
    return Outcome.HUMAN_REVIEW, DecisionRule.UNCLASSIFIED


#: The resolution states the pre-Phase-4 table modelled.
#:
#: Phase 15 added `TEMPORALLY_UNRESOLVED`, `INSUFFICIENT_INFORMATION` and
#: `RESOLUTION_ERROR`. Feeding them to `_pre_phase4_decide` compares the rewrite
#: against an implementation that had no opinion about them - it falls through to
#: whatever the criteria say, which is not a divergence anyone chose. The three new
#: states get their own assertion below instead, on the property that matters.
_PRE_PHASE4_STATUSES = (
    ResolutionStatus.RESOLVED,
    ResolutionStatus.NONE_APPLICABLE,
    ResolutionStatus.CONFLICTING,
)


def _exhaustive_comparison() -> list[tuple[Outcome, Outcome]]:
    """Every input up to 2 required + 2 exclusion criteria, all states."""
    cells = [(v, e) for v in Verdict for e in (True, False)]
    diffs: list[tuple[Outcome, Outcome]] = []
    for n_req in range(3):
        for n_exc in range(3):
            for req in product(cells, repeat=n_req):
                for exc in product(cells, repeat=n_exc):
                    criteria = tuple(
                        CriterionOutcome(f"R{i}", R, v, e) for i, (v, e) in enumerate(req)
                    ) + tuple(CriterionOutcome(f"X{i}", X, v, e) for i, (v, e) in enumerate(exc))
                    for guardrail in GuardrailState:
                        for status in _PRE_PHASE4_STATUSES:
                            resolution = ResolutionState(status=status, version_count=1)
                            new = decide(
                                criteria,
                                guardrail,
                                resolution,
                                attested_assumption(criteria),
                            )
                            old = _pre_phase4_decide(criteria, guardrail, resolution)
                            if new.outcome is not old[0]:
                                diffs.append((old[0], new.outcome))
    return diffs


def test_the_rewrite_never_moves_a_case_toward_a_denial() -> None:
    """The safety invariant of the whole Phase 4 change.

    The rewrite is allowed to change behaviour - it must, or the 410.32 exception
    could not be fixed. What it may never do is turn something that was not a
    denial into one. Every divergence is checked in that direction, exhaustively,
    rather than argued for in a commit message.
    """
    for old, new in _exhaustive_comparison():
        assert new is not Outcome.DENY_RECOMMENDED, f"the rewrite turned {old.value} into a denial"


def test_the_known_divergences_are_exactly_these_two() -> None:
    """Both classes are `DENY_RECOMMENDED` becoming `NEEDS_INFO`.

    They share one cause: a required criterion judged NOT_SATISFIED with no valid
    evidence behind it. The old table treated that as a lesser thing than a
    verdict of INSUFFICIENT_EVIDENCE and checked it *after* the denial rows, so an
    evidenced failure elsewhere - or an established exclusion - denied the case
    while that question stood open. The two are the same thing wearing different
    labels, and both are now open questions, checked before any denial.

    This test exists so the divergence stays a decision. If it changes, someone
    changed the safety ordering, and that requires an ADR amendment (ADR-023).
    """
    classes = {(old, new) for old, new in _exhaustive_comparison()}
    assert classes == {(Outcome.DENY_RECOMMENDED, Outcome.NEEDS_INFO)}


def test_no_phase_15_resolution_state_can_reach_a_denial() -> None:
    """The three states added in Phase 15, over the same exhaustive input space.

    They are excluded from the pre-Phase-4 comparison above because that table had
    no opinion about them - there is nothing to diverge *from*. What can still be
    asserted, and is the only thing worth asserting, is the safety property: a case
    whose applicability is temporally unresolved, under-specified or errored must
    never reach an approval or a denial, whatever its criteria say.

    Non-vacuity is by pairing: the same criteria under `RESOLVED` must reach both a
    denial and an approval somewhere in the space, or this would pass over a corpus
    of inputs that never adjudicates anything.
    """
    added = (
        ResolutionStatus.TEMPORALLY_UNRESOLVED,
        ResolutionStatus.INSUFFICIENT_INFORMATION,
        ResolutionStatus.RESOLUTION_ERROR,
    )
    definitive = {Outcome.APPROVE_RECOMMENDED, Outcome.DENY_RECOMMENDED}
    cells = [(v, e) for v in Verdict for e in (True, False)]
    reached_under_resolved: set[Outcome] = set()

    for n_req in range(3):
        for n_exc in range(3):
            for req in product(cells, repeat=n_req):
                for exc in product(cells, repeat=n_exc):
                    criteria = tuple(
                        CriterionOutcome(f"R{i}", R, v, e) for i, (v, e) in enumerate(req)
                    ) + tuple(CriterionOutcome(f"X{i}", X, v, e) for i, (v, e) in enumerate(exc))
                    semantics = attested_assumption(criteria)
                    for guardrail in GuardrailState:
                        for status in added:
                            outcome = decide(
                                criteria,
                                guardrail,
                                ResolutionState(status=status, version_count=1),
                                semantics,
                            ).outcome
                            assert outcome not in definitive, (
                                f"{status.value} reached {outcome.value}"
                            )
                        reached_under_resolved.add(
                            decide(
                                criteria,
                                GuardrailState.PASSED,
                                ResolutionState(ResolutionStatus.RESOLVED, 1),
                                semantics,
                            ).outcome
                        )

    assert definitive <= reached_under_resolved, (
        "the input space never adjudicates under RESOLVED, so the assertion above "
        f"proves nothing; reached {sorted(o.value for o in reached_under_resolved)}"
    )


def test_the_divergence_is_unreachable_from_the_current_datasets() -> None:
    """No gold or development case exercises the changed path.

    Case generation sets `has_valid_evidence` from the criterion state, so an
    unevidenced NOT_SATISFIED never occurs. That is why gold_v1 needed no
    relabelling - and it is also a gap: the datasets cannot detect a regression in
    the behaviour that changed. Recorded as R-57.
    """
    cases = [
        json.loads(line)
        for path in ("data/gold/cases/gold_v1.jsonl", "data/synthetic/cases/cases.jsonl")
        for line in (REPO / path).read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    assert cases, "no cases loaded"
    states = {entry["state"] for case in cases for entry in case["expected"]["criteria"]}
    assert states <= {"SATISFIED", "NOT_SATISFIED", "UNKNOWN"}
