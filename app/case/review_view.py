"""Everything a reviewer needs to decide, assembled from what the run actually did.

## Nothing here re-runs anything

Evidence, criterion assessments and citations are read from the **audit events the run
emitted**. Re-running retrieval when a reviewer opens a case would return today's corpus
for yesterday's decision, and the reviewer would be shown evidence the recommendation was
never based on - while the screen said "supporting evidence".

That failure would be invisible: the citations would verify, the passages would be
relevant, and the reviewer would be reading a different case from the one the engine
decided. So the projection is strictly a read of the record.

## The two things it must never blur

**An AI recommendation is not a decision.** `ReviewCase` carries `recommendation` and
`human_disposition` as separate fields, and `human_disposition` is `None` until a person
acts. A single "outcome" field would let a UI - or a later report - render the engine's
draft as the answer.

**An authenticated identity is not a qualification.** The reviewer's own qualification
travels with its verification state (`SELF_ASSERTED`), never as a bare string that reads
like a credential.

## Why the abstention reason is mandatory in the projection

A case reaches a human for a reason - insufficient evidence, a contradiction, an
unverifiable citation, an unresolved policy, a provider failure. `routing_explanation`
turns that into a sentence, because a reviewer who cannot tell *why* a case was routed to
them is being asked to re-do the engine's work rather than to judge it.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.audit.models import (
    AuditEventRow,
    CaseRecommendationRow,
    CaseRow,
    HumanReviewEventRow,
)
from app.case.lifecycle import CaseState
from app.case.service import CaseService

__all__ = ["EvidenceRef", "ReviewCase", "ReviewHistoryEntry", "build_review_view"]


#: Why a case is in front of a person, in words a reviewer can act on. Keyed by the
#: abstention reason the decision layer recorded.
_ROUTING_EXPLANATION: dict[str, str] = {
    "INSUFFICIENT_EVIDENCE": (
        "The record does not answer one or more required criteria. This is a question "
        "about documentation, not a finding that the criteria were not met."
    ),
    "CONTRADICTORY_EVIDENCE": (
        "Two criteria were supported by the identical evidence with conflicting "
        "conclusions. The conflict is in the record, not in the model's reasoning."
    ),
    "UNVERIFIABLE_CITATION": (
        "At least one quoted passage could not be matched to its cited source. No "
        "decision is offered on unverifiable grounds."
    ),
    "POLICY_NOT_APPLICABLE": (
        "No policy in the corpus lists the requested procedure. Absence of a policy "
        "generally means contractor discretion, NOT non-coverage."
    ),
    "CONFLICTING_POLICY": (
        "Several policies could govern this request. Which one applies is a human "
        "judgement, not a ranking."
    ),
    "POLICY_TEMPORALLY_UNRESOLVED": (
        "The corpus holds this policy but no version was in force on the date of service."
    ),
    "PROVIDER_LIMITATION": (
        "The model provider did not return a usable response. This is an "
        "infrastructure failure, NOT a finding about the clinical facts."
    ),
    "MODEL_SCHEMA_FAILURE": (
        "The model's response did not satisfy the required structure after bounded "
        "repair. Nothing about the clinical facts was established."
    ),
    "POLICY_SEMANTICS_UNRESOLVED": (
        "How this policy's criteria combine has not been reviewed. The system will not "
        "assume a rule shape nobody has confirmed."
    ),
}


@dataclass(frozen=True, slots=True)
class EvidenceRef:
    """A passage the run actually used, by reference."""

    chunk_id: str
    criterion_ids: tuple[str, ...] = ()
    stage: str = ""


@dataclass(frozen=True, slots=True)
class ReviewHistoryEntry:
    """One prior human decision. **Never edited; a later action is a new entry.**"""

    action: str
    outcome: str | None
    reviewer_principal_id: str | None
    identity_model: str
    authentication_method: str | None
    rationale: str | None
    recommended_outcome_at_review: str | None
    created_at: datetime


@dataclass(frozen=True, slots=True)
class ReviewCase:
    """The reviewer's whole picture. Read-only, assembled from the record."""

    case_id: str
    state: CaseState
    procedure_code: str
    code_system: str
    jurisdiction: str
    date_of_service: Any
    input_sha256: str

    # -- what the ENGINE produced. A draft, never a disposition. ---------------
    recommendation: str | None
    decision_rule: str | None
    abstention_reason: str | None
    routing_explanation: str
    policy_type: str | None
    policy_id: str | None
    policy_version: str | None
    resolution_state: str | None
    resolution_reason: str | None
    contradiction_state: str | None
    provider_failure_kind: str | None
    confidence_state: str
    recommended_at: datetime | None

    # -- what a PERSON decided. `None` until one does. -------------------------
    human_disposition: str | None
    disposition_by: str | None
    disposition_at: datetime | None

    evidence: tuple[EvidenceRef, ...] = ()
    history: tuple[ReviewHistoryEntry, ...] = ()
    audit_event_count: int = 0
    #: Actions this case's state permits. Published so a UI need not encode the graph.
    available_actions: tuple[str, ...] = field(default_factory=tuple)

    @property
    def awaiting_human_review(self) -> bool:
        return self.state is CaseState.HUMAN_REVIEW

    @property
    def is_finalized(self) -> bool:
        return self.state is CaseState.FINALIZED


