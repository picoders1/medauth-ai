"""Deterministic policy resolution: *which policy applies?*

This is the step the architecture exists to protect. A semantic search over the
whole corpus always returns something - for a knee-MRI case it returns a plausible,
well-written, confidently-citable imaging policy that may be the wrong jurisdiction
or a version retired before the date of service. The system then reasons
impeccably over the wrong document and produces a fully-cited wrong answer, and
**citations do not catch it**: they are genuine, the quotes verify, the metadata is
consistent. The policy simply does not govern the case.

So applicability is decided by rules over ``policy_code_links`` - procedure code,
code system, jurisdiction, date of service - with no embeddings and no model. The
result is reproducible, diffable across a corpus refresh, and explainable to a
reviewer in one sentence (ADR-004).

Nothing in this module may import an encoder or ``app.retrieval``; a test asserts
it, because the moment similarity influences applicability the guarantee is gone.
"""

from __future__ import annotations

import uuid
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config.policy import ResolutionPolicy
from app.core.types import CodeSystem, ResolutionStatus
from app.policy.models import (
    DocumentType,
    LinkProvenance,
    LinkType,
    PolicyCodeLink,
    PolicyDocument,
    PolicyVersion,
)
from app.policy.temporal import applies_in_jurisdiction, in_force_on
from app.retrieval.scope import RetrievalScope

__all__ = ["ResolutionRequest", "ResolutionResult", "ResolvedVersion", "resolve"]


@dataclass(frozen=True, slots=True)
class ResolutionRequest:
    """Everything applicability depends on. Deliberately no free text."""

    procedure_code: str
    code_system: CodeSystem
    as_of: date
    jurisdiction: str | None = None
    diagnosis_codes: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class ResolvedVersion:
    """One applicable version, with the provenance a reviewer needs to check it."""

    version_id: str
    document_id: str
    policy_id: str
    document_type: DocumentType
    title: str
    revision_id: str
    scope: str
    jurisdiction: str | None
    effective_date: date
    end_date: date | None
    source_url: str
    contractor: str | None
    matched_code: str
    matched_link_type: LinkType
    supporting_diagnoses: tuple[str, ...] = ()

    @property
    def why(self) -> str:
        """Plain-language reason this version applied. Rendered in the console."""
        window = f"effective {self.effective_date}"
        window += f" to {self.end_date}" if self.end_date else " (in force)"
        where = self.jurisdiction or self.scope.lower()
        return (
            f"{self.document_type.value} {self.policy_id} rev {self.revision_id}: "
            f"code {self.matched_code} listed as {self.matched_link_type.value.lower()}, "
            f"{where}, {window}"
        )


@dataclass(frozen=True, slots=True)
class ResolutionResult:
    """The outcome of applicability, including *why* it came out that way."""

    status: ResolutionStatus
    versions: tuple[ResolvedVersion, ...] = ()
    conflicts: tuple[str, ...] = ()
    request: ResolutionRequest | None = None
    notes: tuple[str, ...] = field(default_factory=tuple)

    def scope_for(self, document_type: DocumentType) -> RetrievalScope | None:
        """Version ids of ONE policy type, or None if this type resolved to nothing.

        The only constructor of a `RetrievalScope`, and the reason a scope whose ids
        disagree with its label is unrepresentable: the partition is taken from each
        version's *actual* `document_type`, never from what the caller asked for.

        Replaces the old `version_ids`, which flattened every resolved version into
        one list. That was harmless while the corpus was regulations only. With NCDs
        adopted it would hand a statutory chunk and a coverage-determination chunk to
        one ANN query and let cosine distance rank across two layers of authority.
        """
        ids = frozenset(
            uuid.UUID(v.version_id) for v in self.versions if v.document_type is document_type
        )
        if not ids:
            return None
        if self.request is None:  # pragma: no cover - resolve() always sets it
            raise ValueError("cannot build a retrieval scope from a result with no request")
        return RetrievalScope(
            document_type=document_type,
            policy_version_ids=ids,
            as_of=self.request.as_of,
        )

    def scopes(self) -> tuple[RetrievalScope, ...]:
        """One scope per policy type present, most authoritative layer first.

        NCD before LCD before ARTICLE before REGULATION - a coverage determination
        answers the coverage question directly, whereas a regulation states the
        statutory conditions above it. The order is a presentation choice; nothing
        merges, and each scope is searched separately or not at all.
        """
        order = (
            DocumentType.NCD,
            DocumentType.LCD,
            DocumentType.ARTICLE,
            DocumentType.REGULATION,
        )
        return tuple(scope for scope in (self.scope_for(t) for t in order) if scope is not None)

    @property
    def governing(self) -> ResolvedVersion | None:
        """The version that governs where several apply - an NCD outranks an LCD."""
        if not self.versions:
            return None
        national = [v for v in self.versions if v.document_type is DocumentType.NCD]
        return national[0] if national else self.versions[0]

    @property
    def explanation(self) -> tuple[str, ...]:
        return tuple(v.why for v in self.versions) + self.conflicts + self.notes


