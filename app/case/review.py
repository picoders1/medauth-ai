"""A named person's decision, recorded beside the machine's — never over it.

`human_review_events` has existed since migration 0005 with the constraints that make
this safe. Nothing produced events. This is the service half.

## An override never edits the recommendation

`record()` inserts. It does not update `case_recommendations`, and there is no method
here that could. The reviewer's decision sits beside what the engine proposed, with
`recommended_outcome_at_review` denormalised onto the row, so "did the human agree, and
with what" is answerable from that one row forever - immune to anything that later
happens to the recommendation table.

That is the property Part I asks for, and it is enforced three ways: by the absence of an
update path here, by the append-only trigger in the database, and by
`ON DELETE RESTRICT` on the foreign key so the recommendation cannot be removed out from
under a decision that judged it.

## Why the rationale rule lives in two places

The database has a `CHECK` requiring a rationale for `DENY` and `OVERRIDE`. This service
checks it too, and that duplication is deliberate rather than sloppy: the constraint is
the guarantee, and the service check is what turns a violation into a 422 a caller can
act on instead of an opaque integrity error. If the two ever disagree, the database wins
and the caller gets a 500 - which is the right way round.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.audit.models import (
    CaseRecommendationRow,
    HumanReviewAction,
    HumanReviewEventRow,
    ReviewOutcome,
)
from app.audit.writer import ActorType, AuditWriter, EventType
from app.case.lifecycle import CaseState, require_transition
from app.case.service import CaseService
from app.core.errors import MedauthError


class ReviewRejected(MedauthError):
    """The submitted review cannot be recorded as given."""


#: Actions a later reader will ask "why" about. A rationale is required for both.
_REQUIRE_RATIONALE = frozenset({HumanReviewAction.DENY, HumanReviewAction.OVERRIDE})

#: What each action concludes clinically. `REQUEST_INFO` is not a conclusion, which is
#: why the case returns to `NEEDS_INFO` rather than finishing.
_OUTCOME_FOR = {
    HumanReviewAction.APPROVE: ReviewOutcome.APPROVED,
    HumanReviewAction.DENY: ReviewOutcome.DENIED,
    HumanReviewAction.REQUEST_INFO: ReviewOutcome.INFORMATION_REQUESTED,
}


def _not_routed_to_a_human(state: CaseState) -> ReviewRejected:
    return ReviewRejected(
        f"case is {state.value}, not {CaseState.HUMAN_REVIEW.value}; only a case routed "
        "to a human may be reviewed"
    )


class HumanReviewService:
    """Records decisions. Cannot edit one, by having no method that does."""

    def __init__(self, session: AsyncSession, *, cases: CaseService) -> None:
        self._session = session
        self._cases = cases

    async def record(
        self,
        case_id: str,
        *,
        caller_id: str,
        request_id: str,
        reviewer_id: str,
        reviewer_qualification: str,
        action: HumanReviewAction,
        rationale: str | None = None,
        override_outcome: ReviewOutcome | None = None,
    ) -> HumanReviewEventRow:
        """Append one review event and move the case. Raises rather than half-doing it."""
        case = await self._cases.get(case_id, caller_id=caller_id)

        if not reviewer_id.strip():
            raise ReviewRejected("a review must name its reviewer")
        if not reviewer_qualification.strip():
            raise ReviewRejected(
                f"{reviewer_id}: no qualification recorded. A later reader must be able "
                "to tell who was competent to make this decision."
            )
        if action in _REQUIRE_RATIONALE and not (rationale or "").strip():
            raise ReviewRejected(
                f"{action.value} requires a rationale. A denial or an override with no "
                "reason given is a decision nobody can review."
            )

        state = CaseState(case.state)
        if state is not CaseState.HUMAN_REVIEW:
            # Not a generic "wrong state" - reviewing a case nobody routed to a human
            # would let a reviewer finalise a case the engine never assessed.
            raise _not_routed_to_a_human(state)

        outcome = (
            override_outcome if action is HumanReviewAction.OVERRIDE else _OUTCOME_FOR.get(action)
        )
        if action is HumanReviewAction.OVERRIDE and outcome is None:
            raise ReviewRejected(
                "an override must say what it overrode TO; otherwise the record shows "
                "disagreement without a decision"
            )

        recommendation = (
            await self._session.execute(
                select(CaseRecommendationRow)
                .where(CaseRecommendationRow.case_uuid == case.id)
                .order_by(CaseRecommendationRow.run_seq.desc())
                .limit(1)
            )
        ).scalar_one_or_none()

        event = HumanReviewEventRow(
            id=uuid.uuid4(),
            request_id=request_id,
            case_id=case_id,
            recommendation_id=recommendation.id if recommendation else None,
            reviewer_id=reviewer_id.strip(),
            reviewer_qualification=reviewer_qualification.strip(),
            action=action,
            outcome=outcome,
            rationale=(rationale or "").strip() or None,
            # Denormalised on purpose - see the module docstring.
            recommended_outcome_at_review=recommendation.outcome if recommendation else None,
            created_at=datetime.now(UTC),
        )
        self._session.add(event)

        writer = AuditWriter(self._session, case_id=case_id, request_id=request_id)
        writer.record(
            EventType.HUMAN_DECISION_RECORDED,
            stage="review",
            actor=ActorType.HUMAN,
            actor_id=reviewer_id.strip(),
            outcome=str(outcome) if outcome else None,
            payload={
                "action": action.value,
                "agreed_with_engine": (
                    recommendation is not None and action is not HumanReviewAction.OVERRIDE
                ),
                "recommended_outcome_at_review": (
                    recommendation.outcome if recommendation else None
                ),
            },
        )

        # REQUEST_INFO returns the case to the submitter; everything else finishes it.
        target = (
            CaseState.NEEDS_INFO
            if action is HumanReviewAction.REQUEST_INFO
            else CaseState.FINALIZED
        )
        case.state = require_transition(state, target)
        case.updated_at = datetime.now(UTC)
        if target is CaseState.FINALIZED:
            writer.record(
                EventType.CASE_FINALIZED,
                stage="review",
                actor=ActorType.HUMAN,
                actor_id=reviewer_id.strip(),
                outcome=str(outcome) if outcome else None,
            )
        await self._session.commit()
        return event

    async def history(self, case_id: str, *, caller_id: str) -> list[HumanReviewEventRow]:
        """Every decision on this case, oldest first. Append-only, so this only grows."""
        await self._cases.get(case_id, caller_id=caller_id)
        rows = await self._session.execute(
            select(HumanReviewEventRow)
            .where(HumanReviewEventRow.case_id == case_id)
            .order_by(HumanReviewEventRow.created_at)
        )
        return list(rows.scalars())
