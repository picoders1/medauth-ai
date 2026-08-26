"""Build the human authenticator from settings. The only place one is constructed.

Mirrors `app/llm/wiring.py`: one place decides which adapter serves which environment,
so "which authenticator is running" is answerable by reading a single function rather
than by tracing configuration through the application.

Returns `None` when nothing is configured, and the caller refuses every review rather
than falling back to the API key. A fallback from human authentication to service
authentication is precisely the defect OD-43 describes, and it would be invisible in a
running system - every review would succeed, attributed to a system.
"""

from __future__ import annotations

from datetime import UTC, datetime

from app.config.settings import Settings
from app.identity.authenticator import (
    _PERMISSION_FOR_ROLE,
    Authenticator,
    DiscoveryFailed,
    OidcAuthenticator,
    StaticAuthenticator,
    discover,
)
from app.identity.principal import (
    AuthenticationMethod,
    Principal,
    PrincipalType,
)

__all__ = ["build_authenticator", "parse_dev_reviewers"]


def parse_dev_reviewers(raw: str) -> dict[str, Principal]:
    """`"token:principal_id:role,..."` -> `{token: Principal}`. Development only.

    An entry naming an unrecognised role yields a principal with **no permissions**
    rather than being skipped: it authenticates and then cannot do anything, which is
    a far clearer failure than a token that silently does not exist.
    """
    principals: dict[str, Principal] = {}
    for entry in raw.split(","):
        parts = [p.strip() for p in entry.split(":")]
        if len(parts) < 2 or not parts[0] or not parts[1]:
            continue
        token, principal_id = parts[0], parts[1]
        role = parts[2] if len(parts) > 2 else ""
        principals[token] = Principal(
            principal_id=principal_id,
            principal_type=PrincipalType.HUMAN,
            authentication_method=AuthenticationMethod.DEVELOPMENT,
            authenticated_at=datetime.now(UTC),
            display_name=principal_id,
            permissions=_PERMISSION_FOR_ROLE.get(role, frozenset()),
            issuer="development",
        )
    return principals


def build_authenticator(settings: Settings) -> Authenticator | None:
    """One adapter, chosen by `auth_mode`. `None` means reviews are refused."""
    if settings.auth_mode == "oidc":
        secret = settings.oidc_secret.get_secret_value()
        if not settings.oidc_issuer or not settings.oidc_audience:
            return None

        jwks_url = settings.oidc_jwks_url or None
        # Discovery is attempted whenever it is enabled and no endpoint is pinned -
        # **regardless of whether a secret is configured**.
        #
        # The first version guarded this with `and not secret`, which meant a
        # configured secret skipped discovery entirely and went straight to symmetric
        # verification. A deployment that set both would silently downgrade from
        # provider verification to a shared password, and every review would still
        # succeed. Found by the test written for the mutation that survived here.
        if not jwks_url and settings.oidc_discovery:
            # Provider-neutral: the issuer is the only thing configured, and the
            # jwks_uri comes from the provider's own document.
            #
            # A discovery failure returns None, which means reviews are refused. It
            # does NOT fall back to a laxer verifier: an authenticator that degraded
            # when its key source was unreachable would be least trustworthy exactly
            # when something was wrong.
            try:
                jwks_url = discover(settings.oidc_issuer)
            except DiscoveryFailed:
                return None

        if not jwks_url and not secret:
            return None
        return OidcAuthenticator(
            issuer=settings.oidc_issuer,
            audience=settings.oidc_audience,
            jwks_url=jwks_url,
            secret=None if jwks_url else secret,
        )

    reviewers = parse_dev_reviewers(settings.dev_reviewers.get_secret_value())
    return StaticAuthenticator(reviewers) if reviewers else None
