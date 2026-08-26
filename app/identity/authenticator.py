"""Turning a credential into a `Principal`, or refusing.

Three implementations behind one protocol: an OIDC/JWT validator for production, a
configured development adapter for local work and tests, and the existing API-key path
for service integrations.

## The adapters differ in how identity is established, not in what it authorises

`Authenticator` returns a `Principal`. Everything downstream - the service-layer
permission checks, the human-only rule, the audit attribution - runs on that object and
cannot tell which adapter produced it. So a test using `StaticAuthenticator` exercises
**the same authorization logic as production**, which is the property that makes the
test adapter worth having rather than a hole beside the real thing.

There is deliberately no adapter that returns a principal without checking anything.

## What the OIDC adapter verifies

Signature, issuer, audience, `exp`, `nbf`, and the presence of `sub`. `verify_signature`
is never disabled and `algorithms` is an allow-list that excludes `none` - an unsigned
token is not a weakly-authenticated token, it is an unauthenticated one wearing the
shape of authentication.

**Permissions are mapped, not read.** The token's groups or roles claim is a string an
identity provider controls; `_PERMISSION_FOR_ROLE` maps known role names onto
permissions and **ignores anything it does not recognise**. A token asserting
`"permissions": ["FINALIZE_CASE"]` grants nothing, because that claim is never consulted.

## Discovery keeps this provider-neutral

No ADR in this repository names an identity provider, and this phase does not choose
one. `discover()` reads the standard `.well-known/openid-configuration` document and
takes the `jwks_uri` from it, so a deployment configures an **issuer** and nothing
vendor-specific. Any conformant OIDC provider works; none is named in code.

The discovery document's own `issuer` must equal the configured one. A document that
advertises a different issuer is either misconfiguration or an attacker redirecting key
discovery, and both are refused - trusting a `jwks_uri` from a document you have not
tied to your expected issuer is how key discovery becomes the attack.

## Symmetric secrets are for tests, never for production

`secret` verifies HS256, where the **verifier holds the key that signs**. Anyone with the
application's configuration can mint a valid reviewer token, which is not authentication -
it is a shared password with extra steps. It exists so tests need no key server.
`Settings` refuses it in production; a test asserts the refusal.

## Development is refused in production

`StaticAuthenticator` is constructible anywhere, but `Settings` refuses
`auth_mode=development` when `is_production`, and a test asserts it. The failure mode of
shipping with the development adapter enabled is a service that authenticates nobody
correctly, so it fails at startup rather than at the first review.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Protocol

import httpx
import jwt
from jwt import PyJWKClient

from app.core.errors import MedauthError
from app.identity.principal import (
    AuthenticationMethod,
    Permission,
    Principal,
    PrincipalType,
)

__all__ = [
    "Authenticator",
    "DiscoveryFailed",
    "NotAuthenticated",
    "OidcAuthenticator",
    "StaticAuthenticator",
    "discover",
]


class NotAuthenticated(MedauthError):
    """No usable credential was presented, or the one presented did not verify."""


#: Role names an identity provider may assert, mapped onto what they permit here.
#:
#: The mapping is the authorization decision; the claim is only an input to it. An
#: unrecognised role contributes nothing rather than being passed through, so a new
#: group in the IdP cannot silently become authority in MEDAUTH.
_PERMISSION_FOR_ROLE: dict[str, frozenset[Permission]] = {
    "medauth-reviewer": frozenset(
        {Permission.READ_CASE, Permission.REVIEW_CASE, Permission.FINALIZE_CASE}
    ),
    "medauth-senior-reviewer": frozenset(
        {
            Permission.READ_CASE,
            Permission.REVIEW_CASE,
            Permission.OVERRIDE_RECOMMENDATION,
            Permission.FINALIZE_CASE,
        }
    ),
    "medauth-readonly": frozenset({Permission.READ_CASE}),
}

#: Signature algorithms accepted. `none` is absent, and its absence is the mechanism -
#: the classic JWT attack is a token whose header asks for it.
_ALGORITHMS = ("RS256", "ES256", "HS256")


class DiscoveryFailed(MedauthError):
    """The provider's configuration document could not be used."""


