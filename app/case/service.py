"""The case lifecycle, orchestrated. **This is not a second decision pipeline.**

`SliceRunner` decides. This persists, transitions, audits and routes around it. The
distinction matters more than it looks: applicability-before-model, the decision table's
row ordering and the citation contract all live inside `SliceRunner`, and re-deriving any
of them here would create a second implementation of the safety properties this project
spent twenty phases establishing.

So `run_case()` calls `SliceRunner.run()` and maps the outcome. It never inspects
criteria, never re-runs applicability, and never decides anything.

## Applicability comes for free, and that is by design

Part N requires applicability before retrieval and model calls. This service does not
enforce that - it *cannot* violate it. `SliceRunner.__init__` refuses to construct a
`PRODUCTION` runner without an `ApplicabilityPort`, and `run()` resolves applicability as
its first stage. A caller who wanted to skip it would have to edit the runner.

## Transaction boundaries

Three transactions, not one, and the shape is deliberate:

1. **submit** - the case row and `CASE_RECEIVED` commit together.
2. **the model call** - *outside* any transaction. It takes seconds, and R-86 has it
   hanging for 6.3 s; holding a pooled connection across that is a connection-pool
   outage waiting for load.
3. **persist** - the recommendation, the lifted stage events and the state change commit
   together, or none of them do.

A case can therefore be found in `PROCESSING` after a crash. That is a real state with a
real meaning - "started, outcome unknown" - which is why the lifecycle has it and why it
is recoverable rather than terminal. The alternative, one long transaction, would trade
an honest intermediate state for a connection leak.

## Failure never becomes a clinical answer

Every exception path transitions to `FAILED` and writes `CASE_FAILED`. `FAILED` has no
edge to `FINALIZED`, so a crashed run cannot become a disposition, and the provider
failure taxonomy travels onto the recommendation row rather than being flattened into
"the model was wrong".
"""

from __future__ import annotations

import hashlib
import json
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.audit.models import CaseRecommendationRow, CaseRow
from app.audit.writer import ActorType, AuditWriter, EventType
from app.case.lifecycle import CaseState, require_transition
from app.contracts.slice import SliceInput
from app.core.errors import MedauthError
from app.decision.abstention import AbstentionReason
from app.decision.models import Outcome
from app.graph.slice import SliceOutcome, SliceRunner

__all__ = ["CaseNotFound", "CaseService", "CaseSubmission", "NotAuthorised"]


class CaseNotFound(MedauthError):
    """No such case, **or** not one this caller may see.

    Deliberately the same error for both. Distinguishing them tells an unauthorised
    caller which case ids exist, which is an enumeration oracle - so ownership failures
    surface as 404, and `NotAuthorised` is reserved for actions on a case the caller can
    already see.
    """


class NotAuthorised(MedauthError):
    """The caller may see this case but may not do this to it."""


#: Outcomes that mean a person must look. Everything else that is not a plain
#: recommendation is a question for the submitter.
_ROUTE_TO_HUMAN = frozenset({Outcome.HUMAN_REVIEW, Outcome.NO_DECISION})


@dataclass(frozen=True, slots=True)
class CaseSubmission:
    """What a caller submitted. The note is hashed, never persisted."""

    case_id: str
    clinical_note: str
    procedure_code: str
    code_system: str
    date_of_service: Any
    diagnosis_codes: tuple[str, ...] = ()
    jurisdiction: str = ""

    def digest(self) -> str:
        """sha256 of the whole submission, so a later reader can prove which input
        produced which recommendation without the note living in the database."""
        payload = {
            "case_id": self.case_id,
            "clinical_note": self.clinical_note,
            "procedure_code": self.procedure_code,
            "code_system": self.code_system,
            "date_of_service": str(self.date_of_service),
            "diagnosis_codes": list(self.diagnosis_codes),
            "jurisdiction": self.jurisdiction,
        }
        return hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()


#: Abstention reasons that mean the provider path broke, not that the model was wrong.
#: The taxonomy's own distinction, carried into the lifecycle rather than restated: a
#: broken response path and a bad answer are different failures with different owners.
_PROVIDER_FAILURE_ABSTENTIONS = frozenset(
    {
        AbstentionReason.PROVIDER_LIMITATION,
        AbstentionReason.MODEL_SCHEMA_FAILURE,
    }
)


