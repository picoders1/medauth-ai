"""Policy criteria: declared by the document, span-verified against it.

Criteria are the bridge between a policy and a clinical case, so how they come into
existence decides whether any downstream evaluation means anything.

**They are not invented.** A criterion is *declared* in the policy document's
metadata with a section anchor and the exact source text it rests on, and ingestion
verifies that text actually occurs in that section - using the same normalizer that
verifies citations (ADR-009). A declaration that cannot be located is rejected, not
stored.

That mirrors what a human reviewer does with a real determination: read it,
transcribe the operative criteria, record where each came from. When a real CMS
document arrives, a human transcribes into this same structure and the identical
verification runs. The verification is real today even though the documents being
verified are not yet authoritative.

Criterion **logic** - how criterion states combine into an expected outcome - is
declared alongside them, because a policy's own logic ("all of the following",
"any of", "except when") is a property of the policy and must not be inferred.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Protocol, runtime_checkable

from app.core.errors import MedauthError
from app.core.normalize import find_span

__all__ = [
    "CriterionDeclaration",
    "CriterionProvenanceError",
    "CriterionType",
    "SectionLike",
    "VerifiedCriterion",
    "criterion_id",
    "verify_criteria",
]

#: Criterion ids are derived, never free text, and never only a description.
#: POLICY_<policy>_<revision>_C<nn> - stable across re-ingestion because it is a
#: pure function of the policy identity and the declared ordinal.
_ID_SAFE = re.compile(r"[^A-Z0-9]+")


@runtime_checkable
class SectionLike(Protocol):
    """The three fields verification needs from a section.

    Structural rather than a concrete import: `documents` holds the criteria it
    parsed, so importing `Section` here would close a cycle. What verification
    actually needs is small enough that a protocol says it precisely.
    """

    @property
    def path(self) -> str: ...

    @property
    def text(self) -> str: ...

    @property
    def page_from(self) -> int: ...


class CriterionType(StrEnum):
    """What role a criterion plays in the policy's own logic.

    ``REQUIRED`` and ``EXCLUSION`` bear on the outcome directly. ``INFORMATIONAL``
    does not - it is recorded because policies state things that are not tests, and
    dropping them would misrepresent the document.

    ``EXCEPTION_CONDITION`` is a condition that appears only inside a policy's
    declared logic, on an alternative pathway. It is not a requirement: failing it
    must never deny, because all it means is that the ordinary rule applies after
    all. 42 CFR 410.32(a)(1) is the case that forced it - a qualified interpreting
    physician may order a diagnostic mammogram from screening findings "even though
    the physician does not treat the beneficiary", so the ordering requirement has
    a route through it that a conjunction cannot express (ADR-023).
    """

    REQUIRED = "REQUIRED"
    EXCLUSION = "EXCLUSION"
    INFORMATIONAL = "INFORMATIONAL"
    EXCEPTION_CONDITION = "EXCEPTION_CONDITION"


class CriterionProvenanceError(MedauthError):
    """A declared criterion could not be located in the section it claims."""


def criterion_id(policy_id: str, revision_id: str, ordinal: int) -> str:
    """Stable, derived criterion identifier."""
    policy = _ID_SAFE.sub("_", policy_id.upper()).strip("_")
    revision = _ID_SAFE.sub("_", revision_id.upper()).strip("_")
    return f"{policy}_{revision}_C{ordinal:02d}"


@dataclass(frozen=True, slots=True)
class CriterionDeclaration:
    """One criterion as the document declares it, before verification."""

    ordinal: int
    criterion_type: CriterionType
    summary: str
    source_section: str
    source_text: str
    #: The clinical fact this criterion tests, as a stable key. Case generation
    #: varies exactly these, which is what makes criterion-level evaluation possible.
    fact_key: str
    #: Optional machine-checkable shape of the test, for cases to be built against.
    comparator: str | None = None
    threshold: str | None = None
    unit: str | None = None
    #: A plain-language reading of the criterion, for reviewers and case building.
    #: It NEVER replaces ``source_text`` - the authoritative wording is what is
    #: verified and what a citation quotes. An interpretation that drifted from the
    #: regulation would otherwise become the de facto policy.
    normalized_interpretation: str = ""
    #: Conditions under which the criterion bears on a request at all.
    applicability: str = ""

    def __post_init__(self) -> None:
        if not self.source_text.strip():
            raise ValueError(f"criterion {self.ordinal}: source_text may not be empty")
        if not self.fact_key.strip():
            raise ValueError(f"criterion {self.ordinal}: fact_key may not be empty")


@dataclass(frozen=True, slots=True)
class VerifiedCriterion:
    """A criterion whose source text was located in the section it named."""

    id: str
    policy_id: str
    revision_id: str
    ordinal: int
    criterion_type: CriterionType
    summary: str
    fact_key: str
    source_section: str
    source_text: str
    source_page: int
    span_start: int
    span_end: int
    comparator: str | None = None
    threshold: str | None = None
    unit: str | None = None
    normalized_interpretation: str = ""
    applicability: str = ""
    #: Populated at ingest, once chunk ids exist.
    source_chunk_ids: tuple[str, ...] = field(default_factory=tuple)

    @property
    def bears_on_outcome(self) -> bool:
        return self.criterion_type is not CriterionType.INFORMATIONAL


def verify_criteria(
    declarations: tuple[CriterionDeclaration, ...],
    sections: tuple[SectionLike, ...],
    *,
    policy_id: str,
    revision_id: str,
) -> tuple[VerifiedCriterion, ...]:
    """Locate every declared criterion in the section it claims to come from.

    Raises:
        CriterionProvenanceError: a declaration names a section that does not exist,
            or quotes text that is not in it. Both are refused rather than stored
            with weaker provenance - a criterion whose source cannot be found is
            indistinguishable from one that was invented.
    """
    by_path = {section.path: section for section in sections}
    verified: list[VerifiedCriterion] = []
    seen_ordinals: set[int] = set()
    seen_fact_keys: set[str] = set()

    for declaration in declarations:
        if declaration.ordinal in seen_ordinals:
            raise CriterionProvenanceError(
                f"{policy_id} rev {revision_id}: duplicate criterion ordinal "
                f"{declaration.ordinal}; ids would collide"
            )
        seen_ordinals.add(declaration.ordinal)

        if declaration.fact_key in seen_fact_keys:
            raise CriterionProvenanceError(
                f"{policy_id} rev {revision_id}: duplicate fact_key "
                f"{declaration.fact_key!r}; a case could not vary the two independently"
            )
        seen_fact_keys.add(declaration.fact_key)

        section = by_path.get(declaration.source_section)
        if section is None:
            raise CriterionProvenanceError(
                f"{policy_id} rev {revision_id} criterion {declaration.ordinal}: "
                f"section {declaration.source_section!r} does not exist in the document. "
                f"Available: {sorted(by_path)}"
            )

        span = find_span(declaration.source_text, section.text)
        if span is None:
            raise CriterionProvenanceError(
                f"{policy_id} rev {revision_id} criterion {declaration.ordinal}: "
                f"declared source text was not found in section "
                f"{declaration.source_section!r}. A criterion whose source cannot be "
                f"located is indistinguishable from one that was invented."
            )

        verified.append(
            VerifiedCriterion(
                id=criterion_id(policy_id, revision_id, declaration.ordinal),
                policy_id=policy_id,
                revision_id=revision_id,
                ordinal=declaration.ordinal,
                criterion_type=declaration.criterion_type,
                summary=declaration.summary,
                fact_key=declaration.fact_key,
                source_section=declaration.source_section,
                source_text=span.slice(section.text),
                source_page=section.page_from,
                span_start=span.start,
                span_end=span.end,
                comparator=declaration.comparator,
                threshold=declaration.threshold,
                unit=declaration.unit,
                normalized_interpretation=declaration.normalized_interpretation,
                applicability=declaration.applicability,
            )
        )

    return tuple(verified)
