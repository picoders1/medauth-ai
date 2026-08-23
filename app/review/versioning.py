"""Review decisions are versioned. History is never mutated.

A qualified reviewer working the OD-19 queue will eventually change things that
other artefacts were built against - the criterion inventory, a policy's declared
semantics, a code link's admissibility, and through those, case labels. The
temptation at that point is to edit the record so it matches the new understanding.

That destroys the only thing the record was for. A gold case labelled in the
data-foundation phase is evidence about what the system decided *then*; a criterion
inventory is evidence about what was transcribed *then*. Overwrite either and every
committed report silently stops meaning what it said.

So review decisions accumulate as **versions**. `review_v1` is what the first
reviewer concluded; `review_v2` is what the second concluded, alongside it. A
correction is a new version that says what it supersedes and why - never an edit.

**Nothing here applies a decision.** A `ReviewVersion` records what a reviewer
concluded and what that touches. Acting on it - retranscribing a criterion,
declaring a policy's logic, regenerating a gold set - is separate, deliberate work,
and `impact` exists so the size of that work is visible before anyone starts it.

Pure: no I/O, no clock. `decided_on` is supplied.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from enum import StrEnum

__all__ = [
    "ReviewDecision",
    "ReviewImpact",
    "ReviewScope",
    "ReviewVersion",
    "next_version",
]


class ReviewScope(StrEnum):
    """What kind of artefact a decision touches.

    Kept explicit rather than inferred from the subject id, because the blast
    radius differs sharply: a criterion decision can invalidate case labels, a
    linkage decision changes which policies resolve, and a semantics decision
    changes whether a policy adjudicates at all.
    """

    PROVISION = "PROVISION"
    CRITERION = "CRITERION"
    POLICY_SEMANTICS = "POLICY_SEMANTICS"
    COVERAGE_STATUS = "COVERAGE_STATUS"
    CODE_LINKAGE = "CODE_LINKAGE"


@dataclass(frozen=True, slots=True)
class ReviewDecision:
    """One reviewer conclusion about one subject.

    `rationale` and `reviewer_id` are required, not optional. An unsigned decision
    with no reasoning is not a review - it is a change of state that nobody can
    later evaluate, and this record exists precisely to be evaluated later.
    """

    scope: ReviewScope
    subject_id: str
    decision: str
    rationale: str
    reviewer_id: str
    decided_on: date

    def __post_init__(self) -> None:
        for name in ("subject_id", "decision", "rationale", "reviewer_id"):
            if not str(getattr(self, name)).strip():
                raise ValueError(f"review decision with an empty {name}")


@dataclass(frozen=True, slots=True)
class ReviewImpact:
    """What a decision would touch if it were acted on.

    Computed, not asserted - see `app.review.impact`. Held here so a review version
    carries its own blast radius rather than requiring a separate lookup at the
    moment someone is deciding whether to act.
    """

    criteria: tuple[str, ...] = ()
    policy_versions: tuple[str, ...] = ()
    gold_cases: tuple[str, ...] = ()
    synthetic_cases: tuple[str, ...] = ()
    evaluation_reports: tuple[str, ...] = ()
    notes: tuple[str, ...] = field(default_factory=tuple)

    @property
    def is_empty(self) -> bool:
        return not (
            self.criteria
            or self.policy_versions
            or self.gold_cases
            or self.synthetic_cases
            or self.evaluation_reports
        )

    @property
    def touches_frozen_data(self) -> bool:
        """Whether acting on this would require a new frozen dataset version.

        Gold cases are frozen. A decision that reaches them cannot be applied by
        editing; it forces a `gold_v2` with a recorded reason, which is a decision
        of its own and not a consequence anyone should discover afterwards.
        """
        return bool(self.gold_cases)


@dataclass(frozen=True, slots=True)
class ReviewVersion:
    """One round of review, immutable once recorded.

    A version supersedes at most one earlier version and never deletes it. Reading
    the chain backwards gives the full history of what was believed and when, which
    is what makes a superseded evaluation result interpretable rather than merely
    wrong.
    """

    version: int
    decisions: tuple[ReviewDecision, ...]
    impact: ReviewImpact
    recorded_on: date
    supersedes: int | None = None
    supersedes_reason: str = ""

    def __post_init__(self) -> None:
        if self.version < 1:
            raise ValueError(f"review version {self.version} is not a version number")
        if self.supersedes is not None:
            if self.supersedes >= self.version:
                raise ValueError(
                    f"review_v{self.version} claims to supersede review_v{self.supersedes}; "
                    "a version can only supersede an earlier one"
                )
            if not self.supersedes_reason.strip():
                raise ValueError(
                    f"review_v{self.version} supersedes review_v{self.supersedes} with no "
                    "recorded reason. Superseding without saying why turns a correction "
                    "into an unexplained divergence."
                )
        if not self.decisions:
            raise ValueError(f"review_v{self.version} records no decisions")

    @property
    def label(self) -> str:
        return f"review_v{self.version}"

    def subjects(self) -> frozenset[tuple[str, str]]:
        """`(scope, subject_id)` pairs this version ruled on."""
        return frozenset((d.scope.value, d.subject_id) for d in self.decisions)


def next_version(history: tuple[ReviewVersion, ...]) -> int:
    """The number a new review version would take.

    Derived from the highest existing version rather than from the count, so a gap
    in the history - a version recorded and later found unusable - does not cause a
    number to be reused. A reused version number would make two different sets of
    decisions indistinguishable in a report.
    """
    return max((v.version for v in history), default=0) + 1
