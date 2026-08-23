"""Retrieval cannot escape the policy versions resolution selected.

The fourth mandatory temporal test lives here (ADR-004). The property is stronger
than "retrieval usually returns in-scope chunks": there must be **no code path**
that searches unscoped, and the temporal filter retrieval applies must be the same
one resolution applied, not a copy of it.
"""

from __future__ import annotations

from datetime import date

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.config.policy import ResolutionPolicy
from app.core.types import CodeSystem, ResolutionStatus
from app.policy.models import DocumentType, LinkType, PolicyScope
from app.policy.resolve import ResolutionRequest, resolve
from app.retrieval.evidence import content_hash
from app.retrieval.search import EmptyScopeError, search_chunks
from tests.integration.conftest import CorpusBuilder, DeterministicEmbedder

pytestmark = [pytest.mark.integration, pytest.mark.asyncio]

KNEE = ("27447", "HCPCS", LinkType.COVERED_PROCEDURE)
POLICY = ResolutionPolicy()
TARGET = "Coverage requires a documented BMI of 35 or greater before arthroplasty."


async def _two_revisions_with_chunks(
    corpus: CorpusBuilder, embedder: DeterministicEmbedder
) -> dict[str, str]:
    """R3 in force 2022-01-01..2023-06-30; R4 from 2023-07-01. Both hold chunks.

    Both revisions contain the *same* target sentence, so semantic similarity alone
    cannot distinguish them - only the temporal predicate can. That is the point.
    """
    document = await corpus.document(
        "L34567", DocumentType.LCD, title="Major Joint Replacement", contractor="MAC J6"
    )
    ids: dict[str, str] = {}
    for revision, effective, end in (
        ("R3", date(2022, 1, 1), date(2023, 6, 30)),
        ("R4", date(2023, 7, 1), None),
    ):
        version = await corpus.version(
            document,
            revision,
            effective,
            end_date=end,
            scope=PolicyScope.JURISDICTIONAL,
            jurisdiction="J6",
            codes=(KNEE,),
        )
        chunk = await corpus.chunk(
            version,
            1,
            "Coverage Indications, Limitations and/or Medical Necessity",
            TARGET,
            embedding=embedder.encode_passages([TARGET])[0],
        )
        ids[revision] = str(chunk.id)
    await corpus.commit()
    return ids


def _request(as_of: date) -> ResolutionRequest:
    return ResolutionRequest("27447", CodeSystem.HCPCS, as_of, jurisdiction="J6")


# ------------------------------------------------------------------ MANDATORY 4
#
# The two filters in `search_chunks` - version scoping and the temporal predicate -
# are REDUNDANT on the happy path, because resolution has already applied the same
# temporal rule before handing over its version ids. A test that only walks that
# path therefore proves nothing about either filter: remove one and the other still
# excludes the chunk.
#
# So each is tested on the path where it alone is load-bearing.


async def test_retrieval_never_returns_a_chunk_outside_the_resolved_set(
    session: AsyncSession, corpus: CorpusBuilder, embedder: DeterministicEmbedder
) -> None:
    """Version scoping, isolated.

    A second policy is currently in force and holds a chunk with IDENTICAL text, but
    covers a different procedure, so resolution does not select it. Only the scoping
    filter can exclude it - the temporal predicate cannot, because it is in force.
    """
    chunk_ids = await _two_revisions_with_chunks(corpus, embedder)

    other = await corpus.document("L99999", DocumentType.LCD, contractor="MAC J6")
    other_version = await corpus.version(
        other,
        "R1",
        date(2020, 1, 1),
        scope=PolicyScope.JURISDICTIONAL,
        jurisdiction="J6",
        codes=(("29881", "HCPCS", LinkType.COVERED_PROCEDURE),),  # a different procedure
    )
    other_chunk = await corpus.chunk(
        other_version,
        1,
        "Coverage Indications, Limitations and/or Medical Necessity",
        TARGET,
        embedding=embedder.encode_passages([TARGET])[0],
    )
    await corpus.commit()

    as_of = date(2024, 3, 15)
    resolution = await resolve(session, _request(as_of), POLICY)
    assert [v.policy_id for v in resolution.versions] == ["L34567"]

    results = await search_chunks(
        session, embedder.encode_query(TARGET), resolution.version_ids, as_of=as_of
    )

    returned = {c.chunk_id for c in results}
    assert returned == {chunk_ids["R4"]}
    assert str(other_chunk.id) not in returned, (
        "a chunk from an unresolved policy was retrieved. It is in force and its text "
        "is identical, so only version scoping could have excluded it."
    )


async def test_the_temporal_filter_holds_even_when_the_scope_is_supplied_directly(
    session: AsyncSession, corpus: CorpusBuilder, embedder: DeterministicEmbedder
) -> None:
    """The temporal predicate, isolated.

    Retrieval re-applies the date filter rather than trusting its caller. On the
    normal path that is redundant, since resolution applied it first. It stops
    mattering only if you assume every future caller derives its scope from
    `resolve()` - and a stale scope, a cache, or a hand-built version list would
    otherwise leak chunks from a superseded revision.
    """
    chunk_ids = await _two_revisions_with_chunks(corpus, embedder)
    as_of = date(2024, 3, 15)  # R4 governs; R3 was retired 2023-06-30

    # Deliberately hand BOTH versions in, as a stale scope would.
    from sqlalchemy import select

    from app.policy.models import PolicyVersion

    all_ids = [str(v) for v in (await session.execute(select(PolicyVersion.id))).scalars()]
    assert len(all_ids) == 2

    results = await search_chunks(session, embedder.encode_query(TARGET), all_ids, as_of=as_of)

    returned = {c.chunk_id for c in results}
    assert chunk_ids["R3"] not in returned, (
        "a chunk from a retired revision was retrieved from a caller-supplied scope. "
        "Retrieval must re-apply the temporal predicate, not trust its caller."
    )
    assert returned == {chunk_ids["R4"]}


