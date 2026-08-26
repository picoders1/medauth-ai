"""The whole lifecycle, end to end, with no live provider.

The previous phase left one honest gap: `run_case()` was implemented and audited but
never exercised. This closes it, and the claim it establishes is narrow and exact:

    APPLICATION_LIFECYCLE_VERIFIED_INDEPENDENT_OF_LIVE_PROVIDER

**Not** that the model is correct. **Not** that R-86 is fixed. A fixture gateway proves
that the application moves a case correctly through submission, execution, audit,
review and finalisation - which is a property of this code, and the only property a
fixture can carry.

## The fixture is the repository's own

`FakeGateway`, `FixtureRetrieval` and `FixtureApplicability` already existed in
`tests/support_slice.py` and are reused rather than rebuilt. `FakeGateway` returns
`UNKNOWN` for any criterion a test does not name, so a fixture cannot make a test pass
by omission.

Production cannot reach any of it:
`test_app_does_not_import_the_evaluation_harness_or_the_test_doubles` forbids `app/`
importing `tests`, proven non-vacuously by injecting the import and watching it fail.
Without that rule a production module could import `FakeGateway` and produce a
fully-formed recommendation with no model, no retrieval and no firewall - and every
downstream check would pass, because the shape would be perfect.
"""

from __future__ import annotations

import hashlib
import uuid
from datetime import UTC, date, datetime
from pathlib import Path

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from app.audit.models import (
    AuditEventRow,
    CaseRecommendationRow,
    HumanReviewAction,
    HumanReviewEventRow,
    ReviewOutcome,
)
from app.case.lifecycle import CaseState, InvalidTransition, require_transition
from app.case.review import HumanReviewService, ReviewRejected
from app.case.service import CaseService, CaseSubmission
from app.contracts.slice import AssessmentState, CodeSystem
from app.decision.semantics import Attestation, PolicySemantics, SemanticsOrigin
from app.graph.slice import RunMode, SliceRunner
from app.policy.logic_loader import load_policy_logic
from app.production_gate import ProductionGate
from tests.support_slice import (
    CRITERIA,
    IDENTITY,
    FakeGateway,
    FixtureApplicability,
    FixtureRetrieval,
    does_not_apply,
)

pytestmark = [pytest.mark.integration, pytest.mark.security]

CALLER = "integrator-a"
REVIEWER = "dr-reviewer-1"
QUALIFICATION = "Board-certified radiologist, NPI on file"


# --------------------------------------------------------------------------- setup


CONFIG_VERSION = "slice.v1"
REPO = Path(__file__).resolve().parents[2]


def _semantics() -> PolicySemantics:
    """The declared logic for the slice policy, attested from its own file.

    Built the same way `test_case_0073_regression` builds it - production refuses an
    unattested assumption, and a fixture that hand-rolled one would be testing a path
    the deployment cannot take.
    """
    path = REPO / "data/policy_logic/42-CFR-410.33.yaml"
    return PolicySemantics.declared(
        policy_id="42 CFR 410.33",
        policy_version="2026-08-13",
        logic=load_policy_logic(path, known_criteria=frozenset(c.criterion_id for c in CRITERIA)),
        attestation=Attestation(
            source=str(path.relative_to(REPO)),
            sha256=hashlib.sha256(path.read_bytes()).hexdigest(),
            origin=SemanticsOrigin.DECLARED_LOGIC_FILE,
        ),
    )


def _runner(gateway: FakeGateway, applicability: object) -> SliceRunner:
    return SliceRunner(
        gateway=gateway,  # type: ignore[arg-type]
        retrieval=FixtureRetrieval(),  # type: ignore[arg-type]
        identity=IDENTITY,
        criteria=CRITERIA,
        semantics=_semantics(),
        decision_config_version=CONFIG_VERSION,
        gate=ProductionGate(
            admissibility_report=REPO / "data/review/slice_admissibility.json",
            decision_records=(REPO / "data/review/focus_001_decision.json",),
        ).evaluate(),
        mode=RunMode.PRODUCTION,
        applicability=applicability,  # type: ignore[arg-type]
    )


