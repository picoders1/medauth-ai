"""The decision table: per-criterion verdicts in, a recommendation out.

Pure. No I/O, no clock, no randomness, no model. `app.decision` may reach
`app.core` and its own modules and nothing else, and a test asserts it by parsing
the AST, so this stays exhaustively testable as a truth table with nothing loaded
(ADR-010).

**Built during the data-foundation phase, deliberately.** ADR-015 requires that a
gold case's label be computed by *the same* function the system will use - a
separate labelling implementation would drift from the production one, and the
evaluation would then measure the difference between two pieces of code rather
than the behaviour of one. So the table lands with the dataset that depends on it.

What is **not** here: the abstention gate. It reads calibrated thresholds that do
not exist until Phase 6 selects them on the dev split, and inventing one now would
be a fabricated threshold with clinical consequences (ADR-011).

---

**Phase 4: the conjunction is now declared, not assumed.**

This table used to require that every required criterion hold. That is a rule no
regulation guarantees, and 42 CFR 410.32(a) disproves it in one sentence: a
qualified interpreting physician may order a diagnostic mammogram from screening
findings "even though the physician does not treat the beneficiary". Under the old
logic that case denied, because the ordering criterion was evidenced NOT_SATISFIED
- a denial the regulation itself contradicts.

So the shape of a policy's logic is now an input (`app.decision.logic`). When a
policy declares none, the engine builds a conjunction *explicitly* and stamps it
`ASSUMED_CONJUNCTION`, which travels on the recommendation and appears in the
logic inventory. The behaviour for such a policy is unchanged - what changed is
that the assumption is now visible and reviewable instead of being a property of
this file that nobody could see.

**Two layers, kept apart.** `logic.evaluate()` says what the *policy* concludes;
this module says what to *recommend*. They are different claims - "the conditions
are met" is a statement about a regulation, "approve" is advice to a reviewer that
also weighs evidence quality, guardrail state and open questions - and a system
that conflates them cannot say which of the two it got wrong.

---

**Phase 15: applicability is resolved, not asserted.**

Rows 1, 2, 14, 15 and 16 form one block at the top of the table and are looked up in
`_ROUTE_FOR_RESOLUTION` rather than branched. Until Phase 15 the live slice passed
`ResolutionState(RESOLVED)` because it had been handed a policy identity, which made
rows 1 and 2 unreachable from the runtime and let a case be adjudicated against a
policy that did not govern it - a denial with seven verified citations, which every
grounding metric passed (R-93, ADR-004). The table already refused that; nothing
ever asked it. What changed in Phase 15 is upstream, and what changed here is that
the refusal is now total over the state space instead of covering the two states
somebody thought of.

**Row order is still the safety design.** Rows 1-6 are all evaluated before any
denial is reachable, and row 6 (an open question) precedes rows 7 and 8 (evidenced
failure). That is the difference between "the note does not say" and "the note says
otherwise", and collapsing it is how automated prior authorization denies people
for missing paperwork. Kleene logic alone would not preserve it: a decisive FALSE
is logically decisive whatever else is unknown. Holding the case anyway is a safety
choice of this system, made here, where it can be read and tested.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import date
from enum import StrEnum

from app.core.types import CriterionKind, ResolutionStatus, Verdict
from app.decision.logic import (
    All,
    Any,
    AtLeast,
    Leaf,
    LogicForm,
    Node,
    Not,
    PolicyEvaluation,
    PolicyLogic,
    PolicyTruth,
    Tri,
    Unless,
    When,
    evaluate,
    leaf_value,
)
from app.decision.models import DecisionRule, Outcome, Recommendation
from app.decision.semantics import PolicySemantics, SemanticsStatus

__all__ = [
    "CriterionOutcome",
    "GuardrailState",
    "ResolutionState",
    "assumed_conjunction",
    "decide",
]


class GuardrailState(StrEnum):
    """What deterministic validation concluded, reduced to what the table needs."""

    PASSED = "PASSED"
    INVALID_CITATION = "INVALID_CITATION"
    CONTRADICTION = "CONTRADICTION"
    MODEL_PATH_FAILED = "MODEL_PATH_FAILED"


@dataclass(frozen=True, slots=True)
class CriterionOutcome:
    """One criterion's verdict, with whether it is backed by valid evidence.

    ``has_valid_evidence`` is separate from the verdict on purpose. A criterion may
    be judged NOT_SATISFIED with nothing behind it, and that must not reach a
    denial - it is missing evidence wearing a verdict's clothes.
    """

    criterion_id: str
    kind: CriterionKind
    verdict: Verdict
    has_valid_evidence: bool = False
    missing_evidence: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class ResolutionState:
    """What policy resolution concluded (ADR-004)."""

    status: ResolutionStatus
    version_count: int = 0


def assumed_conjunction(
    criteria: tuple[CriterionOutcome, ...],
    *,
    policy_id: str = "unspecified",
    policy_version: str = "unspecified",
) -> PolicyLogic:
    """Build the conjunction this engine used to apply silently.

    Every REQUIRED criterion joined by AND, every EXCLUSION joined by OR. It is
    the right shape for most of the corpus and the wrong shape for at least one
    policy, which is why it is stamped `ASSUMED_CONJUNCTION` rather than
    `DECLARED`: the label is the difference between a rule someone checked and a
    default nobody has.
    """
    required = tuple(Leaf(c.criterion_id) for c in criteria if c.kind is CriterionKind.REQUIRED)
    excluded = tuple(Leaf(c.criterion_id) for c in criteria if c.kind is CriterionKind.EXCLUSION)
    return PolicyLogic(
        policy_id=policy_id,
        policy_version=policy_version,
        requirements=All(required),
        exclusions=Any(excluded) if excluded else None,
        form=LogicForm.ASSUMED_CONJUNCTION,
    )


def _leaf_ids(node: Node) -> tuple[str, ...]:
    """Every criterion id the tree references, in order, duplicates kept.

    Used to tell "this policy states no requirements" from "this policy states
    requirements that all happen to hold", which vacuous truth would merge.
    """
    match node:
        case Leaf(criterion_id=cid):
            return (cid,)
        case All(children=children) | Any(children=children) | AtLeast(children=children):
            return tuple(i for c in children for i in _leaf_ids(c))
        case Not(child=child):
            return _leaf_ids(child)
        case Unless(rule=rule, exception=exception):
            return _leaf_ids(rule) + _leaf_ids(exception)
        case When(condition=condition, then=then):
            return _leaf_ids(condition) + _leaf_ids(then)


#: Where a case goes when applicability concluded something other than RESOLVED.
#:
#: Declared as data, and deliberately NOT total over `ResolutionStatus`: `RESOLVED`
#: is absent because it is the one value that continues past this block. Every other
#: member must appear, and `test_every_resolution_status_is_routed` fails if one does
#: not - so the failure mode for a new state is a red test, never a silent fallthrough
#: into adjudication.
#:
#: **No entry produces an approval or a denial**, and a test asserts that over the
#: whole mapping rather than over the entries someone remembered to check.
_ROUTE_FOR_RESOLUTION: dict[ResolutionStatus, tuple[Outcome, DecisionRule]] = {
    # Absence of an NCD/LCD generally means contractor discretion, not non-coverage.
    ResolutionStatus.NONE_APPLICABLE: (Outcome.NEEDS_INFO, DecisionRule.NO_APPLICABLE_POLICY),
    # Which of several policies governs is a human judgement, not a ranking.
    ResolutionStatus.CONFLICTING: (Outcome.HUMAN_REVIEW, DecisionRule.CONFLICTING_POLICY),
    # The corpus has the policy and cannot place the request in any of its windows.
    ResolutionStatus.TEMPORALLY_UNRESOLVED: (
        Outcome.HUMAN_REVIEW,
        DecisionRule.POLICY_TEMPORALLY_UNRESOLVED,
    ),
    # The submitter can answer this one, so it is a request for information.
    ResolutionStatus.INSUFFICIENT_INFORMATION: (
        Outcome.NEEDS_INFO,
        DecisionRule.RESOLUTION_INSUFFICIENT_INFORMATION,
    ),
    # A wiring or infrastructure fault. Fail toward the human, never toward a denial.
    ResolutionStatus.RESOLUTION_ERROR: (
        Outcome.HUMAN_REVIEW,
        DecisionRule.POLICY_RESOLUTION_ERROR,
    ),
}


def decide(
    criteria: tuple[CriterionOutcome, ...],
    guardrail: GuardrailState,
    resolution: ResolutionState,
    semantics: PolicySemantics,
    *,
    as_of: date | None = None,
    decision_config_version: str = "unset",
) -> Recommendation:
    """Map verdicts to a recommendation. Total: every input yields an outcome.

    `semantics` is REQUIRED and has no default. Before Phase 5 this was
    `logic: PolicyLogic | None = None`, and `None` meant "build a conjunction and
    run it" - so a caller who had never consulted the logic inventory got a silent
    adjudication under a rule shape nobody had established (R-59).

    **The fallback is gone, not defaulted.** Reintroducing it means adding a line
    that manufactures semantics from nothing, which is a visible addition in a
    diff rather than a flipped default. `assumed_conjunction()` still exists and is
    still exported - the inventory loader needs it to build a tree - but what it
    returns is a bare `PolicyLogic`, and a bare `PolicyLogic` is no longer
    something this function accepts.

    Omitting the argument is a `TypeError` at call time, caught by `mypy --strict`
    and by every test. That is a signature error, not a runtime failure on data:
    over the value domain this function remains total and still never raises.
    """
    states = {
        c.criterion_id: leaf_value(c.verdict, has_valid_evidence=c.has_valid_evidence, kind=c.kind)
        for c in criteria
    }
    missing_by_id = {c.criterion_id: c.missing_evidence for c in criteria}

    def result(
        outcome: Outcome, rule: DecisionRule, missing: tuple[str, ...] = ()
    ) -> Recommendation:
        # Every recommendation carries what was known about the policy's logic and
        # on whose authority, so an audit row can distinguish an adjudication made
        # against a reviewed policy from one made against an assumption.
        return Recommendation(
            outcome=outcome,
            rule=rule,
            missing_evidence=missing,
            decision_config_version=decision_config_version,
            policy_semantics=semantics.status,
            semantics_origin=semantics.origin,
        )

    # 1, 2, 14, 15, 16 - what applicability concluded, when it concluded anything
    #     other than "the designated policy governs". Looked up rather than
    #     branched, so that a seventh `ResolutionStatus` cannot be introduced
    #     without deciding where a case carrying it goes; `_ROUTE_FOR_RESOLUTION`
    #     is checked for totality by a test.
    #
    #     This block is FIRST. Every guardrail row, every approval and every denial
    #     is downstream of it, which is what makes "an inapplicable policy cannot
    #     produce a definitive decision" a property of the table rather than a
    #     property of whoever called it (R-93).
    route = _ROUTE_FOR_RESOLUTION.get(resolution.status)
    if route is not None:
        return result(*route)

    # 3 - Any unverifiable citation stops the case. Not a warning, not a lowered
    #     score: no evidence, no decision.
    if guardrail is GuardrailState.INVALID_CITATION:
        return result(Outcome.NO_DECISION, DecisionRule.INVALID_CITATION)

    # 4 - The model path was blocked or failed closed. Fail toward the human.
    if guardrail is GuardrailState.MODEL_PATH_FAILED:
        return result(Outcome.HUMAN_REVIEW, DecisionRule.MODEL_PATH_FAILED)

    # 5 - The system does not adjudicate its own inconsistency.
    if guardrail is GuardrailState.CONTRADICTION:
        return result(Outcome.HUMAN_REVIEW, DecisionRule.CONTRADICTORY_VERDICTS)

    # 5a - The corpus is unqualified for this policy version. A human must read
    #      the regulation before anything here can adjudicate (OD-19). Fires
    #      before any denial AND before any approval: guessing the shape of a rule
    #      is not a safer error than admitting it is unknown.
    if semantics.status is SemanticsStatus.REVIEW_REQUIRED:
        return result(Outcome.HUMAN_REVIEW, DecisionRule.POLICY_SEMANTICS_UNRESOLVED)

    # 5b - The runtime cannot establish that what it holds is verified: nobody
    #      consulted the inventory, the value was demoted by the production guard,
    #      or nothing has been transcribed from this policy at all. A wiring or
    #      corpus-coverage fault rather than an unreviewed regulation - different
    #      cause, different rule, different audit row.
    #
    #      The test is on `logic`, not on the status, because the next line is what
    #      uses `logic`: a guard that checks a different field from the one it
    #      protects can drift away from it.
    if semantics.logic is None:
        return result(Outcome.HUMAN_REVIEW, DecisionRule.POLICY_SEMANTICS_UNVERIFIED)

    policy = semantics.logic
    evaluation = evaluate(policy, states, as_of=as_of)

    # 5c - Out of its temporal window. Version selection is by date of service,
    #      never "latest" (ADR-004), so an out-of-scope policy decides nothing.
    if not evaluation.applicable:
        return result(Outcome.HUMAN_REVIEW, DecisionRule.UNCLASSIFIED)

    # A policy stating no requirements cannot approve anything. 42 CFR 411.15 is
    # exactly this: an exclusion overlay with nothing to satisfy. Vacuous truth
    # would turn every such case into an approval, so it is refused explicitly.
    stated_requirements = bool(_leaf_ids(policy.requirements))

    required_ids = frozenset(c.criterion_id for c in criteria if c.kind is CriterionKind.REQUIRED)
    return _recommend(evaluation, stated_requirements, required_ids, missing_by_id, result)


#: Builds a `Recommendation` with the run's config version already attached.
Emit = Callable[..., Recommendation]


def _recommend(
    evaluation: PolicyEvaluation,
    stated_requirements: bool,
    required_ids: frozenset[str],
    missing_by_id: dict[str, tuple[str, ...]],
    emit: Emit,
) -> Recommendation:
    """Map a policy evaluation to advice for a reviewer.

    The ordering below is the safety property, and it is not the ordering that
    pure logic would give. Kleene FALSE is decisive whatever else is unknown -
    logically, a denial would follow. This system holds the case instead, because
    an unresolved question is a reason to ask, not a reason to refuse.

    The one place an unknown does *not* hold the case is when the policy is
    already satisfied without it. That is the Phase 4 improvement: an alternative
    pathway that succeeds makes the unanswered question moot, and asking for it
    anyway would be delay dressed as diligence.
    """
    # 9/11 - Satisfied. Checked FIRST: if a satisfied pathway exists, remaining
    #        unknowns cannot change the answer and must not delay it.
    if evaluation.truth is PolicyTruth.POLICY_SATISFIED and stated_requirements:
        if evaluation.exclusion_value is Tri.TRUE:
            return emit(Outcome.DENY_RECOMMENDED, DecisionRule.EXCLUSION_SATISFIED)
        # Satisfied *despite* a failed requirement means an alternative pathway
        # carried it. Saying so is not cosmetic: "approved because everything was
        # met" and "approved because the regulation provides another route" are
        # different explanations, and a reviewer auditing a denial-adjacent case
        # needs the second one to be visible rather than inferred.
        rule = (
            DecisionRule.EXCEPTION_SATISFIED
            if set(evaluation.false_criteria) & required_ids
            else DecisionRule.ALL_REQUIRED_SATISFIED
        )
        return emit(Outcome.APPROVE_RECOMMENDED, rule)

    # 6 - An open question on a criterion that still matters. BEFORE any denial.
    if evaluation.unknown_criteria:
        missing = tuple(
            detail
            for cid in evaluation.unknown_criteria
            for detail in (missing_by_id.get(cid) or (cid,))
        )
        return emit(Outcome.NEEDS_INFO, DecisionRule.INSUFFICIENT_EVIDENCE, missing)

    # 7 - An exclusion positively established by valid evidence.
    if evaluation.exclusion_value is Tri.TRUE:
        return emit(Outcome.DENY_RECOMMENDED, DecisionRule.EXCLUSION_SATISFIED)

    # 8 - The policy's conditions are established as not met, with evidence, and
    #     no alternative pathway and no open question remains.
    if evaluation.truth is PolicyTruth.POLICY_NOT_SATISFIED and stated_requirements:
        return emit(Outcome.DENY_RECOMMENDED, DecisionRule.REQUIRED_NOT_SATISFIED)

    # 10 - Totality guard. Reaching it is a defect signal and is counted.
    return emit(Outcome.HUMAN_REVIEW, DecisionRule.UNCLASSIFIED)
