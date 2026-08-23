"""Coverage status is recorded with evidence, or it is UNKNOWN.

The failure this file exists to prevent: a status that reads as a coverage
conclusion while resting on a title, a code link, a similarity score or a model's
paraphrase. Every one of those is an unreviewed inference, and a coverage
conclusion is the last place one should be allowed to hide.
"""

from __future__ import annotations

from datetime import date

import pytest

from app.coverage.resolve import CoverageStatus
from app.coverage.status import (
    CoverageEvidence,
    StatusOrigin,
    StatusReviewState,
    determination_status,
)

pytestmark = pytest.mark.unit

QUOTE = "is not covered"
SECTION = "Indications and Limitations of Coverage"
TEXT = f"The service {QUOTE} for this indication."
EVIDENCE = (
    CoverageEvidence(
        section_path=SECTION,
        quote=QUOTE,
        span_start=TEXT.index(QUOTE),
        span_end=TEXT.index(QUOTE) + len(QUOTE),
    ),
)


def _status(**kwargs: object):  # type: ignore[no-untyped-def]
    base = {
        "policy_id": "NCD 310.1",
        "policy_version": "3",
        "status": CoverageStatus.NOT_COVERED,
        "origin": StatusOrigin.SOURCE_STATED,
        "evidence": EVIDENCE,
    }
    return determination_status(**{**base, **kwargs})  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# Authority
# ---------------------------------------------------------------------------


def test_only_the_source_stating_it_is_authoritative() -> None:
    """A reviewer confirms a reading of the source; they do not become the source."""
    assert StatusOrigin.SOURCE_STATED.is_authoritative
    assert not StatusOrigin.HUMAN_REVIEWED.is_authoritative
    assert not StatusOrigin.ENGINEERING_DERIVED.is_authoritative
    assert not StatusOrigin.UNKNOWN.is_authoritative


def test_an_engineering_reading_can_never_be_a_coverage_conclusion() -> None:
    """`ENGINEERING_DERIVED` exists to seed a review queue, not to answer.

    Admitting it would let an engineer's reading of clinical coverage prose become
    the system's answer - which is the same defect as inferring policy semantics,
    applied to the coverage layer.
    """
    assert not StatusOrigin.ENGINEERING_DERIVED.admissible_for_coverage
    record = _status(origin=StatusOrigin.ENGINEERING_DERIVED)
    assert record.establishes is CoverageStatus.UNKNOWN
    # The candidate is preserved - a reviewer will look at it - but it is not what
    # the system reports.
    assert record.status is CoverageStatus.NOT_COVERED


def test_an_unverified_human_judgement_reports_unknown() -> None:
    """A judgement in the queue is not yet a judgement the system acts on."""
    record = _status(
        origin=StatusOrigin.HUMAN_REVIEWED,
        reviewer_id="reviewer-1",
        reviewer_rationale="the text states non-coverage for this indication",
        review_state=StatusReviewState.PENDING,
    )
    assert record.status is CoverageStatus.NOT_COVERED
    assert record.establishes is CoverageStatus.UNKNOWN


def test_a_verified_human_judgement_is_reported_and_is_still_not_authoritative() -> None:
    """The positive control, and the distinction it preserves."""
    record = _status(
        origin=StatusOrigin.HUMAN_REVIEWED,
        reviewer_id="reviewer-1",
        reviewer_rationale="the text states non-coverage for this indication",
        review_state=StatusReviewState.VERIFIED,
        reviewed_at=date(2026, 8, 23),
    )
    assert record.establishes is CoverageStatus.NOT_COVERED
    assert not record.is_authoritative


def test_a_source_stated_status_is_reported_without_a_review_step() -> None:
    """The source speaking for itself needs no confirmation to be reported."""
    record = _status()
    assert record.is_authoritative
    assert record.establishes is CoverageStatus.NOT_COVERED


# ---------------------------------------------------------------------------
# Evidence
# ---------------------------------------------------------------------------


def test_a_substantive_status_without_evidence_is_demoted() -> None:
    """A coverage conclusion must point at the text that supports it."""
    for status in (
        CoverageStatus.COVERED,
        CoverageStatus.NOT_COVERED,
        CoverageStatus.CONDITIONAL,
    ):
        record = _status(status=status, evidence=(), origin=StatusOrigin.HUMAN_REVIEWED)
        assert record.status is CoverageStatus.UNKNOWN, status
        assert record.origin is StatusOrigin.UNKNOWN
        assert any("no located evidence" in note for note in record.notes)


def test_source_stated_without_a_quote_is_demoted() -> None:
    """The strongest claim on the weakest basis.

    Saying the source states something while pointing at nothing is worse than
    saying nothing, because it reads as authoritative.
    """
    record = _status(status=CoverageStatus.NOT_ESTABLISHED, evidence=())
    assert record.origin is StatusOrigin.UNKNOWN
    assert any("no quoted span" in note for note in record.notes)


def test_a_human_review_without_a_signature_is_demoted() -> None:
    """An unsigned judgement with no reasoning is not a review."""
    record = _status(origin=StatusOrigin.HUMAN_REVIEWED, reviewer_id=None)
    assert record.origin is StatusOrigin.UNKNOWN
    assert any("unsigned judgement" in note for note in record.notes)


def test_evidence_must_locate_in_the_text_it_names() -> None:
    """The same span contract the criteria transcriptions live under (ADR-009).

    A status whose evidence cannot be found where it says it is is not evidence,
    it is a summary.
    """
    assert EVIDENCE[0].locates_in(TEXT)
    moved = CoverageEvidence(section_path=SECTION, quote=QUOTE, span_start=0, span_end=len(QUOTE))
    assert not moved.locates_in(TEXT)


def test_empty_or_inverted_evidence_is_refused_at_construction() -> None:
    with pytest.raises(ValueError, match="empty quote"):
        CoverageEvidence(section_path=SECTION, quote="  ", span_start=0, span_end=3)
    with pytest.raises(ValueError, match="span"):
        CoverageEvidence(section_path=SECTION, quote="x", span_start=5, span_end=5)


# ---------------------------------------------------------------------------
# What is never inferred
# ---------------------------------------------------------------------------


def test_no_status_is_derivable_from_metadata_alone() -> None:
    """There is no constructor that takes a title, a code or a similarity score.

    Stated as a test because the absence of an API is easy to erode: the moment
    something accepts a title and returns a status, the inference has been made.
    """
    import inspect

    parameters = set(inspect.signature(determination_status).parameters)
    forbidden = {"title", "code", "similarity", "model_output", "description"}
    assert not parameters & forbidden, (
        f"determination_status accepts {sorted(parameters & forbidden)}; a coverage "
        "status must not be derivable from metadata"
    )
    assert {"status", "origin", "evidence"} <= parameters
