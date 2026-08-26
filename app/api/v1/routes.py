"""API v1. Routes call services and contain no logic.

Every handler here does the same four things: resolve the caller, build the service,
call one method, shape a response. Ownership, state transitions, audit writes and the
rationale rules all live in `app/case/`, so a second entry point cannot reach a case by
skipping something a decorator was doing.

## Correlation

`x-medauth-request-id` is honoured if the caller sends one and generated if not, then
carried into the service, onto every audit event, and back on the response header. A
request that cannot be correlated with its trail is a request nobody can investigate.

## What is not here

No `/cases` listing endpoint. Enumerating cases is a different authorization question
from reading one you submitted, and the ownership model is not rich enough to answer it
yet - so it is absent rather than guessed at.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Request, Response
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1.schemas import (
    AcceptRequest,
    AuditEventResponse,
    AuditTrailResponse,
    CaseResponse,
    CaseStatusResponse,
    EvidenceRefResponse,
    EvidenceResponse,
    OverrideRequest,
    RecommendationResponse,
    RequestInformationRequest,
    ReviewCaseResponse,
    ReviewHistoryResponse,
    ReviewRequest,
    ReviewResponse,
    SubmitCaseRequest,
)
from app.api.v1.security import Caller, caller_from_headers, reviewer_from_headers
from app.audit.models import (
    AuditEventRow,
    CaseRow,
    HumanReviewAction,
    ReviewOutcome,
)
from app.case.lifecycle import CaseState, allowed_next
from app.case.review import HumanReviewService
from app.case.review_view import build_review_view
from app.case.service import CaseService, CaseSubmission
from app.identity.principal import Permission, Principal
from app.identity.qualification import (
    NOT_VERIFIED_NOTICE,
    qualification_of,
    verification_state,
)

router = APIRouter(prefix="/api/v1", tags=["cases"])

CallerDep = Annotated[Caller, Depends(caller_from_headers)]
#: The authenticated HUMAN. Separate dependency from the caller, so a route
#: cannot accidentally satisfy one with the other.
ReviewerDep = Annotated[Principal, Depends(reviewer_from_headers)]


def request_id_for(request: Request) -> str:
    return request.headers.get("x-medauth-request-id") or f"req-{uuid.uuid4().hex[:16]}"


async def session_for(request: Request) -> Any:
    factory = getattr(request.app.state, "session_factory", None)
    if factory is None:  # pragma: no cover - configuration failure surfaces at /ready
        from app.core.errors import ConfigurationError

        raise ConfigurationError("no database session factory is configured")
    async with factory() as session:
        yield session


SessionDep = Annotated[AsyncSession, Depends(session_for)]


def _as_date(value: date | datetime) -> date:
    return value.date() if isinstance(value, datetime) else value


def _case_response(row: CaseRow, request_id: str) -> CaseResponse:
    return CaseResponse(
        case_id=row.case_id,
        case_version=row.case_version,
        state=CaseState(row.state),
        procedure_code=row.procedure_code,
        code_system=row.code_system,
        jurisdiction=row.jurisdiction,
        # The column is timestamptz but a freshly-created row still holds the plain
        # `date` the caller sent, until it round-trips. Normalise rather than assume.
        date_of_service=_as_date(row.date_of_service),
        input_sha256=row.input_sha256,
        created_at=row.created_at,
        updated_at=row.updated_at,
        request_id=request_id,
    )


@router.post("/cases", response_model=CaseResponse, status_code=201)
async def submit_case(
    body: SubmitCaseRequest,
    request: Request,
    response: Response,
    caller: CallerDep,
    session: SessionDep,
) -> CaseResponse:
    """Accept a case. **Does not run it** - see the runbook.

    Submission and execution are separate on purpose: a run takes seconds and, while
    R-86 is open, may take 6.3 s and fail. Binding that to the HTTP request would make
    intake availability depend on a provider defect that is explicitly not ours.
    """
    request_id = request_id_for(request)
    response.headers["x-medauth-request-id"] = request_id
    service = CaseService(session)
    row = await service.submit(
        CaseSubmission(
            case_id=body.case_id,
            clinical_note=body.clinical_note,
            procedure_code=body.procedure_code,
            code_system=body.code_system,
            date_of_service=body.date_of_service,
            diagnosis_codes=body.diagnosis_codes,
            jurisdiction=body.jurisdiction,
        ),
        caller_id=caller.caller_id,
        request_id=request_id,
    )
    return _case_response(row, request_id)


@router.get("/cases/{case_id}", response_model=CaseResponse)
async def get_case(
    case_id: str, request: Request, response: Response, caller: CallerDep, session: SessionDep
) -> CaseResponse:
    request_id = request_id_for(request)
    response.headers["x-medauth-request-id"] = request_id
    row = await CaseService(session).get(case_id, caller_id=caller.caller_id)
    return _case_response(row, request_id)


@router.get("/cases/{case_id}/status", response_model=CaseStatusResponse)
async def get_status(
    case_id: str, request: Request, response: Response, caller: CallerDep, session: SessionDep
) -> CaseStatusResponse:
    request_id = request_id_for(request)
    response.headers["x-medauth-request-id"] = request_id
    row = await CaseService(session).get(case_id, caller_id=caller.caller_id)
    state = CaseState(row.state)
    return CaseStatusResponse(
        case_id=row.case_id,
        state=state,
        allowed_next=tuple(sorted(allowed_next(state), key=lambda s: s.value)),
        awaiting_human_review=state is CaseState.HUMAN_REVIEW,
        updated_at=row.updated_at,
        request_id=request_id,
    )


@router.get("/cases/{case_id}/recommendation", response_model=RecommendationResponse)
async def get_recommendation(
    case_id: str, request: Request, response: Response, caller: CallerDep, session: SessionDep
) -> RecommendationResponse:
    """The engine's conclusion, typed. Never raw model output."""
    request_id = request_id_for(request)
    response.headers["x-medauth-request-id"] = request_id
    service = CaseService(session)
    row = await service.latest_recommendation(case_id, caller_id=caller.caller_id)
    if row is None:
        from app.case.service import CaseNotFound

        # A case with no recommendation is not an error about the case; it is an
        # absence of the thing asked for, and 404 is the honest answer.
        raise CaseNotFound(f"case {case_id} has no recommendation yet")
    case = await service.get(case_id, caller_id=caller.caller_id)
    return RecommendationResponse(
        case_id=case_id,
        outcome=str(row.outcome),
        decision_rule=str(row.decision_rule),
        abstention_reason=row.abstention_reason,
        resolution_state=row.resolution_state,
        resolution_reason=row.resolution_reason,
        policy_type=row.policy_type,
        policy_id=row.policy_id,
        policy_version=row.policy_version,
        provider_failure_kind=row.provider_failure_kind,
        provider_failure_attribution=row.provider_failure_attribution,
        confidence_state=row.confidence_state,
        human_review_required=CaseState(case.state) is CaseState.HUMAN_REVIEW,
        model_calls=row.model_calls,
        run_seq=row.run_seq,
        created_at=row.created_at,
        request_id=request_id,
    )