def _provider_failure_from(outcome: SliceOutcome) -> tuple[str | None, str | None]:
    """Whether this run failed because the provider path did.

    Read off the abstention reason, which is where the runtime records it. Two other
    routes were considered and rejected: `CriterionAssessment` carries no failure field
    (so a helper reading one would silently return None forever), and re-deriving the
    kind from timings or empty assessments would be a second description of a fact the
    adjudication layer already established - which is precisely how R-99 hid R-86 from
    its own taxonomy.

    The kind recorded is the abstention reason itself. MEDAUTH does not know from here
    whether the decoder or the proxy was responsible, and R-86 is the standing evidence
    that guessing would be wrong.
    """
    reason = outcome.recommendation.abstention_reason
    if reason in _PROVIDER_FAILURE_ABSTENTIONS:
        # StrEnum members ARE their values; `Recommendation` annotates these as
        # `str`, so str() is both correct and honest about the declared type.
        return str(reason), "INDETERMINATE"
    return None, None


def _state_for(outcome: Outcome) -> CaseState:
    """Where a decided case goes. Total over `Outcome` by construction.

    A denial draft routes to a **person**, not to a finished state. That is the row-5
    ordering of the decision table showing up in the lifecycle: this system produces a
    recommendation for a human, and `DENY_RECOMMENDED` is the case where that matters
    most.
    """
    if outcome in _ROUTE_TO_HUMAN:
        return CaseState.HUMAN_REVIEW
    if outcome is Outcome.NEEDS_INFO:
        return CaseState.NEEDS_INFO
    if outcome is Outcome.DENY_RECOMMENDED:
        return CaseState.HUMAN_REVIEW
    return CaseState.RECOMMENDATION_READY


