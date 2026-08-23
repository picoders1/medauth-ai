"""The decision table as a truth table. No model, no network, no database.

Gold labels are derived by this function (ADR-015), so an error here corrupts the
evaluation set rather than merely the runtime. That is why it is tested
exhaustively over generated inputs rather than by example.
"""

from __future__ import annotations

import itertools

import pytest

from app.core.types import CriterionKind, ResolutionStatus, Verdict
from app.decision.models import DecisionRule, Outcome
from app.decision.table import CriterionOutcome, GuardrailState, ResolutionState, decide

pytestmark = pytest.mark.unit

RESOLVED = ResolutionState(ResolutionStatus.RESOLVED, version_count=1)
OK = GuardrailState.PASSED


def _c(
    name: str,
    kind: CriterionKind,
    verdict: Verdict,
    *,
    evidence: bool = True,
    missing: tuple[str, ...] = (),
) -> CriterionOutcome:
    return CriterionOutcome(
        name, kind, verdict, has_valid_evidence=evidence, missing_evidence=missing
    )


REQ_OK = _c("r1", CriterionKind.REQUIRED, Verdict.SATISFIED)
REQ_FAIL = _c("r2", CriterionKind.REQUIRED, Verdict.NOT_SATISFIED)
REQ_UNKNOWN = _c("r3", CriterionKind.REQUIRED, Verdict.INSUFFICIENT_EVIDENCE, evidence=False)
EXC_ABSENT = _c("e1", CriterionKind.EXCLUSION, Verdict.NOT_SATISFIED)
EXC_PRESENT = _c("e2", CriterionKind.EXCLUSION, Verdict.SATISFIED)


# ------------------------------------------------------------- row by row
@pytest.mark.parametrize(
    ("criteria", "guardrail", "resolution", "outcome", "rule"),
    [
        (
            (REQ_OK,),
            OK,
            ResolutionState(ResolutionStatus.NONE_APPLICABLE),
            Outcome.NEEDS_INFO,
            DecisionRule.NO_APPLICABLE_POLICY,
        ),
        (
            (REQ_OK,),
            OK,
            ResolutionState(ResolutionStatus.CONFLICTING, 2),
            Outcome.HUMAN_REVIEW,
            DecisionRule.CONFLICTING_POLICY,
        ),
        (
            (REQ_OK,),
            GuardrailState.INVALID_CITATION,
            RESOLVED,
            Outcome.NO_DECISION,
            DecisionRule.INVALID_CITATION,
        ),
        (
            (REQ_OK,),
            GuardrailState.MODEL_PATH_FAILED,
            RESOLVED,
            Outcome.HUMAN_REVIEW,
            DecisionRule.MODEL_PATH_FAILED,
        ),
        (
            (REQ_OK,),
            GuardrailState.CONTRADICTION,
            RESOLVED,
            Outcome.HUMAN_REVIEW,
            DecisionRule.CONTRADICTORY_VERDICTS,
        ),
        (
            (REQ_OK, REQ_UNKNOWN),
            OK,
            RESOLVED,
            Outcome.NEEDS_INFO,
            DecisionRule.INSUFFICIENT_EVIDENCE,
        ),
        (
            (REQ_OK, EXC_PRESENT),
            OK,
            RESOLVED,
            Outcome.DENY_RECOMMENDED,
            DecisionRule.EXCLUSION_SATISFIED,
        ),
        ((REQ_FAIL,), OK, RESOLVED, Outcome.DENY_RECOMMENDED, DecisionRule.REQUIRED_NOT_SATISFIED),
        (
            (REQ_OK, EXC_ABSENT),
            OK,
            RESOLVED,
            Outcome.APPROVE_RECOMMENDED,
            DecisionRule.ALL_REQUIRED_SATISFIED,
        ),
    ],
)
def test_each_row_fires(criteria, guardrail, resolution, outcome, rule) -> None:
    result = decide(criteria, guardrail, resolution)
    assert result.outcome is outcome
    assert result.rule is rule