@router.get("/cases/{case_id}/evidence", response_model=EvidenceResponse)
async def get_evidence(
    case_id: str, request: Request, response: Response, caller: CallerDep, session: SessionDep
) -> EvidenceResponse:
    """Evidence references from the run's own audit trail.

    Read from the events the runtime emitted rather than re-retrieved. Re-running
    retrieval to answer this would return today's corpus for yesterday's decision, and
    a reviewer would be shown evidence the recommendation was never based on.
    """
    request_id = request_id_for(request)
    response.headers["x-medauth-request-id"] = request_id
    await CaseService(session).get(case_id, caller_id=caller.caller_id)

    rows = (
        await session.execute(
            select(AuditEventRow)
            .where(AuditEventRow.case_id == case_id)
            .order_by(AuditEventRow.created_at)
        )
    ).scalars()

    from app.api.v1.schemas import EvidenceItem

    items: list[EvidenceItem] = []
    seen: set[str] = set()
    for event in rows:
        payload: dict[str, Any] = event.payload or {}
        chunk_ids = payload.get("chunk_ids")
        criterion_ids = payload.get("criterion_ids")
        for chunk_id in chunk_ids if isinstance(chunk_ids, list) else ():
            if str(chunk_id) in seen:
                continue
            seen.add(str(chunk_id))
            items.append(
                EvidenceItem(
                    chunk_id=str(chunk_id),
                    criterion_ids=tuple(
                        str(c) for c in (criterion_ids if isinstance(criterion_ids, list) else ())
                    ),
                )
            )
    return EvidenceResponse(
        case_id=case_id,
        items=tuple(items),
        empty_because_not_assessed=not items,
        request_id=request_id,
    )


