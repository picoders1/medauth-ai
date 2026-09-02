"""The contract the reviewer console consumes, asserted against the running API.

These are regression tests for defects found in the React SPA (`web/`). Each one failed
before the corresponding fix and pins the behaviour the console now depends on.

## Why these live here rather than in the frontend

Every claim below is about what the **server** publishes: which state names it emits,
which action tokens it emits, which permission facts it reports, and what its error
envelope looks like. A test in `web/` could only assert what a fixture the frontend
author wrote contains - which is exactly how the original defect survived. The
concurrent attempt at these tests asserted `available_actions: ['ACCEPT', 'OVERRIDE']`,
tokens the server has never emitted, and would have passed against the broken UI.

The other half - that the TypeScript in `web/` matches these same server enums - is
`tests/unit/test_spa_contract_conformance.py`, which reads both sources.

## No model calls

States are reached by driving the legal transitions in `app/case/lifecycle.py` directly.
No `SliceRunner` is configured, no provider is contacted, and nothing under `data/` or
`eval/` is touched.
"""

from __future__ import annotations

import asyncio
import uuid
from collections.abc import AsyncIterator, Iterator

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.api.main import create_app
from app.api.v1.routes import session_for
from app.audit.models import CaseRow
from app.case.lifecycle import CaseState, require_transition
from app.config.settings import Settings
from app.database.engine import build_engine
from app.identity.principal import Permission

pytestmark = [pytest.mark.api, pytest.mark.security]

API_KEY = "key-integrator-00000"
#: READ, REVIEW, OVERRIDE, FINALIZE - may do everything.
SENIOR = "tok-senior"
#: READ, REVIEW, FINALIZE - may accept and request info, may NOT override.
REVIEWER = "tok-reviewer"
#: READ only - may do nothing.
READONLY = "tok-readonly"


def _database_url() -> str:
    import os

    return os.environ.get(
        "MEDAUTH_TEST_DATABASE_URL",
        "postgresql+asyncpg://medauth:medauth@localhost:5435/medauth_test",
    )


@pytest.fixture
def client() -> Iterator[TestClient]:
    settings = Settings(  # type: ignore[call-arg]
        _env_file=None,
        database_url=_database_url(),
        api_keys=f"{API_KEY}:integrator-a",
        auth_mode="development",
        dev_reviewers=(
            f"{SENIOR}:dr-senior:medauth-senior-reviewer,"
            f"{REVIEWER}:dr-reviewer:medauth-reviewer,"
            f"{READONLY}:dr-readonly:medauth-readonly"
        ),
    )
    application = create_app(settings)
    factory = async_sessionmaker(build_engine(settings), expire_on_commit=False)

    async def _session() -> AsyncIterator[AsyncSession]:
        async with factory() as session:
            yield session

    application.dependency_overrides[session_for] = _session
    application.state.session_factory = factory
    with TestClient(application) as test_client:
        yield test_client


def headers(reviewer_token: str | None = SENIOR) -> dict[str, str]:
    head = {"x-api-key": API_KEY}
    if reviewer_token:
        head["authorization"] = f"Bearer {reviewer_token}"
    return head


def new_case(client: TestClient, **overrides: object) -> str:
    """Submit a case. Leaves it in RECEIVED - `POST /cases` does not run anything."""
    case_id = f"CASE-SPA-{uuid.uuid4().hex[:8]}"
    body: dict[str, object] = {
        "case_id": case_id,
        "clinical_note": "Synthetic note for SPA contract testing. No real PHI.",
        "procedure_code": "R0075",
        "code_system": "HCPCS",
        "date_of_service": "2026-08-13",
    }
    body.update(overrides)
    response = client.post("/api/v1/cases", json=body, headers={"x-api-key": API_KEY})
    assert response.status_code == 201, response.text
    return case_id


