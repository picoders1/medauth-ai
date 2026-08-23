"""Structural identifier classification for CFR-style documents.

The Code of Federal Regulations nests paragraphs in a fixed sequence of marker
styles::

    (a)   lowercase letter      TOP
    (1)   arabic numeral        PARAGRAPH
    (i)   lowercase roman       SUBPARAGRAPH
    (A)   uppercase letter      CLAUSE
    (1)   italic arabic         SUBCLAUSE

**The styles overlap, and that is the whole problem.** ``(i)`` is both the ninth
lowercase letter and the first lowercase roman numeral; ``(v)`` and ``(x)`` are the
same. A classifier that inspects a marker in isolation cannot tell them apart, and
one that assumes "single letter means top level" promotes every ``(i)`` in the
document to a section of its own.

That is not hypothetical. Ingesting real 42 CFR 410.38 produced two sections both
named ``Paragraph (i)`` - one a genuine paragraph ``(i)``, one a roman
sub-paragraph - and a criterion citing either would have collided with the other.
`tests/unit/test_hierarchy.py` reproduces that defect against a naive classifier
before proving this one prevents it.

Disambiguation therefore uses **sequence within a known parent**: a marker opens a
level only if it succeeds that level's previous marker, or is that level's first.
``(i)`` after ``(h)`` is a letter; ``(i)`` after ``(3)`` is a roman numeral.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from enum import IntEnum

__all__ = ["HierarchyTracker", "MarkerLevel", "MarkerStyle", "classify_marker_style"]

_ROMAN_SEQUENCE = (
    "i",
    "ii",
    "iii",
    "iv",
    "v",
    "vi",
    "vii",
    "viii",
    "ix",
    "x",
    "xi",
    "xii",
    "xiii",
    "xiv",
    "xv",
    "xvi",
    "xvii",
    "xviii",
    "xix",
    "xx",
)
_MARKER = re.compile(r"^\(([A-Za-z0-9]{1,5})\)")


class MarkerLevel(IntEnum):
    """Depth in the CFR paragraph hierarchy. Lower is shallower."""

    TOP = 1
    PARAGRAPH = 2
    SUBPARAGRAPH = 3
    CLAUSE = 4
    SUBCLAUSE = 5


class MarkerStyle(IntEnum):
    """How a marker is written. Distinct from its depth, because styles overlap."""

    LOWER_LETTER = 1
    ARABIC = 2
    LOWER_ROMAN = 3
    UPPER_LETTER = 4


#: Which depth each style occupies. ``LOWER_LETTER`` and ``LOWER_ROMAN`` are the
#: ambiguous pair, and the reason this module exists.
STYLE_LEVEL: dict[MarkerStyle, MarkerLevel] = {
    MarkerStyle.LOWER_LETTER: MarkerLevel.TOP,
    MarkerStyle.ARABIC: MarkerLevel.PARAGRAPH,
    MarkerStyle.LOWER_ROMAN: MarkerLevel.SUBPARAGRAPH,
    MarkerStyle.UPPER_LETTER: MarkerLevel.CLAUSE,
}


def classify_marker_style(marker: str) -> set[MarkerStyle]:
    """Every style a marker could belong to, read in isolation.

    Returns more than one for the ambiguous markers - which is the honest answer.
    Resolution needs context, and is :class:`HierarchyTracker`'s job.
    """
    styles: set[MarkerStyle] = set()
    if not marker:
        return styles
    if marker.isdigit():
        styles.add(MarkerStyle.ARABIC)
        return styles
    if marker.isupper() and marker.isalpha():
        styles.add(MarkerStyle.UPPER_LETTER)
        return styles
    if marker.islower():
        if len(marker) == 1 and marker.isalpha():
            styles.add(MarkerStyle.LOWER_LETTER)
        if marker in _ROMAN_SEQUENCE:
            styles.add(MarkerStyle.LOWER_ROMAN)
    return styles


def _successor(style: MarkerStyle, previous: str | None) -> str:
    """The marker that would legitimately follow ``previous`` at this style."""
    if style is MarkerStyle.ARABIC:
        return str(int(previous or "0") + 1)
    if style is MarkerStyle.LOWER_ROMAN:
        index = _ROMAN_SEQUENCE.index(previous) + 1 if previous else 0
        return _ROMAN_SEQUENCE[index] if index < len(_ROMAN_SEQUENCE) else ""
    if style is MarkerStyle.UPPER_LETTER:
        return chr(ord(previous) + 1) if previous else "A"
    return chr(ord(previous) + 1) if previous else "a"


@dataclass
class HierarchyTracker:
    """Assigns a depth to each marker as a document is read in order.

    Stateful by necessity: the same marker means different things depending on what
    preceded it, so classification cannot be a pure function of the marker alone.
    """

    _last: dict[MarkerStyle, str | None] = field(default_factory=lambda: dict.fromkeys(MarkerStyle))
    _open_level: MarkerLevel | None = None

    def reset(self) -> None:
        self._last = dict.fromkeys(MarkerStyle)
        self._open_level = None

    def classify(self, text: str) -> tuple[str, MarkerLevel] | None:
        """Classify the marker beginning ``text``, or ``None`` if it has none."""
        match = _MARKER.match(text.strip())
        if not match:
            return None
        marker = match.group(1)
        candidates = classify_marker_style(marker)
        if not candidates:
            return None

        # Prefer a style this marker legitimately continues. Where a marker is
        # ambiguous, the sequence decides - which is exactly the information a
        # marker read in isolation does not carry.
        for style in sorted(candidates, key=lambda s: STYLE_LEVEL[s]):
            if marker == _successor(style, self._last[style]):
                return self._accept(marker, style)

        # No style continues. Treat it as opening the deepest plausible level
        # rather than promoting it: a stray marker must not create a new section.
        style = max(candidates, key=lambda s: STYLE_LEVEL[s])
        return self._accept(marker, style)

    def _accept(self, marker: str, style: MarkerStyle) -> tuple[str, MarkerLevel]:
        level = STYLE_LEVEL[style]
        self._last[style] = marker
        # Opening a level invalidates everything nested beneath it, so a later
        # (i) is read as a fresh roman sequence rather than a continuation.
        for other, other_level in STYLE_LEVEL.items():
            if other_level > level:
                self._last[other] = None
        self._open_level = level
        return marker, level

    def is_top_level(self, text: str) -> bool:
        """Whether ``text`` opens a top-level paragraph - a section boundary."""
        classified = self.classify(text)
        return classified is not None and classified[1] is MarkerLevel.TOP
