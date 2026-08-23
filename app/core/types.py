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
    REQUIRED = "REQUIRED"
    EXCLUSION = "EXCLUSION"
    INFORMATIONAL = "INFORMATIONAL"


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
    """Outcome of deterministic policy resolution (ADR-004)."""

    RESOLVED = "RESOLVED"
    NONE_APPLICABLE = "NONE_APPLICABLE"
    CONFLICTING = "CONFLICTING"


class CodeSystem(StrEnum):
    HCPCS = "HCPCS"
    CPT = "CPT"
    ICD10CM = "ICD10CM"
    ICD10PCS = "ICD10PCS"