def _submission(case_id: str) -> CaseSubmission:
    return CaseSubmission(
        case_id=case_id,
        clinical_note=(
            "HISTORY OF PRESENT ILLNESS\nSynthetic note for lifecycle testing. "
            "No real PHI. Prior conservative management documented."
        ),
        procedure_code="R0075",
        code_system=CodeSystem.HCPCS.value,
        date_of_service=date(2026, 8, 13),
        diagnosis_codes=("J18.9",),
        jurisdiction="MAC-06",
    )


@pytest.fixture
def sessions(engine: AsyncEngine) -> async_sessionmaker[AsyncSession]:
    return async_sessionmaker(engine, expire_on_commit=False)


def new_case_id() -> str:
    return f"CASE-E2E-{uuid.uuid4().hex[:8]}"


async def _events(session: AsyncSession, case_id: str) -> list[AuditEventRow]:
    rows = await session.execute(
        select(AuditEventRow)
        .where(AuditEventRow.case_id == case_id)
        .order_by(AuditEventRow.created_at)
    )
    return list(rows.scalars())


async def _run_to_review(
    sessions: async_sessionmaker[AsyncSession], gateway: FakeGateway
) -> tuple[str, str]:
    """Submit and run one case. Returns `(case_id, request_id)`."""
    case_id, request_id = new_case_id(), f"req-{uuid.uuid4().hex[:12]}"
    submission = _submission(case_id)
    async with sessions() as session:
        service = CaseService(session, runner=_runner(gateway, FixtureApplicability()))
        await service.submit(submission, caller_id=CALLER, request_id=request_id)
        await service.run_case(submission, caller_id=CALLER, request_id=request_id)
    return case_id, request_id


def _satisfied_gateway() -> FakeGateway:
    """Every criterion SATISFIED - a definitive draft, which must still reach a human.

    This is the shape that matters most for this phase. An approval that could finish
    on its own would make this a system that issues determinations; the lifecycle has
    to route it to a person, and the tests below prove it does.
    """
    return FakeGateway(
        assessments={
            # By KIND, not blanket-SATISFIED. Marking everything satisfied also
            # satisfies the EXCLUSION, which denies - correct table behaviour, and it
            # made the first version of this fixture produce a denial while claiming to
            # be the approval path.
            c.criterion_id: (
                AssessmentState.NOT_SATISFIED
                if str(c.kind) == "EXCLUSION"
                else AssessmentState.SATISFIED
            )
            for c in CRITERIA
        },
        citations={c.criterion_id: ("E1",) for c in CRITERIA},
    )


def _denial_draft_gateway() -> FakeGateway:
    """A satisfied exclusion. Produces `DENY_RECOMMENDED` - which must still reach a
    person, and is the case where that matters most."""
    return FakeGateway(
        assessments={c.criterion_id: AssessmentState.SATISFIED for c in CRITERIA},
        citations={c.criterion_id: ("E1",) for c in CRITERIA},
    )


def _unknown_gateway() -> FakeGateway:
    """Every criterion UNKNOWN - reaches row 6, `INSUFFICIENT_EVIDENCE` -> NEEDS_INFO.

    The decision table evaluates "the note does not say" *before* "the note says
    otherwise", which is what stops this system denying for missing paperwork. This
    case is a question for the SUBMITTER, not a reviewer task - and the lifecycle
    distinguishes the two.
    """
    return FakeGateway(
        assessments={c.criterion_id: AssessmentState.UNKNOWN for c in CRITERIA},
        citations={c.criterion_id: ("E1",) for c in CRITERIA},
    )


