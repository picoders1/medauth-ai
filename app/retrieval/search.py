"""Vector search over policy chunks, scoped to resolved policy versions.

The single most important property of this module is the one enforced by its
signature: **there is no way to search the whole corpus.** ``policy_version_ids``
is required and must be non-empty, and passing an empty set raises rather than
widening the search.

That is not defensive coding. A semantic search over everything always returns
something plausible, and the resulting answer is well-cited, internally consistent,
and drawn from a policy that does not govern the case - a failure every grounding
metric passes (ADR-004). Resolution decides applicability; this decides relevance
*within* what resolution already established.

The temporal predicate is imported from :mod:`app.policy.temporal`, not
re-implemented, so retrieval and resolution cannot drift.
"""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from datetime import date

from sqlalchemy import Select, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.policy.models import PolicyChunk, PolicyDocument, PolicyVersion
from app.policy.temporal import in_force_on
from app.retrieval.evidence import EvidenceChunk

__all__ = ["EmptyScopeError", "build_search_statement", "search_chunks"]


class EmptyScopeError(ValueError):
    """Raised when a search is attempted with no resolved policy versions.

    Deliberately an error rather than an empty result: an empty scope means
    resolution returned nothing, and that case must route to NEEDS_INFO through the
    decision table - never fall through to an unscoped search.
    """


def build_search_statement(
    query_vector: Sequence[float],
    policy_version_ids: Sequence[str | uuid.UUID],
    *,
    as_of: date,
    limit: int,
) -> Select[tuple[PolicyChunk, PolicyVersion, PolicyDocument, float]]:
    """Build the scoped ANN query. Separated so its SQL can be asserted in a test."""
    if not policy_version_ids:
        raise EmptyScopeError(
            "vector search requires a non-empty resolved policy version set; "
            "an unscoped search can return a confidently-cited inapplicable policy"
        )

    ids = [uuid.UUID(str(v)) for v in policy_version_ids]
    distance = PolicyChunk.embedding.cosine_distance(query_vector)

    return (
        select(PolicyChunk, PolicyVersion, PolicyDocument, distance.label("distance"))
        .join(PolicyVersion, PolicyVersion.id == PolicyChunk.policy_version_id)
        .join(PolicyDocument, PolicyDocument.id == PolicyVersion.document_id)
        .where(
            PolicyChunk.policy_version_id.in_(ids),
            PolicyChunk.embedding.isnot(None),
            # The SAME predicate resolution used. A second copy of this filter is a
            # defect waiting for a corpus refresh.
            in_force_on(as_of),
        )
        .order_by(distance)
        .limit(limit)
    )


async def search_chunks(
    session: AsyncSession,
    query_vector: Sequence[float],
    policy_version_ids: Sequence[str | uuid.UUID],
    *,
    as_of: date,
    limit: int = 40,
) -> tuple[EvidenceChunk, ...]:
    """Nearest chunks within the resolved versions, closest first."""
    statement = build_search_statement(query_vector, policy_version_ids, as_of=as_of, limit=limit)
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
            effective_date=version.effective_date,
            end_date=version.end_date,
            source_url=document.source_url,
            jurisdiction=version.jurisdiction,
            # pgvector returns cosine DISTANCE; similarity is the useful direction.
            similarity=round(1.0 - float(distance), 6),
        )
        for chunk, version, document, distance in rows
    )
