"""Offset-preserving normalization - the foundation of citation verification.

Two failure directions matter equally and are both asserted here:

* **Too strict** - a quote differing only in whitespace or typography must pass,
  or every citation from a PDF extraction becomes NO_DECISION and the guardrail
  fails safe into uselessness.
* **Too loose** - a quote whose *words* differ must fail, because that is the
  guardrail working. Homoglyph and invisible-character evasion must not create a
  gap between what a human reads and what the matcher compares.
"""

from __future__ import annotations

import pytest

from app.core.normalize import Span, contains, find_span, normalize, normalize_text

pytestmark = pytest.mark.unit

CHUNK = "Coverage  requires a documented\n\tBMI of 35 or greater."


# ------------------------------------------------------------------ folding
@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("  leading and trailing  ", "leading and trailing"),
        ("collapse   many\n\n\tspaces", "collapse many spaces"),
        ("CASE Folded", "case folded"),
        ("smart “quotes” and — dashes", 'smart "quotes" and - dashes'),
        ("﻿bom and zero​width", "bom and zerowidth"),
        ("soft­hyphen", "softhyphen"),
        ("ＦＵＬＬ width", "full width"),
    ],
)
def test_folds_meaningless_differences(raw: str, expected: str) -> None:
    assert normalize_text(raw) == expected


def test_folds_cyrillic_homoglyphs() -> None:
    """'с' is Cyrillic es, not Latin c. A reader cannot tell; the matcher must."""
    spoofed = "соxpаny"  # с о p а -> "coxpany"-shaped
    assert normalize_text(spoofed) == "coxpany"
    assert normalize_text("АВС") == "abc"


# ------------------------------------------------------------------- offsets
def test_offset_map_has_one_entry_per_character() -> None:
    result = normalize(CHUNK)
    assert len(result.offsets) == len(result.text)
    # Every offset must address a real position in the source.
    assert all(0 <= o < len(CHUNK) for o in result.offsets)


def test_span_maps_back_to_the_exact_raw_text() -> None:
    """The reviewer console highlights this span inside the real document."""
    span = find_span("BMI  of   35", CHUNK)
    assert span is not None
    assert span.slice(CHUNK) == "BMI of 35"


def test_span_survives_normalization_inside_the_match() -> None:
    """A newline in the middle of the source is covered by the returned span."""
    span = find_span("documented BMI", CHUNK)
    assert span is not None
    assert "documented" in span.slice(CHUNK) and "BMI" in span.slice(CHUNK)


def test_offsets_are_monotonic() -> None:
    result = normalize(CHUNK)
    assert list(result.offsets) == sorted(result.offsets)


# ------------------------------------------------------- accept / reject
@pytest.mark.parametrize(
    "quote",
    [
        "BMI of 35 or greater",
        "bmi   of 35",  # case + whitespace
        "documented​ BMI",  # zero-width inside the quote
        "dоcumented BMI",  # Cyrillic o
    ],
)
def test_accepts_quotes_that_differ_only_cosmetically(quote: str) -> None:
    assert contains(quote, CHUNK), f"{quote!r} should verify against the chunk"


@pytest.mark.parametrize(
    "quote",
    [
        "BMI of 40 or greater",  # a different number
        "Coverage forbids a documented BMI",  # inverted meaning
        "documented BMI of 35 or less",  # inverted comparator
        "",  # nothing
        "   \n\t ",  # nothing, verbosely
    ],
)
@pytest.mark.security
def test_rejects_quotes_whose_meaning_differs(quote: str) -> None:
    assert not contains(quote, CHUNK), (
        f"{quote!r} verified against the chunk. Span validation is the only thing "
        "standing between a fabricated justification and a recommendation."
    )


def test_empty_quote_is_never_a_citation() -> None:
    assert find_span("", CHUNK) is None
    assert find_span("​​", CHUNK) is None


# --------------------------------------------------------------------- types
def test_span_rejects_impossible_ranges() -> None:
    with pytest.raises(ValueError, match="invalid span"):
        Span(5, 2)
    with pytest.raises(ValueError, match="invalid span"):
        Span(-1, 3)


def test_normalized_text_rejects_a_mismatched_offset_map() -> None:
    from app.core.normalize import NormalizedText

    with pytest.raises(ValueError, match="offset map length"):
        NormalizedText(raw="abc", text="abc", offsets=(0, 1))
