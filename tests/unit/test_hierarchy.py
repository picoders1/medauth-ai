"""Structural identifier classification, and the real defect that motivated it.

Ingesting genuine 42 CFR 410.38 produced two sections both named
``Paragraph (i)`` - one a real top-level paragraph, one a roman sub-paragraph
under ``(d)(1)``. A criterion citing either would have resolved to whichever the
lookup happened to reach first.

The first test here **reproduces that defect** against the naive rule that caused
it. The rest prove the tracker prevents it. A regression test that only asserts
the fixed behaviour cannot show the bug was ever possible.
"""

from __future__ import annotations

import pytest

from app.policy.hierarchy import (
    HierarchyTracker,
    MarkerLevel,
    MarkerStyle,
    classify_marker_style,
)

pytestmark = pytest.mark.unit


#: The rule the original parser used: "a single letter means top level".
def _naive_is_top_level(marker: str) -> bool:
    return len(marker) == 1 and marker.isalpha() and marker.islower()


#: Shape of the real section: (d) has paragraph (1), which has sub-paragraphs
#: (i) and (ii); a genuine top-level (e) follows.
REAL_410_38 = [
    "(a) General scope. Medicare Part B pays for durable medical equipment",
    "(b) Institutions that may not qualify as the patient's home.",
    "(c) Definitions. As used in this section:",
    "(1) Physician has the same meaning as in section 1861(r)(1).",
    "(d) Conditions of Payment. The requirements described in this paragraph",
    "(1) Written Order/Prescription. All DMEPOS items require a written order",
    "(i) Elements. A written order must include the following elements:",
    "(A) Beneficiary Name or Medicare Beneficiary Identifier (MBI).",
    "(B) General Description of the item.",
    "(ii) Timing of the Written Order/Prescription.",
    "(2) Items Requiring a Face-to-Face Encounter.",
    "(i) The encounter must be used for the purpose of gathering information.",
    "(ii) If it is a telehealth encounter, the requirements must be met.",
    "(e) Suspension of face-to-face encounter requirements.",
]


# ------------------------------------------------- the defect, reproduced
def test_the_naive_rule_reproduces_the_original_defect() -> None:
    """Documents the bug: the old rule promotes roman (i) to a section.

    Two distinct ``(i)`` markers become two top-level sections, both of which the
    renderer names "Paragraph (i)" - a collision that silently redirects any
    criterion citing one of them.
    """
    promoted = [
        line[1:2] for line in REAL_410_38 if _naive_is_top_level(line[1:2]) and line[2] == ")"
    ]

    assert promoted.count("i") == 2, "the fixture no longer contains the ambiguous case"
    assert len(promoted) != len(set(promoted)), (
        "the naive rule must produce a duplicate - that duplicate IS the defect"
    )


def test_the_tracker_does_not_reproduce_it() -> None:
    """The same input, classified with parent context: no duplicate top levels."""
    tracker = HierarchyTracker()
    tops = [
        marker
        for line in REAL_410_38
        if (classified := tracker.classify(line)) and classified[1] is MarkerLevel.TOP
        for marker, _ in [classified]
    ]

    assert tops == ["a", "b", "c", "d", "e"], f"top-level sequence was {tops}"
    assert len(tops) == len(set(tops)), "a top-level marker was assigned twice"
    assert "i" not in tops, "roman (i) was promoted to a section again"


# ------------------------------------------------- repeated roman numerals
def test_repeated_roman_numerals_under_different_parents() -> None:
    """(i) appears twice, under (d)(1) and under (d)(2). Both are sub-paragraphs."""
    tracker = HierarchyTracker()
    levels = {}
    for index, line in enumerate(REAL_410_38):
        classified = tracker.classify(line)
        if classified and classified[0] == "i":
            levels[index] = classified[1]

    assert len(levels) == 2, f"expected two (i) markers, saw {len(levels)}"
    assert set(levels.values()) == {MarkerLevel.SUBPARAGRAPH}, (
        f"a repeated roman numeral was classified inconsistently: {levels}"
    )


def test_a_roman_sequence_restarts_under_a_new_parent() -> None:
    """After (2) opens, the next (i) begins a fresh roman run rather than
    continuing the previous one."""
    tracker = HierarchyTracker()
    for line in ["(a) first", "(1) para", "(i) sub", "(ii) sub", "(2) para"]:
        tracker.classify(line)

    marker, level = tracker.classify("(i) sub under the new parent")  # type: ignore[misc]
    assert (marker, level) == ("i", MarkerLevel.SUBPARAGRAPH)


