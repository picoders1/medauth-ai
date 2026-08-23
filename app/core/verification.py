"""What has been established about a criterion, and by whom.

Three claims are routinely collapsed into one word - "verified" - and collapsing
them is how an engineering artefact comes to look like a clinical one:

    SOURCE_VERIFIED     the text is genuinely in the regulation, at the location
                        claimed, in the version claimed. An ENGINEERING fact,
                        established mechanically by span verification.

    QUALIFIED_REVIEWED  a person qualified to read coverage regulation has read it
                        and agreed it is the right criterion, correctly stated.
                        A HUMAN judgement, and no amount of engineering produces it.

    CLINICAL_VALIDATION whether adjudicating cases this way produces clinically
                        correct outcomes. **Not represented here at all**, because
                        nothing in this project is close to establishing it and a
                        member for it would invite someone to set it.

Span verification proves the first and says nothing about the second. Phase 7
transcribed 42 CFR 410.32(b)(3) from the authoritative source and that is
`SOURCE_VERIFIED`; whether the criterion drawn from it is the right one, and
whether it makes C03 adjudicable, is `QUALIFIED_REVIEW_PENDING` and stays that way
until a reviewer says otherwise.

Pure: `app.core` imports nothing from `app`.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from enum import StrEnum

__all__ = [
    "DependencyResolution",
    "QualifiedReviewStatus",
    "SourceVerification",
    "VerificationRecord",
]


class SourceVerification(StrEnum):
    """Whether the text is where it claims to be. Established mechanically."""

    #: `normalize(quote)` is a substring of `normalize(section.text)`, in the named
    #: section, of the named version.
    SOURCE_VERIFIED = "SOURCE_VERIFIED"

    #: The gate ran and refused - wrong text, wrong section, or wrong version.
    SOURCE_VERIFICATION_FAILED = "SOURCE_VERIFICATION_FAILED"

    #: The gate has not run against this item.
    NOT_VERIFIED = "NOT_VERIFIED"


class QualifiedReviewStatus(StrEnum):
    """Whether a qualified reader has agreed. **Never set by engineering.**

    The default is `QUALIFIED_REVIEW_PENDING` and there is no code path that
    advances it. That is deliberate: the moment a pipeline can mark its own output
    reviewed, "reviewed" stops meaning anything.
    """

    QUALIFIED_REVIEW_PENDING = "QUALIFIED_REVIEW_PENDING"
    QUALIFIED_REVIEWED = "QUALIFIED_REVIEWED"
    QUALIFIED_REVIEW_REJECTED = "QUALIFIED_REVIEW_REJECTED"
    #: The reviewer read it and could not settle it from the text alone.
    QUALIFIED_REVIEW_INCONCLUSIVE = "QUALIFIED_REVIEW_INCONCLUSIVE"


class DependencyResolution(StrEnum):
    """Whether a criterion's dependency on another provision has been closed."""

    #: The provision is transcribed AND a reviewer has confirmed the criterion is
    #: adjudicable with it. Both halves are required.
    RESOLVED = "RESOLVED"

    #: The provision is now transcribed and span-verified, and whether that makes
    #: the dependent criterion adjudicable is a reading question nobody has ruled
    #: on. **Transcription alone does not resolve a dependency.**
    SOURCE_VERIFIED_REVIEW_PENDING = "SOURCE_VERIFIED_REVIEW_PENDING"

    #: The provision is transcribed and part of what the criterion needs still is
    #: not in the document at all - so no amount of transcription closes it.
    PARTIALLY_RESOLVABLE_FROM_SOURCE = "PARTIALLY_RESOLVABLE_FROM_SOURCE"

    #: Nothing has been done.
    UNRESOLVED = "UNRESOLVED"

    @property
    def permits_adjudication(self) -> bool:
        """Only a fully resolved dependency lets its criterion be adjudicated.

        `SOURCE_VERIFIED_REVIEW_PENDING` deliberately returns False. Transcribing
        the provision is progress and is not permission - treating it as permission
        would let engineering close a review question by doing engineering work.
        """
        return self is DependencyResolution.RESOLVED


@dataclass(frozen=True, slots=True)
class VerificationRecord:
    """What is established about one criterion, split by who established it."""

    subject_id: str
    source: SourceVerification = SourceVerification.NOT_VERIFIED
    review: QualifiedReviewStatus = QualifiedReviewStatus.QUALIFIED_REVIEW_PENDING
    reviewer_id: str | None = None
    reviewed_on: date | None = None
    notes: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        # A review outcome that names nobody is not a review. Refused rather than
        # demoted, because unlike a runtime value this is written by hand into a
        # committed artefact, and a silent demotion there would hide an edit.
        settled = {
            QualifiedReviewStatus.QUALIFIED_REVIEWED,
            QualifiedReviewStatus.QUALIFIED_REVIEW_REJECTED,
            QualifiedReviewStatus.QUALIFIED_REVIEW_INCONCLUSIVE,
        }
        if self.review in settled and not self.reviewer_id:
            raise ValueError(
                f"{self.subject_id}: {self.review.value} with no reviewer identity. "
                "A review nobody signed cannot be attributed or revisited."
            )

    @property
    def is_source_verified(self) -> bool:
        return self.source is SourceVerification.SOURCE_VERIFIED

    @property
    def is_qualified_reviewed(self) -> bool:
        return self.review is QualifiedReviewStatus.QUALIFIED_REVIEWED

    @property
    def summary(self) -> str:
        """Both axes, always together.

        Rendering only one is how "source verified" ends up in a sentence that
        reads as "reviewed".
        """
        return f"{self.source.value} / {self.review.value}"