# --------------------------------------------------------------------------- 1
# Part D - the success path
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_submit_run_review_finalize(
    sessions: async_sessionmaker[AsyncSession],
) -> None:
    """**The load-bearing test of this phase.** Every state, asserted in order."""
    case_id, request_id = new_case_id(), f"req-{uuid.uuid4().hex[:12]}"
    submission = _submission(case_id)
    gateway = _satisfied_gateway()

    # -- submit -----------------------------------------------------------
    async with sessions() as session:
        service = CaseService(session, runner=_runner(gateway, FixtureApplicability()))
        case = await service.submit(submission, caller_id=CALLER, request_id=request_id)
        assert case.case_id == case_id
        assert CaseState(case.state) is CaseState.RECEIVED
        assert case.submitted_by == CALLER
        assert len(case.input_sha256) == 64

        events = await _events(session, case_id)
        assert [e.event for e in events] == ["CASE_RECEIVED", "CASE_VALIDATED"]
        assert all(e.request_id == request_id for e in events)

    # -- run --------------------------------------------------------------
    async with sessions() as session:
        service = CaseService(session, runner=_runner(gateway, FixtureApplicability()))
        case = await service.run_case(submission, caller_id=CALLER, request_id=request_id)

    async with sessions() as session:
        service = CaseService(session)
        case = await service.get(case_id, caller_id=CALLER)
        # A definitive draft is routed to a person - never finished on its own.
        assert CaseState(case.state) is CaseState.HUMAN_REVIEW

        recommendation = await service.latest_recommendation(case_id, caller_id=CALLER)
        assert recommendation is not None
        assert recommendation.run_seq == 1
        assert recommendation.outcome == "APPROVE_RECOMMENDED"
        assert recommendation.decision_rule
        assert recommendation.policy_id, "the recommendation records no policy identity"
        assert recommendation.policy_version
        assert recommendation.confidence_state == "UNCALIBRATED"
        assert recommendation.model_calls >= 1, "the fixture gateway was never called"

        # -- audit linkage -------------------------------------------------
        events = await _events(session, case_id)
        names = [e.event for e in events]
        assert names[:2] == ["CASE_RECEIVED", "CASE_VALIDATED"]
        assert "RECOMMENDATION_CREATED" in names
        assert "HUMAN_REVIEW_REQUESTED" in names
        assert "RUNTIME_STAGE" in names, "the runtime's own stage events were not lifted"
        assert all(e.case_id == case_id for e in events)
        assert all(e.request_id == request_id for e in events)
        assert all((e.payload or {}).get("correlation_id") == request_id for e in events)

        stages = {e.stage for e in events if e.event == "RUNTIME_STAGE"}
        assert stages, "no runtime stages were recorded"
        assert any((e.payload or {}).get("chunk_ids") for e in events), (
            "no evidence references reached the trail"
        )

    # -- review -----------------------------------------------------------
    async with sessions() as session:
        cases = CaseService(session)
        reviews = HumanReviewService(session, cases=cases)
        event = await reviews.record(
            case_id,
            caller_id=CALLER,
            request_id=request_id,
            reviewer_id=REVIEWER,
            reviewer_qualification=QUALIFICATION,
            action=HumanReviewAction.APPROVE,
        )
        assert event.reviewer_id == REVIEWER
        assert event.outcome is ReviewOutcome.APPROVED
        assert event.recommended_outcome_at_review == recommendation.outcome
        assert event.created_at is not None

    # -- finalized --------------------------------------------------------
    async with sessions() as session:
        case = await CaseService(session).get(case_id, caller_id=CALLER)
        assert CaseState(case.state) is CaseState.FINALIZED

        names = [e.event for e in await _events(session, case_id)]
        assert names[-2:] == ["HUMAN_DECISION_RECORDED", "CASE_FINALIZED"]


@pytest.mark.asyncio
async def test_a_denial_draft_also_requires_a_human(
    sessions: async_sessionmaker[AsyncSession],
) -> None:
    """The case where it matters most.

    A denial that could finish on its own would be this system issuing coverage
    determinations. It reaches `HUMAN_REVIEW` like any other definitive draft, and the
    reviewer who confirms it must give a rationale.
    """
    case_id, request_id = await _run_to_review(sessions, _denial_draft_gateway())

    async with sessions() as session:
        service = CaseService(session)
        case = await service.get(case_id, caller_id=CALLER)
        recommendation = await service.latest_recommendation(case_id, caller_id=CALLER)
        assert recommendation is not None
        assert recommendation.outcome == "DENY_RECOMMENDED"
        assert CaseState(case.state) is CaseState.HUMAN_REVIEW
        assert CaseState(case.state) is not CaseState.FINALIZED

    # A confirming denial still needs its reason.
    async with sessions() as session:
        cases = CaseService(session)
        with pytest.raises(ReviewRejected, match="rationale"):
            await HumanReviewService(session, cases=cases).record(
                case_id,
                caller_id=CALLER,
                request_id=request_id,
                reviewer_id=REVIEWER,
                reviewer_qualification=QUALIFICATION,
                action=HumanReviewAction.DENY,
            )


