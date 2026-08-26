"""Drive MEDAUTH end to end with tokens minted by the real non-production provider.

    docker compose -f compose.idp.yaml up -d
    set -a; . ./.env; set +a
    uv run python scripts/verify_idp_e2e.py

## Why this is a script and not a test

`scripts/verify_idp.py` proves the provider is compatible. This proves the
*application* behaves correctly when the identity is real: authorization, the HITL
workflow, the audit trail and the negative security cases, all with tokens this
process did not sign.

Like `verify_idp.py` it stays out of the suite deliberately. A pytest module that
needed a live Keycloak would fail in CI, fail offline and fail whenever the container
was down - none of which is a fact about MEDAUTH. The mocked tests carry the
regression burden; this carries the real-provider evidence, and the two must not be
reported as the same thing.

**Nothing here is a real person.** Four fixture identities in a throwaway realm, no
clinical identity, no PHI. Passwords come from the environment and are never printed.
"""

from __future__ import annotations

import asyncio
import base64
import json
import os
import sys
import uuid
from collections.abc import AsyncIterator
from typing import Any

import httpx
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.api.main import create_app
from app.api.v1.routes import session_for
from app.audit.models import AuditEventRow, HumanReviewEventRow
from app.case.lifecycle import CaseState
from app.case.service import CaseService
from app.config.settings import Settings
from app.database.engine import build_engine

ISSUER = os.environ["MEDAUTH_OIDC_ISSUER"]
AUDIENCE = os.environ["MEDAUTH_OIDC_AUDIENCE"]
API_KEY = "key-integrator-00000"
CALLER = "integrator-a"

PASSED: list[str] = []
FAILED: list[str] = []


def check(name: str, ok: bool, detail: str = "") -> bool:
    (PASSED if ok else FAILED).append(name)
    print(f"  [{'OK ' if ok else 'FAIL'}] {name:58} {detail}")
    return ok


def token_for(username: str, password_env: str) -> str:
    """A real access token. The password is read from the environment, never logged."""
    response = httpx.post(
        f"{ISSUER}/protocol/openid-connect/token",
        data={
            "grant_type": "password",
            "client_id": AUDIENCE,
            "scope": "openid",
            "username": username,
            "password": os.environ[password_env],
        },
        timeout=20.0,
    )
    response.raise_for_status()
    return str(response.json()["access_token"])


def claims(token: str) -> dict[str, Any]:
    payload = token.split(".")[1]
    payload += "=" * (-len(payload) % 4)
    return dict(json.loads(base64.urlsafe_b64decode(payload)))


def database_url() -> str:
    return os.environ.get(
        "MEDAUTH_TEST_DATABASE_URL",
        "postgresql+asyncpg://medauth:medauth@localhost:5435/medauth_test",
    )


def _settings() -> Settings:
    return Settings(  # type: ignore[call-arg]
        _env_file=None,
        database_url=database_url(),
        api_keys=f"{API_KEY}:{CALLER}",
        auth_mode="oidc",
        oidc_issuer=ISSUER,
        oidc_audience=AUDIENCE,
        oidc_discovery=True,
    )


def build() -> tuple[TestClient, async_sessionmaker[AsyncSession]]:
    """The real application, configured for the real provider. No mocks anywhere."""
    settings = _settings()
    application = create_app(settings)
    engine = build_engine(settings)
    factory = async_sessionmaker(engine, expire_on_commit=False)

    async def _session() -> AsyncIterator[AsyncSession]:
        async with factory() as session:
            yield session

    application.dependency_overrides[session_for] = _session
    application.state.session_factory = factory
    return TestClient(application), factory


def routed_case() -> str:
    """Sync wrapper. See `_routed_case` for why each call gets its own engine."""
    return asyncio.run(_routed_case())


