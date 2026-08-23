"""Chunking: the boundary rule is a safety property, not a tuning preference.

A chunk that spans "Indications" and "Limitations" can yield a citation that is
textually exact and semantically inverted - the quote verifies, the span matches,
the metadata is consistent, and the passage supports the opposite of what the policy
says. The guardrail cannot catch it, because span validation is doing its job on a
chunk that should never have existed (ADR-006).

So the rule is asserted here rather than left to the chunker's judgement, and it is
asserted against adversarial section shapes, not only the convenient ones.
"""

from __future__ import annotations

import itertools

import pytest

from app.core.hashing import content_hash
from app.policy.chunk import chunk_sections, estimate_tokens
from app.policy.documents import Section

pytestmark = pytest.mark.unit


def _section(path: str, words: int, *, word: str = "alpha", page: int = 1) -> Section:
    return Section(path=path, text=" ".join([word] * words), page_from=page, page_to=page)


INDICATIONS = Section(
    path="Coverage Indications, Limitations and/or Medical Necessity",
    text="Total knee arthroplasty is covered when conservative therapy has been completed.",
    page_from=1,
    page_to=1,
)
LIMITATIONS = Section(
    path="Limitations",
    text="Total knee arthroplasty is not covered when active infection is documented.",
    page_from=1,
    page_to=2,
)


# --------------------------------------------------------------- the boundary
def test_a_chunk_never_spans_two_sections() -> None:
    """The inverted-meaning failure, tested directly.

    Both sections are small enough to merge if the chunker packed across
    boundaries - which is exactly what a size-driven chunker would do.
    """
    chunks = chunk_sections((INDICATIONS, LIMITATIONS), max_tokens=400)

    assert len(chunks) == 2
    covered = next(c for c in chunks if c.section_path == "Limitations")
    assert "is not covered" in covered.text
    assert "is covered when" not in covered.text, (
        "a chunk carries text from both Indications and Limitations. A quote from it "
        "would verify while supporting the opposite of what the policy says."
    )


@pytest.mark.parametrize("max_tokens", [20, 50, 120, 400, 4000])
def test_the_boundary_holds_at_every_chunk_size(max_tokens: int) -> None:
    """The guarantee is structural, so no parameter can break it."""
    sections = (
        _section("Indications", 300, word="indicated"),
        _section("Limitations", 300, word="excluded"),
        _section("Documentation Requirements", 40, word="documented"),
    )
    chunks = chunk_sections(sections, max_tokens=max_tokens, overlap_tokens=max_tokens // 4)

    for chunk in chunks:
        words = set(chunk.text.split())
        assert len(words) == 1, (
            f"chunk from {chunk.section_path!r} mixes vocabulary from several "
            f"sections at max_tokens={max_tokens}: {sorted(words)}"
        )


def test_every_part_of_a_split_section_keeps_its_section_path() -> None:
    """A citation to part 3 must still name the section a reviewer will look under.

    Uses a section with NO sentence boundaries, which is the case that has to fall
    back to word splitting. Policy enumerations and code tables look like this.
    """
    chunks = chunk_sections((_section("Limitations", 1200),), max_tokens=100, overlap_tokens=20)

    assert len(chunks) > 1
    assert {c.section_path for c in chunks} == {"Limitations"}
    assert [c.part for c in chunks] == list(range(1, len(chunks) + 1))
    assert {c.of_parts for c in chunks} == {len(chunks)}
    assert all(c.is_split for c in chunks)


# ------------------------------------------------------------------- splitting
def test_an_oversized_section_is_split_with_overlap() -> None:
    chunks = chunk_sections(
        (
            Section(
                path="Coverage",
                text=" ".join(f"Sentence number {i} states a requirement." for i in range(120)),
                page_from=1,
                page_to=3,
            ),
        ),
        max_tokens=80,
        overlap_tokens=24,
    )

    assert len(chunks) > 1
    for earlier, later in itertools.pairwise(chunks):
        shared = set(earlier.text.split()) & set(later.text.split())
        assert shared, "consecutive parts share no overlap; a split criterion could be lost"


def test_a_section_that_fits_is_not_split() -> None:
    chunks = chunk_sections((INDICATIONS,), max_tokens=400)
    assert len(chunks) == 1
    assert chunks[0].of_parts == 1
    assert chunks[0].text == INDICATIONS.text


def test_splitting_does_not_cut_mid_sentence_when_sentences_exist() -> None:
    """A chunk ending mid-clause produces quotes that read complete but are not.

    Word splitting is the last resort and applies only where no sentence boundary
    exists; where one does, it must be preferred.
    """
    chunks = chunk_sections(
        (
            Section(
                path="Coverage",
                text=" ".join(
                    f"Criterion {i} must be documented in the record." for i in range(60)
                ),
                page_from=1,
                page_to=1,
            ),
        ),
        max_tokens=60,
        overlap_tokens=12,
    )
    for chunk in chunks:
        assert chunk.text.rstrip().endswith("."), (
            f"chunk ends mid-sentence: ...{chunk.text[-40:]!r}"
        )


# ------------------------------------------------------------------- metadata
def test_page_ranges_and_ordinals_survive_chunking() -> None:
    chunks = chunk_sections((INDICATIONS, LIMITATIONS))
    assert [c.ordinal for c in chunks] == [1, 2]
    limitations = next(c for c in chunks if c.section_path == "Limitations")
    assert (limitations.page_from, limitations.page_to) == (1, 2)


def test_each_chunk_hashes_its_own_normalized_text() -> None:
    chunks = chunk_sections((INDICATIONS, LIMITATIONS))
    for chunk in chunks:
        assert chunk.text_sha256 == content_hash(chunk.text)
    assert len({c.text_sha256 for c in chunks}) == len(chunks)


def test_trivial_sections_are_dropped() -> None:
    """A heading fragment is not evidence; embedding it adds noise to every search."""
    chunks = chunk_sections((_section("Stub", 2), INDICATIONS), min_tokens=8)
    assert [c.section_path for c in chunks] == [INDICATIONS.path]


def test_empty_input_yields_no_chunks() -> None:
    assert chunk_sections(()) == ()


# ------------------------------------------------------------------- guardrails
def test_overlap_must_be_smaller_than_the_chunk_size() -> None:
    """Otherwise packing cannot make progress and would loop or stall."""
    with pytest.raises(ValueError, match="smaller than max_tokens"):
        chunk_sections((INDICATIONS,), max_tokens=50, overlap_tokens=50)


def test_token_estimate_is_monotonic_and_positive() -> None:
    """It only decides when to split; it is never reported as a measurement."""
    assert estimate_tokens("") >= 1
    assert estimate_tokens("one two three") > estimate_tokens("one")


def test_an_unpunctuated_section_is_still_bounded() -> None:
    """A long enumeration with no sentence boundary must not produce one giant chunk
    wider than the encoder's context - it would be silently truncated at embedding
    time, and the loss would read as a retrieval-quality problem."""
    chunks = chunk_sections((_section("Group 1 Codes", 2000),), max_tokens=120, overlap_tokens=24)

    assert len(chunks) > 1
    assert all(c.token_count <= 120 * 1.2 for c in chunks), (
        f"chunk sizes {[c.token_count for c in chunks]} exceed the budget"
    )
    # Word boundaries only: no fragment may be a partial word.
    assert all(word == "alpha" for c in chunks for word in c.text.split())