# --------------------------------------------------------------------------- 2
# Part E - the override path
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_an_override_preserves_the_recommendation_it_disagreed_with(
    sessions: async_sessionmaker[AsyncSession],
) -> None:
    """The AI recommendation is never overwritten destructively."""
    case_id, request_id = await _run_to_review(sessions, _satisfied_gateway())

    async with sessions() as session:
        before = await CaseService(session).latest_recommendation(case_id, caller_id=CALLER)
        assert before is not None
        original_outcome, original_id = before.outcome, before.id

    async with sessions() as session:
        cases = CaseService(session)
        event = await HumanReviewService(session, cases=cases).record(
            case_id,
            caller_id=CALLER,
            request_id=request_id,
            reviewer_id=REVIEWER,
            reviewer_qualification=QUALIFICATION,
            action=HumanReviewAction.OVERRIDE,
            rationale="Prior imaging in the chart resolves the open criterion.",
            override_outcome=ReviewOutcome.APPROVED,
        )
        assert event.action is HumanReviewAction.OVERRIDE
        assert event.outcome is ReviewOutcome.APPROVED
        assert event.rationale
        assert event.recommendation_id == original_id

    async with sessions() as session:
        after = await CaseService(session).latest_recommendation(case_id, caller_id=CALLER)
        assert after is not None
        # **The point of the test.** The engine's conclusion is untouched.
        assert after.id == original_id
        assert after.outcome == original_outcome

        case = await CaseService(session).get(case_id, caller_id=CALLER)
        assert CaseState(case.state) is CaseState.FINALIZED

        reviews = list(
            (
                await session.execute(
                    select(HumanReviewEventRow).where(HumanReviewEventRow.case_id == case_id)
                )
            ).scalars()
        )
        assert len(reviews) == 1
        assert reviews[0].recommended_outcome_at_review == original_outcome


# --------------------------------------------------------------------------- 3
# Part F - request information
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_request_information_does_not_finalize_and_keeps_the_case_reviewable(
    sessions: async_sessionmaker[AsyncSession],
) -> None:
    case_id, request_id = await _run_to_review(sessions, _satisfied_gateway())

    async with sessions() as session:
        cases = CaseService(session)
        await HumanReviewService(session, cases=cases).record(
            case_id,
            caller_id=CALLER,
            request_id=request_id,
            reviewer_id=REVIEWER,
            reviewer_qualification=QUALIFICATION,
            action=HumanReviewAction.REQUEST_INFO,
            rationale="Please supply the prior imaging report.",
        )

    async with sessions() as session:
        case = await CaseService(session).get(case_id, caller_id=CALLER)
        assert CaseState(case.state) is CaseState.NEEDS_INFO
        assert CaseState(case.state) is not CaseState.FINALIZED

        # The recommendation survives untouched.
        recommendation = await CaseService(session).latest_recommendation(case_id, caller_id=CALLER)
        assert recommendation is not None

        # And the case can still reach a human again rather than being stranded.
        assert CaseState.HUMAN_REVIEW in {
            CaseState.HUMAN_REVIEW,
            CaseState.PROCESSING,
        }
        require_transition(CaseState.NEEDS_INFO, CaseState.HUMAN_REVIEW)

    # Finalisation is impossible while the case sits in NEEDS_INFO.
    async with sessions() as session:
        cases = CaseService(session)
        with pytest.raises(ReviewRejected):
            await HumanReviewService(session, cases=cases).record(
                case_id,
                caller_id=CALLER,
                request_id=request_id,
                reviewer_id=REVIEWER,
                reviewer_qualification=QUALIFICATION,
                action=HumanReviewAction.APPROVE,
            )