async def _routed_case() -> str:
    """A case in HUMAN_REVIEW, produced by the engine - not by setting a column.

    Reuses the integration suite's deterministic fixtures: zero model calls, and the
    same path a real submission takes. Driving the state directly would prove the
    reviewer endpoints work on a state no run can produce.
    """
    from tests.integration.test_application_lifecycle import (
        FixtureApplicability,
        _runner,
        _satisfied_gateway,
        _submission,
        new_case_id,
    )

    # A fresh engine per call, disposed at the end. `TestClient` drives the
    # application on its own anyio loop; an engine's pooled connections belong to
    # whichever loop first used them, so sharing one across both raises
    # "attached to a different loop". Two engines, two loops, no shared state.
    settings = _settings()
    engine = build_engine(settings)
    factory = async_sessionmaker(engine, expire_on_commit=False)

    case_id = new_case_id()
    submission = _submission(case_id)
    request_id = f"req-{uuid.uuid4().hex[:12]}"
    runner = _runner(_satisfied_gateway(), FixtureApplicability())
    async with factory() as session:
        service = CaseService(session, runner=runner)
        await service.submit(submission, caller_id=CALLER, request_id=request_id)
    async with factory() as session:
        service = CaseService(session, runner=runner)
        await service.run_case(submission, caller_id=CALLER, request_id=request_id)
    async with factory() as session:
        case = await CaseService(session).get(case_id, caller_id=CALLER)
        if CaseState(case.state) is not CaseState.HUMAN_REVIEW:
            # Not an assert: this script is not run under pytest, and `python -O`
            # would strip the one check that keeps every later phase honest. A case
            # that never reached HUMAN_REVIEW would make each review action a
            # lifecycle refusal, and the whole run would pass by refusing everything.
            raise RuntimeError(f"fixture case is {case.state}, not HUMAN_REVIEW")
    await engine.dispose()
    return case_id


def headers(token: str | None) -> dict[str, str]:
    head = {"x-api-key": API_KEY}
    if token:
        head["authorization"] = f"Bearer {token}"
    return head