def _explain(abstention_reason: str | None, resolution_reason: str | None) -> str:
    """Why this is in front of a person. Never empty."""
    for key in (abstention_reason, resolution_reason):
        if key and key in _ROUTING_EXPLANATION:
            return _ROUTING_EXPLANATION[key]
    if abstention_reason or resolution_reason:
        # A reason the table does not have a sentence for. Say so rather than
        # rendering a bare enum name and letting a reviewer guess.
        return (
            f"Routed for review: {abstention_reason or resolution_reason}. No "
            "explanation is recorded for this reason yet."
        )
    return (
        "This case carries a definitive draft recommendation. Every recommendation "
        "requires a human disposition before the case is closed."
    )


async def build_review_view(session: AsyncSession, case_id: str, *, caller_id: str) -> ReviewCase:
    """Assemble the projection. Ownership is checked by `CaseService.get`."""
    case: CaseRow = await CaseService(session).get(case_id, caller_id=caller_id)

    recommendation = (
        await session.execute(
            select(CaseRecommendationRow)
            .where(CaseRecommendationRow.case_uuid == case.id)
            .order_by(CaseRecommendationRow.run_seq.desc())
            .limit(1)
        )
    ).scalar_one_or_none()

    events = list(
        (
            await session.execute(
                select(AuditEventRow)
                .where(AuditEventRow.case_id == case_id)
                .order_by(AuditEventRow.created_at)
            )
        ).scalars()
    )

    # Evidence from the run's own trail. NOT re-retrieved - see the module docstring.
    evidence: list[EvidenceRef] = []
    seen: set[str] = set()
    contradiction_state: str | None = None
    for event in events:
        contradiction_state = event.contradiction_state or contradiction_state
        payload: dict[str, Any] = event.payload or {}
        chunk_ids = payload.get("chunk_ids")
        criterion_ids = payload.get("criterion_ids")
        for chunk_id in chunk_ids if isinstance(chunk_ids, list) else ():
            if str(chunk_id) in seen:
                continue
            seen.add(str(chunk_id))
            evidence.append(
                EvidenceRef(
                    chunk_id=str(chunk_id),
                    criterion_ids=tuple(
                        str(c) for c in (criterion_ids if isinstance(criterion_ids, list) else ())
                    ),
                    stage=event.stage,
                )
            )

    reviews = list(
        (
            await session.execute(
                select(HumanReviewEventRow)
                .where(HumanReviewEventRow.case_id == case_id)
                .order_by(HumanReviewEventRow.created_at)
            )
        ).scalars()
    )
    history = tuple(
        ReviewHistoryEntry(
            action=str(row.action),
            outcome=str(row.outcome) if row.outcome else None,
            reviewer_principal_id=row.principal_id,
            identity_model=row.identity_model,
            authentication_method=row.authentication_method,
            rationale=row.rationale,
            recommended_outcome_at_review=row.recommended_outcome_at_review,
            created_at=row.created_at,
        )
        for row in reviews
    )
    # The most recent human decision, if any. Earlier ones stay in `history`.
    latest = reviews[-1] if reviews else None

    state = CaseState(case.state)
    actions: tuple[str, ...] = (
        ("ACCEPT_RECOMMENDATION", "OVERRIDE_RECOMMENDATION", "REQUEST_INFORMATION")
        if state is CaseState.HUMAN_REVIEW
        else ()
    )

    return ReviewCase(
        case_id=case.case_id,
        state=state,
        procedure_code=case.procedure_code,
        code_system=case.code_system,
        jurisdiction=case.jurisdiction,
        date_of_service=case.date_of_service,
        input_sha256=case.input_sha256,
        recommendation=recommendation.outcome if recommendation else None,
        decision_rule=recommendation.decision_rule if recommendation else None,
        abstention_reason=recommendation.abstention_reason if recommendation else None,
        routing_explanation=_explain(
            recommendation.abstention_reason if recommendation else None,
            recommendation.resolution_reason if recommendation else None,
        ),
        policy_type=recommendation.policy_type if recommendation else None,
        policy_id=recommendation.policy_id if recommendation else None,
        policy_version=recommendation.policy_version if recommendation else None,
        resolution_state=recommendation.resolution_state if recommendation else None,
        resolution_reason=recommendation.resolution_reason if recommendation else None,
        contradiction_state=contradiction_state,
        provider_failure_kind=recommendation.provider_failure_kind if recommendation else None,
        confidence_state=recommendation.confidence_state if recommendation else "UNCALIBRATED",
        recommended_at=recommendation.created_at if recommendation else None,
        human_disposition=str(latest.outcome) if latest and latest.outcome else None,
        disposition_by=latest.principal_id if latest else None,
        disposition_at=latest.created_at if latest else None,
        evidence=tuple(evidence),
        history=history,
        audit_event_count=len(events),
        available_actions=actions,
    )
