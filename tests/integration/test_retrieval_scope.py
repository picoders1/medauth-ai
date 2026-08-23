"""Retrieval cannot escape the policy versions resolution selected.

The fourth mandatory temporal test lives here (ADR-004). The property is stronger
than "retrieval usually returns in-scope chunks": there must be **no code path**
that searches unscoped, and the temporal filter retrieval applies must be the same
one resolution applied, not a copy of it.
"""

from __future__ import annotations

import uuid
from datetime import date

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config.policy import ResolutionPolicy
from app.core.identity import PolicyIdentity
from app.core.types import CodeSystem, ResolutionStatus
from app.policy.models import (
    DocumentType,
    LinkProvenance,
    LinkType,
    PolicyCodeLink,
    PolicyDocument,
    PolicyScope,
    PolicyVersion,
)
from app.policy.resolve import ResolutionRequest, ResolutionResult, resolve
from app.retrieval.evidence import content_hash
from app.retrieval.scope import EmptyScopeError, RetrievalScope
from app.retrieval.search import search_chunks
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


def _lcd_scope(resolution: ResolutionResult) -> RetrievalScope:
    """The LCD scope of a resolution, asserted to exist.

    This file's fixtures are LCDs, so a missing scope means resolution failed - and
    the test should say so here rather than fail obscurely inside a query.
    """
    scope = resolution.scope_for(DocumentType.LCD)
    assert scope is not None, "resolution produced no LCD scope"
    return scope


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

    results = await search_chunks(session, embedder.encode_query(TARGET), _lcd_scope(resolution))

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

    all_ids = frozenset((await session.execute(select(PolicyVersion.id))).scalars().all())
    assert len(all_ids) == 2

    stale = RetrievalScope(document_type=DocumentType.LCD, policy_version_ids=all_ids, as_of=as_of)
    results = await search_chunks(session, embedder.encode_query(TARGET), stale)

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
    results = await search_chunks(session, embedder.encode_query(TARGET), _lcd_scope(resolution))

    assert {c.chunk_id for c in results} == {chunk_ids["R3"]}


# ------------------------------------------------------------- scoping contract
async def test_an_unscoped_search_is_impossible(
    session: AsyncSession, corpus: CorpusBuilder, embedder: DeterministicEmbedder
) -> None:
    """An empty scope raises. It must never widen to the whole corpus.

    Phase 5 note: the raise moved from the search to the scope's constructor, so an
    empty scope can no longer be *held* rather than merely not searched. The
    assertion is strictly stronger - there is now no value a caller could pass to
    `search_chunks` that means "everything".
    """
    await _two_revisions_with_chunks(corpus, embedder)

    with pytest.raises(EmptyScopeError, match="at least one"):
        RetrievalScope(
            document_type=DocumentType.LCD,
            policy_version_ids=frozenset(),
            as_of=date(2024, 1, 1),
        )


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

    # Phase 5: an empty resolution yields NO scope at all, rather than an empty one
    # that a search then rejects. There is nothing to hand to `search_chunks`, which
    # is a stronger statement than the raise it used to produce.
    assert resolution.scope_for(DocumentType.LCD) is None
    assert resolution.scopes() == ()


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

    chunk = (await search_chunks(session, embedder.encode_query(TARGET), _lcd_scope(resolution)))[0]

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
    chunk = (await search_chunks(session, embedder.encode_query(TARGET), _lcd_scope(resolution)))[0]

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
    chunk = (await search_chunks(session, embedder.encode_query(TARGET), _lcd_scope(resolution)))[0]
    assert chunk.is_intact()

    from dataclasses import replace

    poisoned = replace(chunk, text="Coverage requires no documentation whatsoever.")
    assert not poisoned.is_intact()

    # Reformatting is not tampering: the hash is over normalized text.
    reformatted = replace(chunk, text=chunk.text.replace(" ", "  ").upper())
    assert content_hash(reformatted.text) == chunk.text_sha256


