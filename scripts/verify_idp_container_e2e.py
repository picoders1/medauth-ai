"""The whole path, through the published port, with nothing simulated.

    docker compose -f compose.idp.yaml up -d      # explicit, never automatic
    docker compose up -d
    set -a; . ./.env; . ./.env.idp; set +a
    uv run python scripts/verify_idp_container_e2e.py

## What this proves that `verify_idp_e2e.py` does not

That script drives the application **in-process** with `TestClient`. Same routes, same
service layer, same real tokens - but the request never crosses a socket, and the
process doing the OIDC verification is this one, on the host, where the issuer happens
to resolve.

This one sends HTTP to `localhost:8015`, and the container performs discovery, fetches
the JWKS and builds the principal itself. That difference is exactly where the issuer
problem lived: `http://localhost:8090/...` names the host from the host and the
container's own empty loopback from inside the container, so a configuration that
worked in-process could not work containerised. One canonical issuer - the docker
bridge gateway - resolves identically from both.

## Cases are seeded by the engine, never by setting a column

The fixture runner writes into the **container's** database over the published
PostgreSQL port. The case is therefore produced by the same `decide()` path a real
submission takes, with zero model calls, and the container serves it back over HTTP.
Setting `state = 'HUMAN_REVIEW'` directly would prove the endpoints work on a state no
run can reach.

Nothing here is a real person and no PHI is used.
"""

from __future__ import annotations

import asyncio
import base64
import json
import os
import sys
import uuid
from typing import Any

import httpx
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import async_sessionmaker

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.audit.models import AuditEventRow, HumanReviewEventRow
from app.case.lifecycle import CaseState
from app.case.service import CaseService
from app.config.settings import Settings
from app.database.engine import build_engine

BASE = os.environ.get("MEDAUTH_CONTAINER_URL", "http://localhost:8015")
ISSUER = os.environ["MEDAUTH_OIDC_ISSUER"]
AUDIENCE = os.environ["MEDAUTH_OIDC_AUDIENCE"]
API_KEY = os.environ["MEDAUTH_API_KEYS"].split(":")[0]
CALLER = os.environ["MEDAUTH_API_KEYS"].split(":")[1]
#: The container's own database, reached over the published port.
CONTAINER_DB = os.environ.get(
    "MEDAUTH_CONTAINER_DATABASE_URL",
    "postgresql+asyncpg://medauth:medauth@localhost:5435/medauth",
)

PASSED: list[str] = []
FAILED: list[str] = []


def check(name: str, ok: bool, detail: str = "") -> bool:
    (PASSED if ok else FAILED).append(name)
    print(f"  [{'OK ' if ok else 'FAIL'}] {name:60} {detail}")
    return ok


def token_for(username: str, password_env: str) -> str:
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


def _settings() -> Settings:
    return Settings(  # type: ignore[call-arg]
        _env_file=None,
        database_url=CONTAINER_DB,
        api_keys=f"{API_KEY}:{CALLER}",
        auth_mode="oidc",
        oidc_issuer=ISSUER,
        oidc_audience=AUDIENCE,
        oidc_discovery=True,
    )


def headers(token: str | None) -> dict[str, str]:
    head = {"x-api-key": API_KEY}
    if token:
        head["authorization"] = f"Bearer {token}"
    return head


def routed_case() -> str:
    """A case in HUMAN_REVIEW inside the CONTAINER's database, produced by the engine."""
    return asyncio.run(_routed_case())


async def _routed_case() -> str:
    from tests.integration.test_application_lifecycle import (
        FixtureApplicability,
        _runner,
        _satisfied_gateway,
        _submission,
        new_case_id,
    )

    engine = build_engine(_settings())
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
            raise RuntimeError(f"seeded case is {case.state}, not HUMAN_REVIEW")
    await engine.dispose()
    return case_id


def _mint(payload: dict[str, Any], *, kid: str = "forged") -> str:
    import jwt
    from cryptography.hazmat.primitives.asymmetric import rsa

    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    return str(jwt.encode(payload, key, algorithm="RS256", headers={"kid": kid}))


def _b64(data: dict[str, Any]) -> str:
    return (
        base64.urlsafe_b64encode(json.dumps(data, separators=(",", ":")).encode())
        .decode()
        .rstrip("=")
    )


def _unsigned(payload: dict[str, Any]) -> str:
    return f"{_b64({'alg': 'none', 'typ': 'JWT'})}.{_b64(payload)}."