def drive(case_id: str, *path: CaseState) -> None:
    """Walk a case along legal transitions. Deterministic; no pipeline, no model.

    Each hop goes through `require_transition`, so this helper cannot put a case into a
    state the lifecycle forbids - a test asking for an illegal shortcut fails here rather
    than asserting against a row the machine cannot produce.

    Synchronous, with its own engine opened and disposed inside one `asyncio.run`. The
    `TestClient` drives the app on a portal loop of its own, and an asyncpg connection
    made on one loop cannot be awaited on another; sharing a session factory between the
    two produces "attached to a different loop" rather than a test failure worth reading.
    """

    async def _run() -> None:
        settings = Settings(_env_file=None, database_url=_database_url())  # type: ignore[call-arg]
        engine = build_engine(settings)
        try:
            async with async_sessionmaker(engine, expire_on_commit=False)() as session:
                row = (
                    await session.execute(select(CaseRow).where(CaseRow.case_id == case_id))
                ).scalar_one()
                for target in path:
                    row.state = require_transition(CaseState(row.state), target)
                await session.commit()
        finally:
            await engine.dispose()

    asyncio.run(_run())


def review_view(client: TestClient, case_id: str, token: str = SENIOR) -> dict:  # type: ignore[type-arg]
    response = client.get(f"/api/v1/cases/{case_id}/review", headers=headers(token))
    assert response.status_code == 200, response.text
    return response.json()


# --------------------------------------------------------------------------- D1
# Lifecycle vocabulary
# ---------------------------------------------------------------------------


def test_every_state_the_server_can_emit_is_reachable_and_reported(client: TestClient) -> None:
    """**Regression, defect 1.** The console declared six state names, four of which the
    server cannot emit (`CREATED`, `SUBMITTED`, `FINAL_INFO`, `CLOSED`), and lacked four
    the server does emit (`RECEIVED`, `PROCESSING`, `NEEDS_INFO`, `FINALIZED`, `FAILED`).

    The consequence was not cosmetic: unknown names fell through to a neutral chip, so a
    **FAILED** case rendered as unremarkable.

    Every state is driven along a legal path and read back through the API, so this
    asserts the wire value rather than the enum's repr.
    """
    paths: dict[CaseState, tuple[CaseState, ...]] = {
        CaseState.RECEIVED: (),
        CaseState.PROCESSING: (CaseState.PROCESSING,),
        CaseState.RECOMMENDATION_READY: (CaseState.PROCESSING, CaseState.RECOMMENDATION_READY),
        CaseState.NEEDS_INFO: (CaseState.NEEDS_INFO,),
        CaseState.HUMAN_REVIEW: (CaseState.HUMAN_REVIEW,),
        CaseState.FINALIZED: (CaseState.HUMAN_REVIEW, CaseState.FINALIZED),
        CaseState.FAILED: (CaseState.FAILED,),
    }
    assert set(paths) == set(CaseState), "a lifecycle state has no coverage here"

    for expected, path in paths.items():
        case_id = new_case(client)
        drive(case_id, *path)
        body = client.get(f"/api/v1/cases/{case_id}", headers={"x-api-key": API_KEY}).json()
        assert body["state"] == expected.value
        # And the reviewer view agrees - the console reads state from both.
        assert review_view(client, case_id)["state"] == expected.value


# --------------------------------------------------------------------------- D2/D4
# Action vocabulary and state gating
# ---------------------------------------------------------------------------


def test_the_action_tokens_are_the_long_form_names(client: TestClient) -> None:
    """**Regression, defect 2.** The console tested `available_actions.includes('OVERRIDE')`.

    The server emits `OVERRIDE_RECOMMENDATION`. `Array.includes` is exact, so override was
    unreachable in the UI for every reviewer, however senior. This pins the exact tokens
    so a shortened name cannot be reintroduced on either side.
    """
    case_id = new_case(client)
    drive(case_id, CaseState.HUMAN_REVIEW)

    actions = review_view(client, case_id)["available_actions"]
    assert sorted(actions) == [
        "ACCEPT_RECOMMENDATION",
        "OVERRIDE_RECOMMENDATION",
        "REQUEST_INFORMATION",
    ]
    # The short forms the console guessed are not, and were never, emitted.
    for guess in ("ACCEPT", "OVERRIDE", "REQUEST_INFO"):
        assert guess not in actions


