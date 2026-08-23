"""Section-aware chunking.

The rule is simple and load-bearing: **a chunk never spans a section boundary.**

Coverage policy is written so that the section *is* the unit of meaning -
"Indications", "Limitations", "Coverage Criteria", "Documentation Requirements". A
chunk straddling Indications and Limitations can produce a citation that is
textually exact and semantically inverted: the quote verifies, the span matches,
the metadata is consistent, and the passage supports the opposite of what the policy
says. The guardrail cannot catch it, because span validation is doing its job on a
chunk that should never have existed.

So chunking sits upstream of the citation contract, and the boundary rule is
asserted by test rather than left to the chunker's judgement (ADR-006).

Oversized sections are split *within* the section, with overlap, and every part
inherits the same ``section_path`` so the resulting citation still names the correct
section.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from app.core.hashing import content_hash
from app.policy.documents import Section

__all__ = ["Chunk", "chunk_sections", "estimate_tokens"]

#: Paragraph and sentence boundaries, preferred split points in that order.
_PARAGRAPH = re.compile(r"\n\s*\n")
_SENTENCE = re.compile(r"(?<=[.!?])\s+(?=[A-Z(])")


def estimate_tokens(text: str) -> int:
    """Approximate token count without a tokenizer dependency.

    Whitespace words scaled by a factor that reflects sub-word splitting on the
    clinical and regulatory vocabulary this corpus uses. It is an **estimate**, used
    only to decide when to split a section - never reported as a measurement, and
    never used where an exact count would matter.
    """
    words = len(text.split())
    return int(words * 1.35) + 1


@dataclass(frozen=True, slots=True)
class Chunk:
    """One section-bounded passage, ready to embed and to cite."""

    ordinal: int
    section_path: str
    text: str
    page_from: int
    page_to: int
    token_count: int
    text_sha256: str
    part: int = 1
    of_parts: int = 1

    @property
    def is_split(self) -> bool:
        return self.of_parts > 1


def _hard_split(unit: str, max_tokens: int) -> list[str]:
    """Last-resort split of a unit that has no sentence boundary to break on.

    Policy documents contain long enumerations and tables that carry no terminal
    punctuation, and such a unit would otherwise produce a chunk wider than the
    encoder's context - silently truncated at embedding time, which degrades
    retrieval in a way that reads as a model-quality problem.

    Splits fall on word boundaries only. Never mid-word: a fragment that is not a
    word cannot be quoted, and a citation to it could never verify.
    """
    words = unit.split()
    if not words:
        return []
    # `estimate_tokens` scales words by a constant, so invert it to get a word budget.
    per_part = max(1, int(max_tokens / 1.35) - 1)
    return [" ".join(words[i : i + per_part]) for i in range(0, len(words), per_part)]


def _split_units(text: str, max_tokens: int) -> list[str]:
    """Break a section into the smallest units a split may fall between.

    Paragraphs first, then sentences within an oversized paragraph, then - only if a
    single sentence still exceeds the budget - words. The ordering matters: a chunk
    ending mid-clause produces quotes that read as complete but are not, so word
    splitting is reached only when nothing better exists.
    """
    units: list[str] = []
    for paragraph in (p.strip() for p in _PARAGRAPH.split(text)):
        if not paragraph:
            continue
        for sentence in (s.strip() for s in _SENTENCE.split(paragraph)):
            if not sentence:
                continue
            if estimate_tokens(sentence) > max_tokens:
                units.extend(_hard_split(sentence, max_tokens))
            else:
                units.append(sentence)
    if units:
        return units
    stripped = text.strip()
    if not stripped:
        return []
    return (
        _hard_split(stripped, max_tokens) if estimate_tokens(stripped) > max_tokens else [stripped]
    )


def _pack(units: list[str], max_tokens: int, overlap_tokens: int) -> list[str]:
    """Greedily pack units into parts, carrying overlap between consecutive parts."""
    parts: list[str] = []
    current: list[str] = []
    current_tokens = 0

    for unit in units:
        unit_tokens = estimate_tokens(unit)
        if current and current_tokens + unit_tokens > max_tokens:
            parts.append(" ".join(current))
            # Carry the tail of the previous part forward, so a criterion split
            # across the boundary is still retrievable from at least one part.
            carried: list[str] = []
            carried_tokens = 0
            for previous in reversed(current):
                previous_tokens = estimate_tokens(previous)
                if carried_tokens + previous_tokens > overlap_tokens:
                    break
                carried.insert(0, previous)
                carried_tokens += previous_tokens
            current = carried
            current_tokens = carried_tokens
        current.append(unit)
        current_tokens += unit_tokens

    if current:
        parts.append(" ".join(current))
    return parts


def chunk_sections(
    sections: tuple[Section, ...],
    *,
    max_tokens: int = 400,
    overlap_tokens: int = 60,
    min_tokens: int = 8,
) -> tuple[Chunk, ...]:
    """Chunk each section independently.

    Sections are processed one at a time and never combined, which is what makes the
    boundary guarantee structural rather than a matter of parameter tuning: there is
    no code path in which text from two sections reaches the same chunk.

    Sections shorter than ``min_tokens`` are dropped - a two-word heading fragment
    is not evidence, and embedding it adds noise to every search.
    """
    if overlap_tokens >= max_tokens:
        raise ValueError(
            f"overlap_tokens ({overlap_tokens}) must be smaller than max_tokens "
            f"({max_tokens}); otherwise packing cannot make progress"
        )

    chunks: list[Chunk] = []
    ordinal = 0

    for section in sections:
        body = section.text.strip()
        if not body or estimate_tokens(body) < min_tokens:
            continue

        parts = (
            [body]
            if estimate_tokens(body) <= max_tokens
            else _pack(_split_units(body, max_tokens), max_tokens, overlap_tokens)
        )

        for index, part in enumerate(parts, start=1):
            ordinal += 1
            chunks.append(
                Chunk(
                    ordinal=ordinal,
                    # Every part inherits the section path, so a citation to part 3
                    # still names the section a reviewer will look under.
                    section_path=section.path,
                    text=part,
                    page_from=section.page_from,
                    page_to=section.page_to,
                    token_count=estimate_tokens(part),
                    text_sha256=content_hash(part),
                    part=index,
                    of_parts=len(parts),
                )
            )

    return tuple(chunks)
