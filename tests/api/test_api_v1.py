"""API v1 against a real database.

The contract tests Part R asks for, plus the ones that matter more: an unauthenticated
caller gets nothing, an unauthorised caller cannot tell a case exists, and a reviewer
cannot deny without saying why.

## Why these run against PostgreSQL

The rules being tested are split between the service and the schema on purpose - the
rationale requirement is a service check *and* a `CHECK` constraint, ownership is a
service check backed by a column. A test with a mocked session would exercise half of
each and report the whole thing green.
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

pytestmark = [pytest.mark.api, pytest.mark.security]

ALICE_KEY = "key-alice-000000"
BOB_KEY = "key-bob-0000000"


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
        api_keys=f"{ALICE_KEY}:alice,{BOB_KEY}:bob",
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
        try:
            test_client.get("/health")
        except Exception as exc:  # pragma: no cover
            pytest.skip(f"application unavailable ({type(exc).__name__})")
        yield test_client


def submission(case_id: str) -> dict[str, object]:
    return {
        "case_id": case_id,
        "clinical_note": "Synthetic note for contract testing. No real PHI.",
        "procedure_code": "R0075",
        "code_system": "HCPCS",
        "date_of_service": "2026-08-13",
        "diagnosis_codes": ["J18.9"],
        "jurisdiction": "MAC-06",
    }


def alice(**extra: str) -> dict[str, str]:
    return {"x-api-key": ALICE_KEY, **extra}


def new_case_id() -> str:
    return f"CASE-API-{uuid.uuid4().hex[:8]}"


# --------------------------------------------------------------------------- 1
# Authentication and ownership
# ---------------------------------------------------------------------------


def test_an_unauthenticated_request_is_refused(client: TestClient) -> None:
    """Before this phase there was no authentication at all: the answer to "who may
    read this case" was "anyone who can reach the port"."""
    response = client.post("/api/v1/cases", json=submission(new_case_id()))
    assert response.status_code == 401
    assert response.json()["error"] == "not_authenticated"


def test_an_unrecognised_key_is_refused(client: TestClient) -> None:
    response = client.post(
        "/api/v1/cases", json=submission(new_case_id()), headers={"x-api-key": "not-a-key"}
    )
    assert response.status_code == 401


def test_another_caller_cannot_tell_the_case_exists(client: TestClient) -> None:
    """**404, not 403.**

    Distinguishing "not yours" from "does not exist" is an enumeration oracle: a caller
    could walk case ids and learn which ones are real. Ownership failures are
    indistinguishable from absence, deliberately.
    """
    case_id = new_case_id()
    assert (
        client.post("/api/v1/cases", json=submission(case_id), headers=alice()).status_code == 201
    )

    mine = client.get(f"/api/v1/cases/{case_id}", headers=alice())
    assert mine.status_code == 200

    theirs = client.get(f"/api/v1/cases/{case_id}", headers={"x-api-key": BOB_KEY})
    assert theirs.status_code == 404
    assert theirs.json()["error"] == "case_not_found"

    missing = client.get(f"/api/v1/cases/{new_case_id()}", headers={"x-api-key": BOB_KEY})
    assert missing.status_code == theirs.status_code
    assert missing.json()["error"] == theirs.json()["error"]


def test_another_caller_cannot_review_the_case(client: TestClient) -> None:
    case_id = new_case_id()
    client.post("/api/v1/cases", json=submission(case_id), headers=alice())
    response = client.post(
        f"/api/v1/cases/{case_id}/review",
        json={
            "reviewer_id": "intruder",
            "reviewer_qualification": "none",
            "action": "APPROVE",
        },
        headers={"x-api-key": BOB_KEY},
    )
    assert response.status_code == 404


# --------------------------------------------------------------------------- 2
# Validation and the error contract
# ---------------------------------------------------------------------------


def test_a_missing_required_field_is_a_422(client: TestClient) -> None:
    body = submission(new_case_id())
    del body["procedure_code"]
    assert client.post("/api/v1/cases", json=body, headers=alice()).status_code == 422


def test_an_unknown_field_is_refused(client: TestClient) -> None:
    """Closed schemas at the API boundary, as everywhere else in this system."""
    body = submission(new_case_id()) | {"patient_ssn": "000-00-0000"}
    assert client.post("/api/v1/cases", json=body, headers=alice()).status_code == 422


def test_an_unknown_case_is_a_404_not_a_503(client: TestClient) -> None:
    """The handler used to map **every** domain error to 503. A caller could not tell a
    missing case from an outage, and both read as "the service is down"."""
    response = client.get(f"/api/v1/cases/{new_case_id()}", headers=alice())
    assert response.status_code == 404
    assert response.json()["error"] == "case_not_found"


def test_every_error_carries_the_request_id(client: TestClient) -> None:
    given = "req-supplied-by-caller"
    response = client.get(
        f"/api/v1/cases/{new_case_id()}", headers=alice(**{"x-medauth-request-id": given})
    )
    assert response.status_code == 404
    assert response.json()["request_id"] == given


def test_no_error_body_leaks_a_traceback(client: TestClient) -> None:
    response = client.get(f"/api/v1/cases/{new_case_id()}", headers=alice())
    body = response.text.lower()
    for leak in ("traceback", 'file "/', "sqlalchemy", "select ", "psycopg", "asyncpg"):
        assert leak not in body


# --------------------------------------------------------------------------- 3
# Correlation
# ---------------------------------------------------------------------------


