"""Check a candidate identity provider against MEDAUTH's contract, in one command.

    uv run python scripts/verify_idp.py --issuer https://... --audience medauth-api
    uv run python scripts/verify_idp.py --issuer https://... --audience medauth-api \
        --token "$ACCESS_TOKEN"

No provider is selected by this repository (ADR-030). This turns selecting one into a
configuration task: point it at a candidate issuer and it reports, check by check,
whether that provider satisfies what `app/identity/authenticator.py` already requires.

## Why a script rather than a test

The mocked tests prove **this repository's** side of the boundary: the parser, the
validation options, the refusals. They cannot prove a real provider's document,
rotation cadence, clock skew or audience convention are compatible, because there is no
provider to ask.

This asks. It is deliberately not part of the test suite - a suite that reached out to
somebody's identity provider would fail in CI, fail offline, and fail whenever that
provider was down, none of which is a fact about MEDAUTH.

## What it never does

It does not obtain a token, hold a client secret, or perform a login. A token, if you
have one, is passed in and is **never printed, logged or written** - only the shape of
what it verified to. Nothing here writes to the repository.
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass
from typing import Any

import httpx

REPO_CONTRACT = "docs/security/identity-provider-contract.md"


@dataclass(frozen=True, slots=True)
class Check:
    name: str
    passed: bool
    detail: str
    #: A failing REQUIRED check means this provider cannot serve MEDAUTH as configured.
    #: An ADVISORY one means something an operator should know before committing.
    required: bool = True


def _get(url: str, timeout: float) -> Any:
    response = httpx.get(url, timeout=timeout, follow_redirects=True)
    response.raise_for_status()
    return response.json()


def verify(issuer: str, audience: str, *, token: str | None, timeout: float) -> list[Check]:
    checks: list[Check] = []
    discovery_url = f"{issuer.rstrip('/')}/.well-known/openid-configuration"

    try:
        document = _get(discovery_url, timeout)
        checks.append(Check("discovery reachable", True, discovery_url))
    except Exception as failure:
        return [Check("discovery reachable", False, f"{discovery_url}: {type(failure).__name__}")]

    advertised = str(document.get("issuer") or "")
    checks.append(
        Check(
            "document advertises the configured issuer",
            advertised.rstrip("/") == issuer.rstrip("/"),
            f"advertised {advertised!r}",
        )
    )

    jwks_uri = str(document.get("jwks_uri") or "")
    checks.append(Check("document advertises a jwks_uri", bool(jwks_uri), jwks_uri or "absent"))
    if not jwks_uri:
        return checks

    # A jwks_uri on a different host is legitimate and worth knowing about: it widens
    # the set of hosts a deployment must be able to reach and must trust.
    from urllib.parse import urlsplit

    same_host = urlsplit(jwks_uri).hostname == urlsplit(issuer).hostname
    checks.append(
        Check(
            "jwks_uri is on the issuer's host",
            same_host,
            urlsplit(jwks_uri).hostname or "?",
            required=False,
        )
    )

    try:
        jwks = _get(jwks_uri, timeout)
        keys = jwks.get("keys") or []
        checks.append(Check("JWKS reachable", bool(keys), f"{len(keys)} key(s)"))
    except Exception as failure:
        checks.append(Check("JWKS reachable", False, type(failure).__name__))
        return checks

    algorithms = {str(k.get("alg") or "") for k in keys if k.get("alg")}
    supported = {"RS256", "ES256"}
    checks.append(
        Check(
            "an asymmetric algorithm MEDAUTH accepts is published",
            bool(algorithms & supported) or not algorithms,
            f"published {sorted(algorithms) or ['unstated']}; MEDAUTH accepts {sorted(supported)}",
        )
    )
    checks.append(
        Check(
            "every key has a kid (rotation depends on it)",
            all(k.get("kid") for k in keys),
            "rotation matches an unknown kid to a refetch",
        )
    )

    if token:
        checks.extend(_verify_token(token, issuer, audience, jwks_uri, timeout))
    else:
        checks.append(
            Check(
                "a real token was verified",
                False,
                "no --token supplied; discovery and keys checked, issuance not",
                required=False,
            )
        )
    return checks


def _verify_token(
    token: str, issuer: str, audience: str, jwks_uri: str, timeout: float
) -> list[Check]:
    """Validate a real token exactly as the application would. Never prints it."""
    import jwt
    from jwt import PyJWKClient

    from app.identity.authenticator import OidcAuthenticator

    checks: list[Check] = []
    try:
        PyJWKClient(jwks_uri, timeout=int(timeout)).get_signing_key_from_jwt(token)
        checks.append(Check("the token's kid resolves in the JWKS", True, "signing key found"))
    except Exception as failure:
        checks.append(Check("the token's kid resolves in the JWKS", False, type(failure).__name__))
        return checks

    try:
        principal = OidcAuthenticator(
            issuer=issuer, audience=audience, jwks_url=jwks_uri
        ).authenticate(token)
    except Exception as failure:
        checks.append(
            Check(
                "the application accepts the token",
                False,
                f"{type(failure).__name__} - see {REPO_CONTRACT} for the required claims",
            )
        )
        return checks

    checks.append(Check("the application accepts the token", True, "validated"))
    # The subject is an identifier the operator already knows; it is the one value
    # worth echoing, because "which subject did it become" is the question being asked.
    checks.append(Check("a stable subject is present", bool(principal.principal_id), "sub present"))
    unverified = jwt.decode(token, options={"verify_signature": False})
    roles = unverified.get("groups") or unverified.get("roles") or []
    checks.append(
        Check(
            "roles arrive under the `groups` claim",
            bool(unverified.get("groups")),
            f"groups={bool(unverified.get('groups'))}, roles={bool(unverified.get('roles'))}; "
            "MEDAUTH reads `groups` (configurable)",
            required=False,
        )
    )
    checks.append(
        Check(
            "at least one role maps to a MEDAUTH permission",
            bool(principal.permissions),
            f"{len(roles)} role(s) presented -> {sorted(p.value for p in principal.permissions)}",
            required=False,
        )
    )
    return checks


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--issuer", required=True)
    parser.add_argument("--audience", required=True)
    parser.add_argument(
        "--token",
        default=None,
        help="an access token from this provider. Never printed or stored.",
    )
    parser.add_argument("--timeout", type=float, default=10.0)
    args = parser.parse_args()

    checks = verify(args.issuer, args.audience, token=args.token, timeout=args.timeout)
    for check in checks:
        mark = "OK " if check.passed else ("FAIL" if check.required else "note")
        print(f"  [{mark}] {check.name:48} {check.detail}")

    failed = [c for c in checks if c.required and not c.passed]
    print()
    if failed:
        print(f"  NOT COMPATIBLE: {len(failed)} required check(s) failed.")
        return 1
    if not args.token:
        print("  Discovery and keys are compatible. Token issuance was NOT verified;")
        print("  re-run with --token to check the whole path.")
        return 0
    print("  Compatible. Record the result against ADR-030 before configuring a deployment.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