def _dated(version: PolicyVersion) -> date:
    """The effective date of a version the temporal predicate admitted."""
    if version.effective_date is None:  # pragma: no cover - guarded by in_force_on
        raise ValueError(
            f"version {version.id} passed the temporal predicate with no effective "
            f"date (temporal_status={version.temporal_status}). in_force_on must "
            "admit only DATED versions."
        )
    return version.effective_date


def _admissible_provenances(policy: ResolutionPolicy) -> tuple[str, ...]:
    """Which link provenances may establish applicability, under this policy.

    Expressed as an explicit membership set rather than a `!=` so that a future
    provenance value has to be classified deliberately instead of being admitted
    because nobody thought about it.
    """
    return tuple(
        provenance.value
        for provenance in LinkProvenance
        if provenance.admissible_in_production
        or (
            provenance is LinkProvenance.ENGINEERING_INFERRED
            and policy.admit_engineering_inferred_links
        )
    )


async def resolve(
    session: AsyncSession,
    request: ResolutionRequest,
    policy: ResolutionPolicy,
) -> ResolutionResult:
    """Resolve applicable policy versions. No embeddings, no model, no clock.

    ``request.as_of`` is supplied by the caller rather than read from a clock, so
    the same request resolves identically today and in a year - which is what makes
    a historical recommendation reproducible.
    """
    admissible = _admissible_provenances(policy)
    statement = (
        select(PolicyVersion, PolicyDocument, PolicyCodeLink)
        .join(PolicyDocument, PolicyDocument.id == PolicyVersion.document_id)
        .join(PolicyCodeLink, PolicyCodeLink.policy_version_id == PolicyVersion.id)
        .where(
            PolicyCodeLink.code == request.procedure_code,
            PolicyCodeLink.code_system == request.code_system.value,
            PolicyCodeLink.link_type == LinkType.COVERED_PROCEDURE.value,
            # A link that rests on resemblance may not establish applicability.
            # Stated as an explicit membership test rather than a `!=` so that a
            # future provenance value has to be classified deliberately instead of
            # being admitted by default.
            PolicyCodeLink.link_provenance.in_(admissible),
            in_force_on(request.as_of),
            applies_in_jurisdiction(request.jurisdiction),
        )
        .order_by(PolicyVersion.effective_date.desc(), PolicyDocument.policy_id)
    )

    rows = (await session.execute(statement)).all()
    if not rows:
        return ResolutionResult(
            status=ResolutionStatus.NONE_APPLICABLE,
            request=request,
            notes=(
                f"No policy version lists {request.code_system.value} "
                f"{request.procedure_code} as a covered procedure in scope on "
                f"{request.as_of}. Absence of an applicable policy is not "
                f"non-coverage (ADR-004).",
            ),
        )

    supporting = await _supporting_diagnoses(
        session, [v.id for v, _, _ in rows], request.diagnosis_codes
    )

    versions = tuple(
        ResolvedVersion(
            version_id=str(version.id),
            document_id=str(document.id),
            policy_id=document.policy_id,
            document_type=DocumentType(document.document_type),
            title=document.title,
            revision_id=version.revision_id,
            scope=str(version.scope),
            jurisdiction=version.jurisdiction,
            # `in_force_on` admits only DATED versions, so this is never None
            # here. Asserted rather than assumed: if the predicate is ever relaxed,
            # this fails loudly instead of propagating a None into a citation.
            effective_date=_dated(version),
            end_date=version.end_date,
            source_url=document.source_url,
            contractor=document.contractor,
            matched_code=link.code,
            matched_link_type=LinkType(link.link_type),
            supporting_diagnoses=tuple(sorted(supporting.get(str(version.id), set()))),
        )
        for version, document, link in rows
    )

    conflicts = _detect_conflicts(versions, policy)
    if conflicts:
        return ResolutionResult(
            status=ResolutionStatus.CONFLICTING,
            versions=versions,
            conflicts=conflicts,
            request=request,
        )

    notes: tuple[str, ...] = ()
    if policy.ncd_governs_over_lcd and len(versions) > 1:
        governing = next((v for v in versions if v.document_type is DocumentType.NCD), None)
        if governing is not None:
            notes = (
                f"NCD {governing.policy_id} governs; the remaining "
                f"{len(versions) - 1} version(s) may add local detail.",
            )

    return ResolutionResult(
        status=ResolutionStatus.RESOLVED, versions=versions, request=request, notes=notes
    )