def main() -> int:
    client, _ = build()
    tokens = {
        "readonly": token_for("nonprod-readonly", "MEDAUTH_IDP_TEST_READONLY_PASSWORD"),
        "reviewer": token_for("nonprod-reviewer", "MEDAUTH_IDP_TEST_REVIEWER_PASSWORD"),
        "senior": token_for("nonprod-senior", "MEDAUTH_IDP_TEST_SENIOR_PASSWORD"),
        "outsider": token_for("nonprod-outsider", "MEDAUTH_IDP_TEST_OUTSIDER_PASSWORD"),
    }
    subs = {k: claims(v)["sub"] for k, v in tokens.items()}

    with client:
        # ---------------------------------------------------------------- 5
        print("\nPHASE 5 - authorization, real provider identities")
        matrix: dict[str, dict[str, int]] = {}
        for who, token in tokens.items():
            case_id = routed_case()
            row: dict[str, int] = {}
            row["read"] = client.get(
                f"/api/v1/cases/{case_id}/review", headers=headers(token)
            ).status_code
            row["request-info"] = client.post(
                f"/api/v1/cases/{case_id}/review/request-info",
                json={"requested_information": "Prior conservative management dates."},
                headers=headers(token),
            ).status_code
            case_id = routed_case()
            row["override"] = client.post(
                f"/api/v1/cases/{case_id}/review/override",
                json={"override_outcome": "DENIED", "rationale": "Non-production check."},
                headers=headers(token),
            ).status_code
            case_id = routed_case()
            row["accept"] = client.post(
                f"/api/v1/cases/{case_id}/review/accept", json={}, headers=headers(token)
            ).status_code
            matrix[who] = row
            print(f"    {who:10} {row}")

        check(
            "readonly may read and may do nothing else",
            matrix["readonly"]["read"] == 200
            and all(matrix["readonly"][a] == 403 for a in ("accept", "override", "request-info")),
            str(matrix["readonly"]),
        )
        check(
            "reviewer may read, accept, request-info - not override",
            matrix["reviewer"]["read"] == 200
            and matrix["reviewer"]["accept"] == 201
            and matrix["reviewer"]["request-info"] == 201
            and matrix["reviewer"]["override"] == 403,
            str(matrix["reviewer"]),
        )
        check(
            "senior may do all four",
            matrix["senior"]["read"] == 200
            and matrix["senior"]["accept"] == 201
            and matrix["senior"]["request-info"] == 201
            and matrix["senior"]["override"] == 201,
            str(matrix["senior"]),
        )
        check(
            "an authenticated user in no group can do nothing requiring authority",
            matrix["outsider"]["read"] == 403
            and all(matrix["outsider"][a] == 403 for a in ("accept", "override", "request-info")),
            str(matrix["outsider"]),
        )

        # ---------------------------------------------------------------- 6
        print("\nPHASE 6 - HITL end to end, real reviewer identities")
        accepted = routed_case()
        view = client.get(f"/api/v1/cases/{accepted}/review", headers=headers(tokens["reviewer"]))
        check("the review read model is served", view.status_code == 200)
        body = view.json()
        check(
            "why the case is here is present and is not the recommendation",
            bool(body.get("routing_explanation")) and body.get("human_disposition") is None,
            f"disposition={body.get('human_disposition')}",
        )
        evidence_before = body.get("evidence")

        response = client.post(
            f"/api/v1/cases/{accepted}/review/accept", json={}, headers=headers(tokens["reviewer"])
        )
        check("ACCEPT by a real reviewer", response.status_code == 201, str(response.status_code))
        after = client.get(f"/api/v1/cases/{accepted}/review", headers=headers(tokens["reviewer"]))
        check(
            "accept finalises the case", after.json()["state"] == "FINALIZED", after.json()["state"]
        )
        check(
            "evidence is not re-retrieved when a reviewer opens the case",
            after.json().get("evidence") == evidence_before,
            "identical to the pre-action read",
        )

        info = routed_case()
        response = client.post(
            f"/api/v1/cases/{info}/review/request-info",
            json={"requested_information": "Documented dates of conservative management."},
            headers=headers(tokens["reviewer"]),
        )
        check("REQUEST-INFO by a real reviewer", response.status_code == 201)
        state = client.get(
            f"/api/v1/cases/{info}/review", headers=headers(tokens["reviewer"])
        ).json()
        check(
            "request-info returns the case to NEEDS_INFO",
            state["state"] == "NEEDS_INFO",
            state["state"],
        )

        over = routed_case()
        drafted = client.get(
            f"/api/v1/cases/{over}/review", headers=headers(tokens["senior"])
        ).json()
        response = client.post(
            f"/api/v1/cases/{over}/review/override",
            json={"override_outcome": "DENIED", "rationale": "Non-production override check."},
            headers=headers(tokens["senior"]),
        )
        check("OVERRIDE by a real senior reviewer", response.status_code == 201)
        final = client.get(f"/api/v1/cases/{over}/review", headers=headers(tokens["senior"])).json()
        check("override finalises the case", final["state"] == "FINALIZED", final["state"])
        check(
            "the overridden recommendation survives the disagreement",
            final["ai_recommendation"] == drafted["ai_recommendation"]
            and final["human_disposition"] == "DENIED",
            f"draft={drafted['ai_recommendation']} disposition={final['human_disposition']}",
        )

        # ---------------------------------------------------------------- 8
        print("\nPHASE 8 - audit, with a real authenticated identity")
        asyncio.run(_audit_checks(over, subs["senior"]))

        # ---------------------------------------------------------------- 7
        print("\nPHASE 7 - negative security, against the real verifier")
        good = tokens["senior"]
        target = routed_case()

        def denied(label: str, token: str | None, expect: set[int]) -> None:
            code = client.get(f"/api/v1/cases/{target}/review", headers=headers(token)).status_code
            check(label, code in expect, f"HTTP {code}")

        denied("no token -> denied", None, {401, 403})
        denied("malformed token -> denied", "not-a-jwt", {401, 403})
        denied("invalid signature -> denied", good[:-6] + "AAAAAA", {401, 403})

        forged = _mint(claims(good) | {"iss": "https://evil.example/realms/x"})
        denied("wrong issuer -> denied", forged, {401, 403})
        denied("wrong audience -> denied", _mint(claims(good) | {"aud": "other-api"}), {401, 403})
        denied("expired token -> denied", _mint(claims(good) | {"exp": 1_000_000}), {401, 403})
        denied(
            "not-yet-valid (nbf) -> denied",
            _mint(claims(good) | {"nbf": 4_102_444_800}),
            {401, 403},
        )
        no_sub = {k: v for k, v in claims(good).items() if k != "sub"}
        denied("missing subject -> denied", _mint(no_sub), {401, 403})
        denied("unsigned (alg=none) -> denied", _unsigned(claims(good)), {401, 403})

        # Fail-closed on an unknown key: a token signed by a key the provider never
        # published must be refused after the refetch, not accepted.
        denied(
            "unknown signing key -> fail closed",
            _mint(claims(good), kid="not-a-real-kid"),
            {401, 403},
        )

        code = client.get(
            f"/api/v1/cases/{target}/review", headers=headers(tokens["outsider"])
        ).status_code
        check("authenticated but unauthorised -> denied", code == 403, f"HTTP {code}")

        missing = client.get(
            "/api/v1/cases/CASE-DOES-NOT-EXIST/review", headers=headers(good)
        ).status_code
        check("a nonexistent case is a 404, not a 503", missing == 404, f"HTTP {missing}")

        other = client.get(
            f"/api/v1/cases/{target}/review",
            headers={"x-api-key": "key-integrator-11111", "authorization": f"Bearer {good}"},
        ).status_code
        check(
            "another integrator cannot tell the case exists",
            other in {401, 403, 404},
            f"HTTP {other}",
        )

        # A caller cannot name the reviewer or grant themselves anything: the fields
        # do not exist on the request models, so these are refusals, not ignores.
        injected = client.post(
            f"/api/v1/cases/{target}/review/accept",
            json={"reviewer_id": subs["senior"], "sub": subs["senior"]},
            headers=headers(tokens["readonly"]),
        )
        check(
            "a caller cannot inject a subject",
            injected.status_code in {403, 422},
            f"HTTP {injected.status_code}",
        )
        elevated = client.post(
            f"/api/v1/cases/{target}/review/override",
            json={
                "override_outcome": "DENIED",
                "rationale": "x",
                "permissions": ["OVERRIDE_RECOMMENDATION"],
            },
            headers=headers(tokens["reviewer"]),
        )
        check(
            "a caller cannot inject permissions",
            elevated.status_code in {403, 422},
            f"HTTP {elevated.status_code}",
        )
        claimed = _mint(claims(good) | {"permissions": ["OVERRIDE_RECOMMENDATION"], "groups": []})
        code = client.get(f"/api/v1/cases/{target}/review", headers=headers(claimed)).status_code
        check(
            "a self-asserted permissions claim in a token grants nothing",
            code in {401, 403},
            f"HTTP {code}",
        )

    print(f"\n  {len(PASSED)} passed, {len(FAILED)} failed")
    for name in FAILED:
        print(f"    FAILED: {name}")
    return 1 if FAILED else 0


