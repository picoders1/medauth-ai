"""Vector search over policy chunks, scoped to resolved policy versions.

The single most important property of this module is the one enforced by its
signature: **there is no way to search the whole corpus, and no way to search
across policy types.** A :class:`~app.retrieval.scope.RetrievalScope` names exactly
one ``document_type`` and cannot be constructed empty, so neither an unscoped search
nor an accidental crossing between regulation and coverage-determination text is
expressible.

That is not defensive coding. A semantic search over everything always returns
something plausible, and the resulting answer is well-cited, internally consistent,
and drawn from a policy that does not govern the case - a failure every grounding
metric passes (ADR-004). Resolution decides applicability; this decides relevance
*within* what resolution already established.

The temporal predicate is imported from :mod:`app.policy.temporal`, not
re-implemented, so retrieval and resolution cannot drift.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import date

from sqlalchemy import Select, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.policy.models import PolicyChunk, PolicyDocument, PolicyVersion
from app.policy.temporal import in_force_on
from app.retrieval.evidence import EvidenceChunk
from app.retrieval.scope import EmptyScopeError, RetrievalScope

__all__ = ["EmptyScopeError", "build_search_statement", "search_chunks"]


#: Re-exported so callers importing from this module keep working. The raise now
#: happens at scope *construction*, so an empty scope cannot be held at all.
EmptyScopeError = EmptyScopeError


def build_search_statement(
    query_vector: Sequence[float],
    scope: RetrievalScope,
    *,
    limit: int,
) -> Select[tuple[PolicyChunk, PolicyVersion, PolicyDocument, float]]:
    """Build the scoped ANN query. Separated so its SQL can be asserted in a test."""
    distance = PolicyChunk.embedding.cosine_distance(query_vector)

    return (
        select(PolicyChunk, PolicyVersion, PolicyDocument, distance.label("distance"))
        .join(PolicyVersion, PolicyVersion.id == PolicyChunk.policy_version_id)
        .join(PolicyDocument, PolicyDocument.id == PolicyVersion.document_id)
        .where(
            PolicyChunk.policy_version_id.in_(scope.ids),
            PolicyChunk.embedding.isnot(None),
            # Defence in depth, and the two layers are not equally load-bearing.
            # The id filter above does the work in practice, because `scope_for()`
            # partitions ids by each version's actual type - remove this line and
            # the cross-layer test still passes.
            #
            # This predicate matters for a scope that was NOT built by `scope_for`:
            # `RetrievalScope` is constructible directly, and a hand-built one can
            # name a type its ids do not belong to. Without this, such a scope would
            # return the other layer's chunks and look like a correct result.
            # `test_a_hand_built_scope_cannot_borrow_another_layers_ids` is the test
            # that fails when this line is deleted.
            PolicyDocument.document_type == scope.document_type.value,
            # The SAME predicate resolution used. A second copy of this filter is a
            # defect waiting for a corpus refresh.
            in_force_on(scope.as_of),
        )
        .order_by(distance)
        .limit(limit)
    )


def _dated(version: PolicyVersion) -> date:
    if version.effective_date is None:  # pragma: no cover - guarded by in_force_on
        raise ValueError(
            f"version {version.id} reached retrieval with no effective date "
            f"(temporal_status={version.temporal_status})"
        )
    return version.effective_date


async def search_chunks(
    session: AsyncSession,
    query_vector: Sequence[float],
    scope: RetrievalScope,
    *,
    limit: int = 40,
) -> tuple[EvidenceChunk, ...]:
    """Nearest chunks within one policy type's resolved versions, closest first."""
    statement = build_search_statement(query_vector, scope, limit=limit)
    rows = (await session.execute(statement)).all()

    return tuple(
        EvidenceChunk(
            chunk_id=str(chunk.id),
            policy_version_id=str(version.id),
            policy_id=document.policy_id,
            document_type=str(document.document_type),
            document_title=document.title,
            revision_id=version.revision_id,
            section_path=chunk.section_path,
            page_from=chunk.page_from,
            page_to=chunk.page_to,
            text=chunk.text,
            text_sha256=chunk.text_sha256,
            # `in_force_on` admits only DATED versions, so a chunk reaching here
            # always has one. A citation with a null effective date would be a
            # derived field the reviewer cannot check.
            effective_date=_dated(version),
            end_date=version.end_date,
            source_url=document.source_url,
            jurisdiction=version.jurisdiction,
            # pgvector returns cosine DISTANCE; similarity is the useful direction.
            similarity=round(1.0 - float(distance), 6),
        )
        for chunk, version, document, distance in rows
    )
