"""OD-43: the reviewer is who the token says, not who the request body claims.

Before this phase the audit trail recorded who **claimed** to decide. `reviewer_id`
arrived in the request body; the API key identified the integrating *system*; nothing
connected them. In an otherwise append-only, trigger-enforced record, the one field
anybody would ask about after a bad outcome was the one field a client chose.

The load-bearing tests here are the ones that prove the *absence* of a path:
`test_a_client_cannot_name_the_reviewer` and
`test_a_service_principal_cannot_review_however_permissioned`.
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator, Iterator
from datetime import UTC, datetime, timedelta

import jwt
import pytest
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.api.main import create_app
from app.api.v1.routes import session_for
from app.config.settings import Settings
from app.database.engine import build_engine
from app.identity.authenticator import (
    NotAuthenticated,
    OidcAuthenticator,
    StaticAuthenticator,
)
from app.identity.principal import (
    HUMAN_ONLY,
    AuthenticationMethod,
    NotAuthorised,
    Permission,
    Principal,
    PrincipalType,
)

pytestmark = [pytest.mark.security, pytest.mark.api]

ISSUER = "https://idp.test/realms/medauth"
AUDIENCE = "medauth-api"
SECRET = "test-signing-secret-not-a-real-one"
API_KEY = "key-integrator-000"


def human(
    principal_id: str,
    *permissions: Permission,
    method: AuthenticationMethod = AuthenticationMethod.DEVELOPMENT,
) -> Principal:
    return Principal(
        principal_id=principal_id,
        principal_type=PrincipalType.HUMAN,
        authentication_method=method,
        authenticated_at=datetime.now(UTC),
        display_name=principal_id,
        permissions=frozenset(permissions),
        issuer=ISSUER,
        stated_qualification="Board-certified radiologist",
    )


def service(principal_id: str, *permissions: Permission) -> Principal:
    return Principal(
        principal_id=principal_id,
        principal_type=PrincipalType.SERVICE,
        authentication_method=AuthenticationMethod.API_KEY,
        authenticated_at=datetime.now(UTC),
        permissions=frozenset(permissions),
    )


def token(**overrides: object) -> str:
    now = datetime.now(UTC)
    claims: dict[str, object] = {
        "sub": "dr-alice",
        "iss": ISSUER,
        "aud": AUDIENCE,
        "exp": now + timedelta(minutes=10),
        "nbf": now - timedelta(seconds=5),
        "iat": now,
        "name": "Alice Reviewer",
        "groups": ["medauth-reviewer"],
    }
    claims.update(overrides)
    secret = str(overrides.pop("_secret", SECRET))
    return jwt.encode(claims, secret, algorithm="HS256")


def oidc() -> OidcAuthenticator:
    return OidcAuthenticator(issuer=ISSUER, audience=AUDIENCE, secret=SECRET)


# --------------------------------------------------------------------------- 1
# The type boundary
# ---------------------------------------------------------------------------


def test_a_service_principal_cannot_review_however_permissioned() -> None:
    """**Load-bearing.** The type check runs *before* permissions are consulted.

    A service integration that acquired `REVIEW_CASE` - by a mapping typo, by an
    over-broad IdP group - still cannot review. If this were "a principal holding the
    permission may review", OD-43 would be reintroduced under a better-looking name.
    """
    over_permissioned = service("integrator-a", *HUMAN_ONLY, Permission.READ_CASE)
    for permission in sorted(HUMAN_ONLY, key=lambda p: p.value):
        assert over_permissioned.has(permission), "the fixture is not actually over-permissioned"
        with pytest.raises(NotAuthorised, match="human-only"):
            over_permissioned.require(permission)


def test_a_human_with_the_permission_may_act_so_the_check_is_not_vacuous() -> None:
    reviewer = human("dr-alice", Permission.REVIEW_CASE, Permission.FINALIZE_CASE)
    reviewer.require(Permission.REVIEW_CASE)
    reviewer.require(Permission.FINALIZE_CASE)


def test_a_human_without_the_permission_is_denied() -> None:
    reader = human("dr-bob", Permission.READ_CASE)
    with pytest.raises(NotAuthorised, match="does not hold"):
        reader.require(Permission.REVIEW_CASE)


def test_override_is_a_separate_authority_from_review() -> None:
    """Disagreeing with the engine is not the same authority as agreeing with it."""
    reviewer = human("dr-alice", Permission.REVIEW_CASE, Permission.FINALIZE_CASE)
    reviewer.require(Permission.REVIEW_CASE)
    with pytest.raises(NotAuthorised):
        reviewer.require(Permission.OVERRIDE_RECOMMENDATION)


def test_request_info_is_guarded_by_review_case_alone() -> None:
    """The gap a surviving mutation found.

    `REQUEST_INFO` does not finalise, so it deliberately skips the `FINALIZE_CASE`
    check - which means `REVIEW_CASE` is the **only** thing guarding it. Removing that
    check was caught for APPROVE (finalisation still refused) and slipped through here,
    so the check looked redundant when it is the sole guard on this path.
    """
    from app.case.review import HumanReviewService

    unpermissioned = human("dr-nobody")
    assert unpermissioned.permissions == frozenset()
    with pytest.raises(NotAuthorised, match="REVIEW_CASE"):
        unpermissioned.require(Permission.REVIEW_CASE)

    # And the service asks for it before anything else - including on the one action
    # that never reaches the finalisation check.
    import inspect

    source = inspect.getsource(HumanReviewService.record)
    first_check = source.index("reviewer.require(Permission.REVIEW_CASE)")
    finalize_check = source.index("reviewer.require(Permission.FINALIZE_CASE)")
    assert first_check < finalize_check, (
        "REVIEW_CASE is no longer the first authorization check; REQUEST_INFO would "
        "then be unguarded"
    )


def test_a_service_principal_may_still_read_and_submit() -> None:
    """The boundary must not break integrations - only clinical decisions."""
    integrator = service("integrator-a", Permission.SUBMIT_CASE, Permission.READ_CASE)
    integrator.require(Permission.SUBMIT_CASE)
    integrator.require(Permission.READ_CASE)


# --------------------------------------------------------------------------- 2
# Token validation
# ---------------------------------------------------------------------------


def test_a_valid_token_authenticates_and_maps_roles() -> None:
    principal = oidc().authenticate(token())
    assert principal.principal_id == "dr-alice"
    assert principal.principal_type is PrincipalType.HUMAN
    assert principal.authentication_method is AuthenticationMethod.OIDC
    assert principal.issuer == ISSUER
    assert principal.has(Permission.REVIEW_CASE)


@pytest.mark.parametrize(
    ("label", "overrides"),
    [
        ("expired", {"exp": datetime.now(UTC) - timedelta(minutes=1)}),
        ("not yet valid", {"nbf": datetime.now(UTC) + timedelta(hours=1)}),
        ("wrong issuer", {"iss": "https://evil.test/"}),
        ("wrong audience", {"aud": "some-other-api"}),
        ("no subject", {"sub": ""}),
    ],
)
def test_a_token_that_fails_any_check_is_refused(label: str, overrides: dict) -> None:
    with pytest.raises(NotAuthenticated):
        oidc().authenticate(token(**overrides))


def test_a_token_signed_with_the_wrong_key_is_refused() -> None:
    forged = jwt.encode(
        {
            "sub": "dr-alice",
            "iss": ISSUER,
            "aud": AUDIENCE,
            "exp": datetime.now(UTC) + timedelta(minutes=10),
        },
        "not-the-signing-secret",
        algorithm="HS256",
    )
    with pytest.raises(NotAuthenticated):
        oidc().authenticate(forged)


def test_an_unsigned_token_is_refused() -> None:
    """`alg: none` is the classic JWT attack. `none` is absent from the allow-list, and
    its absence is the mechanism."""
    unsigned = jwt.encode(
        {
            "sub": "dr-alice",
            "iss": ISSUER,
            "aud": AUDIENCE,
            "exp": datetime.now(UTC) + timedelta(minutes=10),
        },
        key="",
        algorithm="none",
    )
    with pytest.raises(NotAuthenticated):
        oidc().authenticate(unsigned)


def test_a_token_cannot_grant_itself_permissions() -> None:
    """**Permissions are mapped from recognised roles, never read from the token.**

    A `permissions` claim is not consulted at all, and an unrecognised group
    contributes nothing - so a new IdP group cannot silently become authority here.
    """
    forged = oidc().authenticate(
        token(
            groups=["medauth-god-mode", "administrators"],
            permissions=["FINALIZE_CASE", "OVERRIDE_RECOMMENDATION"],
            roles=["medauth-senior-reviewer"],
        )
    )
    assert forged.permissions == frozenset(), (
        "an unrecognised role or a self-asserted permission claim granted authority"
    )


def test_a_recognised_role_does_grant_so_the_mapping_is_not_vacuous() -> None:
    senior = oidc().authenticate(token(groups=["medauth-senior-reviewer"]))
    assert senior.has(Permission.OVERRIDE_RECOMMENDATION)


def test_the_error_does_not_say_which_check_failed() -> None:
    """Telling a caller *which* verification failed is a hint for the next attempt.

    This failed on its first run. The message interpolated `type(failure).__name__`,
    and PyJWT's exception types are `InvalidIssuerError`, `ExpiredSignatureError`,
    `InvalidAudienceError` - each of which names the check. The cause still reaches the
    log via the exception chain; it no longer reaches the caller.
    """
    for overrides in (
        {"iss": "https://evil.test/"},
        {"aud": "other"},
        {"exp": datetime.now(UTC) - timedelta(minutes=1)},
    ):
        with pytest.raises(NotAuthenticated) as raised:
            oidc().authenticate(token(**overrides))
        message = str(raised.value).lower()
        for leak in ("issuer", "audience", "expired", "signature", "iss", "aud"):
            assert leak not in message, f"the refusal names the failed check: {message!r}"
        # The cause is preserved for the log, just not for the caller.
        assert raised.value.__cause__ is not None


def test_a_verifier_cannot_be_built_with_both_or_neither_key_source() -> None:
    """A verifier with a fallback is a verifier whose strength depends on which branch
    ran."""
    from app.core.errors import MedauthError

    for kwargs in (
        {"jwks_url": "https://idp.test/jwks", "secret": SECRET},
        {},
    ):
        with pytest.raises(MedauthError):
            OidcAuthenticator(issuer=ISSUER, audience=AUDIENCE, **kwargs)  # type: ignore[arg-type]


# --------------------------------------------------------------------------- 3
# Production refuses the development adapter
# ---------------------------------------------------------------------------


def test_production_refuses_the_development_authenticator() -> None:
    """It would authenticate anybody who guessed a configured token name. Failing at
    startup beats failing at the first clinical review."""
    from app.core.errors import ConfigurationError

    with pytest.raises(ConfigurationError, match="auth_mode"):
        Settings(  # type: ignore[call-arg]
            _env_file=None,
            environment="production",
            auth_mode="development",
            llm_api_key="x",
            api_keys="k:c",
        )


# --------------------------------------------------------------------------- 4
# End to end, through the API
# ---------------------------------------------------------------------------


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
        auth_mode="oidc",
        oidc_issuer=ISSUER,
        oidc_audience=AUDIENCE,
        oidc_secret=SECRET,
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


def submit(client: TestClient, case_id: str) -> None:
    client.post(
        "/api/v1/cases",
        json={
            "case_id": case_id,
            "clinical_note": "Synthetic note. No real PHI.",
            "procedure_code": "R0075",
            "code_system": "HCPCS",
            "date_of_service": "2026-08-13",
        },
        headers={"x-api-key": API_KEY},
    )


def new_case_id() -> str:
    return f"CASE-AUTH-{uuid.uuid4().hex[:8]}"


def review_body(**extra: object) -> dict[str, object]:
    return {"action": "APPROVE", "stated_qualification": "Radiologist", **extra}


def test_an_api_key_alone_cannot_review(client: TestClient) -> None:
    """**The headline.** A service credential is not a reviewer."""
    case_id = new_case_id()
    submit(client, case_id)
    response = client.post(
        f"/api/v1/cases/{case_id}/review",
        json=review_body(),
        headers={"x-api-key": API_KEY},
    )
    assert response.status_code == 401
    assert response.json()["error"] == "not_authenticated"


def test_a_client_cannot_name_the_reviewer(client: TestClient) -> None:
    """**Load-bearing.** The field is gone, not validated away.

    `extra="forbid"` means a client sending `reviewer_id` gets a 422 naming it, rather
    than having it silently dropped - a silently-ignored identity field is worse than a
    rejected one, because the caller believes it worked.
    """
    case_id = new_case_id()
    submit(client, case_id)
    for forbidden in ("reviewer_id", "accepted_by", "finalized_by", "principal_id"):
        response = client.post(
            f"/api/v1/cases/{case_id}/review",
            json=review_body(**{forbidden: "dr-somebody-else"}),
            headers={"x-api-key": API_KEY, "authorization": f"Bearer {token()}"},
        )
        assert response.status_code == 422, f"{forbidden} was accepted"
        assert forbidden in response.text


def test_an_expired_token_is_refused_at_the_api(client: TestClient) -> None:
    case_id = new_case_id()
    submit(client, case_id)
    response = client.post(
        f"/api/v1/cases/{case_id}/review",
        json=review_body(),
        headers={
            "x-api-key": API_KEY,
            "authorization": f"Bearer {token(exp=datetime.now(UTC) - timedelta(minutes=1))}",
        },
    )
    assert response.status_code == 401


def test_a_reviewer_without_permission_is_403_not_401(client: TestClient) -> None:
    """Authenticated, and still not allowed. The two answers are different."""
    case_id = new_case_id()
    submit(client, case_id)
    response = client.post(
        f"/api/v1/cases/{case_id}/review",
        json=review_body(),
        headers={
            "x-api-key": API_KEY,
            "authorization": f"Bearer {token(groups=['medauth-readonly'])}",
        },
    )
    assert response.status_code == 403
    assert response.json()["error"] == "not_authorised"


def test_ownership_still_hides_the_case_from_another_integrator(
    client: TestClient,
) -> None:
    """Case visibility and review authority stay separate concerns."""
    case_id = new_case_id()
    submit(client, case_id)
    response = client.post(
        f"/api/v1/cases/{case_id}/review",
        json=review_body(),
        headers={"x-api-key": "not-a-key", "authorization": f"Bearer {token()}"},
    )
    # Refused at the caller boundary, before the reviewer's authority matters.
    assert response.status_code == 401


def test_the_static_adapter_runs_the_same_authorization_path() -> None:
    """A test adapter that bypassed authorization would be a hole beside the real
    thing rather than a substitute for it."""
    adapter = StaticAuthenticator({"tok-a": human("dr-alice", Permission.READ_CASE)})
    principal = adapter.authenticate("tok-a")
    with pytest.raises(NotAuthorised):
        principal.require(Permission.REVIEW_CASE)
    with pytest.raises(NotAuthenticated):
        adapter.authenticate("tok-unknown")