async def _audit(case_id: str, expected_sub: str) -> None:
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
        check("a review event was written by the container", len(rows) == 1, f"{len(rows)} row(s)")
        row = rows[0]
        check(
            "principal_id is the provider sub",
            row.principal_id == expected_sub,
            str(row.principal_id),
        )
        check(
            "identity_issuer accompanies it",
            row.identity_issuer == ISSUER,
            str(row.identity_issuer),
        )
        check(
            "identity model is AUTHENTICATED_HUMAN",
            row.identity_model == "AUTHENTICATED_HUMAN",
            str(row.identity_model),
        )
        check(
            "authentication method is OIDC",
            (row.authentication_method or "").upper() == "OIDC",
            str(row.authentication_method),
        )

        events = list(
            (
                await session.execute(select(AuditEventRow).where(AuditEventRow.case_id == case_id))
            ).scalars()
        )
        check("audit events exist", len(events) > 0, f"{len(events)} events")
        check(
            "no clinical text reached the payloads",
            not any("HISTORY OF PRESENT ILLNESS" in json.dumps(e.payload or {}) for e in events),
        )
        for statement, label in (
            ("UPDATE human_review_events SET rationale='x' WHERE case_id=:c", "UPDATE"),
            ("DELETE FROM human_review_events WHERE case_id=:c", "DELETE"),
        ):
            try:
                await session.execute(text(statement), {"c": case_id})
                await session.rollback()
                check(f"{label} on review history refused", False, "it succeeded")
            except Exception as failure:
                await session.rollback()
                check(
                    f"{label} on review history refused",
                    "append" in str(failure).lower(),
                    type(failure).__name__,
                )
    await engine.dispose()


