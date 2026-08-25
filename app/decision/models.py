"""The decision vocabulary. Reachable from ``app.decision`` and nowhere else.

``Outcome`` is the only place in this codebase where an approval or a denial can
be named. ``app.intake`` and ``app.adjudication`` cannot import this module, and
``tests/unit/test_layer_boundaries.py`` asserts it by parsing the AST - so the
constraint holds even for a module that is never imported at runtime.
"""

from __future__ import annotations

from enum import IntEnum, StrEnum

from pydantic import BaseModel, ConfigDict, Field

from app.decision.semantics import SemanticsOrigin, SemanticsStatus

__all__ = ["DecisionRule", "Outcome", "Recommendation"]


class Outcome(StrEnum):
    """What the system recommends to a human reviewer.

    Every member is a first-class terminal state with its own rendering and its
    own audit row. None is an error path.
    """

    APPROVE_RECOMMENDED = "APPROVE_RECOMMENDED"
    DENY_RECOMMENDED = "DENY_RECOMMENDED"
    NEEDS_INFO = "NEEDS_INFO"
    HUMAN_REVIEW = "HUMAN_REVIEW"
    NO_DECISION = "NO_DECISION"


class DecisionRule(IntEnum):
    """The row of the decision table that produced a recommendation.

    Recorded on every recommendation so an outcome is *explainable* rather than
    merely reported. The numbering is the evaluation order, and the order is
    itself a safety property: rows 1-6 are all checked before any denial becomes
    reachable, and row 6 (missing evidence) precedes rows 7 and 8 (evidenced
    non-satisfaction). That is what separates "the note does not say" from "the
    note says otherwise" - see ADR-010.
    """

    NO_APPLICABLE_POLICY = 1
    CONFLICTING_POLICY = 2
    INVALID_CITATION = 3
    MODEL_PATH_FAILED = 4
    CONTRADICTORY_VERDICTS = 5
    INSUFFICIENT_EVIDENCE = 6
    EXCLUSION_SATISFIED = 7
    REQUIRED_NOT_SATISFIED = 8
    ALL_REQUIRED_SATISFIED = 9
    UNCLASSIFIED = 10

    # Phase 4. The number is the rule's identity, not its position: 11 and 12
    # are refinements that fire *inside* the ordering above, and where they fire
    # is stated here so the numbering cannot be misread as a new tail.
    #
    #   EXCEPTION_SATISFIED       replaces rule 9 when the policy was satisfied
    #                             through an alternative pathway rather than by
    #                             every requirement holding on its own.
    #   POLICY_SEMANTICS_UNRESOLVED  fires immediately after rule 5 and before
    #                             any denial: a policy whose logic is not yet
    #                             established cannot produce a recommendation.
    EXCEPTION_SATISFIED = 11
    POLICY_SEMANTICS_UNRESOLVED = 12

    #: Phase 5. The runtime could not establish that the semantics it holds are
    #: verified - nobody consulted the logic inventory, or what was supplied could
    #: not be attested against it. Fires in the same position as rule 12, after
    #: rule 5 and before any denial or approval.
    #:
    #: Kept separate from 12 deliberately. Rule 12 is a corpus problem, fixed by
    #: qualified review (OD-19); rule 13 is a wiring problem, fixed by fixing the
    #: caller. Collapsing them would make a misconfigured deployment
    #: indistinguishable from an honestly-unreviewed corpus, in the audit trail
    #: of all places.
    POLICY_SEMANTICS_UNVERIFIED = 13

    #: Phase 15. What deterministic policy *applicability* concluded, when it
    #: concluded something other than "the designated policy governs".
    #:
    #: These three fire immediately after rows 1 and 2 - with which they form one
    #: block - and therefore before every guardrail row and before any approval or
    #: denial. That position is the R-93 fix: until Phase 15 the runtime asserted
    #: `RESOLVED` because it had been handed a policy identity, so rows 1 and 2 were
    #: unreachable from the live slice and a case whose policy did not govern was
    #: adjudicated against it anyway.
    #:
    #:   POLICY_TEMPORALLY_UNRESOLVED  a policy lists the procedure and no version of
    #:                             it was in force on the date of service. Not the
    #:                             same claim as row 1: the corpus HAS the policy.
    #:   RESOLUTION_INSUFFICIENT_INFORMATION
    #:                             the request cannot establish applicability at all
    #:                             - no code, no code system, or no date of service.
    #:                             A question for the submitter, so NEEDS_INFO.
    #:   POLICY_RESOLUTION_ERROR   resolution failed, or returned a policy other than
    #:                             the one this runtime adjudicates. A wiring or
    #:                             infrastructure fault; it fails toward the human.
    POLICY_TEMPORALLY_UNRESOLVED = 14
    RESOLUTION_INSUFFICIENT_INFORMATION = 15
    POLICY_RESOLUTION_ERROR = 16


class Recommendation(BaseModel):
    """The system's output. Produced by ``decide()``, never by a model."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    outcome: Outcome
    rule: DecisionRule
    abstained: bool = False
    abstention_reason: str | None = None
    missing_evidence: tuple[str, ...] = ()
    gate_features: dict[str, float] = Field(default_factory=dict)
    decision_config_version: str = "unset"

    #: What was known about the policy's logic, and on whose authority. Defaults
    #: are the fail-closed values so a hand-built `Recommendation` cannot claim
    #: provenance it does not have.
    policy_semantics: SemanticsStatus = SemanticsStatus.POLICY_SEMANTICS_UNKNOWN
    semantics_origin: SemanticsOrigin = SemanticsOrigin.UNCONSULTED