# ------------------------------------------------------ repeated arabic
def test_repeated_paragraph_labels_under_different_parents() -> None:
    """(1) recurs under (c) and (d). Neither is a section."""
    tracker = HierarchyTracker()
    seen = [
        tracker.classify(line)
        for line in ["(c) Definitions", "(1) first", "(d) Conditions", "(1) first again"]
    ]
    levels = [c[1] for c in seen if c]

    assert levels == [
        MarkerLevel.TOP,
        MarkerLevel.PARAGRAPH,
        MarkerLevel.TOP,
        MarkerLevel.PARAGRAPH,
    ]


# -------------------------------------------------------- letter vs roman
@pytest.mark.parametrize(
    ("preceding", "expected"),
    [
        (["(g) g", "(h) h"], MarkerLevel.TOP),  # (i) after (h) is a letter
        (["(a) a", "(1) one"], MarkerLevel.SUBPARAGRAPH),  # (i) after (1) is roman
    ],
)
def test_the_same_marker_means_different_things_by_context(
    preceding: list[str], expected: MarkerLevel
) -> None:
    """The core ambiguity, decided by sequence rather than by the marker itself."""
    tracker = HierarchyTracker()
    for line in preceding:
        tracker.classify(line)

    classified = tracker.classify("(i) the ambiguous marker")
    assert classified is not None
    assert classified[1] is expected


def test_marker_styles_are_reported_honestly_in_isolation() -> None:
    """Read alone, (i) is genuinely both. Saying so is more useful than guessing."""
    assert classify_marker_style("i") == {MarkerStyle.LOWER_LETTER, MarkerStyle.LOWER_ROMAN}
    assert classify_marker_style("v") == {MarkerStyle.LOWER_LETTER, MarkerStyle.LOWER_ROMAN}
    assert classify_marker_style("b") == {MarkerStyle.LOWER_LETTER}
    assert classify_marker_style("ii") == {MarkerStyle.LOWER_ROMAN}
    assert classify_marker_style("3") == {MarkerStyle.ARABIC}
    assert classify_marker_style("B") == {MarkerStyle.UPPER_LETTER}


# ------------------------------------------------------- nesting and depth
def test_full_depth_is_tracked() -> None:
    tracker = HierarchyTracker()
    expected = [
        ("a", MarkerLevel.TOP),
        ("1", MarkerLevel.PARAGRAPH),
        ("i", MarkerLevel.SUBPARAGRAPH),
        ("A", MarkerLevel.CLAUSE),
    ]
    for line, want in zip(["(a) top", "(1) para", "(i) sub", "(A) clause"], expected, strict=True):
        assert tracker.classify(line) == want


def test_a_stray_marker_does_not_open_a_section() -> None:
    """An out-of-sequence marker is read at the deepest plausible level.

    Promoting it would let a malformed document invent section boundaries, and a
    chunk could then span what should have been one.
    """
    tracker = HierarchyTracker()
    tracker.classify("(a) top")
    classified = tracker.classify("(x) wildly out of sequence")
    assert classified is not None
    assert classified[1] is not MarkerLevel.TOP


# ------------------------------------------------------ body text is not a marker
@pytest.mark.parametrize(
    "line",
    [
        "The supplier must maintain the written order.",
        "See sections 1861(e)(1), 1861(mm)(1) and 1819(a)(1) of the Act.",
        "",
        "Conditions of Payment",
        "(2026) is a year, not a marker",
    ],
)
def test_body_text_and_headings_are_not_classified_as_markers(line: str) -> None:
    """A mid-sentence citation like 1861(e)(1) must not open a paragraph."""
    tracker = HierarchyTracker()
    classified = tracker.classify(line)
    assert classified is None or classified[1] is not MarkerLevel.TOP


def test_reset_clears_state_between_documents() -> None:
    tracker = HierarchyTracker()
    for line in ["(a) a", "(b) b", "(c) c"]:
        tracker.classify(line)
    tracker.reset()

    assert tracker.classify("(a) a fresh document") == ("a", MarkerLevel.TOP)
