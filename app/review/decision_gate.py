"""A domain decision that engineering cannot make, modelled so it cannot be faked.

FOCUS-001 asks whether criterion C03 can be adjudicated from 42 CFR 410.32 alone.
It is a question about how to read a regulation, and there is no engineering answer
to it: not a heuristic, not a similarity score, not a model's opinion. The whole
value of the gate is that it stays shut until a person who can answer it does.

So the risk this module addresses is not that someone will answer it wrongly. It is
that a later change will make it *appear* answered - a default that reads as
approval, a status that advances when a pipeline runs, an "engineering acceptance"
that quietly becomes the decision.

Three defences, in order of how hard they are to erode:

**No constructor produces an accepted decision.** `DecisionGate.pending()` is the
only way to make one, and `submit()` is the only way to advance it. `submit()`
requires a reviewer identity, a stated qualification and a rationale, and refuses
without them.

**Acceptance is a separate act from submission.** A submitted decision is
`SUBMITTED`, not `ACCEPTED`. Advancing it needs a second call naming who accepted
it, so a single forged call cannot produce an admissible state.

**The gate reports `is_resolved` only for `ACCEPTED`.** Everything else - pending,
submitted, rejected, superseded - leaves production blocked. A rejected decision is
not a decision that unblocks anything.

Pure: no I/O, no clock. Timestamps are supplied.
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from datetime import date
from enum import StrEnum

__all__ = [
    "DecisionGate",
    "DecisionStatus",
    "GateError",
    "ReviewerIdentity",
]


class DecisionStatus(StrEnum):
    """Where a domain decision sits. `ACCEPTED` is the only unblocking value.

    There is deliberately no `ENGINEERING_ACCEPTED`, no `PROVISIONAL` and no
    `ASSUMED`. Each would be a state that reads as progress while meaning that
    nobody qualified has answered, and the point of this gate is that no such state
    exists.
    """

    #: Nobody has answered. The default, and the reason the default is safe.
    PENDING = "PENDING"

    #: A reviewer has supplied a decision. **Does not unblock anything yet** -
    #: acceptance is a separate act, so one forged call cannot reach an admissible
    #: state.
    SUBMITTED = "SUBMITTED"

    #: Accepted into the record. The only status that resolves the gate.
    ACCEPTED = "ACCEPTED"

    #: The submission was not accepted. The gate stays shut.
    REJECTED = "REJECTED"

    #: A later decision replaced this one. Kept, never deleted.
    SUPERSEDED = "SUPERSEDED"

    @property
    def resolves_gate(self) -> bool:
        return self is DecisionStatus.ACCEPTED


class GateError(ValueError):
    """An illegal transition or an incomplete submission. Never recovered from."""


@dataclass(frozen=True, slots=True)
class ReviewerIdentity:
    """Who answered, and on what standing.

    `qualification` is required and free text on purpose: the project cannot
    enumerate what qualifies someone to read coverage regulation, and a closed list
    would either exclude a legitimate reviewer or become a checkbox. What it can
    require is that the claim is *recorded*, so a later reader can weigh it.
    """

    reviewer_id: str
    qualification: str

    def __post_init__(self) -> None:
        if not self.reviewer_id.strip():
            raise GateError("a reviewer decision with no identity cannot be attributed")
        if not self.qualification.strip():
            raise GateError(
                f"{self.reviewer_id}: no qualification recorded. A later reader must be "
                "able to weigh who answered, not just that someone did."
            )


@dataclass(frozen=True, slots=True)
class DecisionGate:
    """One externally-supplied domain decision.

    Construct with `pending()`. There is no constructor that yields an accepted
    gate, and `__post_init__` refuses one built by hand.
    """

    focus_id: str
    question: str
    policy_id: str
    policy_version: str
    permitted_decisions: tuple[str, ...]
    affected_criteria: tuple[str, ...] = ()
    affected_cases: tuple[str, ...] = ()
    source_references: tuple[str, ...] = ()
    decision_version: int = 1
    status: DecisionStatus = DecisionStatus.PENDING
    reviewer: ReviewerIdentity | None = None
    reviewer_decision: str | None = None
    reviewer_rationale: str | None = None
    review_timestamp: date | None = None
    accepted_by: str | None = None
    #: When acceptance was recorded. Persisted rather than checked and discarded: an
    #: acceptance whose date nobody kept cannot later be placed relative to the
    #: submission it accepted, which is the one ordering the record exists to prove.
    accepted_at: date | None = None
    supersedes: int | None = None
    notes: tuple[str, ...] = field(default_factory=tuple)

    def __post_init__(self) -> None:
        if not self.permitted_decisions:
            raise GateError(f"{self.focus_id}: no permitted decisions declared")

        answered = {
            DecisionStatus.SUBMITTED,
            DecisionStatus.ACCEPTED,
            DecisionStatus.REJECTED,
        }
        if self.status in answered:
            if self.reviewer is None:
                raise GateError(
                    f"{self.focus_id}: {self.status.value} with no reviewer. A domain "
                    "decision that names nobody is not a decision."
                )
            if not (self.reviewer_decision and self.reviewer_rationale):
                raise GateError(
                    f"{self.focus_id}: {self.status.value} with no decision or no "
                    "rationale. An answer with no reasoning cannot be evaluated later, "
                    "which is what the record is for."
                )
            if self.reviewer_decision not in self.permitted_decisions:
                raise GateError(
                    f"{self.focus_id}: {self.reviewer_decision!r} is not one of "
                    f"{list(self.permitted_decisions)}. The option set is closed so an "
                    "answer cannot quietly change the question."
                )
        if self.status is DecisionStatus.ACCEPTED and not self.accepted_by:
            raise GateError(
                f"{self.focus_id}: ACCEPTED with nobody recorded as accepting it. "
                "Acceptance is a separate act from submission, so that one forged "
                "call cannot reach an admissible state."
            )
        if self.status is DecisionStatus.ACCEPTED and self.accepted_at is None:
            raise GateError(
                f"{self.focus_id}: ACCEPTED with no acceptance date. Who accepted and "
                "when are both part of the act; a record keeping only the first cannot "
                "show that acceptance followed submission."
            )
        if (
            self.accepted_at is not None
            and self.review_timestamp is not None
            and self.accepted_at < self.review_timestamp
        ):
            raise GateError(
                f"{self.focus_id}: accepted on {self.accepted_at} but submitted on "
                f"{self.review_timestamp}. An acceptance cannot predate what it accepts."
            )

    # -- state -------------------------------------------------------------

    @property
    def is_resolved(self) -> bool:
        """Whether this gate unblocks anything. Only `ACCEPTED` does.

        A `REJECTED` decision is an answer and is not a resolution: it means the
        reviewer declined the framing, and the gate stays shut.
        """
        return self.status.resolves_gate

    @property
    def blocks_production(self) -> bool:
        return not self.is_resolved

    # -- constructors and transitions --------------------------------------

    @classmethod
    def pending(
        cls,
        *,
        focus_id: str,
        question: str,
        policy_id: str,
        policy_version: str,
        permitted_decisions: tuple[str, ...],
        affected_criteria: tuple[str, ...] = (),
        affected_cases: tuple[str, ...] = (),
        source_references: tuple[str, ...] = (),
        decision_version: int = 1,
    ) -> DecisionGate:
        """The only way to create a gate. Always starts unanswered."""
        return cls(
            focus_id=focus_id,
            question=question,
            policy_id=policy_id,
            policy_version=policy_version,
            permitted_decisions=permitted_decisions,
            affected_criteria=affected_criteria,
            affected_cases=affected_cases,
            source_references=source_references,
            decision_version=decision_version,
            status=DecisionStatus.PENDING,
        )

    def submit(
        self,
        *,
        reviewer: ReviewerIdentity,
        decision: str,
        rationale: str,
        on: date,
    ) -> DecisionGate:
        """Record a reviewer's answer. Produces `SUBMITTED`, never `ACCEPTED`.

        Deliberately cannot reach an unblocking state in one call. Whoever supplies
        the decision and whoever accepts it into the record are two acts, and a
        gate that could be opened by a single call is a gate one mistake wide.
        """
        if self.status is not DecisionStatus.PENDING:
            raise GateError(
                f"{self.focus_id}: cannot submit against a {self.status.value} gate. "
                "A new answer supersedes the old one rather than overwriting it."
            )
        if not rationale.strip():
            raise GateError(f"{self.focus_id}: a decision with no rationale")
        return replace(
            self,
            status=DecisionStatus.SUBMITTED,
            reviewer=reviewer,
            reviewer_decision=decision,
            reviewer_rationale=rationale.strip(),
            review_timestamp=on,
        )

    def accept(self, *, accepted_by: str, accepted_at: date) -> DecisionGate:
        """Accept a submitted decision into the record. The only unblocking step.

        `accepted_at` is required rather than defaulted. A default would have to come
        from a clock, and a date the system supplied is not evidence of when a person
        acted - it is evidence of when the script ran.
        """
        if self.status is not DecisionStatus.SUBMITTED:
            raise GateError(
                f"{self.focus_id}: only a SUBMITTED decision can be accepted, not "
                f"{self.status.value}"
            )
        if not accepted_by.strip():
            raise GateError(f"{self.focus_id}: acceptance with nobody recorded")
        return replace(
            self,
            status=DecisionStatus.ACCEPTED,
            accepted_by=accepted_by.strip(),
            accepted_at=accepted_at,
        )

    def reject(self, *, reason: str) -> DecisionGate:
        """Decline a submission. The gate stays shut and the answer is kept."""
        if self.status is not DecisionStatus.SUBMITTED:
            raise GateError(
                f"{self.focus_id}: only a SUBMITTED decision can be rejected, not "
                f"{self.status.value}"
            )
        if not reason.strip():
            raise GateError(f"{self.focus_id}: rejection with no reason")
        return replace(self, status=DecisionStatus.REJECTED, notes=(*self.notes, reason.strip()))

    def supersede(self, *, reason: str) -> DecisionGate:
        """Mark this version replaced. Never deletes it.

        Returns the superseded version; the caller records a NEW gate at
        `decision_version + 1` beside it. History accumulates.
        """
        if not reason.strip():
            raise GateError(f"{self.focus_id}: superseding with no recorded reason")
        return replace(self, status=DecisionStatus.SUPERSEDED, notes=(*self.notes, reason.strip()))
