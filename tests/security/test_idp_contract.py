"""The conformance verifier, exercised against a simulated provider.

`scripts/verify_idp.py` is what turns selecting an identity provider into a
configuration task (ADR-030). It is not part of the suite's network path - it reaches
out to a provider, and a suite that did that would fail offline, fail in CI and fail
whenever somebody else's service was down.

These tests prove the *verifier* is correct, using a simulated document and key set. They
do **not** prove any real provider is compatible, and no test can: there is no provider
to ask. That distinction is the whole point of ADR-030 and it is restated here so a
future reader does not mistake a green suite for a verified integration.
"""

from __future__ import annotations

import httpx
import pytest
import respx

from scripts.verify_idp import verify

pytestmark = pytest.mark.security

ISSUER = "https://idp.example.test/realms/medauth"
AUDIENCE = "medauth-api"


def document(**overrides: object) -> dict[str, object]:
    base: dict[str, object] = {
        "issuer": ISSUER,
        "jwks_uri": f"{ISSUER}/protocol/openid-connect/certs",
    }
    base.update(overrides)
    return base


def jwks(**overrides: object) -> dict[str, object]:
    key: dict[str, object] = {"kid": "abc123", "alg": "RS256", "kty": "RSA"}
    key.update(overrides)
    return {"keys": [key]}


def run(doc: dict[str, object], key_set: dict[str, object] | None = None) -> dict[str, bool]:
    with respx.mock(assert_all_called=False) as mock:
        mock.get(f"{ISSUER}/.well-known/openid-configuration").mock(
            return_value=httpx.Response(200, json=doc)
        )
        if key_set is not None:
            mock.get(str(doc.get("jwks_uri"))).mock(return_value=httpx.Response(200, json=key_set))
        checks = verify(ISSUER, AUDIENCE, token=None, timeout=2.0)
    return {c.name: c.passed for c in checks}


def test_a_conformant_provider_passes_every_required_check() -> None:
    """The positive control. A verifier that failed everything would 'prove' every
    provider incompatible and be useless."""
    with respx.mock(assert_all_called=False) as mock:
        mock.get(f"{ISSUER}/.well-known/openid-configuration").mock(
            return_value=httpx.Response(200, json=document())
        )
        mock.get(f"{ISSUER}/protocol/openid-connect/certs").mock(
            return_value=httpx.Response(200, json=jwks())
        )
        checks = verify(ISSUER, AUDIENCE, token=None, timeout=2.0)

    required = [c for c in checks if c.required]
    assert required, "no required checks ran"
    assert all(c.passed for c in required), [c.name for c in required if not c.passed]
    # And it does NOT claim a token was verified when none was supplied.
    assert any(c.name == "a real token was verified" and not c.passed for c in checks)


def test_an_issuer_mismatch_fails() -> None:
    """The key-discovery attack, caught by the verifier as well as the application."""
    results = run(document(issuer="https://evil.test/"), jwks())
    assert results["document advertises the configured issuer"] is False


def test_an_unreachable_issuer_fails_and_stops() -> None:
    with respx.mock(assert_all_called=False) as mock:
        mock.get(f"{ISSUER}/.well-known/openid-configuration").mock(
            return_value=httpx.Response(503)
        )
        checks = verify(ISSUER, AUDIENCE, token=None, timeout=2.0)
    assert len(checks) == 1 and not checks[0].passed


def test_a_missing_jwks_uri_fails() -> None:
    results = run(document(jwks_uri=""))
    assert results["document advertises a jwks_uri"] is False


def test_a_symmetric_only_provider_fails() -> None:
    """HS256 is refused in production, so a provider publishing only symmetric keys
    cannot serve MEDAUTH however conformant it otherwise is."""
    results = run(document(), jwks(alg="HS256", kty="oct"))
    assert results["an asymmetric algorithm MEDAUTH accepts is published"] is False


def test_keys_without_a_kid_fail_because_rotation_depends_on_it() -> None:
    """Rotation matches an unknown `kid` to a refetch. Without one, a rotation locks
    out every reviewer until a restart - and only during the rotation."""
    results = run(document(), {"keys": [{"alg": "RS256", "kty": "RSA"}]})
    assert results["every key has a kid (rotation depends on it)"] is False


def test_a_jwks_uri_on_another_host_is_a_note_not_a_failure() -> None:
    """Legitimate, and worth an operator knowing: it widens the set of hosts a
    deployment must reach and trust."""
    doc = document(jwks_uri="https://keys.example.test/certs")
    with respx.mock(assert_all_called=False) as mock:
        mock.get(f"{ISSUER}/.well-known/openid-configuration").mock(
            return_value=httpx.Response(200, json=doc)
        )
        mock.get("https://keys.example.test/certs").mock(
            return_value=httpx.Response(200, json=jwks())
        )
        checks = verify(ISSUER, AUDIENCE, token=None, timeout=2.0)

    host_check = next(c for c in checks if c.name == "jwks_uri is on the issuer's host")
    assert host_check.passed is False
    assert host_check.required is False, "an advisory note was made a hard failure"
    assert all(c.passed for c in checks if c.required)


def test_the_verifier_is_not_wired_into_the_application() -> None:
    """It is an operator tool. A production import would put a network call to
    somebody else's service on an application path."""
    from pathlib import Path

    # Walked rather than shelled out to `git grep`: a subprocess here would trip the
    # partial-executable-path lint, and silencing a security lint to write a security
    # test is the wrong trade.
    app = Path(__file__).resolve().parents[2] / "app"
    offenders = [
        str(path.relative_to(app.parent))
        for path in app.rglob("*.py")
        if "verify_idp" in path.read_text(encoding="utf-8")
    ]
    assert not offenders, f"app/ imports the operator verifier: {offenders}"
