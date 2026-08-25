"""Contradiction detection, and the line it must not cross.

R-89 was that decision-table row 5 existed and nothing could reach it. Closing that
creates the opposite risk: a detector that fires on ordinary cases gets switched off,
and a detector that infers clinical content is adjudicating the adjudicator.

So these tests come in two halves. Half prove it catches real conflicts. Half prove
it stays quiet on things that look like conflicts and are not — and that half is the
one that keeps the check alive.
"""

from __future__ import annotations

import pytest

from app.contracts.slice import AssessmentState, ClinicalFact, CriterionAssessment
from app.decision.table import GuardrailState
from app.guardrail.contradiction import (
    ContradictionFinding,
    ContradictionReport,
    ContradictionState,
    analyse_contradictions,
    guardrail_state_for,
)

pytestmark = [pytest.mark.unit, pytest.mark.security]

C01 = "42_CFR_410_33_2026_08_13_C01"
C02 = "42_CFR_410_33_2026_08_13_C02"
C05 = "42_CFR_410_33_2026_08_13_C05"


def assess(
    criterion_id: str,
    state: AssessmentState,
    evidence: tuple[str, ...] = ("E1",),
) -> CriterionAssessment:
    return CriterionAssessment(
        criterion_id=criterion_id,
        assessment=state,
        evidence_ids=evidence if state is not AssessmentState.UNKNOWN else (),
        rationale_summary="fixture",
    )


def fact(fact_id: str, kind: str, value: str, start: int, end: int) -> ClinicalFact:
    return ClinicalFact(
        fact_id=fact_id,
        kind=kind,
        value=value,
        span_start=start,
        span_end=end,
        extraction_prompt_id="intake.v2",
    )


# ---------------------------------------------------------------------------
# 1. Explicit contradiction
# ---------------------------------------------------------------------------


def test_two_criteria_on_the_same_chunk_reaching_opposite_verdicts() -> None:
    """One passage cannot both establish and refute."""
    report = analyse_contradictions(
        (
            assess(C01, AssessmentState.SATISFIED),
            assess(C02, AssessmentState.NOT_SATISFIED),
        ),
        cited_chunks={C01: frozenset({"chunk-d"}), C02: frozenset({"chunk-d"})},
    )
    assert report.state is ContradictionState.CONTRADICTION
    assert report.is_decisive
    finding = report.findings[0]
    assert finding.kind == "SAME_EVIDENCE_OPPOSITE_VERDICTS"
    assert set(finding.criterion_ids) == {C01, C02}
    assert finding.evidence_ids == ("chunk-d",)
    assert set(finding.conflicting_values) == {"SATISFIED", "NOT_SATISFIED"}


def test_the_same_criterion_assessed_twice_differently() -> None:
    """Should be impossible, which is why it is checked. Left undetected it would
    silently keep whichever verdict happened to be last."""
    report = analyse_contradictions(
        (
            assess(C01, AssessmentState.SATISFIED),
            assess(C01, AssessmentState.NOT_SATISFIED),
        ),
        cited_chunks={C01: frozenset({"chunk-d"})},
    )
    assert report.state is ContradictionState.CONTRADICTION
    # Both detectors fire here, and correctly: the same criterion assessed twice is
    # also two opposite verdicts on the same chunk. Asserted as membership rather
    # than position - ordering findings would be testing the loop, not the rule.
    assert "DUPLICATE_CRITERION_DISAGREEMENT" in {f.kind for f in report.findings}


def test_conflicting_facts_from_the_same_span() -> None:
    """The same words cannot carry two readings."""
    report = analyse_contradictions(
        (assess(C01, AssessmentState.SATISFIED), assess(C02, AssessmentState.SATISFIED)),
        facts=(
            fact("F1", "DOCUMENTATION", "written order on file", 0, 20),
            fact("F2", "DOCUMENTATION", "no written order on file", 0, 20),
        ),
        cited_chunks={C01: frozenset({"a"}), C02: frozenset({"b"})},
    )
    assert report.state is ContradictionState.CONTRADICTION
    finding = next(f for f in report.findings if f.kind == "SAME_SPAN_DIFFERENT_VALUES")
    assert set(finding.fact_ids) == {"F1", "F2"}
    assert len(finding.conflicting_values) == 2


