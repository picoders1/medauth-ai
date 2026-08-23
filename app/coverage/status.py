"""What a coverage determination establishes, and on whose authority.

Phase 5 built coverage *resolution* - which determination version governs a date of
service - and deliberately stopped there. Every governing NCD resolved to `UNKNOWN`,
because nothing recorded what any determination actually establishes. That was safe
and it was empty (OD-26, R-61).

This module is how a status comes to exist without being invented. It does **not**
derive a status from anything: not the title, not procedure similarity, not code
linkage, not semantic similarity, not the absence of language, and not a model's
reading of the prose. Every one of those would be an unreviewed inference presented
as a coverage conclusion, which is the failure this whole project is built around
refusing.

A status exists only when something says so, and the record says which something:

    SOURCE_STATED        the determination's own text states it, quoted and located
    HUMAN_REVIEWED       a qualified reviewer read it and recorded a judgement
    ENGINEERING_DERIVED  an engineer's reading. NOT authoritative, and NOT
                         admissible for production coverage conclusions
    UNKNOWN              nobody has said anything

**Only `SOURCE_STATED` is authoritative.** `HUMAN_REVIEWED` is admissible and not
authoritative - a reviewer confirms a reading of the source; they do not become the
source. That distinction is the same one `LinkProvenance` draws for code linkage,
and for the same reason.

Pure: no I/O, no clock, no model. Evidence arrives already extracted.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from enum import StrEnum

from app.coverage.resolve import CoverageStatus

__all__ = [
    "CoverageDetermination",
    "CoverageEvidence",
    "StatusOrigin",
    "StatusReviewState",
    "determination_status",
]


class StatusOrigin(StrEnum):
    """Who says this determination establishes what it establishes."""

    #: The determination's own text states it. Requires a quoted span and a
    #: location within the document. Authoritative.
    SOURCE_STATED = "SOURCE_STATED"

    #: A qualified reviewer read the determination and recorded a judgement.
    #: Admissible, and **not** authoritative - reviewing a reading does not make
    #: the reviewer the source.
    HUMAN_REVIEWED = "HUMAN_REVIEWED"

    #: An engineer's reading. Recorded so a candidate can be prepared for review,
    #: and **never** admissible as a production coverage conclusion.
    ENGINEERING_DERIVED = "ENGINEERING_DERIVED"

    #: Nobody has said anything. The default, and the reason the default is safe.
    UNKNOWN = "UNKNOWN"

    @property
    def is_authoritative(self) -> bool:
        return self is StatusOrigin.SOURCE_STATED

    @property
    def admissible_for_coverage(self) -> bool:
        """Whether a status of this origin may be reported as what a policy establishes.

        `ENGINEERING_DERIVED` is excluded: it exists to seed a review queue, not to
        answer a coverage question. Admitting it would let an engineer's reading of
        clinical coverage prose become the system's answer.
        """
        return self in (StatusOrigin.SOURCE_STATED, StatusOrigin.HUMAN_REVIEWED)


class StatusReviewState(StrEnum):
    """Where a candidate status sits in the review workflow.

    `VERIFIED` is reachable only by a person. Nothing in this module sets it, and a
    test asserts that no committed record carries it while the queue is unworked.
    """

    PENDING = "PENDING"
    IN_REVIEW = "IN_REVIEW"
    VERIFIED = "VERIFIED"
    REJECTED = "REJECTED"
    INTERPRETATION_REQUIRED = "INTERPRETATION_REQUIRED"


@dataclass(frozen=True, slots=True)
class CoverageEvidence:
    """A span of the determination that supports a status claim.

    `quote` must be a substring of the section it names - the same span-verification
    contract the criteria transcriptions live under (ADR-009). A status whose
    evidence cannot be located in the document is not evidence, it is a summary.
    """

    section_path: str
    quote: str
    #: Character offsets into that section's text, so a reviewer can find it.
    span_start: int
    span_end: int

    def __post_init__(self) -> None:
        if not self.quote.strip():
            raise ValueError("coverage evidence with an empty quote")
        if self.span_end <= self.span_start:
            raise ValueError(f"coverage evidence span {self.span_start}:{self.span_end} is empty")

    def locates_in(self, section_text: str) -> bool:
        """Whether the quote is genuinely where the record says it is."""
        return section_text[self.span_start : self.span_end] == self.quote


@dataclass(frozen=True, slots=True)
class CoverageDetermination:
    """A recorded claim about what one NCD version establishes.

    Construct through `determination_status()`, which enforces the rule that an
    authoritative or admissible status must carry the evidence for it.
    """

    policy_id: str
    policy_version: str
    status: CoverageStatus
    origin: StatusOrigin
    evidence: tuple[CoverageEvidence, ...] = ()
    review_state: StatusReviewState = StatusReviewState.PENDING
    reviewer_id: str | None = None
    reviewer_rationale: str | None = None
    reviewed_at: date | None = None
    notes: tuple[str, ...] = field(default_factory=tuple)

    @property
    def is_authoritative(self) -> bool:
        return self.origin.is_authoritative

    @property
    def establishes(self) -> CoverageStatus:
        """The status this record may be reported as establishing.

        An inadmissible origin, or an unverified human judgement, reports `UNKNOWN`
        rather than its own status. The candidate is preserved on the record - it is
        what a reviewer will look at - but it is not what the system says.
        """
        if not self.origin.admissible_for_coverage:
            return CoverageStatus.UNKNOWN
        if (
            self.origin is StatusOrigin.HUMAN_REVIEWED
            and self.review_state is not StatusReviewState.VERIFIED
        ):
            return CoverageStatus.UNKNOWN
        return self.status


def determination_status(
    *,
    policy_id: str,
    policy_version: str,
    status: CoverageStatus,
    origin: StatusOrigin,
    evidence: tuple[CoverageEvidence, ...] = (),
    review_state: StatusReviewState = StatusReviewState.PENDING,
    reviewer_id: str | None = None,
    reviewer_rationale: str | None = None,
    reviewed_at: date | None = None,
    notes: tuple[str, ...] = (),
) -> CoverageDetermination:
    """Build a determination record, demoting any claim its evidence cannot support.

    Three demotions, each to `UNKNOWN` with the reason recorded, and each chosen so
    that the *type* cannot hold an unsupported claim rather than relying on a check
    somebody might skip:

    1. **A substantive status with no evidence.** `COVERED`, `NOT_COVERED` and
       `CONDITIONAL` are claims about what a document says; without a located quote
       there is nothing to check them against.
    2. **`SOURCE_STATED` with no evidence.** Claiming the source states something
       while pointing at nothing is the strongest available claim on the weakest
       available basis.
    3. **`HUMAN_REVIEWED` with no reviewer.** A judgement nobody signed is not a
       reviewed judgement.

    Demotion rather than a raise, for the same reason as `PolicySemantics`: a
    malformed record routes a case to a human instead of raising inside a decision
    path.
    """
    problems: list[str] = []
    substantive = status in (
        CoverageStatus.COVERED,
        CoverageStatus.NOT_COVERED,
        CoverageStatus.CONDITIONAL,
    )

    if substantive and not evidence:
        problems.append(
            f"{status.value} claimed with no located evidence; a coverage conclusion "
            "must point at the text that supports it"
        )
    if origin is StatusOrigin.SOURCE_STATED and not evidence:
        problems.append("SOURCE_STATED claimed with no quoted span from the source")
    if origin is StatusOrigin.HUMAN_REVIEWED and not (reviewer_id and reviewer_rationale):
        problems.append(
            "HUMAN_REVIEWED claimed with no reviewer identity and rationale; an "
            "unsigned judgement is not a reviewed one"
        )

    if problems:
        return CoverageDetermination(
            policy_id=policy_id,
            policy_version=policy_version,
            status=CoverageStatus.UNKNOWN,
            origin=StatusOrigin.UNKNOWN,
            evidence=evidence,
            review_state=review_state,
            notes=(*notes, *problems),
        )

    return CoverageDetermination(
        policy_id=policy_id,
        policy_version=policy_version,
        status=status,
        origin=origin,
        evidence=evidence,
        review_state=review_state,
        reviewer_id=reviewer_id,
        reviewer_rationale=reviewer_rationale,
        reviewed_at=reviewed_at,
        notes=notes,
    )
