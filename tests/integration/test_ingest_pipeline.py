"""Ingestion end to end, against a real database.

The properties that matter here are about *refusal* and *immutability*: a corpus
refresh must not be able to rewrite the text that adjudicated a settled case, and a
document that would sit in the corpus unreachable must be rejected at the door
rather than discovered later as a resolution gap.
"""

from __future__ import annotations

from datetime import date
from pathlib import Path

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config.policy import ResolutionPolicy
from app.core.types import CodeSystem, ResolutionStatus
from app.policy.acquire import AcquiredDocument, LocalDirectorySource, SourceUnavailableError
from app.policy.documents import SourceRef
from app.policy.ingest import IngestError, ingest_all, ingest_document
from app.policy.models import (
    DocumentType,
    PolicyChunk,
    PolicyCodeLink,
    PolicyDocument,
    PolicyVersion,
)
from app.policy.resolve import ResolutionRequest, resolve
from app.retrieval.search import search_chunks
from tests.integration.conftest import DeterministicEmbedder

pytestmark = [pytest.mark.integration, pytest.mark.asyncio]

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "cms"
POLICY = ResolutionPolicy()


def _corpus() -> list[AcquiredDocument]:
    return list(LocalDirectorySource(FIXTURES, synthetic=True).documents())


async def _count(session: AsyncSession, model: type) -> int:
    return int((await session.execute(select(func.count()).select_from(model))).scalar_one())


# --------------------------------------------------------------------- ingest
async def test_the_fixture_corpus_ingests_end_to_end(
    session: AsyncSession, embedder: DeterministicEmbedder
) -> None:
    corpus = _corpus()
    result = await ingest_all(session, corpus, embedder)
    await session.commit()

    # Counts derive from the corpus: adding a policy family must not break this.
    expected_versions = len(corpus)
    expected_documents = len({Path(d.source.uri).name.rsplit("-", 1)[0] for d in corpus})

    assert result.documents == expected_versions
    assert result.versions_created == expected_versions
    assert result.chunks > 0
    assert result.embedded == result.chunks

    assert await _count(session, PolicyDocument) == expected_documents
    assert await _count(session, PolicyVersion) == expected_versions
    assert await _count(session, PolicyChunk) == result.chunks
    assert await _count(session, PolicyCodeLink) > 0

    # Every registry entry is marked synthetic, and that flag reaches the report.
    assert all(entry.synthetic for entry in result.registry)


async def test_reingesting_an_unchanged_corpus_creates_nothing(
    session: AsyncSession, embedder: DeterministicEmbedder
) -> None:
    """Idempotent on content hash, so a scheduled refresh is safe to re-run."""
    await ingest_all(session, _corpus(), embedder)
    await session.commit()
    chunks_before = await _count(session, PolicyChunk)

    second = await ingest_all(session, _corpus(), embedder)
    await session.commit()

    assert second.versions_created == 0
    assert second.versions_skipped == len(_corpus())
    assert await _count(session, PolicyChunk) == chunks_before


async def test_editing_a_revision_in_place_is_refused(
    session: AsyncSession, embedder: DeterministicEmbedder
) -> None:
    """A revision's text is immutable.

    If it were not, a corpus refresh could silently change which text adjudicated a
    settled case - and the audit trail would still point at the same revision id.

    The edit deliberately targets text no criterion depends on. Editing text a
    criterion cites is refused *earlier*, by criterion verification, which is
    defence in depth rather than the property under test here.
    """
    await ingest_all(session, _corpus(), embedder)
    await session.commit()

    original = next(d for d in _corpus() if "LCD-L34567-R4" in d.source.uri)
    edited = AcquiredDocument(
        raw=original.raw.replace(
            "Conservative therapy minimum duration",
            "Conservative therapy minimum period",
        ),
        source=SourceRef(
            uri=original.source.uri,
            retrieved_at=date(2026, 8, 23),
            sha256="deadbeef" * 8,  # a different hash: the content changed
            synthetic=True,
        ),
    )

    with pytest.raises(IngestError, match="publish a new revision_id"):
        await ingest_document(session, edited, embedder)


