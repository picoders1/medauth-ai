"""Caller identity, and an honest account of what it is not.

There was no authentication in this application at all: the answer to *who may read
this case* was *anyone who can reach the port*. This is the smallest thing that fixes
that without inventing a clinical user model the project has no basis for.

## What it is

An API key maps to a caller id. Cases are owned by the caller that submitted them, and
`CaseService.get()` refuses any other caller. Enforcement is in the **service**, not in
a route decorator, so a second entry point added later cannot reach a case by forgetting
to decorate.

## Two boundaries, not one (OD-43)

`caller_from_headers` establishes the **integrating system** from an API key: which
cases may be seen. `reviewer_from_headers` establishes the **authenticated person** from
a bearer token: who decided. They are separate dependencies returning separate types, so
a route cannot satisfy one with the other and a service cannot mistake them.

An API key alone can never review, override or finalise. `Principal.require()` refuses a
`SERVICE` principal for those actions **before** consulting its permissions, so the
refusal survives a permission mapping that is too generous.

## What the caller boundary is still NOT

- **Not a user model.** A caller is an integrating system, not a person.
- **Not role-based.** It knows ownership and nothing else.
- **Not a session.** No login, no expiry, no rotation flow. Rotation is redeploying the
  configured keys.

## Keys are compared in constant time

`secrets.compare_digest`, because a plain `==` on a secret leaks its prefix through
timing. Cheap to do correctly, and the sort of thing that is never fixed later.
"""

from __future__ import annotations

import secrets

from fastapi import Header, Request

from app.core.errors import MedauthError
from app.identity.authenticator import NotAuthenticated as TokenNotAuthenticated
from app.identity.principal import Principal

__all__ = [
    "Caller",
    "NotAuthenticated",
    "caller_from_headers",
    "parse_api_keys",
    "reviewer_from_headers",
]


class NotAuthenticated(MedauthError):
    """No usable credential was presented."""


class Caller:
    """Who is calling. Immutable, and carries no secret."""

    __slots__ = ("caller_id",)

    def __init__(self, caller_id: str) -> None:
        self.caller_id = caller_id

    def __repr__(self) -> str:  # pragma: no cover - diagnostics only
        return f"Caller({self.caller_id!r})"


def parse_api_keys(raw: str) -> dict[str, str]:
    """`"key1:caller-a,key2:caller-b"` -> `{key: caller_id}`.

    Configuration, not code, so adding an integrator is a deployment change. An empty
    or malformed entry is skipped rather than becoming a caller named "" that every
    unauthenticated request would match.
    """
    mapping: dict[str, str] = {}
    for entry in raw.split(","):
        key, _, caller = entry.partition(":")
        if key.strip() and caller.strip():
            mapping[key.strip()] = caller.strip()
    return mapping


def caller_from_headers(
    request: Request,
    x_api_key: str | None = Header(default=None, alias="x-api-key"),
) -> Caller:
    """Resolve the caller, or refuse. A FastAPI dependency.

    When **no keys are configured at all** this raises rather than admitting everyone.
    An unconfigured deployment failing closed is the only safe reading: the alternative
    is that forgetting to set a variable silently opens every case to the network.
    """
    configured: dict[str, str] = getattr(request.app.state, "api_keys", {}) or {}
    if not configured:
        raise NotAuthenticated(
            "no API keys are configured; this deployment cannot authenticate callers"
        )
    if not x_api_key:
        raise NotAuthenticated("missing x-api-key")

    for key, caller_id in configured.items():
        if secrets.compare_digest(key, x_api_key):
            return Caller(caller_id)
    raise NotAuthenticated("unrecognised API key")


def reviewer_from_headers(
    request: Request,
    authorization: str | None = Header(default=None, alias="authorization"),
) -> Principal:
    """Resolve the authenticated **human**, or refuse. A FastAPI dependency.

    Separate from `caller_from_headers` on purpose: an API key identifies a system and
    can never stand in for a person. A deployment with no authenticator configured
    refuses every review rather than falling back to the caller - the fallback is
    exactly the defect OD-43 describes, and it would be invisible.
    """
    authenticator = getattr(request.app.state, "authenticator", None)
    if authenticator is None:
        raise NotAuthenticated(
            "no human authenticator is configured; this deployment cannot accept "
            "reviews. An API key identifies a system and is never a reviewer."
        )
    if not authorization:
        raise NotAuthenticated("missing bearer token for a human review action")

    scheme, _, token = authorization.partition(" ")
    if scheme.lower() != "bearer" or not token.strip():
        raise NotAuthenticated("authorization header must be a bearer token")

    try:
        principal: Principal = authenticator.authenticate(token.strip())
    except TokenNotAuthenticated as failure:
        # Re-raised as this module's type so the API error table has one entry to map.
        # The message is the authenticator's, which says only that it did not verify.
        raise NotAuthenticated(str(failure)) from failure
    return principal
