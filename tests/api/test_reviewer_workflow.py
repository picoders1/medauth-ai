"""The reviewer workflow, end to end through the API — and what it must never say.

Three groups: the read model shows what the run actually did; the three actions carry
different authority and different requirements; and the UI cannot present a draft as a
decision.

The load-bearing tests are `test_a_qualification_grants_nothing` and
`test_the_ui_never_renders_a_recommendation_as_a_decision`. The first keeps identity,
qualification and competence apart; the second keeps the interface from undoing the
architecture.
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator, Iterator

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.api.main import create_app
from app.api.v1.routes import session_for
from app.config.settings import Settings
from app.database.engine import build_engine
from app.identity.principal import HUMAN_ONLY, Permission
from app.identity.qualification import QualificationState

pytestmark = [pytest.mark.api, pytest.mark.security]

API_KEY = "key-integrator-00000"
SENIOR = "tok-senior"
REVIEWER = "tok-reviewer"
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
    engine = build_engine(settings)
    factory = async_sessionmaker(engine, expire_on_commit=False)

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


def new_case(client: TestClient) -> str:
    case_id = f"CASE-RW-{uuid.uuid4().hex[:8]}"
    client.post(
        "/api/v1/cases",
        json={
            "case_id": case_id,
            "clinical_note": "Synthetic note for reviewer-workflow testing. No real PHI.",
            "procedure_code": "R0075",
            "code_system": "HCPCS",
            "date_of_service": "2026-08-13",
        },
        headers={"x-api-key": API_KEY},
    )
    return case_id


# --------------------------------------------------------------------------- 1
# Identity, qualification, competence
# ---------------------------------------------------------------------------


def test_a_qualification_grants_nothing(client: TestClient) -> None:
    """**Load-bearing.** Three concepts, kept apart.

    A reviewer states an impressive qualification and holds only `READ_CASE`. Every
    human-only action is still refused, because `stated_qualification` is not consulted
    by any authorization path - there is no function that maps one to a permission.
    """
    case_id = new_case(client)
    impressive = "Chief of Radiology, 30 years, board certified"

    for path, body in (
        ("accept", {"stated_qualification": impressive}),
        (
            "override",
            {
                "override_outcome": "APPROVED",
                "rationale": "I am very senior",
                "stated_qualification": impressive,
            },
        ),
        ("request-info", {"requested_information": "x", "stated_qualification": impressive}),
    ):
        response = client.post(
            f"/api/v1/cases/{case_id}/review/{path}", json=body, headers=headers(READONLY)
        )
        assert response.status_code == 403, f"{path} was permitted on a stated qualification"
        assert response.json()["error"] == "not_authorised"


def test_no_authorization_path_reads_the_stated_qualification() -> None:
    """Structural. The separation is an absence, not a rule somebody keeps."""
    import inspect

    from app.identity import authenticator, principal, qualification

    for module in (principal, authenticator):
        source = inspect.getsource(module)
        assert "stated_qualification" not in source.replace(
            'stated_qualification: str = ""', ""
        ).replace("stated_qualification=", ""), (
            f"{module.__name__} consults the stated qualification while deciding authority"
        )
    # And the qualification module grants nothing: it returns labels only.
    exported = [n for n in dir(qualification) if not n.startswith("_")]
    assert "Permission" not in exported


def test_a_qualification_is_never_reported_as_verified(client: TestClient) -> None:
    """No registry exists, so `VERIFIED_BY_REGISTRY` must be unreachable."""
    case_id = new_case(client)
    body = client.get(f"/api/v1/cases/{case_id}/review", headers=headers()).json()
    assert body["qualification_state"] in {
        QualificationState.SELF_ASSERTED.value,
        QualificationState.NOT_STATED.value,
    }
    assert body["qualification_state"] != QualificationState.VERIFIED_BY_REGISTRY.value
    assert "not been verified" in body["qualification_notice"]


def test_verification_state_is_exercised_with_and_without_a_qualification() -> None:
    """Both branches, because a test that only saw one proved nothing.

    Two mutations survived against the earlier version of this file - one making every
    principal `SELF_ASSERTED`, one making a stated qualification report as
    `VERIFIED_BY_REGISTRY`. Both slipped through because the only test used a principal
    that stated nothing, so the branch under test never ran.
    """
    from datetime import UTC, datetime

    from app.identity.principal import AuthenticationMethod, Principal, PrincipalType
    from app.identity.qualification import qualification_of, verification_state

    def principal(qualification: str) -> Principal:
        return Principal(
            principal_id="dr-x",
            principal_type=PrincipalType.HUMAN,
            authentication_method=AuthenticationMethod.OIDC,
            authenticated_at=datetime.now(UTC),
            stated_qualification=qualification,
        )

    stated = principal("Board-certified radiologist")
    assert qualification_of(stated) == "Board-certified radiologist"
    # Stated, and STILL only self-asserted. No registry exists to say otherwise.
    assert verification_state(stated) is QualificationState.SELF_ASSERTED
    assert verification_state(stated) is not QualificationState.VERIFIED_BY_REGISTRY

    for blank in ("", "   "):
        assert verification_state(principal(blank)) is QualificationState.NOT_STATED

    # And no reachable input produces the verified state.
    for text in ("", "MD", "Chief of Radiology", "VERIFIED_BY_REGISTRY"):
        assert verification_state(principal(text)) is not (
            QualificationState.VERIFIED_BY_REGISTRY
        ), "a qualification reported as registry-verified with no registry integrated"


def test_the_human_only_actions_are_the_three_review_actions() -> None:
    assert HUMAN_ONLY == frozenset(
        {
            Permission.REVIEW_CASE,
            Permission.OVERRIDE_RECOMMENDATION,
            Permission.FINALIZE_CASE,
        }
    )


# --------------------------------------------------------------------------- 2
# The read model
# ---------------------------------------------------------------------------


def test_the_review_view_separates_the_draft_from_the_disposition(
    client: TestClient,
) -> None:
    """Two fields, never one. A single `outcome` would let a consumer render the
    engine's draft as the answer."""
    case_id = new_case(client)
    body = client.get(f"/api/v1/cases/{case_id}/review", headers=headers()).json()

    assert "ai_recommendation" in body
    assert "human_disposition" in body
    assert body["human_disposition"] is None, "a case with no review has a disposition"
    assert "not a decision" in body["ai_recommendation_label"]
    assert body["human_disposition_label"] == "Human disposition"
    assert "outcome" not in body, "a merged outcome field is back"


