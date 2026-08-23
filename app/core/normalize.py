"""Offset-preserving text normalization.

Citation verification asks one question: *does this quote occur in that stored
chunk?* Asking it on raw text is too strict - a PDF extraction differs from the
model's rendering by whitespace alone. Asking it on naively normalized text
loses the ability to point at the source, because the offsets no longer line up.

So normalization here carries an **offset map**: ``offsets[i]`` is the index in
the raw string of the character that produced ``text[i]``. A span found in
normalized text maps back to an exact span in the raw text, which is what lets
the reviewer console highlight the quote inside the real document.

The transformation is deliberately narrow. It folds differences that carry no
meaning - whitespace runs, case, Unicode confusables, invisible formatting
characters - and nothing else. A quote whose *words* differ must fail, because
that failure is the guardrail working (ADR-009).

Confusable folding is the security half: a homoglyph-substituted quote
("SATISFIED" with a Cyrillic 'e') would otherwise fail verification and, worse,
a homoglyph-substituted *chunk* could smuggle text past a comparison. Both fold
to the same normalized form here.
"""

from __future__ import annotations

import unicodedata
from dataclasses import dataclass

__all__ = ["NormalizedText", "Span", "contains", "find_span", "normalize", "normalize_text"]


# Format and invisible characters. These carry no meaning and are a standard
# evasion vector, so they produce zero output characters.
_DROP = frozenset(
    "​"  # zero width space
    "‌"  # zero width non-joiner
    "‍"  # zero width joiner
    "⁠"  # word joiner
    "﻿"  # zero width no-break space / BOM
    "­"  # soft hyphen
    "᠎"  # mongolian vowel separator
    "‎"  # left-to-right mark
    "‏"  # right-to-left mark
    "‪‫‬‭‮"  # directional embedding/override
    "⁦⁧⁨⁩"  # directional isolates
)

# Homoglyphs that NFKC does not fold, mapped to their ASCII counterparts.
# Cyrillic and Greek lookalikes dominate real substitution attacks.
_CONFUSABLES = {
    # Cyrillic -> Latin
    "а": "a",
    "е": "e",
    "о": "o",
    "р": "p",
    "с": "c",
    "у": "y",
    "х": "x",
    "А": "A",
    "В": "B",
    "Е": "E",
    "К": "K",
    "М": "M",
    "Н": "H",
    "О": "O",
    "Р": "P",
    "С": "C",
    "Т": "T",
    "Х": "X",
    "І": "I",
    "і": "i",
    "ј": "j",
    "һ": "h",
    "ԛ": "q",
    "ԁ": "d",
    # Greek -> Latin
    "α": "a",
    "β": "B",
    "ε": "e",
    "ι": "i",
    "κ": "k",
    "ν": "v",
    "ο": "o",
    "ρ": "p",
    "σ": "o",
    "υ": "u",
    "χ": "x",
    "Α": "A",
    "Β": "B",
    "Ε": "E",
    "Ζ": "Z",
    "Η": "H",
    "Ι": "I",
    "Κ": "K",
    "Μ": "M",
    "Ν": "N",
    "Ο": "O",
    "Ρ": "P",
    "Τ": "T",
    "Υ": "Y",
    "Χ": "X",
    # Punctuation that differs only typographically
    "‐": "-",
    "‑": "-",
    "‒": "-",
    "–": "-",
    "—": "-",
    "―": "-",
    "−": "-",
    "⁃": "-",
    "‘": "'",
    "’": "'",
    "‚": "'",
    "‛": "'",
    "′": "'",
    "“": '"',
    "”": '"',
    "„": '"',
    "‟": '"',
    "″": '"',
    "«": '"',
    "»": '"',
    "⁄": "/",
    "∕": "/",
}


@dataclass(frozen=True, slots=True)
class Span:
    """A half-open character range ``[start, end)`` into a raw string."""

    start: int
    end: int

    def __post_init__(self) -> None:
        if self.start < 0 or self.end < self.start:
            raise ValueError(f"invalid span: [{self.start}, {self.end})")

    def slice(self, raw: str) -> str:
        return raw[self.start : self.end]

    def __len__(self) -> int:
        return self.end - self.start


@dataclass(frozen=True, slots=True)
class NormalizedText:
    """Normalized text alongside the map back to its source.

    ``offsets`` has exactly ``len(text)`` entries; ``offsets[i]`` is the index in
    ``raw`` of the character that produced ``text[i]``.
    """

    raw: str
    text: str
    offsets: tuple[int, ...]

    def __post_init__(self) -> None:
        if len(self.text) != len(self.offsets):
            raise ValueError(
                f"offset map length {len(self.offsets)} != text length {len(self.text)}"
            )

    def raw_span(self, start: int, end: int) -> Span:
        """Map a half-open range in ``text`` back to a span in ``raw``.

        The end maps to one past the last *contributing* source character, so the
        returned span covers every raw character that produced the match -
        including any that normalized away inside it.
        """
        if not 0 <= start <= end <= len(self.text):
            raise ValueError(f"range [{start}, {end}) outside normalized text")
        if start == end:
            at = self.offsets[start] if start < len(self.offsets) else len(self.raw)
            return Span(at, at)
        return Span(self.offsets[start], self.offsets[end - 1] + 1)


def normalize(raw: str) -> NormalizedText:
    """Normalize ``raw`` while retaining a map back to it."""
    out: list[str] = []
    offsets: list[int] = []
    pending_space = False
    seen_output = False

    for src_index, char in enumerate(raw):
        if char in _DROP:
            continue

        # NFKC per character keeps the mapping one-source-to-many-output, which
        # a whole-string normalization would not. Handles fullwidth forms,
        # ligatures and compatibility digits.
        expanded = unicodedata.normalize("NFKC", char) or char

        for piece in expanded:
            if piece in _DROP:
                continue
            if piece.isspace():
                # Collapse runs; never emit leading whitespace.
                if seen_output:
                    pending_space = True
                continue

            folded = _CONFUSABLES.get(piece, piece).casefold()
            if pending_space:
                out.append(" ")
                offsets.append(src_index)
                pending_space = False
            for produced in folded:
                out.append(produced)
                offsets.append(src_index)
            seen_output = True

    # `pending_space` left set means trailing whitespace, which is dropped.
    return NormalizedText(raw=raw, text="".join(out), offsets=tuple(offsets))


def normalize_text(raw: str) -> str:
    """Normalized form only, for comparisons that do not need offsets."""
    return normalize(raw).text


def find_span(needle: str, haystack: str) -> Span | None:
    """Locate ``needle`` inside ``haystack``, comparing normalized forms.

    Returns a span into the **raw** ``haystack``, or ``None`` if absent. An empty
    or whitespace-only needle never matches: a citation quoting nothing is not a
    citation.
    """
    n_needle = normalize(needle)
    if not n_needle.text:
        return None
    n_hay = normalize(haystack)
    at = n_hay.text.find(n_needle.text)
    if at < 0:
        return None
    return n_hay.raw_span(at, at + len(n_needle.text))


def contains(needle: str, haystack: str) -> bool:
    """Whether ``needle`` occurs in ``haystack`` under normalization."""
    return find_span(needle, haystack) is not None
