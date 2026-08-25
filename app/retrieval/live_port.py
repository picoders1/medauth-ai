"""Real retrieval behind the slice's `RetrievalPort`. pgvector, scoped, reranked.

Everything the slice has run against until now was a fixture corpus. That was right
for proving the pipeline, and it is wrong for measuring it: a retrieval metric taken
against a hand-built dictionary measures the dictionary.

## The scope is this adapter's responsibility, not the slice's

`RetrievalPort` says so, and it matters here. The scope is built from the policy
identity the caller was given and the date of service the case carries - **never
widened, never inferred, and never derived from what the query happens to match**.
A vector search over the whole corpus always returns something, and a
confidently-cited answer from an inapplicable policy is the worst failure available:
the citations are genuine, so every grounding metric passes it (ADR-004).

## One query per criterion, and what that means

The query is the criterion's own authoritative text plus its interpretation. This is
a **deliberate simplification and a stated limitation**: the retrieved set is
therefore about the criterion rather than about the case, so a note that never
mentions supervision still retrieves the supervision passage. That is what makes
`UNKNOWN` the model's job rather than retrieval's, and it is why "evidence retrieved"
here is not evidence that the evidence was relevant.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.identity import PolicyIdentity
from app.policy.models import DocumentType
from app.retrieval.embed import Embedder
from app.retrieval.evidence import EvidenceChunk
from app.retrieval.rerank import Reranker, rerank
from app.retrieval.scope import RetrievalScope
from app.retrieval.search import search_chunks

__all__ = ["LiveRetrieval"]


@dataclass
class LiveRetrieval:
    """pgvector search inside one policy version, then a cross-encoder rerank.

    `version_ids` is supplied rather than resolved here. Resolution is deterministic
    SQL on code, jurisdiction and date of service, and a retrieval adapter that
    re-resolved could hand back evidence from a version the caller never admitted.
    """

    session: AsyncSession
    embedder: Embedder
    version_ids: frozenset[object]
    reranker: Reranker | None = None
    top_k: int = 40
    rerank_top_n: int = 5
    #: `(criterion_id, chunk_ids)` for every call, so the experiment record can show
    #: what each criterion actually saw rather than what it was configured to see.
    calls: list[tuple[str, tuple[str, ...]]] = field(default_factory=list)

    async def evidence_for(
        self, criterion: object, *, identity: PolicyIdentity, as_of: date
    ) -> tuple[EvidenceChunk, ...]:
        criterion_id = getattr(criterion, "criterion_id", "")
        query = " ".join(
            part
            for part in (
                getattr(criterion, "authoritative_text", ""),
                getattr(criterion, "interpretation", ""),
            )
            if part
        )

        # Built per call from the identity the caller was given. `RetrievalScope`
        # refuses an empty version set at construction, so an unscoped search is not
        # merely discouraged here - it is unconstructible.
        scope = RetrievalScope(
            document_type=DocumentType(identity.policy_type.value),
            policy_version_ids=frozenset(self.version_ids),  # type: ignore[arg-type]
            as_of=as_of,
        )

        chunks = await search_chunks(
            self.session, self.embedder.encode_query(query), scope, limit=self.top_k
        )
        if self.reranker is not None and chunks:
            chunks = rerank(self.reranker, query, chunks, top_n=self.rerank_top_n)
        else:
            chunks = chunks[: self.rerank_top_n]

        self.calls.append((criterion_id, tuple(c.chunk_id for c in chunks)))
        return chunks
