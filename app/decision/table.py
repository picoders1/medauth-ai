"""The decision table: per-criterion verdicts in, a recommendation out.

Pure. No I/O, no clock, no randomness, no model. `app.decision` may import only
`app.core`, and a test asserts it, so this stays exhaustively testable as a truth
table with nothing loaded (ADR-010).

**Built during the data-foundation phase, deliberately.** ADR-015 requires that a
gold case's label be computed by *the same* function the system will use - a
separate labelling implementation would drift from the production one, and the
evaluation would then measure the difference between two pieces of code rather
than the behaviour of one. So the table lands with the dataset that depends on it.

What is **not** here: the abstention gate. It reads calibrated thresholds that do
not exist until Phase 6 selects them on the dev split, and inventing one now would
be a fabricated threshold with clinical consequences (ADR-011).

Row order is the safety design. Rows 1-6 are all evaluated before any denial is
reachable, and row 6 (missing evidence) precedes rows 7 and 8 (evidenced failure).
That is the difference between "the note does not say" and "the note says
otherwise", and collapsing it is how automated prior authorization denies people
for missing paperwork.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from app.core.types import CriterionKind, ResolutionStatus, Verdict
from app.decision.models import DecisionRule, Outcome, Recommendation

__all__ = ["CriterionOutcome", "GuardrailState", "ResolutionState", "decide"]


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


def decide(
    criteria: tuple[CriterionOutcome, ...],
    guardrail: GuardrailState,
    resolution: ResolutionState,
    *,
    decision_config_version: str = "unset",
) -> Recommendation:
    """Map verdicts to a recommendation. Total: every input yields an outcome."""
    required = [c for c in criteria if c.kind is CriterionKind.REQUIRED]
    exclusions = [c for c in criteria if c.kind is CriterionKind.EXCLUSION]

    def result(
        outcome: Outcome, rule: DecisionRule, missing: tuple[str, ...] = ()
    ) -> Recommendation:
        return Recommendation(
            outcome=outcome,
            rule=rule,
            missing_evidence=missing,
            decision_config_version=decision_config_version,
        )

    # 1 - No applicable policy. Absence of an NCD/LCD generally means contractor
    #     discretion, not non-coverage. This must never be a denial.
    if resolution.status is ResolutionStatus.NONE_APPLICABLE:
        return result(Outcome.NEEDS_INFO, DecisionRule.NO_APPLICABLE_POLICY)

    # 2 - Conflicting policies. Which governs is a human judgement.
    if resolution.status is ResolutionStatus.CONFLICTING:
        return result(Outcome.HUMAN_REVIEW, DecisionRule.CONFLICTING_POLICY)

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

    # 6 - Missing evidence on a required criterion. BEFORE any denial row.
    undecided = [c for c in required if c.verdict is Verdict.INSUFFICIENT_EVIDENCE]
    if undecided:
        missing = tuple(
            detail
            for criterion in undecided
            for detail in (criterion.missing_evidence or (criterion.criterion_id,))
        )
        return result(Outcome.NEEDS_INFO, DecisionRule.INSUFFICIENT_EVIDENCE, missing)

    # 7 - An exclusion positively established by valid evidence.
    if any(c.verdict is Verdict.SATISFIED and c.has_valid_evidence for c in exclusions):
        return result(Outcome.DENY_RECOMMENDED, DecisionRule.EXCLUSION_SATISFIED)

    # 8 - A required criterion positively established as NOT met, with evidence.
    #     Without evidence this is row 6, not a denial.
    evidenced_failure = [
        c for c in required if c.verdict is Verdict.NOT_SATISFIED and c.has_valid_evidence
    ]
    if evidenced_failure:
        return result(Outcome.DENY_RECOMMENDED, DecisionRule.REQUIRED_NOT_SATISFIED)

    unevidenced_failure = [
        c for c in required if c.verdict is Verdict.NOT_SATISFIED and not c.has_valid_evidence
    ]
    if unevidenced_failure:
        return result(
            Outcome.NEEDS_INFO,
            DecisionRule.INSUFFICIENT_EVIDENCE,
            tuple(c.criterion_id for c in unevidenced_failure),
        )

    # 9 - Everything required is satisfied and nothing excludes.
    if required and all(c.verdict in (Verdict.SATISFIED, Verdict.NOT_APPLICABLE) for c in required):
        return result(Outcome.APPROVE_RECOMMENDED, DecisionRule.ALL_REQUIRED_SATISFIED)

    # 10 - Totality guard. Reaching it is a defect signal and is counted.
    return result(Outcome.HUMAN_REVIEW, DecisionRule.UNCLASSIFIED)