async def test_a_document_that_could_never_resolve_is_refused(
    session: AsyncSession, embedder: DeterministicEmbedder
) -> None:
    """It would look ingested while being unreachable by any request."""
    original = next(d for d in _corpus() if "LCD-L34567-R4" in d.source.uri)
    broken = AcquiredDocument(
        raw=original.raw.replace("link: COVERED_PROCEDURE", "link: SUPPORTING_DIAGNOSIS"),
        source=original.source,
    )

    from app.policy.validate import DocumentValidationError

    with pytest.raises(DocumentValidationError, match="no COVERED_PROCEDURE"):
        await ingest_document(session, broken, embedder)


async def test_an_empty_corpus_directory_is_reported_not_silently_accepted(
    tmp_path: Path,
) -> None:
    with pytest.raises(SourceUnavailableError, match="no documents"):
        list(LocalDirectorySource(tmp_path).documents())


async def test_an_encoder_of_the_wrong_width_is_refused(session: AsyncSession) -> None:
    """A truncated embedding degrades retrieval in a way that reads as a model
    problem and is nearly impossible to attribute later."""
    with pytest.raises(IngestError, match="Refusing to write"):
        await ingest_all(session, _corpus()[:1], DeterministicEmbedder(dimension=384))


# ------------------------------------------------- the ingested corpus resolves
async def test_the_ingested_corpus_supports_temporal_resolution(
    session: AsyncSession, embedder: DeterministicEmbedder
) -> None:
    """The whole phase, on a corpus that came through the real pipeline."""
    await ingest_all(session, _corpus(), embedder)
    await session.commit()

    for as_of, expected in [(date(2023, 3, 15), "R3"), (date(2024, 3, 15), "R4")]:
        resolution = await resolve(
            session,
            ResolutionRequest("27447", CodeSystem.HCPCS, as_of, "J6"),
            POLICY,
        )
        assert resolution.status is ResolutionStatus.RESOLVED
        assert [v.revision_id for v in resolution.versions] == [expected], as_of

        # 27447 resolves to an LCD in this fixture corpus. Naming the type
        # explicitly is the point of the Phase 5 scope: the caller states which
        # layer of authority it is searching, and cannot get another by accident.
        scope = resolution.scope_for(DocumentType.LCD)
        assert scope is not None
        hits = await search_chunks(
            session, embedder.encode_query("conservative therapy duration"), scope
        )
        assert hits
        assert {h.revision_id for h in hits} == {expected}


async def test_the_national_policy_resolves_without_a_jurisdiction(
    session: AsyncSession, embedder: DeterministicEmbedder
) -> None:
    await ingest_all(session, _corpus(), embedder)
    await session.commit()

    resolution = await resolve(
        session,
        ResolutionRequest("70450", CodeSystem.HCPCS, date(2024, 3, 15)),
        POLICY,
    )
    assert resolution.status is ResolutionStatus.RESOLVED
    assert [v.policy_id for v in resolution.versions] == ["220.1"]


async def test_chunks_never_span_a_section_boundary_after_real_ingestion(
    session: AsyncSession, embedder: DeterministicEmbedder
) -> None:
    """The boundary rule, verified on chunks that went through the whole pipeline."""
    await ingest_all(session, _corpus(), embedder)
    await session.commit()

    chunks = (await session.execute(select(PolicyChunk))).scalars().all()
    assert chunks

    indications = [c for c in chunks if c.section_path.startswith("Coverage Indications")]
    limitations = [c for c in chunks if c.section_path == "Limitations"]
    assert indications and limitations

    for chunk in indications:
        assert "is not covered" not in chunk.text, (
            f"chunk {chunk.ordinal} in {chunk.section_path!r} carries Limitations text. "
            "A quote from it would verify while inverting the policy's meaning."
        )