# --------------------------------------------------- the safety properties
def test_no_applicable_policy_can_never_deny() -> None:
    """Absence of an NCD/LCD means contractor discretion, not non-coverage.

    Asserted over EVERY combination of verdicts and guardrail states, because the
    property must not depend on what the criteria happened to say.
    """
    pool = [REQ_OK, REQ_FAIL, REQ_UNKNOWN, EXC_PRESENT, EXC_ABSENT]
    empty = ResolutionState(ResolutionStatus.NONE_APPLICABLE)

    for size in range(len(pool) + 1):
        for combination in itertools.combinations(pool, size):
            for guardrail in GuardrailState:
                result = decide(combination, guardrail, empty)
                assert result.outcome is not Outcome.DENY_RECOMMENDED, (
                    f"resolution was empty yet the table denied: {combination}, {guardrail}"
                )
                assert result.outcome is Outcome.NEEDS_INFO


def test_missing_evidence_outranks_evidenced_failure() -> None:
    """Row 6 before rows 7 and 8.

    "The note does not say" and "the note says otherwise" are different answers.
    Collapsing them is how automated prior authorization denies people for missing
    paperwork - here it is structurally unreachable.
    """
    result = decide((REQ_UNKNOWN, REQ_FAIL, EXC_PRESENT), OK, RESOLVED)
    assert result.outcome is Outcome.NEEDS_INFO
    assert result.rule is DecisionRule.INSUFFICIENT_EVIDENCE


def test_a_failure_without_evidence_is_not_a_denial() -> None:
    """A verdict of NOT_SATISFIED backed by nothing is missing evidence wearing a
    verdict's clothes."""
    unevidenced = _c("r9", CriterionKind.REQUIRED, Verdict.NOT_SATISFIED, evidence=False)
    result = decide((REQ_OK, unevidenced), OK, RESOLVED)
    assert result.outcome is Outcome.NEEDS_INFO
    assert result.rule is DecisionRule.INSUFFICIENT_EVIDENCE


def test_an_exclusion_without_evidence_does_not_deny() -> None:
    unevidenced = _c("e9", CriterionKind.EXCLUSION, Verdict.SATISFIED, evidence=False)
    assert decide((REQ_OK, unevidenced), OK, RESOLVED).outcome is Outcome.APPROVE_RECOMMENDED


def test_an_invalid_citation_stops_the_case_whatever_the_verdicts() -> None:
    pool = [REQ_OK, REQ_FAIL, REQ_UNKNOWN, EXC_PRESENT]
    for size in range(len(pool) + 1):
        for combination in itertools.combinations(pool, size):
            result = decide(combination, GuardrailState.INVALID_CITATION, RESOLVED)
            assert result.outcome is Outcome.NO_DECISION


def test_informational_criteria_never_change_the_outcome() -> None:
    info = _c("i1", CriterionKind.INFORMATIONAL, Verdict.NOT_SATISFIED)
    assert decide((REQ_OK,), OK, RESOLVED).outcome is decide((REQ_OK, info), OK, RESOLVED).outcome


# --------------------------------------------------------------- totality
def test_decide_is_total_over_generated_inputs() -> None:
    """Every reachable combination yields an outcome; nothing raises."""
    kinds = list(CriterionKind)
    verdicts = list(Verdict)
    seen_rules: set[DecisionRule] = set()

    for kind, verdict, evidence in itertools.product(kinds, verdicts, [True, False]):
        for guardrail in GuardrailState:
            for status in ResolutionStatus:
                result = decide(
                    (_c("x", kind, verdict, evidence=evidence),),
                    guardrail,
                    ResolutionState(status, 1),
                )
                assert isinstance(result.outcome, Outcome)
                seen_rules.add(result.rule)

    # The generated space must actually exercise the interesting rows, or this
    # test would pass while covering nothing.
    for required in (
        DecisionRule.NO_APPLICABLE_POLICY,
        DecisionRule.CONFLICTING_POLICY,
        DecisionRule.INVALID_CITATION,
        DecisionRule.INSUFFICIENT_EVIDENCE,
        DecisionRule.EXCLUSION_SATISFIED,
        DecisionRule.REQUIRED_NOT_SATISFIED,
        DecisionRule.ALL_REQUIRED_SATISFIED,
    ):
        assert required in seen_rules, f"{required.name} was never reached"


def test_missing_evidence_detail_reaches_the_recommendation() -> None:
    """A NEEDS_INFO that does not say what is missing is not actionable."""
    result = decide(
        (
            _c(
                "r5",
                CriterionKind.REQUIRED,
                Verdict.INSUFFICIENT_EVIDENCE,
                evidence=False,
                missing=("conservative therapy duration",),
            ),
        ),
        OK,
        RESOLVED,
    )
    assert result.missing_evidence == ("conservative therapy duration",)