def test_the_review_view_always_explains_why_the_case_is_here(
    client: TestClient,
) -> None:
    """A reviewer who cannot tell why a case reached them is being asked to redo the
    engine's work rather than judge it."""
    case_id = new_case(client)
    body = client.get(f"/api/v1/cases/{case_id}/review", headers=headers()).json()
    assert body["routing_explanation"], "no explanation was rendered"
    assert len(body["routing_explanation"]) > 40


def test_the_review_view_publishes_the_actions_the_state_permits(
    client: TestClient,
) -> None:
    """A case not in HUMAN_REVIEW offers nothing, so a UI need not encode the graph."""
    case_id = new_case(client)
    body = client.get(f"/api/v1/cases/{case_id}/review", headers=headers()).json()
    assert body["state"] == "RECEIVED"
    assert body["available_actions"] == []


def test_the_review_view_requires_authentication_and_read_permission(
    client: TestClient,
) -> None:
    case_id = new_case(client)
    assert (
        client.get(f"/api/v1/cases/{case_id}/review", headers={"x-api-key": API_KEY}).status_code
        == 401
    )
    unknown = client.get(f"/api/v1/cases/{uuid.uuid4().hex}/review", headers=headers())
    assert unknown.status_code == 404, "anti-enumeration behaviour was lost"


# --------------------------------------------------------------------------- 3
# The three actions
# ---------------------------------------------------------------------------


def test_an_override_requires_a_rationale_and_a_target(client: TestClient) -> None:
    """Both are required by the request model's *shape*, not by a validation branch."""
    case_id = new_case(client)
    for body in (
        {"override_outcome": "APPROVED"},  # no rationale
        {"rationale": "because"},  # no target
    ):
        response = client.post(
            f"/api/v1/cases/{case_id}/review/override", json=body, headers=headers()
        )
        assert response.status_code == 422


def test_request_information_must_say_what_is_wanted(client: TestClient) -> None:
    """A request with nothing asked returns the case with no way to satisfy it."""
    case_id = new_case(client)
    response = client.post(
        f"/api/v1/cases/{case_id}/review/request-info", json={}, headers=headers()
    )
    assert response.status_code == 422


