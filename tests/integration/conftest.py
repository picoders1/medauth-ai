"""Integration fixtures: a real PostgreSQL with pgvector.

These tests need a database because the properties under test are database
properties - a temporal predicate that must be evaluated by the same engine that
will evaluate it in production, and a CHECK constraint that must actually refuse a
bad row. Asserting them against an in-memory fake would test the fake.
"""

from __future__ import annotations

import os
from collections.abc import AsyncIterator
from datetime import UTC, date, datetime

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from app.config.settings import Settings
from app.database.engine import build_engine
from app.policy.models import (
    DocumentType,
    LinkType,
    PolicyChunk,
    PolicyCodeLink,
    PolicyDocument,
    PolicyScope,
    PolicyVersion,
    TemporalStatus,
)

pytestmark = pytest.mark.integration

CORPUS_TABLES = ("policy_chunks", "policy_code_links", "policy_versions", "policy_documents")


def _database_url() -> str:
    """A database dedicated to tests.

    These tests TRUNCATE the corpus tables on every setup. Pointing them at the
    working database destroys whatever corpus is loaded there - which is exactly
    what happened: a full test run wiped an ingested 42 CFR corpus and left fixture
    rows behind, and the next retrieval evaluation reported 0.0000 recall because
    nothing resolved. That was OD-16, and this is its fix.
    """
    return os.environ.get(
        "MEDAUTH_TEST_DATABASE_URL",
        "postgresql+asyncpg://medauth:medauth@localhost:5435/medauth_test",
    )


@pytest.fixture
async def engine() -> AsyncIterator[AsyncEngine]:
    # Function-scoped: pytest-asyncio binds an async fixture to the test's event
    # loop, and a session-scoped one would outlive it.
    engine = build_engine(Settings(_env_file=None, database_url=_database_url()))  # type: ignore[call-arg]
    try:
        async with engine.connect() as connection:
            await connection.execute(text("SELECT 1"))
    except Exception as exc:
        await engine.dispose()
        pytest.skip(f"PostgreSQL unavailable ({type(exc).__name__}); run `make up`")
    yield engine
    await engine.dispose()


@pytest.fixture
async def session(engine: AsyncEngine) -> AsyncIterator[AsyncSession]:
    """A clean corpus per test. Truncation, not rollback, because HNSW index
    behaviour and CHECK constraints should be exercised against committed rows."""
    factory = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
    async with factory() as session:
        await session.execute(text(f"TRUNCATE {', '.join(CORPUS_TABLES)} CASCADE"))
        await session.commit()
        yield session
        await session.rollback()


class CorpusBuilder:
    """Builds a policy corpus for a test, in the shape real CMS material takes."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def document(
        self,
        policy_id: str,
        document_type: DocumentType,
        *,
        title: str | None = None,
        contractor: str | None = None,
    ) -> PolicyDocument:
        document = PolicyDocument(
            policy_id=policy_id,
            document_type=document_type.value,
            title=title or f"{document_type.value} {policy_id}",
            source_url=f"https://example.invalid/mcd/{policy_id}",
            source_authority="CMS",
            contractor=contractor,
            first_seen_at=datetime.now(UTC),
        )
        self._session.add(document)
        await self._session.flush()
        return document

    async def version(
        self,
        document: PolicyDocument,
        revision_id: str,
        effective_date: date | None,
        *,
        end_date: date | None = None,
        scope: PolicyScope = PolicyScope.NATIONAL,
        jurisdiction: str | None = None,
        codes: tuple[tuple[str, str, LinkType], ...] = (),
        temporal_status: TemporalStatus = TemporalStatus.DATED,
        effective_date_source: str = "",
    ) -> PolicyVersion:
        version = PolicyVersion(
            document_id=document.id,
            revision_id=revision_id,
            scope=scope.value,
            jurisdiction=jurisdiction,
            effective_date=effective_date,
            end_date=end_date,
            temporal_status=temporal_status.value,
            effective_date_source=effective_date_source,
            content_sha256=f"{document.policy_id}-{revision_id}".ljust(64, "0")[:64],
            ingested_at=datetime.now(UTC),
        )
        self._session.add(version)
        await self._session.flush()
        for code, code_system, link_type in codes:
            self._session.add(
                PolicyCodeLink(
                    policy_version_id=version.id,
                    code=code,
                    code_system=code_system,
                    link_type=link_type.value,
                )
            )
        await self._session.flush()
        return version

    async def chunk(
        self,
        version: PolicyVersion,
        ordinal: int,
        section_path: str,
        body: str,
        *,
        page_from: int = 1,
        page_to: int = 1,
        embedding: list[float] | None = None,
    ) -> PolicyChunk:
        import hashlib

        from app.core.normalize import normalize_text

        chunk = PolicyChunk(
            policy_version_id=version.id,
            section_path=section_path,
            ordinal=ordinal,
            page_from=page_from,
            page_to=page_to,
            text=body,
            text_sha256=hashlib.sha256(normalize_text(body).encode()).hexdigest(),
            token_count=len(body.split()),
            embedding=embedding,
        )
        self._session.add(chunk)
        await self._session.flush()
        return chunk

    async def commit(self) -> None:
        await self._session.commit()


@pytest.fixture
def corpus(session: AsyncSession) -> CorpusBuilder:
    return CorpusBuilder(session)


class DeterministicEmbedder:
    """A real-shaped encoder without the 2 GB dependency.

    Vectors are derived from a hash of the text, so they are stable across runs and
    identical text embeds identically - which is all the properties under test here
    require. Scoping, temporal filtering and citation verification are not
    properties of the encoder, and testing them through a real one would make the
    suite slow, non-deterministic and dependent on a model download.

    Encoder *quality* is measured separately, by the Phase 1 comparison report.
    """

    def __init__(self, dimension: int = 768) -> None:
        self._dimension = dimension

    @property
    def model_id(self) -> str:
        return "deterministic-test-embedder"

    @property
    def dimension(self) -> int:
        return self._dimension

    def _vector(self, text: str) -> list[float]:
        import hashlib
        import math

        from app.core.normalize import normalize_text

        seed = hashlib.sha256(normalize_text(text).encode()).digest()
        raw = [
            int.from_bytes(hashlib.sha256(seed + i.to_bytes(4, "big")).digest()[:4], "big") / 2**32
            - 0.5
            for i in range(self._dimension)
        ]
        norm = math.sqrt(sum(x * x for x in raw)) or 1.0
        return [x / norm for x in raw]

    def encode_passages(self, texts: list[str]) -> list[list[float]]:
        return [self._vector(t) for t in texts]

    def encode_query(self, text: str) -> list[float]:
        return self._vector(text)


@pytest.fixture
def embedder() -> DeterministicEmbedder:
    return DeterministicEmbedder()


def test_the_test_database_is_not_the_working_database() -> None:
    """Regression guard for OD-16.

    These tests TRUNCATE the corpus tables on setup. Pointed at the working
    database they destroy whatever corpus is loaded there - which happened: a full
    test run wiped an ingested 42 CFR corpus, left fixture rows behind, and the next
    retrieval evaluation reported 0.0000 recall because nothing resolved. The
    failure was silent in both directions, which is what made it dangerous.
    """
    from app.config.settings import Settings

    test_url = _database_url()
    working_url = Settings(_env_file=None).database_url  # type: ignore[call-arg]

    assert test_url != working_url, (
        "the integration tests are pointed at the working database. They truncate "
        "the corpus tables, so running them would destroy any ingested corpus."
    )
    assert test_url.rsplit("/", 1)[-1] != working_url.rsplit("/", 1)[-1]