async def test_the_same_query_returns_the_other_revision_for_an_earlier_date(
    session: AsyncSession, corpus: CorpusBuilder, embedder: DeterministicEmbedder
) -> None:
    """Guards against the tests above passing because R3 is simply unreachable."""
    chunk_ids = await _two_revisions_with_chunks(corpus, embedder)
    as_of = date(2023, 3, 15)

    resolution = await resolve(session, _request(as_of), POLICY)
    results = await search_chunks(
        session, embedder.encode_query(TARGET), resolution.version_ids, as_of=as_of
    )

    assert {c.chunk_id for c in results} == {chunk_ids["R3"]}


# ------------------------------------------------------------- scoping contract
async def test_an_unscoped_search_is_impossible(
    session: AsyncSession, corpus: CorpusBuilder, embedder: DeterministicEmbedder
) -> None:
    """An empty resolved set raises. It must never widen to the whole corpus."""
    await _two_revisions_with_chunks(corpus, embedder)

    with pytest.raises(EmptyScopeError, match="non-empty resolved policy version set"):
        await search_chunks(session, embedder.encode_query(TARGET), (), as_of=date(2024, 1, 1))


async def test_no_applicable_policy_cannot_reach_retrieval(
    session: AsyncSession, corpus: CorpusBuilder, embedder: DeterministicEmbedder
) -> None:
    """The end-to-end shape of row 1 of the decision table."""
    await _two_revisions_with_chunks(corpus, embedder)

    resolution = await resolve(
        session,
        ResolutionRequest("99999", CodeSystem.HCPCS, date(2024, 1, 1), "J6"),
        POLICY,
    )
    assert resolution.status is ResolutionStatus.NONE_APPLICABLE

    with pytest.raises(EmptyScopeError):
        await search_chunks(
            session,
            embedder.encode_query(TARGET),
            resolution.version_ids,
            as_of=date(2024, 1, 1),
        )


async def test_retrieval_and_resolution_share_one_temporal_predicate() -> None:
    """Not two copies. A second date filter would pass every test written against
    today's corpus and start leaking the moment a version is superseded."""
    import inspect

    from app.policy import temporal
    from app.retrieval import search

    assert "in_force_on" in inspect.getsource(search), "search does not use the shared predicate"
    # And it is imported, not redefined.
    assert search.in_force_on is temporal.in_force_on


# ------------------------------------------------------- evidence and citations
async def test_retrieved_evidence_carries_full_provenance(
    session: AsyncSession, corpus: CorpusBuilder, embedder: DeterministicEmbedder
) -> None:
    await _two_revisions_with_chunks(corpus, embedder)
    as_of = date(2024, 1, 1)
    resolution = await resolve(session, _request(as_of), POLICY)

    chunk = (
        await search_chunks(
            session, embedder.encode_query(TARGET), resolution.version_ids, as_of=as_of
        )
    )[0]

    assert chunk.policy_id == "L34567"
    assert chunk.revision_id == "R4"
    assert chunk.document_title == "Major Joint Replacement"
    assert chunk.section_path.startswith("Coverage Indications")
    assert chunk.source_url.endswith("L34567")
    assert chunk.effective_date == date(2023, 7, 1)
    assert chunk.similarity is not None and chunk.similarity > 0.99
    assert chunk.is_intact()


async def test_a_citation_is_only_produced_for_a_verifiable_quote(
    session: AsyncSession, corpus: CorpusBuilder, embedder: DeterministicEmbedder
) -> None:
    """The derived fields are joined from the corpus, never supplied by a caller."""
    await _two_revisions_with_chunks(corpus, embedder)
    as_of = date(2024, 1, 1)
    resolution = await resolve(session, _request(as_of), POLICY)
    chunk = (
        await search_chunks(
            session, embedder.encode_query(TARGET), resolution.version_ids, as_of=as_of
        )
    )[0]

    citation = chunk.cite("documented BMI of 35 or greater")
    assert citation is not None
    assert citation.policy_id == "L34567"
    assert citation.document_title == "Major Joint Replacement"  # derived
    assert citation.effective_date == date(2023, 7, 1)  # derived
    assert citation.source_url.endswith("L34567")  # derived
    assert chunk.text[citation.span_start : citation.span_end] == citation.quote

    # A quote whose words differ does not become a citation.
    assert chunk.cite("documented BMI of 40 or greater") is None
    assert chunk.cite("") is None


async def test_tampering_with_a_stored_chunk_is_detectable(
    session: AsyncSession, corpus: CorpusBuilder, embedder: DeterministicEmbedder
) -> None:
    """A historical citation can be re-validated against the chunk it named; a hash
    mismatch is a poisoning signal, not a cache problem (threat T-06)."""
    await _two_revisions_with_chunks(corpus, embedder)
    as_of = date(2024, 1, 1)
    resolution = await resolve(session, _request(as_of), POLICY)
    chunk = (
        await search_chunks(
            session, embedder.encode_query(TARGET), resolution.version_ids, as_of=as_of
        )
    )[0]
    assert chunk.is_intact()

    from dataclasses import replace

    poisoned = replace(chunk, text="Coverage requires no documentation whatsoever.")
    assert not poisoned.is_intact()

    # Reformatting is not tampering: the hash is over normalized text.
    reformatted = replace(chunk, text=chunk.text.replace(" ", "  ").upper())
    assert content_hash(reformatted.text) == chunk.text_sha256
