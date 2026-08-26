"""What the trail records when a person decides — and what it records for the ones
who decided before there was a way to know.

OD-43 closed the identity gap going forward. It must not close it retroactively: a
historical review event has no authenticated principal, because there was none, and
back-filling one would make an old record look like evidence it is not.

So every row says which identity model it was written under, and this file asserts both
halves — `AUTHENTICATED_HUMAN` rows name a principal, and the database refuses one that
does not.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

import pytest
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from app.audit.models import HumanReviewAction, HumanReviewEventRow, ReviewOutcome
from app.case.lifecycle import CaseState
from app.case.review import HumanReviewService
from app.case.service import CaseService, CaseSubmission
from app.contracts.slice import CodeSystem
from app.identity.principal import (
    AuthenticationMethod,
    Permission,
    Principal,
    PrincipalType,
)

pytestmark = [pytest.mark.integration, pytest.mark.security]

CALLER = "integrator-a"


def reviewer(principal_id: str = "dr-alice") -> Principal:
    return Principal(
        principal_id=principal_id,
        principal_type=PrincipalType.HUMAN,
        authentication_method=AuthenticationMethod.OIDC,
        authenticated_at=datetime.now(UTC),
        display_name="Alice Reviewer",
        permissions=frozenset(
            {
                Permission.READ_CASE,
                Permission.REVIEW_CASE,
                Permission.OVERRIDE_RECOMMENDATION,
                Permission.FINALIZE_CASE,
            }
        ),
        issuer="https://idp.test/realms/medauth",
        stated_qualification="Board-certified radiologist",
    )


@pytest.fixture
def sessions(engine: AsyncEngine) -> async_sessionmaker[AsyncSession]:
    return async_sessionmaker(engine, expire_on_commit=False)


async def _case_in_review(sessions: async_sessionmaker[AsyncSession]) -> str:
    """A case sitting in HUMAN_REVIEW, via the real service and the real runner."""
    from datetime import date

    from tests.integration.test_application_lifecycle import (
        _runner,
        _satisfied_gateway,
    )
    from tests.support_slice import FixtureApplicability

    case_id = f"CASE-AUD-{uuid.uuid4().hex[:8]}"
    submission = CaseSubmission(
        case_id=case_id,
        clinical_note="Synthetic note for audit-identity testing. No real PHI.",
        procedure_code="R0075",
        code_system=CodeSystem.HCPCS.value,
        date_of_service=date(2026, 8, 13),
        jurisdiction="MAC-06",
    )
    async with sessions() as session:
        service = CaseService(session, runner=_runner(_satisfied_gateway(), FixtureApplicability()))
        await service.submit(submission, caller_id=CALLER, request_id="req-aud")
        await service.run_case(submission, caller_id=CALLER, request_id="req-aud")
    return case_id


@pytest.mark.asyncio
async def test_the_trail_records_the_authenticated_principal_not_a_typed_name(
    sessions: async_sessionmaker[AsyncSession],
) -> None:
    """**The point of OD-43.**

    `reviewer_id` and `principal_id` are both written and both come from the token.
    There is no parameter a caller could have used to make them differ, which is why
    the fix is an absence rather than a validation.
    """
    case_id = await _case_in_review(sessions)
    principal = reviewer()

    async with sessions() as session:
        cases = CaseService(session)
        await HumanReviewService(session, cases=cases).record(
            case_id,
            reviewer=principal,
            caller_id=CALLER,
            request_id="req-aud",
            action=HumanReviewAction.APPROVE,
        )

    async with sessions() as session:
        row = (
            await session.execute(
                select(HumanReviewEventRow).where(HumanReviewEventRow.case_id == case_id)
            )
        ).scalar_one()

        assert row.identity_model == "AUTHENTICATED_HUMAN"
        assert row.principal_id == principal.principal_id
        assert row.principal_type == PrincipalType.HUMAN.value
        assert row.authentication_method == AuthenticationMethod.OIDC.value
        assert row.identity_issuer == principal.issuer
        # The name and the authenticated subject agree, because only one of them exists.
        assert row.reviewer_id == principal.principal_id
        # The column is a String, so a re-read row holds the value, not the member.
        assert row.outcome == ReviewOutcome.APPROVED.value

        case = await CaseService(session).get(case_id, caller_id=CALLER)
        assert CaseState(case.state) is CaseState.FINALIZED


@pytest.mark.asyncio
async def test_the_database_refuses_an_authenticated_review_with_no_principal(
    engine: AsyncEngine,
) -> None:
    """The service always supplies one. The constraint is what makes that a guarantee
    rather than a habit - the API is not the only writer a deployment might have."""
    with pytest.raises(Exception):  # noqa: B017 - the driver's type is not the point
        async with engine.begin() as connection:
            await connection.execute(
                text(
                    "INSERT INTO human_review_events "
                    "(id, request_id, case_id, reviewer_id, reviewer_qualification, "
                    " action, identity_model, created_at) "
                    "VALUES (:id, 'r', 'CASE-X', 'dr-nobody', 'q', 'APPROVE', "
                    " 'AUTHENTICATED_HUMAN', :t)"
                ),
                {"id": uuid.uuid4(), "t": datetime.now(UTC)},
            )


@pytest.mark.asyncio
async def test_a_legacy_row_is_still_insertable_and_labelled(
    engine: AsyncEngine,
) -> None:
    """Historical rows are **preserved, not rewritten**.

    A review recorded before OD-43 has no authenticated principal because there was
    none. It is labelled `LEGACY_CALLER_SUPPLIED` so a reader can tell how much the
    identity on it is worth, rather than being back-filled with a principal that would
    make it look like evidence it is not.
    """
    case_id = f"CASE-LEG-{uuid.uuid4().hex[:8]}"
    async with engine.begin() as connection:
        await connection.execute(
            text(
                "INSERT INTO human_review_events "
                "(id, request_id, case_id, reviewer_id, reviewer_qualification, "
                " action, identity_model, created_at) "
                "VALUES (:id, 'r', :c, 'dr-legacy', 'stated at the time', 'APPROVE', "
                " 'LEGACY_CALLER_SUPPLIED', :t)"
            ),
            {"id": uuid.uuid4(), "c": case_id, "t": datetime.now(UTC)},
        )

    async with engine.connect() as connection:
        row = (
            await connection.execute(
                text(
                    "SELECT identity_model, principal_id FROM human_review_events "
                    "WHERE case_id = :c"
                ),
                {"c": case_id},
            )
        ).one()
    assert row[0] == "LEGACY_CALLER_SUPPLIED"
    assert row[1] is None, "a legacy row was back-filled with a principal it never had"


@pytest.mark.asyncio
async def test_a_review_event_still_cannot_be_rewritten(engine: AsyncEngine) -> None:
    """The identity columns join an append-only table; they do not weaken it."""
    case_id = f"CASE-IMM-{uuid.uuid4().hex[:8]}"
    async with engine.begin() as connection:
        await connection.execute(
            text(
                "INSERT INTO human_review_events "
                "(id, request_id, case_id, reviewer_id, reviewer_qualification, "
                " action, identity_model, principal_id, principal_type, "
                " authentication_method, created_at) "
                "VALUES (:id, 'r', :c, 'dr-alice', 'q', 'APPROVE', "
                " 'AUTHENTICATED_HUMAN', 'dr-alice', 'HUMAN', 'OIDC', :t)"
            ),
            {"id": uuid.uuid4(), "c": case_id, "t": datetime.now(UTC)},
        )

    for statement in (
        "UPDATE human_review_events SET principal_id = 'dr-someone-else' WHERE case_id = :c",
        "DELETE FROM human_review_events WHERE case_id = :c",
    ):
        with pytest.raises(Exception):  # noqa: B017
            async with engine.begin() as connection:
                await connection.execute(text(statement), {"c": case_id})

    async with engine.connect() as connection:
        surviving = (
            await connection.execute(
                text("SELECT principal_id FROM human_review_events WHERE case_id = :c"),
                {"c": case_id},
            )
        ).scalar()
    assert surviving == "dr-alice", "the recorded identity was rewritten"


@pytest.mark.asyncio
async def test_one_reviewer_cannot_be_recorded_as_another(
    sessions: async_sessionmaker[AsyncSession],
) -> None:
    """Impersonation, attempted the only way left.

    There is no `reviewer_id` parameter, so the strongest available attempt is to pass a
    principal built for somebody else - which is not an attack on the service, it is
    the authenticator being wrong. The service records exactly the principal it is
    handed, and the boundary that keeps that honest is token validation, tested in
    `test_reviewer_identity.py`.
    """
    import inspect

    signature = inspect.signature(HumanReviewService.record)
    for forbidden in ("reviewer_id", "accepted_by", "finalized_by", "principal_id"):
        assert forbidden not in signature.parameters, (
            f"`{forbidden}` is a parameter again - the identity is expressible by a "
            "caller, which is exactly OD-43"
        )
    assert "reviewer" in signature.parameters
