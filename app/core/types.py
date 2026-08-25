"""Closed domain vocabulary shared by every layer.

What is **not** here is as deliberate as what is. ``Outcome`` and
``Recommendation`` live in ``app.decision`` rather than here, so that the
layer-boundary test can assert they are unreachable from ``app.intake`` and
``app.adjudication``. If they lived in ``core`` - which every package may import -
the invariant would be unenforceable by construction (ADR-010).
"""

from __future__ import annotations

from enum import StrEnum

__all__ = [
    "CitationStatus",
    "CodeSystem",
    "CriterionKind",
    "CriterionLogic",
    "ResolutionStatus",
    "Verdict",
]


class Verdict(StrEnum):
    """A model's judgement about ONE criterion.

    This is the entire vocabulary available to an adjudication call. There is no
    case-level outcome member, and there never may be: a successful prompt
    injection cannot emit an approval because no approval token exists in the
    schema it is filling.
    """

    SATISFIED = "SATISFIED"
    NOT_SATISFIED = "NOT_SATISFIED"
    INSUFFICIENT_EVIDENCE = "INSUFFICIENT_EVIDENCE"
    NOT_APPLICABLE = "NOT_APPLICABLE"


class CriterionKind(StrEnum):
    """What role a criterion plays in a policy's logic.

    ``EXCEPTION_CONDITION`` never enters a conjunction on its own. It exists only
    on an alternative pathway inside declared policy logic, so failing it cannot
    deny - it simply means the ordinary rule still governs (ADR-023).
    """

    REQUIRED = "REQUIRED"
    EXCLUSION = "EXCLUSION"
    INFORMATIONAL = "INFORMATIONAL"
    EXCEPTION_CONDITION = "EXCEPTION_CONDITION"


class CriterionLogic(StrEnum):
    ALL_OF = "ALL_OF"
    ANY_OF = "ANY_OF"
    N_OF = "N_OF"
    LEAF = "LEAF"


class CitationStatus(StrEnum):
    """Why a citation passed or failed deterministic verification (ADR-009)."""

    VALID = "VALID"
    SPAN_MISMATCH = "SPAN_MISMATCH"
    UNKNOWN_CHUNK = "UNKNOWN_CHUNK"
    METADATA_MISMATCH = "METADATA_MISMATCH"
    OUT_OF_EVIDENCE_SET = "OUT_OF_EVIDENCE_SET"


class ResolutionStatus(StrEnum):
    """Outcome of deterministic policy resolution (ADR-004, ADR-028).

    Six distinct states, and **none of them may be collapsed into ``RESOLVED``**.
    Phase 14 shipped a runtime that asserted ``RESOLVED`` because it had been handed
    a policy identity, which made every other state unreachable and produced a
    fully-cited denial against a policy that did not govern the case (R-93). Only
    ``RESOLVED`` permits retrieval or adjudication; every other member routes to a
    human or to a request for information, and the routing is declared as data in
    `app.decision.table` so a seventh member cannot be added without deciding where
    it goes.

    **Two names per concept, on purpose.** ``NONE_APPLICABLE`` and ``CONFLICTING``
    are the values this repository has written into `data/gold/cases/gold_v1.jsonl`
    and into committed evaluation reports since Phase 2. Phase 15 names the same two
    states ``NOT_APPLICABLE`` and ``MULTIPLE_CANDIDATES``; they are declared below as
    enum *aliases*, so `ResolutionStatus.NOT_APPLICABLE is
    ResolutionStatus.NONE_APPLICABLE` and the serialised value is unchanged.
    Renaming instead would have rewritten a frozen dataset and four immutable
    reports to gain nothing a reader could check.
    """

    #: The designated policy version governs this request. The ONLY state from which
    #: retrieval and adjudication may proceed.
    RESOLVED = "RESOLVED"

    #: No policy governs this request. Absence of an NCD/LCD generally means
    #: contractor discretion, not non-coverage - so this is never a denial (row 1).
    NONE_APPLICABLE = "NONE_APPLICABLE"

    #: Several policies could govern and which one does is a human judgement. Also
    #: covers a corpus defect - two versions of one document in force at once.
    CONFLICTING = "CONFLICTING"

    #: A policy lists the procedure, but no version of it was in force on the date of
    #: service. Distinct from NONE_APPLICABLE: the corpus has the policy and cannot
    #: place the request inside any of its windows, which is a temporal answer rather
    #: than a coverage one.
    TEMPORALLY_UNRESOLVED = "TEMPORALLY_UNRESOLVED"

    #: The request does not carry enough to decide applicability at all - no
    #: procedure code, no code system, no date of service. A question for the
    #: submitter, not for a reviewer.
    INSUFFICIENT_INFORMATION = "INSUFFICIENT_INFORMATION"

    #: Resolution could not be performed, or produced a policy other than the one
    #: this runtime is wired to adjudicate. A wiring or infrastructure fault; it
    #: fails toward the human, never toward a denial.
    RESOLUTION_ERROR = "RESOLUTION_ERROR"

    # Phase-15 vocabulary. Aliases - same member, same value, no new state.
    NOT_APPLICABLE = "NONE_APPLICABLE"
    MULTIPLE_CANDIDATES = "CONFLICTING"

    @property
    def permits_adjudication(self) -> bool:
        """Whether a case in this state may reach retrieval and a model.

        Written as an identity test against the one admitting value rather than as
        a membership test over the refusing ones: a new state added tomorrow is
        refused by default instead of admitted by omission.
        """
        return self is ResolutionStatus.RESOLVED


class CodeSystem(StrEnum):
    HCPCS = "HCPCS"
    CPT = "CPT"
    ICD10CM = "ICD10CM"
    ICD10PCS = "ICD10PCS"