@router.post("/cases/{case_id}/review", response_model=ReviewResponse, status_code=201)
async def submit_review(
    case_id: str,
    body: ReviewRequest,
    request: Request,
    response: Response,
    caller: CallerDep,
    reviewer: ReviewerDep,
    session: SessionDep,
) -> ReviewResponse:
    """Record a human decision. Appends; never edits the recommendation.

    Two identities, deliberately: `caller` is the integrating system (which case may be
    seen), `reviewer` is the authenticated person (who decided). Collapsing them is the
    defect OD-43 names.
    """
    request_id = request_id_for(request)
    response.headers["x-medauth-request-id"] = request_id
    cases = CaseService(session)
    reviews = HumanReviewService(session, cases=cases)
    event = await reviews.record(
        case_id,
        reviewer=reviewer,
        caller_id=caller.caller_id,
        request_id=request_id,
        action=body.action,
        rationale=body.rationale,
        override_outcome=body.override_outcome,
        stated_qualification=body.stated_qualification,
    )
    case = await cases.get(case_id, caller_id=caller.caller_id)
    return ReviewResponse(
        case_id=case_id,
        action=body.action,
        outcome=event.outcome,
        reviewer_id=event.reviewer_id,
        principal_type=str(event.principal_type),
        authentication_method=str(event.authentication_method),
        identity_model=event.identity_model,
        recommended_outcome_at_review=event.recommended_outcome_at_review,
        case_state=CaseState(case.state),
        created_at=event.created_at,
        request_id=request_id,
    )


@router.get("/cases/{case_id}/audit", response_model=AuditTrailResponse)
async def get_audit(
    case_id: str, request: Request, response: Response, caller: CallerDep, session: SessionDep
) -> AuditTrailResponse:
    request_id = request_id_for(request)
    response.headers["x-medauth-request-id"] = request_id
    await CaseService(session).get(case_id, caller_id=caller.caller_id)

    rows = (
        await session.execute(
            select(AuditEventRow)
            .where(AuditEventRow.case_id == case_id)
            .order_by(AuditEventRow.created_at)
        )
    ).scalars()
    return AuditTrailResponse(
        case_id=case_id,
        events=tuple(
            AuditEventResponse(
                event=row.event,
                stage=row.stage,
                outcome=row.outcome,
                abstention_reason=row.abstention_reason,
                resolution_state=row.resolution_state,
                provider_failure_kind=row.provider_failure_kind,
                actor_type=(row.payload or {}).get("actor_type"),
                correlation_id=(row.payload or {}).get("correlation_id"),
                created_at=row.created_at,
            )
            for row in rows
        ),
        request_id=request_id,
    )


# --------------------------------------------------------------------------- review
#
# Three endpoints, not one with an `action` field. A reviewer accepting a recommendation
# and a reviewer overriding it need different inputs and carry different authority, and
# a single endpoint would have to validate "rationale required unless action == ACCEPT"
# in prose. Here the requirement is the request model's shape.


@router.get("/cases/{case_id}/review", response_model=ReviewCaseResponse)
async def get_review_view(
    case_id: str,
    request: Request,
    response: Response,
    caller: CallerDep,
    reviewer: ReviewerDep,
    session: SessionDep,
) -> ReviewCaseResponse:
    """Everything a reviewer needs. **Nothing is re-run to produce it.**

    Evidence comes from the audit events the original run emitted. Re-running retrieval
    here would show today's corpus for yesterday's decision, under a heading that said
    "supporting evidence".
    """
    request_id = request_id_for(request)
    response.headers["x-medauth-request-id"] = request_id
    reviewer.require(Permission.READ_CASE)

    view = await build_review_view(session, case_id, caller_id=caller.caller_id)
    return ReviewCaseResponse(
        case_id=view.case_id,
        state=view.state,
        procedure_code=view.procedure_code,
        code_system=view.code_system,
        jurisdiction=view.jurisdiction,
        date_of_service=_as_date(view.date_of_service),
        input_sha256=view.input_sha256,
        ai_recommendation=view.recommendation,
        decision_rule=view.decision_rule,
        abstention_reason=view.abstention_reason,
        routing_explanation=view.routing_explanation,
        policy_type=view.policy_type,
        policy_id=view.policy_id,
        policy_version=view.policy_version,
        resolution_state=view.resolution_state,
        resolution_reason=view.resolution_reason,
        contradiction_state=view.contradiction_state,
        provider_failure_kind=view.provider_failure_kind,
        confidence_state=view.confidence_state,
        recommended_at=view.recommended_at,
        human_disposition=view.human_disposition,
        disposition_by=view.disposition_by,
        disposition_at=view.disposition_at,
        reviewer_principal_id=reviewer.principal_id,
        reviewer_qualification=qualification_of(reviewer),
        qualification_state=verification_state(reviewer).value,
        qualification_notice=NOT_VERIFIED_NOTICE,
        evidence=tuple(
            EvidenceRefResponse(chunk_id=e.chunk_id, criterion_ids=e.criterion_ids, stage=e.stage)
            for e in view.evidence
        ),
        history=tuple(
            ReviewHistoryResponse(
                action=h.action,
                outcome=h.outcome,
                reviewer_principal_id=h.reviewer_principal_id,
                identity_model=h.identity_model,
                authentication_method=h.authentication_method,
                rationale=h.rationale,
                recommended_outcome_at_review=h.recommended_outcome_at_review,
                created_at=h.created_at,
            )
            for h in view.history
        ),
        available_actions=view.available_actions,
        audit_event_count=view.audit_event_count,
        request_id=request_id,
    )