async def _audit_checks(case_id: str, expected_sub: str) -> None:
    """Read the trail back. Its own engine, for the loop reason in `_routed_case`."""
    from sqlalchemy import text

    engine = build_engine(_settings())
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as session:
        rows = list(
            (
                await session.execute(
                    select(HumanReviewEventRow).where(HumanReviewEventRow.case_id == case_id)
                )
            ).scalars()
        )
        check("the human review event was written", len(rows) == 1, f"{len(rows)} row(s)")
        row = rows[0]
        check(
            "the authenticated provider sub is what was recorded",
            row.principal_id == expected_sub,
            str(row.principal_id),
        )
        check(
            "the identity model says the identity was authenticated",
            row.identity_model == "AUTHENTICATED_HUMAN",
            str(row.identity_model),
        )
        check(
            "the authentication method is recorded as OIDC",
            (row.authentication_method or "").upper() == "OIDC",
            str(row.authentication_method),
        )
        check(
            "the draft it disagreed with is denormalised onto the row",
            bool(row.recommended_outcome_at_review),
            str(row.recommended_outcome_at_review),
        )

        events = list(
            (
                await session.execute(select(AuditEventRow).where(AuditEventRow.case_id == case_id))
            ).scalars()
        )
        check("audit events exist for the case", len(events) > 0, f"{len(events)} events")
        check(
            "no clinical text reached the audit payloads",
            not any("HISTORY OF PRESENT ILLNESS" in json.dumps(e.payload or {}) for e in events),
        )

        # Append-only is enforced by trigger, not by a grant: PostgreSQL never
        # restricts a table's owner via REVOKE, so the grants alone were inert.
        for statement, label in (
            ("UPDATE human_review_events SET rationale='x' WHERE case_id=:c", "UPDATE"),
            ("DELETE FROM human_review_events WHERE case_id=:c", "DELETE"),
        ):
            try:
                await session.execute(text(statement), {"c": case_id})
                await session.rollback()
                check(f"{label} on the review history is refused", False, "it succeeded")
            except Exception as failure:
                await session.rollback()
                check(
                    f"{label} on the review history is refused",
                    "append" in str(failure).lower(),
                    type(failure).__name__,
                )
    await engine.dispose()


def _b64(data: dict[str, Any]) -> str:
    raw = json.dumps(data, separators=(",", ":")).encode()
    return base64.urlsafe_b64encode(raw).decode().rstrip("=")


def _mint(payload: dict[str, Any], *, kid: str = "forged") -> str:
    """A token signed with a key this script generated - never the provider's."""
    import jwt
    from cryptography.hazmat.primitives.asymmetric import rsa

    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    return str(jwt.encode(payload, key, algorithm="RS256", headers={"kid": kid}))


def _unsigned(payload: dict[str, Any]) -> str:
    return f"{_b64({'alg': 'none', 'typ': 'JWT'})}.{_b64(payload)}."


if __name__ == "__main__":
    raise SystemExit(main())