def test_accept_needs_no_rationale(client: TestClient) -> None:
    """Agreeing with a recorded, cited, rule-derived recommendation adds nothing a
    later reader lacks. Disagreeing does - which is why override differs."""
    case_id = new_case(client)
    response = client.post(f"/api/v1/cases/{case_id}/review/accept", json={}, headers=headers())
    # Refused for STATE (not in HUMAN_REVIEW), not for a missing rationale.
    assert response.status_code == 422
    assert "rationale" not in response.json()["detail"].lower()
    assert "HUMAN_REVIEW" in response.json()["detail"]


def test_a_reviewer_without_override_permission_cannot_override(
    client: TestClient,
) -> None:
    """`medauth-reviewer` may review and finalise, and may not disagree."""
    case_id = new_case(client)
    response = client.post(
        f"/api/v1/cases/{case_id}/review/override",
        json={"override_outcome": "APPROVED", "rationale": "disagree"},
        headers=headers(REVIEWER),
    )
    assert response.status_code == 403


def test_no_action_endpoint_accepts_a_reviewer_identity(client: TestClient) -> None:
    """OD-43, at every new endpoint. The field does not exist to be sent."""
    case_id = new_case(client)
    for path, body in (
        ("accept", {}),
        ("override", {"override_outcome": "APPROVED", "rationale": "r"}),
        ("request-info", {"requested_information": "x"}),
    ):
        for field in ("reviewer_id", "accepted_by", "finalized_by", "principal_id"):
            response = client.post(
                f"/api/v1/cases/{case_id}/review/{path}",
                json={**body, field: "dr-somebody-else"},
                headers=headers(),
            )
            assert response.status_code == 422, f"{path} accepted {field}"
            assert field in response.text


# --------------------------------------------------------------------------- 4
# UI safety
# ---------------------------------------------------------------------------


def test_the_ui_never_renders_a_recommendation_as_a_decision(
    client: TestClient,
) -> None:
    """**Load-bearing.** The interface must not undo the architecture.

    Both blocks must be present and distinctly labelled, every time. A UI that showed
    one "outcome" would make a draft look like a determination however careful the
    backend was.
    """
    case_id = new_case(client)
    page = client.get(f"/ui/cases/{case_id}", headers=headers())
    assert page.status_code == 200
    body = page.text

    assert "AI-generated recommendation — not a decision" in body
    assert "Human disposition" in body
    assert "No human decision has been recorded on this case." in body
    # And the reason comes before the draft - a reviewer reads the question first.
    assert body.index("Why this case needs a person") < body.index("AI-generated recommendation"), (
        "the recommendation is rendered above the reason it was routed (anchoring, R-04)"
    )


def test_the_ui_shows_the_qualification_is_unverified(client: TestClient) -> None:
    case_id = new_case(client)
    body = client.get(f"/ui/cases/{case_id}", headers=headers()).text
    assert "grants no permission" in body or "not been verified" in body


def test_the_ui_requires_the_same_credentials_as_the_api(client: TestClient) -> None:
    """There is no UI-only path to case data."""
    case_id = new_case(client)
    assert client.get(f"/ui/cases/{case_id}").status_code == 401
    assert client.get(f"/ui/cases/{case_id}", headers={"x-api-key": API_KEY}).status_code == 401
    assert client.get(f"/ui/cases/{uuid.uuid4().hex}", headers=headers()).status_code == 404


def test_the_ui_offers_no_actions_on_a_case_not_open_for_review(
    client: TestClient,
) -> None:
    """A RECEIVED case is not reviewable, and the page says so rather than showing
    buttons the service would refuse.

    This test first asserted that the *permission*-based hiding was visible, and failed:
    on a RECEIVED case the whole actions block is absent, so there is nothing to hide.
    Permission-based hiding is a different scenario and needs a case in HUMAN_REVIEW -
    which this fixture cannot produce without running the pipeline. The service-side
    refusal is covered by `test_a_reviewer_without_override_permission_cannot_override`,
    and that is the half that actually enforces anything.
    """
    case_id = new_case(client)
    body = client.get(f"/ui/cases/{case_id}", headers=headers(REVIEWER)).text
    assert "is not open for review" in body
    assert "review/accept" not in body, "an action form was offered on a non-reviewable case"
    assert "review/override" not in body


def test_the_ui_loads_no_third_party_resource(client: TestClient) -> None:
    """No CDN, no script tag, no external font: a third party in the page is a third
    party in the decision."""
    case_id = new_case(client)
    body = client.get(f"/ui/cases/{case_id}", headers=headers()).text
    for marker in ("<script", "http://", "cdn.", "googleapis", "unpkg", "jsdelivr"):
        assert marker not in body, f"the page pulls in {marker!r}"
