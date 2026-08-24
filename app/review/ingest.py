"""Accepting a decision that came from outside, without being able to forge one.

FOCUS-001 will eventually be answered by a person. This is the path that answer
travels, and its whole job is to be strict about *attribution* while being
completely silent about *substance*.

**The validator does not judge the answer.** Whether narrowing C03 is the right
reading of 42 CFR 410.32 is exactly the question engineering cannot settle. What it
can check is: was a properly attributed decision supplied, by someone who named
themselves and their standing, citing the packet they were given, with a rationale,
at a recorded time - and was it accepted by a second, separately-recorded act.

Those are all questions about the *envelope*, and getting them wrong is how an
unreviewed default comes to look like a reviewed decision.

## Why submission and acceptance stay apart

A single function that turned an external file into `ACCEPTED` would be one call
wide. Ingesting a submission and accepting it are separate entry points requiring
different attribution, so a malformed or forged submission stops at `SUBMITTED`,
which unblocks nothing.

## What "accepted by the same mechanism" means

An acceptance recorded by the same identity that submitted the decision is refused.
Not because self-acceptance is always wrong, but because it collapses two acts into
one and removes the only structural check on the first. If the same person must do
both, that is a process decision for OD-29 to settle - and it will be visible in the
record rather than silently permitted here.

Pure: no I/O. The payload arrives already parsed. `scripts/ingest_focus_decision.py`
does the reading.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date
from typing import Any

from app.review.decision_gate import DecisionGate, DecisionStatus, GateError, ReviewerIdentity

__all__ = [
    "REQUIRED_SUBMISSION_FIELDS",
    "IngestError",
    "ValidationIssue",
    "accept_decision",
    "ingest_submission",
    "validate_submission",
]

#: Everything an external submission must carry. Absence of any one is a refusal,
#: never a default - a decision missing its rationale is not a decision with an
#: empty rationale, it is an unattributable state change.
REQUIRED_SUBMISSION_FIELDS = (
    "focus_id",
    "reviewer_identity",
    "reviewer_qualification",
    "decision",
    "rationale",
    "source_reference",
    "submitted_at",
)

#: The acceptance half. Recorded separately, by someone other than the submitter.
REQUIRED_ACCEPTANCE_FIELDS = ("accepted_by", "accepted_at")

_ISO_DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")

#: A rationale must actually say something. Not a quality bar - a length this short
#: only catches "ok", "yes", "agreed", which are the shapes a rubber stamp takes.
_MIN_RATIONALE_WORDS = 8


class IngestError(GateError):
    """An external decision could not be ingested. Never recovered from."""


@dataclass(frozen=True, slots=True)
class ValidationIssue:
    """One reason a submission was refused, and what would fix it."""

    field: str
    problem: str
    remedy: str


def _as_date(value: object, field: str, issues: list[ValidationIssue]) -> date | None:
    raw = str(value or "").strip()
    if not raw:
        issues.append(
            ValidationIssue(field, "missing", f"supply {field} as an ISO date (YYYY-MM-DD)")
        )
        return None
    if not _ISO_DATE.match(raw):
        issues.append(ValidationIssue(field, f"{raw!r} is not an ISO date", "use YYYY-MM-DD"))
        return None
    try:
        return date.fromisoformat(raw)
    except ValueError:
        issues.append(ValidationIssue(field, f"{raw!r} is not a real date", "check the value"))
        return None


def validate_submission(
    payload: dict[str, Any],
    *,
    gate: DecisionGate,
    expected_source_references: tuple[str, ...],
) -> tuple[ValidationIssue, ...]:
    """Check the envelope. **Says nothing about whether the answer is right.**

    Every issue is returned rather than raising on the first, so a reviewer sending
    a decision back gets one list of corrections instead of discovering them one
    round-trip at a time.
    """
    issues: list[ValidationIssue] = []

    for field in REQUIRED_SUBMISSION_FIELDS:
        if not str(payload.get(field) or "").strip():
            issues.append(ValidationIssue(field, "missing or empty", f"supply {field}"))

    if str(payload.get("focus_id") or "").strip() not in {"", gate.focus_id}:
        issues.append(
            ValidationIssue(
                "focus_id",
                f"{payload['focus_id']!r} does not match the open gate {gate.focus_id!r}",
                "submit against the gate the packet names",
            )
        )

    decision = str(payload.get("decision") or "").strip()
    if decision and decision not in gate.permitted_decisions:
        issues.append(
            ValidationIssue(
                "decision",
                f"{decision!r} is not one of {list(gate.permitted_decisions)}",
                "choose one of the permitted options, or OTHER and state the reading",
            )
        )

    rationale = str(payload.get("rationale") or "").strip()
    if rationale and len(rationale.split()) < _MIN_RATIONALE_WORDS:
        issues.append(
            ValidationIssue(
                "rationale",
                f"{len(rationale.split())} words; a decision needs reasoning that can "
                "be evaluated later",
                "state why the reading follows from the source",
            )
        )

    # The reviewer must be answering the packet they were given. A submission
    # citing something else may be a considered answer to a different question, and
    # accepting it would silently rebase the decision onto a source nobody checked.
    reference = str(payload.get("source_reference") or "").strip()
    if reference and expected_source_references:
        if not any(expected in reference for expected in expected_source_references):
            issues.append(
                ValidationIssue(
                    "source_reference",
                    f"{reference!r} matches none of the packet's references "
                    f"{list(expected_source_references)}",
                    "cite the reviewer packet or the authoritative source it quotes",
                )
            )

    _as_date(payload.get("submitted_at"), "submitted_at", issues)

    if gate.status is not DecisionStatus.PENDING:
        issues.append(
            ValidationIssue(
                "focus_id",
                f"the gate is already {gate.status.value}",
                "a later answer supersedes the earlier one rather than overwriting it",
            )
        )

    return tuple(issues)


def ingest_submission(
    payload: dict[str, Any],
    *,
    gate: DecisionGate,
    expected_source_references: tuple[str, ...],
) -> DecisionGate:
    """Turn a validated external payload into a `SUBMITTED` gate.

    **Cannot produce `ACCEPTED`.** That is a separate call with separate
    attribution, so a malformed or forged submission stops here, where it unblocks
    nothing.
    """
    issues = validate_submission(
        payload, gate=gate, expected_source_references=expected_source_references
    )
    if issues:
        detail = "; ".join(f"{i.field}: {i.problem}" for i in issues)
        raise IngestError(f"{gate.focus_id}: submission refused - {detail}")

    submitted_at = date.fromisoformat(str(payload["submitted_at"]).strip())
    return gate.submit(
        reviewer=ReviewerIdentity(
            reviewer_id=str(payload["reviewer_identity"]).strip(),
            qualification=str(payload["reviewer_qualification"]).strip(),
        ),
        decision=str(payload["decision"]).strip(),
        rationale=str(payload["rationale"]).strip(),
        on=submitted_at,
    )


def accept_decision(gate: DecisionGate, payload: dict[str, Any]) -> DecisionGate:
    """Accept a submitted decision. The only step that unblocks anything.

    Refuses acceptance by the identity that submitted it. Not because
    self-acceptance is always wrong, but because it collapses two acts into one and
    removes the only structural check on the first.
    """
    if gate.status is not DecisionStatus.SUBMITTED:
        raise IngestError(
            f"{gate.focus_id}: cannot accept a {gate.status.value} gate. Acceptance "
            "follows submission; there is no path that does both."
        )

    missing = [f for f in REQUIRED_ACCEPTANCE_FIELDS if not str(payload.get(f) or "").strip()]
    if missing:
        raise IngestError(f"{gate.focus_id}: acceptance missing {missing}")

    accepted_by = str(payload["accepted_by"]).strip()
    if gate.reviewer is not None and accepted_by == gate.reviewer.reviewer_id:
        raise IngestError(
            f"{gate.focus_id}: {accepted_by!r} both submitted and accepted this "
            "decision. That collapses two acts into one and removes the only "
            "structural check on the first. If one person must do both, record that "
            "as a process decision (OD-29) rather than routing around this."
        )

    issues: list[ValidationIssue] = []
    accepted_at = _as_date(payload.get("accepted_at"), "accepted_at", issues)
    if issues:
        raise IngestError(
            f"{gate.focus_id}: " + "; ".join(f"{i.field}: {i.problem}" for i in issues)
        )
    if accepted_at is not None and gate.review_timestamp is not None:
        if accepted_at < gate.review_timestamp:
            raise IngestError(
                f"{gate.focus_id}: accepted on {accepted_at} but submitted on "
                f"{gate.review_timestamp}. An acceptance cannot predate what it accepts."
            )

    if accepted_at is None:  # pragma: no cover - _as_date raised above if it were
        raise IngestError(f"{gate.focus_id}: acceptance with no date")
    return gate.accept(accepted_by=accepted_by, accepted_at=accepted_at)