# ------------------------------------------------- regulation / coverage layers
async def test_a_regulation_chunk_cannot_enter_a_coverage_scope(
    session: AsyncSession, corpus: CorpusBuilder, embedder: DeterministicEmbedder
) -> None:
    """The defect NCD adoption would have created, proven impossible.

    A REGULATION version and an NCD version, linked to the **same** procedure code,
    both in force on the same date, both holding the **identical** sentence.

    Neither of the existing filters can separate them: semantic similarity cannot,
    because the text is byte-identical, and the temporal predicate cannot, because
    both are in force. Only the policy-type predicate can. Before Phase 5 this had
    no chance of passing - `ResolutionResult.version_ids` flattened both into one
    scope and a single ANN query ranked a statutory-conditions chunk against a
    coverage-determination chunk on cosine distance.

    The two answer different questions. 42 CFR states the conditions of payment;
    an NCD states whether an item is covered. Ranking them together produces a
    fluent, well-cited answer drawn from the wrong layer of authority.
    """
    shared_code = ("A1234", "HCPCS", LinkType.COVERED_PROCEDURE)
    as_of = date(2024, 3, 15)
    sentence = "The item must be used in the beneficiary's home."

    ids: dict[DocumentType, str] = {}
    for policy_id, document_type in (
        ("42 CFR 410.38", DocumentType.REGULATION),
        ("NCD 280.1", DocumentType.NCD),
    ):
        document = await corpus.document(policy_id, document_type, title=policy_id)
        version = await corpus.version(
            document,
            "R1",
            date(2022, 1, 1),
            scope=PolicyScope.NATIONAL,
            codes=(shared_code,),
        )
        chunk = await corpus.chunk(
            version, 1, "General scope", sentence, embedding=embedder.encode_passages([sentence])[0]
        )
        ids[document_type] = str(chunk.id)
    await corpus.commit()

    resolution = await resolve(session, ResolutionRequest("A1234", CodeSystem.HCPCS, as_of), POLICY)
    assert resolution.status is ResolutionStatus.RESOLVED
    assert len(resolution.versions) == 2, "both layers must resolve, or this proves nothing"

    query = embedder.encode_query(sentence)
    for document_type in (DocumentType.REGULATION, DocumentType.NCD):
        scope = resolution.scope_for(document_type)
        assert scope is not None
        returned = {c.chunk_id for c in await search_chunks(session, query, scope)}
        assert returned == {ids[document_type]}, (
            f"a {document_type.value} scope returned {returned}; the other layer's "
            "chunk crossed into it despite carrying identical text"
        )


async def test_a_scope_names_exactly_one_policy_type(
    session: AsyncSession, corpus: CorpusBuilder, embedder: DeterministicEmbedder
) -> None:
    """`scopes()` partitions; it never merges.

    The union of every scope's ids must equal the resolved set exactly - nothing
    dropped, nothing duplicated - and no two scopes may share an id. A partition
    that lost a version would silently narrow retrieval; one that duplicated a
    version would put the same chunk in two layers.
    """
    await _two_revisions_with_chunks(corpus, embedder)
    resolution = await resolve(session, _request(date(2024, 3, 15)), POLICY)

    scopes = resolution.scopes()
    assert scopes
    assert len({s.document_type for s in scopes}) == len(scopes)

    union: set[uuid.UUID] = set()
    for scope in scopes:
        assert not (union & scope.policy_version_ids), "a version appears in two scopes"
        union |= scope.policy_version_ids
    assert union == {uuid.UUID(v.version_id) for v in resolution.versions}


async def test_a_hand_built_scope_cannot_borrow_another_layers_ids(
    session: AsyncSession, corpus: CorpusBuilder, embedder: DeterministicEmbedder
) -> None:
    """A scope whose label disagrees with its ids returns nothing, not the wrong layer.

    `scope_for()` cannot produce such a scope - it partitions by each version's own
    document type - so this is about the value object being constructible directly.
    A caller who builds one by hand, or a future partitioning bug, must not get the
    other layer's chunks back looking like a correct result.

    This is the test that makes the `document_type` predicate in
    `build_search_statement` load-bearing. Deleting that line makes this fail while
    every other test in this file still passes, which is exactly why it exists
    separately rather than being folded into the cross-layer test above.
    """
    document = await corpus.document("NCD 280.1", DocumentType.NCD, title="Coverage")
    version = await corpus.version(
        document, "R1", date(2022, 1, 1), scope=PolicyScope.NATIONAL, codes=(KNEE,)
    )
    text = "The item is covered when furnished in the beneficiary's home."
    await corpus.chunk(
        version, 1, "Indications", text, embedding=embedder.encode_passages([text])[0]
    )
    await corpus.commit()

    # The ids belong to an NCD; the scope claims to be a regulation scope.
    mismatched = RetrievalScope(
        document_type=DocumentType.REGULATION,
        policy_version_ids=frozenset({uuid.UUID(str(version.id))}),
        as_of=date(2024, 3, 15),
    )
    assert await search_chunks(session, embedder.encode_query(text), mismatched) == ()

    # And the honestly-labelled scope over the same ids does return it, so the
    # emptiness above is the type filter and not a broken fixture.
    honest = RetrievalScope(
        document_type=DocumentType.NCD,
        policy_version_ids=mismatched.policy_version_ids,
        as_of=mismatched.as_of,
    )
    assert len(await search_chunks(session, embedder.encode_query(text), honest)) == 1


