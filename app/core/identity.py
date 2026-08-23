"""Canonical policy identity. Policy type is part of the key, never metadata.

Until Phase 6 a policy version was addressed three different ways depending on
where you stood: a bare UUID in retrieval, `(policy_id, revision_id)` in the
linkage YAML and the criteria inventory, and `(policy_id, document_type)` in the
database's unique constraint. The three agreed only because the corpus contained
one policy type.

Adopting NCDs ended that. `NCD 310.1` and a regulation could in principle share a
`policy_id`, share a `revision_id`, carry identical text and be in force on the same
date - and every composite key except the database's would treat them as one
document. R-62 is that gap in the evaluation runners; this module is the fix for the
class rather than the instance.

**Type participates in identity.** `PolicyIdentity` is `(policy_type, policy_id,
version)` and there is no constructor that omits the type. A function taking a
`PolicyIdentity` cannot be handed a half-identity by accident, which is what a
convention - "remember to pass the document type too" - cannot promise.

**The prefix is enforced, not assumed.** `42 CFR 410.32` and `NCD 310.1` are
distinguishable by eye today only because whoever wrote them was careful.
`PolicyIdentity` refuses a `policy_id` whose prefix disagrees with its type, so a
bare policy id in a log line, a citation or an error message is unambiguous about
which layer of authority it names.

Pure: `app.core` imports nothing from `app`, so this is usable from every layer
including `app.decision`.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

__all__ = ["PolicyIdentity", "PolicyIdentityError", "PolicyType"]


class PolicyType(StrEnum):
    """Where a document sits in the Medicare coverage hierarchy.

    The layers are distinct sources of authority and must not be conflated:
    statute, then REGULATION (42 CFR), then NCD (national), then LCD (local, by
    contractor), with ARTICLE attached to an LCD. A regulation labelled as an NCD
    would misstate both its authority and its scope.

    Defined here rather than in `app.policy.models` because identity is domain
    vocabulary, not a persistence detail, and `app.decision` may not import
    `app.policy`. `DocumentType` in `app.policy.models` is an alias of this.
    """

    REGULATION = "REGULATION"
    NCD = "NCD"
    LCD = "LCD"
    ARTICLE = "ARTICLE"

    @property
    def id_prefix(self) -> str:
        """The prefix a `policy_id` of this type must carry.

        Chosen to match what the sources themselves use: CFR sections are cited
        "42 CFR 410.32", NCDs are prefixed to disambiguate their bare dotted
        numbers (`310.1` alone says nothing), and LCD/Article ids already begin
        with their own letter.
        """
        return {
            PolicyType.REGULATION: "42 CFR ",
            PolicyType.NCD: "NCD ",
            PolicyType.LCD: "L",
            PolicyType.ARTICLE: "A",
        }[self]


class PolicyIdentityError(ValueError):
    """A policy identity is malformed. Never recovered from by defaulting."""


@dataclass(frozen=True, slots=True)
class PolicyIdentity:
    """One version of one policy, addressed unambiguously.

    Ordering of the fields is deliberate: type first, because it is the thing that
    was previously optional and is now the thing that cannot be omitted.
    """

    policy_type: PolicyType
    policy_id: str
    version: str

    def __post_init__(self) -> None:
        if not self.policy_id.strip():
            raise PolicyIdentityError("policy_id is empty")
        if not self.version.strip():
            raise PolicyIdentityError(f"{self.policy_id}: version is empty")
        if not self.policy_id.startswith(self.policy_type.id_prefix):
            raise PolicyIdentityError(
                f"{self.policy_id!r} does not carry the {self.policy_type.value} "
                f"prefix {self.policy_type.id_prefix!r}. A bare policy id must say "
                "which layer of authority it names - otherwise a regulation and a "
                "coverage determination can be told apart only by whoever wrote them."
            )

    @property
    def key(self) -> tuple[str, str, str]:
        """The composite key. Use this wherever a dict or set is keyed by policy."""
        return (self.policy_type.value, self.policy_id, self.version)

    @property
    def scope_key(self) -> tuple[str, str]:
        """Type and id, without the version. For grouping versions of one policy."""
        return (self.policy_type.value, self.policy_id)

    def __str__(self) -> str:
        return f"{self.policy_type.value}:{self.policy_id}:{self.version}"

    @classmethod
    def parse(cls, raw: str) -> PolicyIdentity:
        """Round-trips `__str__`. Refuses anything else.

        `policy_id` may itself contain colons in principle, so the split is bounded
        at the ends rather than done naively - the type is the first field and the
        version is the last.
        """
        parts = raw.split(":")
        if len(parts) < 3:
            raise PolicyIdentityError(
                f"{raw!r} is not a policy identity; expected '<TYPE>:<policy id>:<version>'"
            )
        type_token, version = parts[0], parts[-1]
        policy_id = ":".join(parts[1:-1])
        try:
            policy_type = PolicyType(type_token)
        except ValueError as exc:
            raise PolicyIdentityError(f"{raw!r}: unknown policy type {type_token!r}") from exc
        return cls(policy_type=policy_type, policy_id=policy_id, version=version)

    @classmethod
    def infer(cls, policy_id: str, version: str) -> PolicyIdentity:
        """Recover the type from a prefixed `policy_id`.

        A migration aid for artefacts written before type was part of identity -
        the criteria inventory, the linkage YAML, gold case records. It refuses
        rather than guessing when no prefix matches, because a default here would
        reintroduce exactly the ambiguity this module removes.

        New code should carry a `PolicyIdentity` rather than reconstructing one.
        """
        # Longest prefix first, so "42 CFR " is not shadowed by a shorter match.
        for policy_type in sorted(PolicyType, key=lambda t: -len(t.id_prefix)):
            if policy_id.startswith(policy_type.id_prefix):
                return cls(policy_type=policy_type, policy_id=policy_id, version=version)
        raise PolicyIdentityError(
            f"{policy_id!r} carries no recognised policy-type prefix. Its type cannot "
            "be inferred, and guessing one would defeat the point of the prefix."
        )