async def _record_review(
    *,
    case_id: str,
    request: Request,
    response: Response,
    caller: Caller,
    reviewer: Principal,
    session: AsyncSession,
    action: HumanReviewAction,
    rationale: str | None,
    override_outcome: ReviewOutcome | None,
    stated_qualification: str,
) -> ReviewResponse:
    """One path to the service, shared by the three endpoints.

    The endpoints differ in what they *accept*; they must not differ in what they
    *record*, or the three would drift into three slightly different review semantics.
    """
    request_id = request_id_for(request)
    response.headers["x-medauth-request-id"] = request_id
    cases = CaseService(session)
    event = await HumanReviewService(session, cases=cases).record(
        case_id,
        reviewer=reviewer,
        caller_id=caller.caller_id,
        request_id=request_id,
        action=action,
        rationale=rationale,
        override_outcome=override_outcome,
        stated_qualification=stated_qualification,
    )
    case = await cases.get(case_id, caller_id=caller.caller_id)
    return ReviewResponse(
        case_id=case_id,
        action=action,
        outcome=event.outcome,
        reviewer_id=event.reviewer_id,
        principal_type=str(event.principal_type),
        authentication_method=str(event.authentication_method),
        identity_model=event.identity_model,
        recommended_outcome_at_review=event.recommended_outcome_at_review,
        case_state=CaseState(case.state),
        created_at=event.created_at,
        request_id=request_id,
    )


@router.post("/cases/{case_id}/review/accept", response_model=ReviewResponse, status_code=201)
async def accept_recommendation(
    case_id: str,
    body: AcceptRequest,
    request: Request,
    response: Response,
    caller: CallerDep,
    reviewer: ReviewerDep,
    session: SessionDep,
) -> ReviewResponse:
    """Adopt the engine's recommendation as the human disposition."""
    return await _record_review(
        case_id=case_id,
        request=request,
        response=response,
        caller=caller,
        reviewer=reviewer,
        session=session,
        action=HumanReviewAction.APPROVE,
        rationale=body.comment,
        override_outcome=None,
        stated_qualification=body.stated_qualification,
    )


@router.post("/cases/{case_id}/review/override", response_model=ReviewResponse, status_code=201)
async def override_recommendation(
    case_id: str,
    body: OverrideRequest,
    request: Request,
    response: Response,
    caller: CallerDep,
    reviewer: ReviewerDep,
    session: SessionDep,
) -> ReviewResponse:
    """Decide against the engine. Requires `OVERRIDE_RECOMMENDATION` and a rationale.

    The engine's recommendation is **not** edited. This appends beside it.
    """
    return await _record_review(
        case_id=case_id,
        request=request,
        response=response,
        caller=caller,
        reviewer=reviewer,
        session=session,
        action=HumanReviewAction.OVERRIDE,
        rationale=body.rationale,
        override_outcome=body.override_outcome,
        stated_qualification=body.stated_qualification,
    )


@router.post("/cases/{case_id}/review/request-info", response_model=ReviewResponse, status_code=201)
async def request_information(
    case_id: str,
    body: RequestInformationRequest,
    request: Request,
    response: Response,
    caller: CallerDep,
    reviewer: ReviewerDep,
    session: SessionDep,
) -> ReviewResponse:
    """Return the case to the submitter with a stated request."""
    return await _record_review(
        case_id=case_id,
        request=request,
        response=response,
        caller=caller,
        reviewer=reviewer,
        session=session,
        action=HumanReviewAction.REQUEST_INFO,
        rationale=body.requested_information,
        override_outcome=None,
        stated_qualification=body.stated_qualification,
    )