# --------------------------------------------------------------------------- 4
# Part G - a provider-like failure
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_a_provider_like_failure_never_becomes_approve_or_deny(
    sessions: async_sessionmaker[AsyncSession],
) -> None:
    """A fixture simulation of the R-86 shape. **This does not fix or test R-86.**

    R-86 is a live provider defect, attributed PROVIDER_SIDE with its root cause not
    established. What this proves is the application's half: when the provider path
    fails, the case reaches a human and never a clinical answer.
    """
    from app.llm.gateway import GatewayOutcome

    gateway = FakeGateway(
        assessments={c.criterion_id: AssessmentState.SATISFIED for c in CRITERIA},
        citations={c.criterion_id: ("E1",) for c in CRITERIA},
        # SCHEMA_INVALID is R-86's downstream shape: the call returned, and what came
        # back could not be used. The fixture asserts nothing about WHY - that is the
        # provider's question and it is still open.
        fail_assessment=GatewayOutcome.SCHEMA_INVALID,
    )
    case_id, _ = await _run_to_review(sessions, gateway)

    async with sessions() as session:
        service = CaseService(session)
        case = await service.get(case_id, caller_id=CALLER)
        recommendation = await service.latest_recommendation(case_id, caller_id=CALLER)
        assert recommendation is not None

        # No clinical answer, whatever the fixture "wanted" to assess.
        assert recommendation.outcome not in {"APPROVE_RECOMMENDED", "DENY_RECOMMENDED"}
        # And the case is a person's problem now.
        assert CaseState(case.state) in {CaseState.HUMAN_REVIEW, CaseState.NEEDS_INFO}
        assert CaseState(case.state) is not CaseState.FINALIZED

        names = [e.event for e in await _events(session, case_id)]
        assert "RECOMMENDATION_CREATED" in names


# --------------------------------------------------------------------------- 5
# Part K - finalization safety
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_a_recommendation_cannot_be_finalized_without_a_human(
    sessions: async_sessionmaker[AsyncSession],
) -> None:
    """Asserted at the machine, because that is where it is enforced."""
    with pytest.raises(InvalidTransition):
        require_transition(CaseState.RECOMMENDATION_READY, CaseState.FINALIZED)
    with pytest.raises(InvalidTransition):
        require_transition(CaseState.FAILED, CaseState.FINALIZED)
    with pytest.raises(InvalidTransition):
        require_transition(CaseState.FINALIZED, CaseState.HUMAN_REVIEW)


@pytest.mark.asyncio
async def test_a_finalized_case_cannot_be_reviewed_again(
    sessions: async_sessionmaker[AsyncSession],
) -> None:
    """Part L: a duplicate finalisation is **REJECTED**, not idempotent.

    Two reviewers must not both be able to finalise. The second attempt fails loudly
    rather than silently succeeding, because "already done" and "you did it" are
    different answers to give a reviewer.
    """
    case_id, request_id = await _run_to_review(sessions, _satisfied_gateway())

    async with sessions() as session:
        cases = CaseService(session)
        await HumanReviewService(session, cases=cases).record(
            case_id,
            caller_id=CALLER,
            request_id=request_id,
            reviewer_id=REVIEWER,
            reviewer_qualification=QUALIFICATION,
            action=HumanReviewAction.APPROVE,
        )

    async with sessions() as session:
        cases = CaseService(session)
        with pytest.raises(ReviewRejected):
            await HumanReviewService(session, cases=cases).record(
                case_id,
                caller_id=CALLER,
                request_id=request_id,
                reviewer_id="dr-reviewer-2",
                reviewer_qualification=QUALIFICATION,
                action=HumanReviewAction.DENY,
                rationale="Second opinion.",
            )

    async with sessions() as session:
        reviews = list(
            (
                await session.execute(
                    select(HumanReviewEventRow).where(HumanReviewEventRow.case_id == case_id)
                )
            ).scalars()
        )
        assert len(reviews) == 1, "a second decision was recorded on a finalised case"


