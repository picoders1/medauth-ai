"""What is known about a policy's decision logic, and on whose authority.

Phase 4 gave policies a way to *state* their logic. It did not give the decision
engine a way to know whether anyone had looked. `decide()` accepted
`logic: PolicyLogic | None = None` and, given `None`, built an assumed conjunction
and executed it - so a caller who had never consulted the logic inventory got a
silent adjudication under a rule shape nobody established. Four of eight policy
versions in the corpus are classified `REVIEW_REQUIRED`; the record stated a doubt
the runtime did not act on. That was R-59.

This module removes the possibility rather than the default. `decide()` now takes a
`PolicySemantics` as a required argument, and there is no longer any code path that
manufactures one. Reintroducing the hole means *adding* a fallback - a visible line
in a diff - not flipping a default.

**The invariant is a construction rule, not a check.** `PolicySemantics` is built
only through the classmethods below, and each demotes to
`POLICY_SEMANTICS_UNKNOWN` when an executable status arrives without both a matching
`PolicyLogic` and an `Attestation` naming the artefact that supplied it. There is no
validation anyone can forget to call: the type cannot represent an unattested
assumption. Demotion rather than a raise keeps `decide()` total - a misconfigured
caller routes cases to a human instead of raising in an adjudication path.

**Two failure causes, kept apart.** `REVIEW_REQUIRED` means the *corpus* has not
been qualified - a human must read the policy (OD-19). `POLICY_SEMANTICS_UNKNOWN`
means the *runtime wiring* cannot establish that what it holds is verified - an
engineer must fix the caller. They produce different decision rules and different
audit rows, because a misconfigured deployment must not be indistinguishable from an
honestly-unreviewed corpus.

Purity: no I/O, no clock, no settings. `app.decision` may import only `app.core` and
its own modules, so reading the inventory, hashing it and deciding what a given
environment will accept all belong to `app.policy` - see
`app/policy/logic_loader.py` and `app/policy/semantics_guard.py`.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from enum import StrEnum

from app.decision.logic import LogicForm, PolicyLogic

__all__ = [
    "PRODUCTION_ORIGINS",
    "Attestation",
    "PolicySemantics",
    "SemanticsOrigin",
    "SemanticsStatus",
]


class SemanticsStatus(StrEnum):
    """What is known about this policy version's decision logic.

    The first four mirror `LogicForm` and the logic inventory exactly - a test
    asserts the two vocabularies stay aligned, so a new inventory classification
    cannot appear without a decision here about how it executes.

    The fifth has no `LogicForm` counterpart on purpose. `LogicForm` answers "how
    did this tree come to be?" and presupposes a tree; `POLICY_SEMANTICS_UNKNOWN`
    means there is no tree to ask about.
    """

    #: A person read the regulation and wrote its logic down. Executes.
    DECLARED = "DECLARED"

    #: No logic declared, and no wording suggesting a conjunction misreads it.
    #: Executes, but only when the inventory attests that it looked.
    ASSUMED_CONJUNCTION = "ASSUMED_CONJUNCTION"

    #: The inventory found exception, alternative or conditional wording and no
    #: declaration. The corpus is unqualified. A human must read it (OD-19).
    REVIEW_REQUIRED = "REVIEW_REQUIRED"

    #: Nothing has been transcribed from this policy, so there is nothing to
    #: adjudicate. Every ingested NCD lands here until criteria exist for it.
    NO_CRITERIA = "NO_CRITERIA"

    #: Nobody consulted the inventory, or what was supplied could not be
    #: attested. A wiring fault, not a corpus fault. This is the default, and it
    #: is the reason the default is safe.
    POLICY_SEMANTICS_UNKNOWN = "POLICY_SEMANTICS_UNKNOWN"

    @property
    def is_executable(self) -> bool:
        """Whether this status may produce a definitive policy truth."""
        return self in (SemanticsStatus.DECLARED, SemanticsStatus.ASSUMED_CONJUNCTION)


class SemanticsOrigin(StrEnum):
    """Which artefact answered the question, and whether production accepts it."""

    #: `data/policy_logic/inventory.json`, loaded and hashed at startup.
    POLICY_LOGIC_INVENTORY = "POLICY_LOGIC_INVENTORY"

    #: A `data/policy_logic/*.yaml` declaration, loaded and hashed.
    DECLARED_LOGIC_FILE = "DECLARED_LOGIC_FILE"

    #: Nothing was consulted. Carried by every fail-closed value.
    UNCONSULTED = "UNCONSULTED"

    #: Reproduction of the assumption gold_v1's labels were computed under.
    #: Written only by `eval/replay.py`, which lives outside `app/` so that a
    #: production module importing it is a layer-boundary test failure.
    GOLD_V1_REPLAY = "GOLD_V1_REPLAY"


#: Origins production will act on. Everything else is demoted by
#: `app.policy.semantics_guard.admissible` before it reaches `decide()`.
PRODUCTION_ORIGINS = frozenset(
    {SemanticsOrigin.POLICY_LOGIC_INVENTORY, SemanticsOrigin.DECLARED_LOGIC_FILE}
)


@dataclass(frozen=True, slots=True)
class Attestation:
    """Which committed artefact answered, and what it hashed to when it did.

    The digest is what makes the replay path a real boundary rather than a naming
    convention. A hand-written attestation - including one built in a test - has a
    digest that does not match the inventory loaded at startup, so production
    refuses it without needing to recognise where it came from.
    """

    source: str
    sha256: str
    origin: SemanticsOrigin


@dataclass(frozen=True, slots=True)
class PolicySemantics:
    """The answer to "what is this policy version's logic, and who says so?".

    Construct through the classmethods, never through `PolicySemantics(...)`
    directly - only the classmethods apply the demotion rule, and the demotion
    rule is the entire safety property of this module.
    """

    policy_id: str
    policy_version: str
    status: SemanticsStatus
    logic: PolicyLogic | None = None
    attestation: Attestation | None = None
    notes: tuple[str, ...] = ()

    # -- properties ---------------------------------------------------------

    @property
    def origin(self) -> SemanticsOrigin:
        return self.attestation.origin if self.attestation else SemanticsOrigin.UNCONSULTED

    @property
    def is_executable(self) -> bool:
        """True only when a tree exists AND the status permits executing it.

        Both halves are checked because either alone has been wrong at some point:
        a status can be executable with no tree (a demotion that did not clear
        `logic`), and a tree can exist under a status that must not run it
        (`REVIEW_REQUIRED` with a declared file present).
        """
        return self.status.is_executable and self.logic is not None

    def demoted(self, reason: str) -> PolicySemantics:
        """A copy that cannot execute, carrying why. Used by the production guard."""
        return replace(
            self,
            status=SemanticsStatus.POLICY_SEMANTICS_UNKNOWN,
            logic=None,
            attestation=None,
            notes=(*self.notes, reason),
        )

    # -- constructors -------------------------------------------------------

    @classmethod
    def _executable(
        cls,
        *,
        policy_id: str,
        policy_version: str,
        status: SemanticsStatus,
        expected_form: LogicForm,
        logic: PolicyLogic | None,
        attestation: Attestation | None,
        notes: tuple[str, ...],
    ) -> PolicySemantics:
        """Build an executable value, or demote it and say why.

        Three ways to fail, each demoted rather than raised so that a
        misconfiguration reaches a human as a routed case rather than as a 500 on
        the adjudication path.
        """
        problems: list[str] = []
        if logic is None:
            problems.append(f"{status.value} claimed with no policy logic supplied")
        elif logic.form is not expected_form:
            problems.append(f"{status.value} claimed but the supplied logic is {logic.form.value}")
        if attestation is None:
            problems.append(
                f"{status.value} claimed with no attestation naming the artefact that supplied it"
            )

        if problems:
            return cls(
                policy_id=policy_id,
                policy_version=policy_version,
                status=SemanticsStatus.POLICY_SEMANTICS_UNKNOWN,
                logic=None,
                attestation=None,
                notes=(*notes, *problems),
            )
        return cls(
            policy_id=policy_id,
            policy_version=policy_version,
            status=status,
            logic=logic,
            attestation=attestation,
            notes=notes,
        )

    @classmethod
    def declared(
        cls,
        *,
        policy_id: str,
        policy_version: str,
        logic: PolicyLogic | None,
        attestation: Attestation | None,
        notes: tuple[str, ...] = (),
    ) -> PolicySemantics:
        """A policy whose logic someone read off the regulation and wrote down."""
        return cls._executable(
            policy_id=policy_id,
            policy_version=policy_version,
            status=SemanticsStatus.DECLARED,
            expected_form=LogicForm.DECLARED,
            logic=logic,
            attestation=attestation,
            notes=notes,
        )

    @classmethod
    def assumed(
        cls,
        *,
        policy_id: str,
        policy_version: str,
        logic: PolicyLogic | None,
        attestation: Attestation | None,
        notes: tuple[str, ...] = (),
    ) -> PolicySemantics:
        """A conjunction the inventory looked at and found no reason to doubt.

        Still requires an attestation. "The inventory says a conjunction is
        probably right here" and "nobody checked" produce the same tree, and the
        whole point of R-59 is that they must not produce the same behaviour.
        """
        return cls._executable(
            policy_id=policy_id,
            policy_version=policy_version,
            status=SemanticsStatus.ASSUMED_CONJUNCTION,
            expected_form=LogicForm.ASSUMED_CONJUNCTION,
            logic=logic,
            attestation=attestation,
            notes=notes,
        )

    @classmethod
    def review_required(
        cls,
        *,
        policy_id: str,
        policy_version: str,
        notes: tuple[str, ...] = (),
    ) -> PolicySemantics:
        """The corpus is unqualified for this version. No tree is carried.

        Any declared logic that happened to exist is deliberately dropped: if the
        inventory says this version needs review, holding a tree beside that
        verdict invites someone to run it.
        """
        return cls(
            policy_id=policy_id,
            policy_version=policy_version,
            status=SemanticsStatus.REVIEW_REQUIRED,
            logic=None,
            attestation=None,
            notes=notes,
        )

    @classmethod
    def no_criteria(
        cls,
        *,
        policy_id: str,
        policy_version: str,
        notes: tuple[str, ...] = (),
    ) -> PolicySemantics:
        """Nothing transcribed from this policy, so nothing to adjudicate."""
        return cls(
            policy_id=policy_id,
            policy_version=policy_version,
            status=SemanticsStatus.NO_CRITERIA,
            logic=None,
            attestation=None,
            notes=notes,
        )

    @classmethod
    def unconsulted(
        cls,
        *,
        policy_id: str = "unspecified",
        policy_version: str = "unspecified",
        notes: tuple[str, ...] = (),
    ) -> PolicySemantics:
        """The fail-closed value. Nobody asked the inventory.

        This is what a caller gets by constructing nothing, and what the
        production guard returns for anything it refuses.
        """
        return cls(
            policy_id=policy_id,
            policy_version=policy_version,
            status=SemanticsStatus.POLICY_SEMANTICS_UNKNOWN,
            logic=None,
            attestation=None,
            notes=notes or ("the policy logic inventory was not consulted",),
        )