async def test_the_r62_collision_cannot_occur_end_to_end(
    session: AsyncSession, corpus: CorpusBuilder, embedder: DeterministicEmbedder
) -> None:
    """R-62, constructed as adversarially as the schema permits.

    A REGULATION and an NCD sharing a procedure code, a revision id, a date of
    service and a byte-identical target sentence. Every discriminator except policy
    type is deliberately removed:

      * similarity cannot separate them - the text is identical
      * the temporal predicate cannot - both are in force
      * the revision id cannot - they are the same string
      * the code cannot - the same code resolves to both

    Before Phase 6 the evaluation runners scoped by version id alone, and a set
    built that way would have merged whichever version arrived last. Here each
    scope must return exactly its own chunk.
    """
    shared_code = ("Z9999", "HCPCS", LinkType.COVERED_PROCEDURE)
    shared_revision = "R1"
    as_of = date(2024, 6, 1)
    sentence = "The service must be furnished under the conditions stated in this policy."

    chunks: dict[DocumentType, str] = {}
    for policy_id, document_type in (
        ("42 CFR 410.99", DocumentType.REGULATION),
        ("NCD 410.99", DocumentType.NCD),
    ):
        document = await corpus.document(policy_id, document_type, title=policy_id)
        version = await corpus.version(
            document,
            shared_revision,
            date(2022, 1, 1),
            scope=PolicyScope.NATIONAL,
            codes=(shared_code,),
        )
        chunk = await corpus.chunk(
            version, 1, "Conditions", sentence, embedding=embedder.encode_passages([sentence])[0]
        )
        chunks[document_type] = str(chunk.id)
    await corpus.commit()

    resolution = await resolve(session, ResolutionRequest("Z9999", CodeSystem.HCPCS, as_of), POLICY)
    assert len(resolution.versions) == 2, "both layers must resolve, or this proves nothing"
    assert len({v.revision_id for v in resolution.versions}) == 1, (
        "the revision ids must collide, or the test is not the collision case"
    )

    # Identities, however, do not collide.
    identities = {
        PolicyIdentity(
            policy_type=v.document_type, policy_id=v.policy_id, version=v.revision_id
        ).key
        for v in resolution.versions
    }
    assert len(identities) == 2

    query = embedder.encode_query(sentence)
    for document_type, expected_chunk in chunks.items():
        scope = resolution.scope_for(document_type)
        assert scope is not None
        returned = {c.chunk_id for c in await search_chunks(session, query, scope)}
        assert returned == {expected_chunk}, (
            f"a {document_type.value} scope returned {returned}; the other layer "
            "crossed in despite differing only by policy type"
        )


async def test_an_engineering_inferred_link_cannot_establish_applicability(
    session: AsyncSession, corpus: CorpusBuilder
) -> None:
    """Applicability from resemblance is what ADR-004 exists to prevent.

    Two policies linked to the same code, one curated and one inferred. Only the
    curated one may resolve - and the curated one resolving is the positive control
    that proves the fixture reaches the query at all.
    """
    curated = await corpus.document("42 CFR 410.98", DocumentType.REGULATION, title="Curated")
    inferred_doc = await corpus.document("NCD 410.98", DocumentType.NCD, title="Inferred")
    for document in (curated, inferred_doc):
        await corpus.version(document, "R1", date(2022, 1, 1), scope=PolicyScope.NATIONAL, codes=())
    await corpus.commit()

    versions = (
        await session.execute(
            select(PolicyVersion, PolicyDocument)
            .join(PolicyDocument, PolicyDocument.id == PolicyVersion.document_id)
            .where(PolicyDocument.policy_id.in_(["42 CFR 410.98", "NCD 410.98"]))
        )
    ).all()
    for version, document in versions:
        session.add(
            PolicyCodeLink(
                policy_version_id=version.id,
                code="Y8888",
                code_system="HCPCS",
                link_type=LinkType.COVERED_PROCEDURE.value,
                link_provenance=(
                    LinkProvenance.HUMAN_CURATED.value
                    if document.document_type == DocumentType.REGULATION.value
                    else LinkProvenance.ENGINEERING_INFERRED.value
                ),
            )
        )
    await session.commit()

    resolution = await resolve(
        session, ResolutionRequest("Y8888", CodeSystem.HCPCS, date(2024, 6, 1)), POLICY
    )
    resolved = {v.policy_id for v in resolution.versions}
    assert resolved == {"42 CFR 410.98"}, (
        f"resolution returned {resolved}; an ENGINEERING_INFERRED link established "
        "applicability, which is applicability from resemblance"
    )
