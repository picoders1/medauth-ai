"""Who is acting, and what they are allowed to do.

OD-43: the audit trail recorded who **claimed** to decide. `reviewer_id` arrived in the
request body, the API key identified the integrating *system*, and nothing connected the
two. In an otherwise append-only, trigger-enforced, tamper-proof record, the one field
anybody would actually ask about after a bad outcome was the one field a client chose.

## SERVICE and HUMAN are different kinds, not different values

`PrincipalType` is checked by **identity** (`is HUMAN`), never by membership in a set of
non-human types, and `Permission.HUMAN_ONLY` names the actions a service may never take
however many permissions it accumulates. A service integration that acquired
`REVIEW_CASE` - by a mapping typo, by an over-broad group in an IdP - still cannot
review, because the type check happens first and does not consult permissions at all.

That separation is the whole point of the OD. Collapsing it into "a principal with the
right permission" would reintroduce the gap under a better-looking name.

## Permissions are granted, never inferred

A `Principal` carries exactly the permissions it was constructed with. Nothing here
derives a permission from a role name, a display name, an email domain or an issuer -
each of those is a string an identity provider controls, and inferring authority from
one is how "reviewer" in a group name becomes the right to finalise a case.

## No passwords, ever

There is no credential on this object and no method that verifies one. Identity comes
from an authenticated token or from a configured development principal; this module
holds the *result* of authentication and never performs it.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum

from app.core.errors import MedauthError

__all__ = [
    "HUMAN_ONLY",
    "AuthenticationMethod",
    "NotAuthorised",
    "Permission",
    "Principal",
    "PrincipalType",
]


class PrincipalType(StrEnum):
    """What kind of actor this is. **Never inferred from permissions.**"""

    #: A person, authenticated as themselves.
    HUMAN = "HUMAN"
    #: An integrating system. Legitimate for submitting and reading cases; never for
    #: deciding one.
    SERVICE = "SERVICE"


class Permission(StrEnum):
    """What an actor may do. Granted explicitly; never derived from a role string."""

    #: Submit a case and read back what happened to it.
    SUBMIT_CASE = "SUBMIT_CASE"
    READ_CASE = "READ_CASE"
    #: Record a clinical review decision on a case routed to a human.
    REVIEW_CASE = "REVIEW_CASE"
    #: Decide against the engine's recommendation. Separate from REVIEW_CASE because
    #: disagreeing with the system is a different authority from agreeing with it.
    OVERRIDE_RECOMMENDATION = "OVERRIDE_RECOMMENDATION"
    #: Bring a case to a terminal disposition.
    FINALIZE_CASE = "FINALIZE_CASE"


#: Actions **no service principal may take**, whatever permissions it holds.
#:
#: Checked before permissions, not alongside them. A service that somehow acquired
#: `REVIEW_CASE` still cannot review - which is the property OD-43 exists to establish,
#: and it must not depend on a permission mapping being correct.
HUMAN_ONLY: frozenset[Permission] = frozenset(
    {
        Permission.REVIEW_CASE,
        Permission.OVERRIDE_RECOMMENDATION,
        Permission.FINALIZE_CASE,
    }
)


class AuthenticationMethod(StrEnum):
    """How this principal was established. Recorded on every human audit event.

    A later reader needs to know not just *who* decided but *on what basis the system
    believed them* - a development principal and an OIDC subject are not the same
    evidence, and a trail that rendered them identically would be misleading in exactly
    the situation it exists for.
    """

    #: A validated OIDC/JWT bearer token. The production path.
    OIDC = "OIDC"
    #: A configured development principal. **Never valid in production** - the settings
    #: validator refuses it, and a test asserts the refusal.
    DEVELOPMENT = "DEVELOPMENT"
    #: A service API key. Establishes a SERVICE principal and nothing more.
    API_KEY = "API_KEY"


class NotAuthorised(MedauthError):
    """The principal is authenticated but may not do this.

    Distinct from `NotAuthenticated` (401) and from `CaseNotFound` (404, which also
    covers "not yours" so that case ids cannot be enumerated). This is 403: we know who
    you are, you may see this, and you may not do that.
    """


@dataclass(frozen=True, slots=True)
class Principal:
    """An authenticated actor. Immutable, and carries no credential.

    Frozen because a principal that could be mutated after authentication is a
    principal whose permissions can be widened between the check and the write.
    """

    principal_id: str
    principal_type: PrincipalType
    authentication_method: AuthenticationMethod
    authenticated_at: datetime
    display_name: str = ""
    permissions: frozenset[Permission] = field(default_factory=frozenset)
    #: The identity provider that asserted this, where one did. Recorded on the audit
    #: event: "which system vouched for this person" is part of the answer to "who
    #: decided", and it is not reconstructible later.
    issuer: str | None = None
    #: Free text, supplied by the person, describing their competence to decide. NOT
    #: an authority claim - this project cannot enumerate clinical credentials, and a
    #: dropdown would imply it had. It is context for a later reader, and it is
    #: recorded beside the authenticated identity rather than instead of it.
    stated_qualification: str = ""

    @property
    def is_human(self) -> bool:
        return self.principal_type is PrincipalType.HUMAN

    def has(self, permission: Permission) -> bool:
        return permission in self.permissions

    def require(self, permission: Permission) -> None:
        """Raise unless this principal may do it. **The only supported way to check.**

        Type first, then permission. A service is refused for a human-only action
        before its permissions are consulted at all, so the refusal cannot be undone by
        granting it something.
        """
        if permission in HUMAN_ONLY and not self.is_human:
            raise NotAuthorised(
                f"{self.principal_id} is a {self.principal_type.value} principal and "
                f"{permission.value} is a human-only action. A service integration "
                "cannot make a clinical decision, however it is configured."
            )
        if permission not in self.permissions:
            raise NotAuthorised(f"{self.principal_id} does not hold {permission.value}")
