"""Identity, qualification and competence are three things. This keeps them apart.

The reviewer authentication phase established **who** someone is. It established
nothing about whether they are competent to make a coverage decision, and the gap
between those two is exactly where a system starts implying more than it knows.

## The three concepts, and what this repository can say about each

| concept | question | what MEDAUTH has |
|---|---|---|
| **identity** | who is this? | a validated OIDC subject. **Established.** |
| **qualification** | what are they credentialed to do? | a sentence they typed. **`SELF_ASSERTED`.** |
| **competence** | are they able to decide *this* case? | nothing at all. **Not modelled.** |

`stated_qualification` is the second one, and it is informational. It appears beside a
decision so a later reader knows what the reviewer said about themselves - not so the
system can act on it.

## Qualification grants nothing, and cannot

There is no function here that takes a qualification and returns a permission, and no
call site that could pass one. `verification_state()` returns a *label*, and
`Permission` is granted only by the role mapping in `app/identity/authenticator.py`.
That is the separation Part D asks for, expressed as an absence rather than as a rule
somebody has to keep.

If a verified credential registry ever exists, `VERIFIED_BY_REGISTRY` becomes reachable
and the label changes. **It still would not grant a permission** - a credential says
what someone may do in the world, and an authorization says what they may do in this
system, and conflating them is how a licence number becomes a bypass.
"""

from __future__ import annotations

from enum import StrEnum

from app.identity.principal import Principal

__all__ = ["QualificationState", "qualification_of", "verification_state"]


class QualificationState(StrEnum):
    """How much the system knows about a reviewer's credentials.

    Three states, and **two of them are currently unreachable**. That is deliberate:
    a vocabulary that only contains what exists today cannot express the difference
    between "we checked and they are qualified" and "nobody has checked", which is the
    distinction a reader of a past decision most needs.
    """

    #: No qualification was stated at all.
    NOT_STATED = "NOT_STATED"
    #: The reviewer typed something about themselves. **Nobody verified it.** This is
    #: the only state a live deployment can currently produce.
    SELF_ASSERTED = "SELF_ASSERTED"
    #: A credential registry confirmed it. **Unreachable today** - no such registry is
    #: integrated, and inventing one would be the fabrication this project refuses.
    VERIFIED_BY_REGISTRY = "VERIFIED_BY_REGISTRY"


#: What the UI and the audit trail render beside a decision when nothing verified it.
#: A phrase rather than a flag, because "QUALIFICATION_NOT_VERIFIED" printed next to a
#: clinical decision has to be readable by whoever is reading that decision.
NOT_VERIFIED_NOTICE = "Qualification is self-asserted and has not been verified by any registry."


def qualification_of(principal: Principal) -> str:
    """What the reviewer said about themselves. May be empty."""
    return principal.stated_qualification.strip()


def verification_state(principal: Principal) -> QualificationState:
    """How much is known about it.

    Never returns `VERIFIED_BY_REGISTRY`: no registry is integrated. When one is, this
    function grows a lookup - and still does not grant anything.
    """
    return (
        QualificationState.SELF_ASSERTED
        if qualification_of(principal)
        else QualificationState.NOT_STATED
    )