async def _supporting_diagnoses(
    session: AsyncSession, version_ids: list[object], diagnosis_codes: tuple[str, ...]
) -> dict[str, set[str]]:
    """Which of the case's diagnosis codes each version lists as supporting.

    Recorded for the reviewer, and **not** used to decide applicability. A policy
    applies because it covers the procedure; whether the diagnosis supports medical
    necessity is a criterion question, adjudicated later. Conflating the two would
    make "this policy applies" and "this policy is satisfied" the same test.
    """
    if not diagnosis_codes or not version_ids:
        return {}
    statement = select(PolicyCodeLink).where(
        PolicyCodeLink.policy_version_id.in_(version_ids),
        PolicyCodeLink.code.in_(diagnosis_codes),
        PolicyCodeLink.link_type == LinkType.SUPPORTING_DIAGNOSIS.value,
    )
    found: dict[str, set[str]] = defaultdict(set)
    for link in (await session.execute(statement)).scalars():
        found[str(link.policy_version_id)].add(link.code)
    return dict(found)


def _detect_conflicts(
    versions: tuple[ResolvedVersion, ...], policy: ResolutionPolicy
) -> tuple[str, ...]:
    """Genuine policy conflict, and corpus defects that masquerade as one."""
    conflicts: list[str] = []

    # A data-integrity defect: two versions of the SAME document in force at once
    # means the temporal ranges overlap, and the corpus is wrong. Surfacing it as a
    # conflict routes the case to a human instead of silently picking one.
    by_document: dict[str, list[ResolvedVersion]] = defaultdict(list)
    for version in versions:
        by_document[version.document_id].append(version)
    for group in by_document.values():
        if len(group) > 1:
            revisions = ", ".join(sorted(v.revision_id for v in group))
            conflicts.append(
                f"Corpus defect: {group[0].document_type.value} {group[0].policy_id} has "
                f"overlapping in-force versions ({revisions}). Temporal ranges must not overlap."
            )

    # A genuine conflict: two different LCDs governing the same request. This is not
    # resolved by ranking - which local policy controls is a human judgement.
    if policy.multiple_lcds_are_conflicting:
        lcd_documents = {v.policy_id for v in versions if v.document_type is DocumentType.LCD}
        if len(lcd_documents) > 1:
            conflicts.append(
                f"Multiple local coverage determinations apply "
                f"({', '.join(sorted(lcd_documents))}). Which governs is a human judgement."
            )

    return tuple(conflicts)