@pytest.mark.asyncio
async def test_a_duplicate_submission_is_rejected(
    sessions: async_sessionmaker[AsyncSession],
) -> None:
    """Part L: **REJECTED**, not idempotent. Case ids are the caller's, and silently
    returning the existing case would hide a collision between two different requests
    that happened to choose the same id."""
    from app.core.errors import MedauthError

    case_id = new_case_id()
    submission = _submission(case_id)
    async with sessions() as session:
        await CaseService(session).submit(submission, caller_id=CALLER, request_id="req-1")
    async with sessions() as session:
        with pytest.raises(MedauthError, match="already exists"):
            await CaseService(session).submit(submission, caller_id=CALLER, request_id="req-2")


@pytest.mark.asyncio
async def test_a_second_run_appends_a_recommendation_rather_than_replacing_one(
    sessions: async_sessionmaker[AsyncSession],
) -> None:
    """Part L: **ACCEPTED**, and additive.

    A case may legitimately be re-run - after a corpus refresh, or once a provider
    outage clears. The earlier recommendation is not overwritten; `run_seq` orders
    them, so the record shows what was concluded and when.
    """
    case_id, request_id = await _run_to_review(sessions, _satisfied_gateway())
    submission = _submission(case_id)

    async with sessions() as session:
        cases = CaseService(session)
        await HumanReviewService(session, cases=cases).record(
            case_id,
            caller_id=CALLER,
            request_id=request_id,
            reviewer_id=REVIEWER,
            reviewer_qualification=QUALIFICATION,
            action=HumanReviewAction.REQUEST_INFO,
            rationale="More detail please.",
        )

    async with sessions() as session:
        service = CaseService(session, runner=_runner(_satisfied_gateway(), FixtureApplicability()))
        await service.run_case(submission, caller_id=CALLER, request_id=request_id)

    async with sessions() as session:
        rows = list(
            (
                await session.execute(
                    select(CaseRecommendationRow)
                    .join(
                        __import__("app.audit.models", fromlist=["CaseRow"]).CaseRow,
                        CaseRecommendationRow.case_uuid
                        == __import__("app.audit.models", fromlist=["CaseRow"]).CaseRow.id,
                    )
                    .where(
                        __import__("app.audit.models", fromlist=["CaseRow"]).CaseRow.case_id
                        == case_id
                    )
                    .order_by(CaseRecommendationRow.run_seq)
                )
            ).scalars()
        )
        assert [r.run_seq for r in rows] == [1, 2]


# --------------------------------------------------------------------------- 6
# Part J - authorization through the lifecycle
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_another_caller_cannot_review_and_cannot_tell_the_case_exists(
    sessions: async_sessionmaker[AsyncSession],
) -> None:
    from app.case.service import CaseNotFound

    case_id, request_id = await _run_to_review(sessions, _satisfied_gateway())

    async with sessions() as session:
        cases = CaseService(session)
        with pytest.raises(CaseNotFound):
            await cases.get(case_id, caller_id="someone-else")
        with pytest.raises(CaseNotFound):
            await HumanReviewService(session, cases=cases).record(
                case_id,
                caller_id="someone-else",
                request_id=request_id,
                reviewer_id="intruder",
                reviewer_qualification="none",
                action=HumanReviewAction.APPROVE,
            )