def discover(issuer: str, *, timeout_seconds: float = 5.0) -> str:
    """Return the provider's `jwks_uri`, or raise. Provider-neutral by construction.

    Fetched at startup rather than per request: a discovery call on the authentication
    path would make every review depend on the provider's availability, and would be a
    request amplifier pointed at somebody else's service.
    """
    url = f"{issuer.rstrip('/')}/.well-known/openid-configuration"
    try:
        response = httpx.get(url, timeout=timeout_seconds)
        response.raise_for_status()
        document = response.json()
    except Exception as failure:
        raise DiscoveryFailed(f"could not read {url}: {type(failure).__name__}") from failure

    advertised = str(document.get("issuer") or "")
    if advertised.rstrip("/") != issuer.rstrip("/"):
        # The classic key-discovery attack: a document that points elsewhere.
        raise DiscoveryFailed(
            f"the discovery document advertises issuer {advertised!r}, not the "
            f"configured {issuer!r}; a jwks_uri from an untied document is not trusted"
        )
    jwks_uri = str(document.get("jwks_uri") or "")
    if not jwks_uri:
        raise DiscoveryFailed(f"{url} advertises no jwks_uri")
    return jwks_uri


class Authenticator(Protocol):
    """Credential in, `Principal` out, or raise. Never returns an unauthenticated one."""

    def authenticate(self, credential: str) -> Principal: ...


def _permissions_for(roles: list[str]) -> frozenset[Permission]:
    granted: set[Permission] = set()
    for role in roles:
        granted |= _PERMISSION_FOR_ROLE.get(role, frozenset())
    return frozenset(granted)


@dataclass(frozen=True, slots=True)
class StaticAuthenticator:
    """A configured principal table. Development and tests only.

    Exercises the identical downstream authorization path - it produces a `Principal`
    and nothing else, so there is no branch anywhere that treats a development
    principal more permissively than an OIDC one.
    """

    principals: dict[str, Principal]

    def authenticate(self, credential: str) -> Principal:
        principal = self.principals.get(credential)
        if principal is None:
            raise NotAuthenticated("unrecognised development credential")
        return principal


class OidcAuthenticator:
    """Validates a bearer token against an identity provider's keys.

    `jwks_url` is fetched and cached by `PyJWKClient`; `secret` is the symmetric
    alternative used by tests that do not want a key server. Exactly one must be given -
    an authenticator that could fall back from one to the other would be an
    authenticator whose verification depends on configuration nobody re-reads.
    """

    def __init__(
        self,
        *,
        issuer: str,
        audience: str,
        jwks_url: str | None = None,
        secret: str | None = None,
        roles_claim: str = "groups",
    ) -> None:
        if bool(jwks_url) == bool(secret):
            raise MedauthError(
                "OidcAuthenticator needs exactly one of jwks_url or secret; a "
                "verifier with a fallback is a verifier whose strength depends on "
                "which branch ran"
            )
        self._issuer = issuer
        self._audience = audience
        self._secret = secret
        self._roles_claim = roles_claim
        self._jwks: PyJWKClient | None = PyJWKClient(jwks_url) if jwks_url else None

    def _key(self, token: str) -> Any:
        if self._jwks is not None:
            return self._jwks.get_signing_key_from_jwt(token).key
        return self._secret

    def authenticate(self, credential: str) -> Principal:
        try:
            claims: dict[str, Any] = jwt.decode(
                credential,
                key=self._key(credential),
                algorithms=list(_ALGORITHMS),
                issuer=self._issuer,
                audience=self._audience,
                options={
                    # Every one of these is a real attack when disabled. They are
                    # listed rather than left to defaults so that a future edit has to
                    # say out loud which verification it is switching off.
                    "verify_signature": True,
                    "verify_exp": True,
                    "verify_nbf": True,
                    "verify_iat": True,
                    "verify_aud": True,
                    "verify_iss": True,
                    "require": ["exp", "iss", "aud", "sub"],
                },
            )
        except jwt.InvalidTokenError as failure:
            # A FIXED message. The first version interpolated
            # `type(failure).__name__`, which is `InvalidIssuerError`,
            # `ExpiredSignatureError`, `InvalidAudienceError` - each of which names the
            # check that failed, and that is a hint about how to craft the next token.
            # Its own test caught it.
            #
            # The specific cause is not lost: it travels on the exception chain
            # (`from failure`) and reaches the log with the request id attached, where
            # an operator can see it and a caller cannot.
            raise NotAuthenticated("token did not verify") from failure

        subject = str(claims.get("sub") or "").strip()
        if not subject:
            raise NotAuthenticated("token carries no subject")

        raw_roles = claims.get(self._roles_claim) or []
        roles = [str(r) for r in raw_roles] if isinstance(raw_roles, list) else []

        return Principal(
            principal_id=subject,
            principal_type=PrincipalType.HUMAN,
            authentication_method=AuthenticationMethod.OIDC,
            authenticated_at=datetime.now(UTC),
            display_name=str(claims.get("name") or ""),
            # Mapped from recognised roles. A `permissions` claim in the token is NOT
            # read - see the module docstring.
            permissions=_permissions_for(roles),
            issuer=str(claims.get("iss") or self._issuer),
        )