def main() -> int:
    client = httpx.Client(base_url=BASE, timeout=30.0)
    tokens = {
        "readonly": token_for("nonprod-readonly", "MEDAUTH_IDP_TEST_READONLY_PASSWORD"),
        "reviewer": token_for("nonprod-reviewer", "MEDAUTH_IDP_TEST_REVIEWER_PASSWORD"),
        "senior": token_for("nonprod-senior", "MEDAUTH_IDP_TEST_SENIOR_PASSWORD"),
        "outsider": token_for("nonprod-outsider", "MEDAUTH_IDP_TEST_OUTSIDER_PASSWORD"),
    }
    subs = {k: claims(v)["sub"] for k, v in tokens.items()}

    print("\nPHASE 4 - the container verifies a real token itself")
    check(
        "the container is ready on the published port",
        client.get("/ready").status_code == 200,
        BASE,
    )
    seeded = routed_case()
    check(
        "a real token authenticates through :8015",
        client.get(f"/api/v1/cases/{seeded}/review", headers=headers(tokens["senior"])).status_code
        == 200,
        "the container performed discovery and JWKS retrieval",
    )

    print("\nPHASE 5 - authorization matrix, published port, real tokens")
    matrix: dict[str, dict[str, int]] = {}
    for who, token in tokens.items():
        case_id = routed_case()
        row = {
            "read": client.get(
                f"/api/v1/cases/{case_id}/review", headers=headers(token)
            ).status_code,
            "request-info": client.post(
                f"/api/v1/cases/{case_id}/review/request-info",
                json={"requested_information": "Dates of conservative management."},
                headers=headers(token),
            ).status_code,
        }
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
        "readonly: read only",
        matrix["readonly"]["read"] == 200
        and all(matrix["readonly"][a] == 403 for a in ("accept", "override", "request-info")),
        str(matrix["readonly"]),
    )
    check(
        "reviewer: read/accept/request-info, NOT override",
        matrix["reviewer"]["read"] == 200
        and matrix["reviewer"]["accept"] == 201
        and matrix["reviewer"]["request-info"] == 201
        and matrix["reviewer"]["override"] == 403,
        str(matrix["reviewer"]),
    )
    check(
        "senior: all four",
        all(matrix["senior"][a] in {200, 201} for a in matrix["senior"]),
        str(matrix["senior"]),
    )
    check(
        "outsider: nothing",
        all(matrix["outsider"][a] == 403 for a in matrix["outsider"]),
        str(matrix["outsider"]),
    )

    print("\nPHASE 6 - HITL through the published port")
    case_id = routed_case()
    view = client.get(f"/api/v1/cases/{case_id}/review", headers=headers(tokens["reviewer"])).json()
    check("the read model is served", bool(view.get("routing_explanation")))
    check(
        "AI draft is distinct from human disposition",
        view.get("ai_recommendation") is not None and view.get("human_disposition") is None,
        f"draft={view.get('ai_recommendation')} disposition={view.get('human_disposition')}",
    )
    evidence_before = view.get("evidence")
    check(
        "ACCEPT",
        client.post(
            f"/api/v1/cases/{case_id}/review/accept", json={}, headers=headers(tokens["reviewer"])
        ).status_code
        == 201,
    )
    after = client.get(
        f"/api/v1/cases/{case_id}/review", headers=headers(tokens["reviewer"])
    ).json()
    check("accept -> FINALIZED", after["state"] == "FINALIZED", after["state"])
    check(
        "evidence is not re-retrieved",
        after.get("evidence") == evidence_before,
        "identical to the pre-action read",
    )

    case_id = routed_case()
    check(
        "REQUEST-INFO",
        client.post(
            f"/api/v1/cases/{case_id}/review/request-info",
            json={"requested_information": "Dates."},
            headers=headers(tokens["reviewer"]),
        ).status_code
        == 201,
    )
    check(
        "request-info -> NEEDS_INFO",
        client.get(f"/api/v1/cases/{case_id}/review", headers=headers(tokens["reviewer"])).json()[
            "state"
        ]
        == "NEEDS_INFO",
    )

    over = routed_case()
    drafted = client.get(f"/api/v1/cases/{over}/review", headers=headers(tokens["senior"])).json()
    check(
        "reviewer cannot OVERRIDE",
        client.post(
            f"/api/v1/cases/{over}/review/override",
            json={"override_outcome": "DENIED", "rationale": "x"},
            headers=headers(tokens["reviewer"]),
        ).status_code
        == 403,
    )
    check(
        "senior OVERRIDE",
        client.post(
            f"/api/v1/cases/{over}/review/override",
            json={"override_outcome": "DENIED", "rationale": "Non-production override."},
            headers=headers(tokens["senior"]),
        ).status_code
        == 201,
    )
    final = client.get(f"/api/v1/cases/{over}/review", headers=headers(tokens["senior"])).json()
    check("override -> FINALIZED", final["state"] == "FINALIZED", final["state"])
    check(
        "the overridden AI draft survives",
        final["ai_recommendation"] == drafted["ai_recommendation"]
        and final["human_disposition"] == "DENIED",
        f"draft={final['ai_recommendation']} disposition={final['human_disposition']}",
    )

    print("\nPHASE 9 - audit integrity, from the container's own database")
    asyncio.run(_audit(over, subs["senior"]))

    print("\nPHASE 7 - fail-closed, against the containerised verifier")
    good = tokens["senior"]
    target = routed_case()
    codes: dict[str, int] = {}

    def denied(label: str, token: str | None) -> None:
        code = client.get(f"/api/v1/cases/{target}/review", headers=headers(token)).status_code
        codes[label] = code
        check(f"{label} -> denied", code in {401, 403}, f"HTTP {code}")

    denied("no token", None)
    denied("malformed token", "not-a-jwt")
    denied("invalid signature", good[:-6] + "AAAAAA")
    denied("wrong issuer", _mint(claims(good) | {"iss": "https://evil.example/realms/x"}))
    denied("wrong audience", _mint(claims(good) | {"aud": "other-api"}))
    denied("expired", _mint(claims(good) | {"exp": 1_000_000}))
    denied("nbf in the future", _mint(claims(good) | {"nbf": 4_102_444_800}))
    denied("missing subject", _mint({k: v for k, v in claims(good).items() if k != "sub"}))
    denied("alg=none", _unsigned(claims(good)))
    denied("unknown kid", _mint(claims(good), kid="a-kid-never-published"))
    denied("unknown kid, repeated", _mint(claims(good), kid="another-unpublished-kid"))
    denied(
        "token claiming its own permissions",
        _mint(claims(good) | {"permissions": ["OVERRIDE_RECOMMENDATION"], "groups": []}),
    )

    # The refusals must be indistinguishable. A different status code for one of them
    # is an oracle: it tells a caller which check failed.
    distinct = sorted(set(codes.values()))
    check(
        "every authentication refusal is the same status", len(distinct) == 1, f"codes={distinct}"
    )
    bodies = {
        client.get(f"/api/v1/cases/{target}/review", headers=headers(t)).text
        for t in (
            good[:-6] + "AAAAAA",
            _mint(claims(good), kid="x"),
            _mint(claims(good) | {"aud": "nope"}),
        )
    }
    scrubbed = {
        json.dumps({k: v for k, v in json.loads(b).items() if k != "request_id"}, sort_keys=True)
        for b in bodies
    }
    check(
        "bad signature, unknown kid and wrong audience are indistinguishable",
        len(scrubbed) == 1,
        f"{len(scrubbed)} distinct bodies",
    )

    check(
        "authenticated but unauthorised -> 403",
        client.get(
            f"/api/v1/cases/{target}/review", headers=headers(tokens["outsider"])
        ).status_code
        == 403,
    )
    check(
        "a nonexistent case is 404",
        client.get("/api/v1/cases/CASE-NOT-A-REAL-CASE/review", headers=headers(good)).status_code
        == 404,
    )
    other = client.get(
        f"/api/v1/cases/{target}/review",
        headers={"x-api-key": "key-not-a-real-key", "authorization": f"Bearer {good}"},
    ).status_code
    check(
        "another integrator cannot tell the case exists", other in {401, 403, 404}, f"HTTP {other}"
    )
    check(
        "a caller cannot inject a subject",
        client.post(
            f"/api/v1/cases/{target}/review/accept",
            json={"reviewer_id": subs["senior"], "sub": subs["senior"]},
            headers=headers(tokens["readonly"]),
        ).status_code
        in {403, 422},
    )
    check(
        "a caller cannot inject permissions",
        client.post(
            f"/api/v1/cases/{target}/review/override",
            json={
                "override_outcome": "DENIED",
                "rationale": "x",
                "permissions": ["OVERRIDE_RECOMMENDATION"],
            },
            headers=headers(tokens["reviewer"]),
        ).status_code
        in {403, 422},
    )

    print(f"\n  {len(PASSED)} passed, {len(FAILED)} failed")
    for name in FAILED:
        print(f"    FAILED: {name}")
    client.close()
    return 1 if FAILED else 0


if __name__ == "__main__":
    raise SystemExit(main())