# ---------------------------------------------------------------------------
# 2. No contradiction — the half that keeps the check usable
# ---------------------------------------------------------------------------


def test_criteria_citing_different_chunks_do_not_conflict() -> None:
    """Opposite verdicts on DIFFERENT passages are ordinary adjudication.

    A requirement met and an exclusion unmet is the shape of an approvable case.
    Flagging it would fire on almost everything.
    """
    report = analyse_contradictions(
        (
            assess(C01, AssessmentState.SATISFIED),
            assess(C05, AssessmentState.NOT_SATISFIED),
        ),
        cited_chunks={C01: frozenset({"chunk-d"}), C05: frozenset({"chunk-b"})},
    )
    assert report.state is ContradictionState.NO_CONTRADICTION
    assert not report.is_decisive


def test_criteria_sharing_one_chunk_among_several_do_not_conflict() -> None:
    """Overlap is not identity. Two criteria legitimately share a passage while
    testing different things, and only an identical source set is a conflict."""
    report = analyse_contradictions(
        (
            assess(C01, AssessmentState.SATISFIED),
            assess(C02, AssessmentState.NOT_SATISFIED),
        ),
        cited_chunks={
            C01: frozenset({"chunk-d", "chunk-x"}),
            C02: frozenset({"chunk-d", "chunk-y"}),
        },
    )
    assert report.state is ContradictionState.NO_CONTRADICTION


def test_semantically_similar_but_non_conflicting_values_are_not_flagged() -> None:
    """Different spans may legitimately differ.

    A note can record a verbal order in one sentence and a written one in another;
    that is a sequence, not a contradiction. **Judging whether the two conflict
    requires reading, and reading is exactly what this layer refuses to do** - a
    detector that inferred clinical meaning would be adjudicating the adjudicator.
    """
    report = analyse_contradictions(
        (assess(C01, AssessmentState.SATISFIED), assess(C02, AssessmentState.SATISFIED)),
        facts=(
            fact("F1", "DOCUMENTATION", "verbal order taken", 0, 18),
            fact("F2", "DOCUMENTATION", "written order received", 30, 52),
        ),
        cited_chunks={C01: frozenset({"a"}), C02: frozenset({"b"})},
    )
    assert report.state is ContradictionState.NO_CONTRADICTION


def test_identical_facts_from_the_same_span_are_not_a_conflict() -> None:
    """Duplicate extraction is noise, not disagreement."""
    report = analyse_contradictions(
        (assess(C01, AssessmentState.SATISFIED), assess(C02, AssessmentState.SATISFIED)),
        facts=(
            fact("F1", "DOCUMENTATION", "written order", 0, 13),
            fact("F2", "DOCUMENTATION", "written order", 0, 13),
        ),
        cited_chunks={C01: frozenset({"a"}), C02: frozenset({"b"})},
    )
    assert report.state is ContradictionState.NO_CONTRADICTION


def test_conflicting_documentation_dates_on_the_same_span_are_caught() -> None:
    report = analyse_contradictions(
        (assess(C01, AssessmentState.SATISFIED), assess(C02, AssessmentState.SATISFIED)),
        facts=(
            fact("F1", "TEMPORAL", "order dated 2026-09-01", 10, 32),
            fact("F2", "TEMPORAL", "order dated 2026-09-14", 10, 32),
        ),
        cited_chunks={C01: frozenset({"a"}), C02: frozenset({"b"})},
    )
    assert report.state is ContradictionState.CONTRADICTION


def test_conflicting_clinical_findings_on_different_spans_are_not_inferred() -> None:
    """Two findings in different sentences are two findings.

    Recorded as a KNOWN LIMITATION rather than a gap being hidden: semantic conflict
    across spans is real and this layer does not detect it. Saying otherwise would be
    the overclaim.
    """
    report = analyse_contradictions(
        (assess(C01, AssessmentState.SATISFIED), assess(C02, AssessmentState.SATISFIED)),
        facts=(
            fact("F1", "FINDING", "supervisor covers two sites", 0, 27),
            fact("F2", "FINDING", "supervisor covers five sites", 40, 68),
        ),
        cited_chunks={C01: frozenset({"a"}), C02: frozenset({"b"})},
    )
    assert report.state is ContradictionState.NO_CONTRADICTION