def test_actions_are_published_only_while_the_case_is_open_for_review(client: TestClient) -> None:
    """**Regression, defect 4.** Accept and request-info consulted nothing and stayed
    clickable on any case, including a finalised one, so the UI offered actions the
    service would refuse.

    Only `HUMAN_REVIEW` publishes actions. Every other state publishes none - including
    the two terminal ones, where no reviewer of any authority could act.
    """
    for path in (
        (),
        (CaseState.PROCESSING,),
        (CaseState.PROCESSING, CaseState.RECOMMENDATION_READY),
        (CaseState.NEEDS_INFO,),
        (CaseState.FAILED,),
        (CaseState.HUMAN_REVIEW, CaseState.FINALIZED),
    ):
        case_id = new_case(client)
        drive(case_id, *path)
        body = review_view(client, case_id)
        assert body["available_actions"] == [], f"actions were offered on a {body['state']} case"


def test_the_service_refuses_an_action_the_view_did_not_publish(client: TestClient) -> None:
    """The gating is advisory in the client and enforced in the service.

    A console that ignored `available_actions` entirely is still refused, so the UI fix
    is a usability improvement on top of an enforced boundary rather than the boundary
    itself.
    """
    case_id = new_case(client)
    drive(case_id, CaseState.HUMAN_REVIEW, CaseState.FINALIZED)

    response = client.post(
        f"/api/v1/cases/{case_id}/review/accept", json={}, headers=headers(SENIOR)
    )
    assert response.status_code >= 400, "a finalised case accepted a review"


# --------------------------------------------------------------------------- D2/D3
# Authority, reported separately from state
# ---------------------------------------------------------------------------


def test_the_review_view_reports_this_reviewers_permissions(client: TestClient) -> None:
    """**Regression, defects 2 and 3.** State and authority are separate gates.

    `available_actions` answers "what does this case's state permit" and is identical for
    every reviewer. It is **not** an authorization answer, and the console's message
    "Override requires senior-reviewer authority" attributed a state refusal to a
    permission that had never been consulted.

    The API now reports the authority half from the same `Principal` the service checks -
    the flags `app/api/reviewer_ui.py` already passed to the Jinja page.
    """
    case_id = new_case(client)
    drive(case_id, CaseState.HUMAN_REVIEW)

    senior = review_view(client, case_id, SENIOR)
    reviewer = review_view(client, case_id, REVIEWER)
    readonly = review_view(client, case_id, READONLY)

    # State says the same thing to all three. Authority does not.
    assert (
        senior["available_actions"]
        == reviewer["available_actions"]
        == readonly["available_actions"]
    )

    assert (senior["may_review"], senior["may_override"], senior["may_finalize"]) == (
        True,
        True,
        True,
    )
    assert (reviewer["may_review"], reviewer["may_override"], reviewer["may_finalize"]) == (
        True,
        False,
        True,
    ), "a plain reviewer was reported as able to override"
    assert (readonly["may_review"], readonly["may_override"], readonly["may_finalize"]) == (
        False,
        False,
        False,
    )


def test_the_reported_permissions_match_what_the_service_enforces(client: TestClient) -> None:
    """**Load-bearing.** The reported flags must not drift from the enforced checks.

    A console that trusted `may_override` while the service checked something else would
    present a button that 403s - or worse, hide one that would have worked. Both
    directions are asserted: the reviewer the API says may not override is refused, and
    the reviewer it says may override succeeds.
    """
    # Denied: the API reports may_override false, and the service refuses.
    case_id = new_case(client)
    drive(case_id, CaseState.HUMAN_REVIEW)
    assert review_view(client, case_id, REVIEWER)["may_override"] is False
    refused = client.post(
        f"/api/v1/cases/{case_id}/review/override",
        json={"override_outcome": "DENIED", "rationale": "disagree with the draft"},
        headers=headers(REVIEWER),
    )
    assert refused.status_code == 403
    assert refused.json()["error"] == "not_authorised"

    # Permitted: the API reports may_override true, and the service accepts.
    senior_case = new_case(client)
    drive(senior_case, CaseState.HUMAN_REVIEW)
    assert review_view(client, senior_case, SENIOR)["may_override"] is True
    allowed = client.post(
        f"/api/v1/cases/{senior_case}/review/override",
        json={"override_outcome": "DENIED", "rationale": "disagree with the draft"},
        headers=headers(SENIOR),
    )
    assert allowed.status_code == 201, allowed.text
    assert allowed.json()["action"] == "OVERRIDE"