def test_the_request_id_propagates_to_the_response_and_the_trail(client: TestClient) -> None:
    case_id = new_case_id()
    given = f"req-{uuid.uuid4().hex[:12]}"
    created = client.post(
        "/api/v1/cases", json=submission(case_id), headers=alice(**{"x-medauth-request-id": given})
    )
    assert created.status_code == 201
    assert created.json()["request_id"] == given
    assert created.headers["x-medauth-request-id"] == given

    trail = client.get(f"/api/v1/cases/{case_id}/audit", headers=alice())
    assert trail.status_code == 200
    events = trail.json()["events"]
    assert events, "submitting a case wrote no audit events"
    assert {e["event"] for e in events} >= {"CASE_RECEIVED", "CASE_VALIDATED"}
    assert all(e["correlation_id"] == given for e in events)


# --------------------------------------------------------------------------- 4
# The lifecycle, and what a review may do
# ---------------------------------------------------------------------------


def test_a_new_case_is_received_and_publishes_its_legal_next_states(
    client: TestClient,
) -> None:
    case_id = new_case_id()
    client.post("/api/v1/cases", json=submission(case_id), headers=alice())
    status = client.get(f"/api/v1/cases/{case_id}/status", headers=alice()).json()
    assert status["state"] == "RECEIVED"
    assert status["awaiting_human_review"] is False
    assert "PROCESSING" in status["allowed_next"]
    # A case cannot jump to a finished state; the graph says so and so does the API.
    assert "FINALIZED" not in status["allowed_next"]


def test_a_case_not_routed_to_a_human_cannot_be_reviewed(client: TestClient) -> None:
    """Otherwise a reviewer could finalise a case the engine never assessed."""
    case_id = new_case_id()
    client.post("/api/v1/cases", json=submission(case_id), headers=alice())
    response = client.post(
        f"/api/v1/cases/{case_id}/review",
        json={
            "reviewer_id": "dr-reviewer",
            "reviewer_qualification": "Board-certified radiologist",
            "action": "APPROVE",
        },
        headers=alice(),
    )
    assert response.status_code == 422
    assert response.json()["error"] == "review_rejected"
    assert "RECEIVED" in response.json()["detail"]


def test_a_denial_without_a_rationale_is_refused(client: TestClient) -> None:
    """A denial with no reason given is a decision nobody can review."""
    case_id = new_case_id()
    client.post("/api/v1/cases", json=submission(case_id), headers=alice())
    response = client.post(
        f"/api/v1/cases/{case_id}/review",
        json={
            "reviewer_id": "dr-reviewer",
            "reviewer_qualification": "Board-certified radiologist",
            "action": "DENY",
        },
        headers=alice(),
    )
    assert response.status_code == 422
    assert "rationale" in response.json()["detail"].lower()


def test_an_override_without_a_rationale_is_refused(client: TestClient) -> None:
    case_id = new_case_id()
    client.post("/api/v1/cases", json=submission(case_id), headers=alice())
    response = client.post(
        f"/api/v1/cases/{case_id}/review",
        json={
            "reviewer_id": "dr-reviewer",
            "reviewer_qualification": "Board-certified radiologist",
            "action": "OVERRIDE",
            "override_outcome": "APPROVED",
        },
        headers=alice(),
    )
    assert response.status_code == 422
    assert "rationale" in response.json()["detail"].lower()


def test_a_reviewer_must_name_a_qualification(client: TestClient) -> None:
    case_id = new_case_id()
    client.post("/api/v1/cases", json=submission(case_id), headers=alice())
    response = client.post(
        f"/api/v1/cases/{case_id}/review",
        json={
            "reviewer_id": "dr-reviewer",
            "reviewer_qualification": "",
            "action": "APPROVE",
        },
        headers=alice(),
    )
    # Refused by the request schema before the service is even reached.
    assert response.status_code == 422


def test_a_case_with_no_recommendation_says_so(client: TestClient) -> None:
    case_id = new_case_id()
    client.post("/api/v1/cases", json=submission(case_id), headers=alice())
    response = client.get(f"/api/v1/cases/{case_id}/recommendation", headers=alice())
    assert response.status_code == 404


def test_evidence_is_empty_and_says_why_before_a_run(client: TestClient) -> None:
    """ "No evidence" and "not assessed yet" are different facts."""
    case_id = new_case_id()
    client.post("/api/v1/cases", json=submission(case_id), headers=alice())
    body = client.get(f"/api/v1/cases/{case_id}/evidence", headers=alice()).json()
    assert body["items"] == []
    assert body["empty_because_not_assessed"] is True


def test_a_duplicate_case_id_is_refused(client: TestClient) -> None:
    case_id = new_case_id()
    assert (
        client.post("/api/v1/cases", json=submission(case_id), headers=alice()).status_code == 201
    )
    again = client.post("/api/v1/cases", json=submission(case_id), headers=alice())
    assert again.status_code == 422
    assert "already exists" in again.json()["detail"]


# --------------------------------------------------------------------------- 5
# What the API must never expose
# ---------------------------------------------------------------------------


def test_the_case_response_carries_a_digest_not_the_note(client: TestClient) -> None:
    """The submitted note is hashed on receipt and never stored or returned."""
    case_id = new_case_id()
    body = submission(case_id)
    created = client.post("/api/v1/cases", json=body, headers=alice()).json()
    assert len(created["input_sha256"]) == 64
    assert (
        str(body["clinical_note"])
        not in client.get(f"/api/v1/cases/{case_id}", headers=alice()).text
    )


def test_the_audit_trail_carries_no_clinical_text(client: TestClient) -> None:
    case_id = new_case_id()
    body = submission(case_id)
    client.post("/api/v1/cases", json=body, headers=alice())
    trail = client.get(f"/api/v1/cases/{case_id}/audit", headers=alice()).text
    assert str(body["clinical_note"]) not in trail
    assert "Synthetic note" not in trail
