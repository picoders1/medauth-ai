"""Ingestion: acquire -> validate -> parse -> structure -> chunk -> embed -> persist.

Two properties of this pipeline are worth stating because they are easy to lose.

**Versions are added, never edited.** Re-ingesting a policy whose content hash is
unchanged is a no-op; a changed hash creates a *new* version row. That is what makes
a recommendation issued last year still reproducible: the version it cited still
resolves for its date of service, and a corpus refresh cannot retroactively rewrite
a settled case.

**The embedding dimension is asserted, never assumed.** A model whose width differs
from the vector column is refused rather than truncated, because a silently
truncated embedding degrades retrieval in a way that reads as a model-quality
problem and is nearly impossible to attribute later.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import MedauthError
from app.policy.acquire import AcquiredDocument, RegistryEntry
from app.policy.chunk import chunk_sections
from app.policy.documents import ParsedDocument
from app.policy.models import (
    EMBEDDING_DIMENSION,
    PolicyChunk,
    PolicyCodeLink,
    PolicyDocument,
    PolicyVersion,
)
from app.policy.parse import parse_document
from app.policy.validate import validate_document
from app.retrieval.embed import Embedder

__all__ = ["IngestError", "IngestResult", "ingest_all", "ingest_document"]

log = structlog.get_logger(__name__)


class IngestError(MedauthError):
    """Ingestion refused to write."""


@dataclass
class IngestResult:
    documents: int = 0
    versions_created: int = 0
    versions_skipped: int = 0
    chunks: int = 0
    embedded: int = 0
    warnings: list[str] = field(default_factory=list)
    registry: list[RegistryEntry] = field(default_factory=list)

    def merge(self, other: IngestResult) -> None:
        self.documents += other.documents
        self.versions_created += other.versions_created
        self.versions_skipped += other.versions_skipped
        self.chunks += other.chunks
        self.embedded += other.embedded
        self.warnings.extend(other.warnings)
        self.registry.extend(other.registry)


def _assert_dimension(embedder: Embedder) -> None:
    measured = embedder.dimension
    if measured != EMBEDDING_DIMENSION:
        raise IngestError(
            f"encoder {embedder.model_id!r} emits {measured} dimensions but "
            f"policy_chunks.embedding is vector({EMBEDDING_DIMENSION}). Refusing to write: "
            "a truncated or padded embedding degrades retrieval in a way that looks like "
            "a model-quality problem. Change the encoder, or migrate the column and "
            "re-embed the whole corpus."
        )


async def _upsert_document(session: AsyncSession, parsed: ParsedDocument) -> PolicyDocument:
    identity = parsed.identity
    existing = (
        await session.execute(
            select(PolicyDocument).where(
                PolicyDocument.policy_id == identity.policy_id,
                PolicyDocument.document_type == identity.document_type.value,
            )
        )
    ).scalar_one_or_none()
    if existing is not None:
        # Title and URL may be corrected on refresh; identity may not.
        existing.title = identity.title
        existing.source_url = identity.source_url
        existing.contractor = identity.contractor
        return existing

    document = PolicyDocument(
        policy_id=identity.policy_id,
        document_type=identity.document_type.value,
        title=identity.title,
        source_url=identity.source_url,
        source_authority=identity.source_authority,
        contractor=identity.contractor,
        first_seen_at=datetime.now(UTC),
    )
    session.add(document)
    await session.flush()
    return document


async def ingest_document(
    session: AsyncSession,
    acquired: AcquiredDocument,
    embedder: Embedder | None = None,
    *,
    max_tokens: int = 400,
    overlap_tokens: int = 60,
) -> IngestResult:
    """Ingest one document. Idempotent on an unchanged content hash."""
    parsed = parse_document(acquired.raw, acquired.source)
    report = validate_document(parsed, strict=True)
    identity = parsed.identity

    result = IngestResult(documents=1, warnings=list(report.warnings))
    result.registry.append(
        RegistryEntry(
            policy_id=identity.policy_id,
            document_type=identity.document_type.value,
            revision_id=identity.revision_id,
            title=identity.title,
            source_uri=acquired.source.uri,
            source_url=identity.source_url,
            retrieved_at=acquired.source.retrieved_at,
            sha256=acquired.source.sha256,
            adapter=acquired.source.adapter,
            synthetic=acquired.source.synthetic,
            licence_note=acquired.source.licence_note,
        )
    )

    document = await _upsert_document(session, parsed)

    existing = (
        await session.execute(
            select(PolicyVersion).where(
                PolicyVersion.document_id == document.id,
                PolicyVersion.revision_id == identity.revision_id,
            )
        )
    ).scalar_one_or_none()

    if existing is not None:
        if existing.content_sha256 == acquired.source.sha256:
            result.versions_skipped = 1
            log.info(
                "version_unchanged",
                policy_id=identity.policy_id,
                revision=identity.revision_id,
            )
            return result
        raise IngestError(
            f"{identity.policy_id} rev {identity.revision_id} already exists with a "
            f"different content hash. A revision's text is immutable: publish a new "
            f"revision_id rather than editing one, or a settled case would silently "
            f"change which text adjudicated it."
        )

    version = PolicyVersion(
        document_id=document.id,
        revision_id=identity.revision_id,
        scope=identity.scope.value,
        jurisdiction=identity.jurisdiction,
        effective_date=identity.effective_date,
        temporal_status=identity.temporal_status.value,
        window_derivation=identity.window_derivation.value,
        effective_date_source=identity.effective_date_source,
        end_date=identity.end_date,
        revision_date=identity.revision_date,
        content_sha256=acquired.source.sha256,
        ingested_at=datetime.now(UTC),
    )
    session.add(version)
    await session.flush()
    result.versions_created = 1

    for ref in parsed.codes:
        session.add(
            PolicyCodeLink(
                policy_version_id=version.id,
                code=ref.code,
                code_system=ref.code_system.value,
                link_type=ref.link_type.value,
            )
        )

    chunks = chunk_sections(parsed.sections, max_tokens=max_tokens, overlap_tokens=overlap_tokens)
    vectors: list[list[float]] | None = None
    if embedder is not None and chunks:
        _assert_dimension(embedder)
        vectors = embedder.encode_passages([c.text for c in chunks])
        result.embedded = len(vectors)

    for index, chunk in enumerate(chunks):
        session.add(
            PolicyChunk(
                policy_version_id=version.id,
                section_path=chunk.section_path,
                ordinal=chunk.ordinal,
                page_from=chunk.page_from,
                page_to=chunk.page_to,
                text=chunk.text,
                text_sha256=chunk.text_sha256,
                token_count=chunk.token_count,
                embedding=vectors[index] if vectors else None,
            )
        )
    result.chunks = len(chunks)

    await session.flush()
    log.info(
        "version_ingested",
        policy_id=identity.policy_id,
        revision=identity.revision_id,
        chunks=len(chunks),
        embedded=result.embedded,
    )
    return result


async def ingest_all(
    session: AsyncSession,
    documents: list[AcquiredDocument],
    embedder: Embedder | None = None,
    **kwargs: int,
) -> IngestResult:
    """Ingest a corpus in one transaction. Any failure rolls the whole batch back."""
    total = IngestResult()
    for acquired in documents:
        total.merge(await ingest_document(session, acquired, embedder, **kwargs))
    return total