# --------------------------------------------------------------------------- 7
# Parts H, I, N - the trail itself
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_the_lifecycle_trail_survives_every_mutation_attempt(
    sessions: async_sessionmaker[AsyncSession], engine: AsyncEngine
) -> None:
    """Part I, against **real lifecycle rows** rather than a synthetic one."""
    from sqlalchemy import text

    case_id, request_id = await _run_to_review(sessions, _satisfied_gateway())
    async with sessions() as session:
        cases = CaseService(session)
        await HumanReviewService(session, cases=cases).record(
            case_id,
            caller_id=CALLER,
            request_id=request_id,
            reviewer_id=REVIEWER,
            reviewer_qualification=QUALIFICATION,
            action=HumanReviewAction.APPROVE,
        )

    async with sessions() as session:
        before = len(await _events(session, case_id))
    assert before > 3, "the lifecycle wrote too few events for this test to mean anything"

    for statement, params in (
        ("UPDATE audit_events SET event = 'tampered' WHERE case_id = :c", {"c": case_id}),
        ("DELETE FROM audit_events WHERE case_id = :c", {"c": case_id}),
        ("TRUNCATE audit_events", {}),
        ("UPDATE human_review_events SET action = 'DENY' WHERE case_id = :c", {"c": case_id}),
        ("DELETE FROM human_review_events WHERE case_id = :c", {"c": case_id}),
    ):
        with pytest.raises(Exception):  # noqa: B017 - the driver's type is not the point
            async with engine.begin() as connection:
                await connection.execute(text(statement), params)

    async with sessions() as session:
        assert len(await _events(session, case_id)) == before


@pytest.mark.asyncio
async def test_the_trail_carries_no_clinical_text(
    sessions: async_sessionmaker[AsyncSession],
) -> None:
    """Part N. Checked against the note that was actually submitted."""
    case_id, _ = await _run_to_review(sessions, _satisfied_gateway())
    note = _submission(case_id).clinical_note

    async with sessions() as session:
        events = await _events(session, case_id)
        blob = " ".join(f"{e.event}{e.stage}{e.payload}" for e in events)

    words = note.split()
    for start in range(0, len(words) - 5, 3):
        window = " ".join(words[start : start + 5])
        assert window not in blob, f"the trail quotes the clinical note: {window!r}"
    for forbidden in ("prompt", "completion", "Bearer ", "api_key"):
        assert forbidden not in blob


# --------------------------------------------------------------------------- 8
# Applicability refuses before any model call
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_an_inapplicable_case_never_reaches_the_model(
    sessions: async_sessionmaker[AsyncSession],
) -> None:
    """CASE-0073's shape, through the whole application.

    A denial with seven verified citations against a policy that did not govern the
    case is what R-93 was. The lifecycle must refuse before spending a model call.
    """
    case_id, request_id = new_case_id(), f"req-{uuid.uuid4().hex[:12]}"
    submission = _submission(case_id)
    refusing = FixtureApplicability(finding=does_not_apply())
    # Every criterion NOT_SATISFIED - the shape that reaches row 8 and denies. If the
    # model were consulted at all, this fixture would produce a denial.
    gateway = FakeGateway(
        assessments={c.criterion_id: AssessmentState.NOT_SATISFIED for c in CRITERIA},
        citations={c.criterion_id: ("E1",) for c in CRITERIA},
    )

    async with sessions() as session:
        service = CaseService(session, runner=_runner(gateway, refusing))
        await service.submit(submission, caller_id=CALLER, request_id=request_id)
        await service.run_case(submission, caller_id=CALLER, request_id=request_id)

    assert gateway.calls == [], "the model was called for a case no policy governs"

    async with sessions() as session:
        service = CaseService(session)
        case = await service.get(case_id, caller_id=CALLER)
        recommendation = await service.latest_recommendation(case_id, caller_id=CALLER)
        assert recommendation is not None
        assert recommendation.outcome != "DENY_RECOMMENDED"
        assert CaseState(case.state) is not CaseState.FINALIZED


@pytest.mark.asyncio
async def test_retention_still_works_on_lifecycle_rows(
    sessions: async_sessionmaker[AsyncSession], engine: AsyncEngine
) -> None:
    from sqlalchemy import text

    case_id, _ = await _run_to_review(sessions, _satisfied_gateway())
    async with sessions() as session:
        assert await _events(session, case_id)

    async with engine.begin() as connection:
        removed = (
            await connection.execute(
                text("SELECT purge_audit_before(:before)"),
                {"before": datetime.now(UTC).replace(year=2099)},
            )
        ).scalar()
    assert removed is not None and removed >= 1

    async with sessions() as session:
        assert await _events(session, case_id) == []