# ---------------------------------------------------------------------------
# 3. Incomplete evidence stays non-decisive
# ---------------------------------------------------------------------------


def test_too_little_evidence_is_undetermined_not_clean() -> None:
    """ "Could not check" and "checked and clean" send a reviewer to different places.

    A case where nothing was decided has not been cleared of contradictions, and
    reporting `NO_CONTRADICTION` would claim a check that never ran.
    """
    report = analyse_contradictions((assess(C01, AssessmentState.UNKNOWN),))
    assert report.state is ContradictionState.UNDETERMINED
    assert not report.is_decisive
    assert any("did not run" in note for note in report.notes)


def test_undetermined_never_stops_a_case() -> None:
    """Non-decisive means non-decisive in both directions."""
    for state in ContradictionState:
        report = ContradictionReport(
            state=state,
            findings=(
                (ContradictionFinding(kind="K", reason="r", criterion_ids=(C01,)),)
                if state is ContradictionState.CONTRADICTION
                else ()
            ),
        )
        assert report.is_decisive is (state is ContradictionState.CONTRADICTION)


# ---------------------------------------------------------------------------
# 4. A finding must be checkable
# ---------------------------------------------------------------------------


def test_a_contradiction_with_no_finding_is_refused() -> None:
    """It would route a case to a human with nothing to read."""
    with pytest.raises(ValueError, match="no findings"):
        ContradictionReport(state=ContradictionState.CONTRADICTION)


def test_a_finding_reported_without_changing_the_state_is_refused() -> None:
    """A conflict recorded and ignored is worse than one not found."""
    with pytest.raises(ValueError, match="does not change the state"):
        ContradictionReport(
            state=ContradictionState.NO_CONTRADICTION,
            findings=(ContradictionFinding(kind="K", reason="r", criterion_ids=(C01,)),),
        )


def test_a_finding_must_name_a_reason_and_a_criterion() -> None:
    with pytest.raises(ValueError, match="no reason"):
        ContradictionFinding(kind="K", reason="  ", criterion_ids=(C01,))
    with pytest.raises(ValueError, match="not locatable"):
        ContradictionFinding(kind="K", reason="r", criterion_ids=())


def test_the_audit_payload_carries_ids_and_no_clinical_text() -> None:
    report = analyse_contradictions(
        (
            assess(C01, AssessmentState.SATISFIED),
            assess(C02, AssessmentState.NOT_SATISFIED),
        ),
        cited_chunks={C01: frozenset({"chunk-d"}), C02: frozenset({"chunk-d"})},
    )
    payload = report.audit_payload
    assert payload["contradiction_state"] == "CONTRADICTION"
    assert payload["evidence_ids"] == ["chunk-d"]
    assert "conflicting_values" not in payload


# ---------------------------------------------------------------------------
# 5. The mapping onto the decision table
# ---------------------------------------------------------------------------


def test_only_a_contradiction_reaches_decision_table_row_5() -> None:
    """R-89's actual claim, tested where it can be seen.

    Row 5 existed through Phases 11 and 12 and nothing could reach it. This is the
    one function that can, so it is tested directly rather than through the slice -
    an inline ternary buried in a long argument list proved hard to show sensitive
    to mutation, which is a good reason not to leave a rule there.
    """
    contradiction = ContradictionReport(
        state=ContradictionState.CONTRADICTION,
        findings=(ContradictionFinding(kind="K", reason="r", criterion_ids=(C01,)),),
    )
    assert guardrail_state_for(contradiction) is GuardrailState.CONTRADICTION

    for state in (ContradictionState.NO_CONTRADICTION, ContradictionState.UNDETERMINED):
        assert guardrail_state_for(ContradictionReport(state=state)) is GuardrailState.PASSED


def test_undetermined_does_not_reach_row_5() -> None:
    """ "Could not check" must not stop a case, and must not clear one either.

    It maps to PASSED because there is no table row for an unknown, and inventing
    one to hold an unknown is how an unknown becomes a verdict. The report still
    carries UNDETERMINED where a reviewer reads it.
    """
    report = ContradictionReport(state=ContradictionState.UNDETERMINED)
    assert guardrail_state_for(report) is GuardrailState.PASSED
    assert not report.is_decisive
    assert report.state is not ContradictionState.NO_CONTRADICTION