def test_request_info_needs_no_finalize_permission(client: TestClient) -> None:
    """The permission table the console mirrors is not uniform across the three actions.

    `app/case/review.py` requires `FINALIZE_CASE` for every action **except**
    `REQUEST_INFO`, because returning a case to the submitter does not dispose of it. A
    console that gated all three identically would hide an action a reviewer may take.
    """
    case_id = new_case(client)
    drive(case_id, CaseState.HUMAN_REVIEW)

    response = client.post(
        f"/api/v1/cases/{case_id}/review/request-info",
        json={"requested_information": "Supply the supervising physician's attestation."},
        headers=headers(REVIEWER),
    )
    assert response.status_code == 201, response.text
    assert response.json()["case_state"] == CaseState.NEEDS_INFO.value


def test_the_permission_flags_name_real_permissions() -> None:
    """The three reported flags map onto three actual `Permission` members.

    A flag named for a permission that does not exist would be a client-side rule
    wearing the API's clothes.
    """
    for name in ("REVIEW_CASE", "OVERRIDE_RECOMMENDATION", "FINALIZE_CASE"):
        assert name in {p.value for p in Permission}


def test_the_permission_flags_did_not_introduce_a_merged_outcome_field(client: TestClient) -> None:
    """Guards the existing invariant while adding fields beside it.

    `test_the_review_view_separates_the_draft_from_the_disposition` asserts `outcome` is
    absent from this response. Restating it here means a future field addition is
    checked by the test that added fields, not only by a test written earlier.
    """
    case_id = new_case(client)
    drive(case_id, CaseState.HUMAN_REVIEW)
    body = review_view(client, case_id)
    assert "outcome" not in body
    assert body["ai_recommendation_label"] == "AI-generated recommendation - not a decision"
    assert body["human_disposition_label"] == "Human disposition"


# --------------------------------------------------------------------------- D5
# The submit contract
# ---------------------------------------------------------------------------


def test_case_id_is_required_and_is_the_callers_to_choose(client: TestClient) -> None:
    """**Regression, defect 5.** The form labelled `case_id` "optional" and omitted it
    when blank, which is a 422 on the documented happy path.

    `docs/architecture/application-lifecycle.md` §4 settles which side was wrong: "case
    ids are the caller's; silently returning the existing case would hide a collision
    between two different requests". The server must not mint one, so the console was
    fixed rather than the contract.
    """
    response = client.post(
        "/api/v1/cases",
        json={
            "clinical_note": "Synthetic note. No real PHI.",
            "procedure_code": "R0075",
            "code_system": "HCPCS",
            "date_of_service": "2026-08-13",
        },
        headers={"x-api-key": API_KEY},
    )
    assert response.status_code == 422, "case_id became optional; the console assumes otherwise"
    detail = response.json()["detail"]
    assert [e["loc"][-1] for e in detail] == ["case_id"]
    assert [e["type"] for e in detail] == ["missing"]


def test_a_duplicate_case_id_is_refused_rather_than_merged(client: TestClient) -> None:
    """Why the id cannot be server-generated: collisions must surface, not deduplicate."""
    case_id = new_case(client)
    again = client.post(
        "/api/v1/cases",
        json={
            "case_id": case_id,
            "clinical_note": "A different submission reusing the same id.",
            "procedure_code": "R0070",
            "code_system": "HCPCS",
            "date_of_service": "2026-08-14",
        },
        headers={"x-api-key": API_KEY},
    )
    assert again.status_code >= 400, "a duplicate case id was silently accepted"


# --------------------------------------------------------------------------- D6
# Submission is not execution
# ---------------------------------------------------------------------------


def test_submitting_a_case_does_not_run_it(client: TestClient) -> None:
    """**Regression, defect 6.** `POST /cases` accepts and persists; it does not execute.

    The console navigated straight to a case detail that showed no recommendation and no
    actions, with nothing saying why, so a deliberate architecture read as a broken page.
    The fix is what the UI *says*; this pins the behaviour it must describe, so the
    sentence cannot quietly become false.
    """
    case_id = new_case(client)
    body = client.get(f"/api/v1/cases/{case_id}", headers={"x-api-key": API_KEY}).json()
    assert body["state"] == CaseState.RECEIVED.value

    view = review_view(client, case_id)
    assert view["ai_recommendation"] is None
    assert view["available_actions"] == []

    # And there is no endpoint that would have run it - the console must not imply one.
    routes = {getattr(r, "path", "") for r in client.app.routes}  # type: ignore[union-attr]
    for invented in ("/api/v1/cases/{case_id}/run", "/api/v1/cases/{case_id}/execute"):
        assert invented not in routes