class CaseService:
    """Persist, run, audit, route. Routes call this; it contains the logic."""

    def __init__(self, session: AsyncSession, *, runner: SliceRunner | None = None) -> None:
        self._session = session
        self._runner = runner

    # -- reads ------------------------------------------------------------

    async def get(self, case_id: str, *, caller_id: str) -> CaseRow:
        """The one place ownership is checked. Every read goes through it."""
        row = (
            await self._session.execute(select(CaseRow).where(CaseRow.case_id == case_id))
        ).scalar_one_or_none()
        if row is None:
            raise CaseNotFound(f"case {case_id} not found")
        if row.submitted_by != caller_id:
            # Same error as absence - see CaseNotFound.
            raise CaseNotFound(f"case {case_id} not found")
        return row

    async def latest_recommendation(
        self, case_id: str, *, caller_id: str
    ) -> CaseRecommendationRow | None:
        case = await self.get(case_id, caller_id=caller_id)
        return (
            await self._session.execute(
                select(CaseRecommendationRow)
                .where(CaseRecommendationRow.case_uuid == case.id)
                .order_by(CaseRecommendationRow.run_seq.desc())
                .limit(1)
            )
        ).scalar_one_or_none()

    # -- writes -----------------------------------------------------------

    async def submit(
        self, submission: CaseSubmission, *, caller_id: str, request_id: str
    ) -> CaseRow:
        """Persist the case and its first event, in one transaction."""
        existing = (
            await self._session.execute(
                select(CaseRow).where(CaseRow.case_id == submission.case_id)
            )
        ).scalar_one_or_none()
        if existing is not None:
            raise MedauthError(f"case {submission.case_id} already exists")

        row = CaseRow(
            id=uuid.uuid4(),
            case_id=submission.case_id,
            case_version=1,
            state=CaseState.RECEIVED,
            submitted_by=caller_id,
            input_sha256=submission.digest(),
            procedure_code=submission.procedure_code,
            code_system=submission.code_system,
            jurisdiction=submission.jurisdiction,
            date_of_service=submission.date_of_service,
            created_at=datetime.now(UTC),
            updated_at=datetime.now(UTC),
        )
        self._session.add(row)

        writer = AuditWriter(self._session, case_id=submission.case_id, request_id=request_id)
        writer.record(
            EventType.CASE_RECEIVED,
            stage="submit",
            actor=ActorType.CALLER,
            actor_id=caller_id,
            payload={"input_sha256": row.input_sha256, "case_version": 1},
        )
        writer.record(
            EventType.CASE_VALIDATED,
            stage="submit",
            actor=ActorType.SYSTEM,
            payload={
                "procedure_code": submission.procedure_code,
                "code_system": submission.code_system,
                "diagnosis_code_count": len(submission.diagnosis_codes),
            },
        )
        await self._session.commit()
        return row

    async def run_case(
        self, submission: CaseSubmission, *, caller_id: str, request_id: str
    ) -> CaseRow:
        """Run the verified pipeline and persist what it concluded.

        The model call happens between two transactions, not inside one - see the
        module docstring.
        """
        if self._runner is None:
            raise MedauthError("no SliceRunner is configured; this deployment cannot run cases")

        case = await self.get(submission.case_id, caller_id=caller_id)
        case.state = require_transition(CaseState(case.state), CaseState.PROCESSING)
        await self._session.commit()

        try:
            outcome = await self._runner.run(
                SliceInput(
                    case_id=submission.case_id,
                    clinical_note=submission.clinical_note,
                    procedure_code=submission.procedure_code,
                    code_system=submission.code_system,
                    date_of_service=submission.date_of_service,
                    diagnosis_codes=submission.diagnosis_codes,
                    jurisdiction=submission.jurisdiction or None,
                )
            )
        except Exception as failure:
            await self._fail(case, request_id=request_id, reason=type(failure).__name__)
            raise

        return await self._persist(case, outcome, request_id=request_id)

    async def _persist(self, case: CaseRow, outcome: SliceOutcome, *, request_id: str) -> CaseRow:
        """The recommendation, the lifted trail and the state change, together."""
        writer = AuditWriter(self._session, case_id=case.case_id, request_id=request_id)
        # Lifted, not re-derived - the runtime produced these while doing the work.
        writer.record_slice(outcome.audit)

        recommendation = outcome.recommendation
        finding = outcome.applicability
        # The taxonomy travels on the runtime's own audit events - the outcome does not
        # carry a provider-failure field, and inventing one here would be a second
        # description of the same fact (R-99's shape).
        provider_failure, provider_attribution = _provider_failure_from(outcome)
        seq = (
            await self._session.execute(
                select(CaseRecommendationRow)
                .where(CaseRecommendationRow.case_uuid == case.id)
                .order_by(CaseRecommendationRow.run_seq.desc())
                .limit(1)
            )
        ).scalar_one_or_none()

        row = CaseRecommendationRow(
            id=uuid.uuid4(),
            case_uuid=case.id,
            run_seq=(seq.run_seq + 1) if seq else 1,
            outcome=recommendation.outcome.value,
            decision_rule=str(recommendation.rule),
            abstention_reason=(
                str(recommendation.abstention_reason) if recommendation.abstention_reason else None
            ),
            resolution_state=finding.state.value if finding else None,
            resolution_reason=finding.reason.value if finding else None,
            policy_type=outcome.identity.policy_type if outcome.identity else None,
            policy_id=outcome.identity.policy_id if outcome.identity else None,
            policy_version=outcome.identity.version if outcome.identity else None,
            provider_failure_kind=provider_failure,
            provider_failure_attribution=provider_attribution,
            model_id=outcome.model_id or None,
            model_calls=outcome.model_calls,
            prompt_tokens=int(outcome.tokens.get("prompt", 0)),
            completion_tokens=int(outcome.tokens.get("completion", 0)),
            latency_ms=int(sum(outcome.timings_ms.values())),
            confidence_state="UNCALIBRATED",
            created_at=datetime.now(UTC),
        )
        self._session.add(row)

        if provider_failure:
            # A broken response path, recorded as one. Never MODEL_WRONG.
            writer.record(
                EventType.PROVIDER_FAILURE,
                stage="adjudicate",
                provider_failure_kind=provider_failure,
                payload={"attribution": provider_attribution or "UNKNOWN"},
            )
        if recommendation.abstention_reason:
            writer.record(
                EventType.ABSTENTION,
                stage="decide",
                outcome=recommendation.outcome.value,
                abstention_reason=str(recommendation.abstention_reason),
            )
        writer.record(
            EventType.RECOMMENDATION_CREATED,
            stage="decide",
            outcome=recommendation.outcome.value,
            payload={"run_seq": row.run_seq, "decision_rule": str(recommendation.rule)},
        )

        target = _state_for(recommendation.outcome)
        case.state = require_transition(CaseState(case.state), target)
        case.updated_at = datetime.now(UTC)
        if target is CaseState.HUMAN_REVIEW:
            writer.record(
                EventType.HUMAN_REVIEW_REQUESTED,
                stage="route",
                outcome=recommendation.outcome.value,
                payload={"reason": "routed by outcome"},
            )
        await self._session.commit()
        return case

    async def _fail(self, case: CaseRow, *, request_id: str, reason: str) -> None:
        """A crashed run is never a clinical outcome."""
        writer = AuditWriter(self._session, case_id=case.case_id, request_id=request_id)
        writer.record(EventType.CASE_FAILED, stage="run", payload={"error_kind": reason})
        case.state = require_transition(CaseState(case.state), CaseState.FAILED)
        case.updated_at = datetime.now(UTC)
        await self._session.commit()