# --------------------------------------------------------------------------- D7
# Safety parity with the Jinja reviewer page
# ---------------------------------------------------------------------------


def test_the_review_view_carries_the_fields_the_console_must_display(client: TestClient) -> None:
    """**Regression, defect 7.** Fields the console fetched and then dropped.

    `criterion_ids` connects a chunk to the criterion it was retrieved for; `input_sha256`
    proves which submission produced which recommendation; `audit_event_count` says how
    much record stands behind the page; `identity_model` distinguishes an authenticated
    reviewer from a self-declared one. The Jinja page renders all four.
    """
    case_id = new_case(client)
    drive(case_id, CaseState.HUMAN_REVIEW)
    body = review_view(client, case_id)

    for field in ("input_sha256", "audit_event_count", "recommended_at", "routing_explanation"):
        assert field in body, f"{field} left the review contract"
    assert isinstance(body["evidence"], list)
    assert isinstance(body["history"], list)

    # A recorded review exposes the identity model the console must label.
    client.post(
        f"/api/v1/cases/{case_id}/review/request-info",
        json={"requested_information": "Supply the attestation."},
        headers=headers(SENIOR),
    )
    history = review_view(client, case_id)["history"]
    assert history, "a recorded review did not appear in history"
    assert "identity_model" in history[0]


def test_the_routing_explanation_is_always_present_for_the_console_to_show_first(
    client: TestClient,
) -> None:
    """Anti-anchoring (R-04) needs something to put above the draft.

    The console renders `routing_explanation` before `ai_recommendation` on both tabs
    that show them. That ordering is only meaningful if the field is never empty.
    """
    for path in ((), (CaseState.HUMAN_REVIEW,), (CaseState.FAILED,)):
        case_id = new_case(client)
        drive(case_id, *path)
        explanation = review_view(client, case_id)["routing_explanation"]
        assert isinstance(explanation, str) and explanation.strip()


# --------------------------------------------------------------------------- D8
# The error envelope
# ---------------------------------------------------------------------------


def test_the_error_envelope_is_error_detail_request_id(client: TestClient) -> None:
    """**Regression, defect 8.** The console's `ApiError` declared `code` and `title`.

    The server sends neither. It sends `error` (the category), `detail`, `request_id` and
    `case_id`, so the category was unavailable to the UI and the request id - the one
    thing a reviewer would quote when asking why an action failed - was never shown.
    """
    unauthenticated = client.get("/api/v1/cases/NOPE")
    assert unauthenticated.status_code == 401
    body = unauthenticated.json()
    assert body["error"] == "not_authenticated"
    assert isinstance(body["detail"], str)
    assert body["request_id"]
    assert "code" not in body and "title" not in body

    missing = client.get("/api/v1/cases/NOPE", headers={"x-api-key": API_KEY})
    assert missing.status_code == 404
    assert missing.json()["error"] == "case_not_found"
    assert missing.json()["request_id"]


def test_a_validation_error_carries_a_field_list_the_console_can_render(
    client: TestClient,
) -> None:
    """On a 422 `detail` is a list of issues, not a string.

    The console stringified neither shape and showed "Request failed (HTTP 422)". The
    issue list is what turns that into "case_id: Field required".
    """
    response = client.post("/api/v1/cases", json={}, headers={"x-api-key": API_KEY})
    assert response.status_code == 422
    detail = response.json()["detail"]
    assert isinstance(detail, list) and detail
    for issue in detail:
        assert {"type", "loc", "msg"} <= set(issue)


def test_the_request_id_is_also_on_a_response_header(client: TestClient) -> None:
    """The console falls back to the header when the body is not JSON."""
    case_id = new_case(client)
    response = client.get(f"/api/v1/cases/{case_id}", headers={"x-api-key": API_KEY})
    assert response.headers["x-medauth-request-id"]
