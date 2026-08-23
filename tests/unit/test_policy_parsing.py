"""Parsing, structuring and validation of policy documents.

The theme is that every one of these refuses rather than guesses. A parser that
infers identity from a filename, or flattens a layout it does not recognise, or
ingests a truncated fetch, produces a corpus that looks healthy and resolves
wrongly - and the wrongness surfaces much later as a retrieval problem where it is
almost impossible to attribute.
"""

from __future__ import annotations

import re
from datetime import date
from pathlib import Path

import pytest

from app.policy.documents import DocumentIdentity, Page, SourceRef
from app.policy.models import DocumentType, LinkType, PolicyScope
from app.policy.parse import PolicyParseError, parse_document, split_front_matter
from app.policy.structure import UnrecognisedLayoutError, detect_sections
from app.policy.validate import DocumentValidationError, validate_document

pytestmark = pytest.mark.unit

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "cms"
SOURCE = SourceRef(uri="fixture", retrieved_at=date(2026, 8, 23), sha256="0" * 64, synthetic=True)


def _load(name: str) -> str:
    return (FIXTURES / name).read_text(encoding="utf-8")


# ------------------------------------------------------------------- identity
def test_identity_comes_from_the_document_not_the_filename() -> None:
    """A filename records how someone saved a file. It carries no authority."""
    raw = _load("LCD-L34567-R4.md")
    document = parse_document(
        raw, SourceRef("saved-under-a-completely-unrelated-name.md", date(2026, 1, 1), "a" * 64)
    )

    assert document.identity.policy_id == "L34567"
    assert document.identity.revision_id == "R4"
    assert document.identity.document_type is DocumentType.LCD


def test_two_revisions_of_one_policy_are_distinguishable() -> None:
    r3 = parse_document(_load("LCD-L34567-R3.md"), SOURCE).identity
    r4 = parse_document(_load("LCD-L34567-R4.md"), SOURCE).identity

    assert r3.policy_id == r4.policy_id
    assert r3.natural_key != r4.natural_key
    assert r3.end_date == date(2023, 6, 30)
    assert r4.end_date is None
    assert r3.effective_date < r4.effective_date


def test_a_document_with_no_metadata_block_is_refused() -> None:
    with pytest.raises(PolicyParseError, match="never inferred from its filename"):
        parse_document("Coverage Indications\nSome text.\n", SOURCE)


@pytest.mark.parametrize(
    ("mutation", "expected"),
    [
        ("policy_id", "policy_id is required"),
        ("effective_date", "effective_date is required"),
        ("source_url", "source_url is required"),
    ],
)
def test_missing_required_identity_fields_are_refused(mutation: str, expected: str) -> None:
    raw = _load("LCD-L34567-R4.md").replace(f"{mutation}:", f"unused_{mutation}:", 1)
    with pytest.raises(PolicyParseError, match=expected):
        parse_document(raw, SOURCE)


def test_a_jurisdictional_policy_without_a_jurisdiction_is_refused() -> None:
    """Otherwise applicability is undecidable and the policy would apply nowhere."""
    with pytest.raises(ValueError, match="jurisdictional scope needs a jurisdiction"):
        DocumentIdentity(
            policy_id="L1",
            document_type=DocumentType.LCD,
            title="t",
            revision_id="R1",
            scope=PolicyScope.JURISDICTIONAL,
            effective_date=date(2024, 1, 1),
            source_url="https://example.invalid",
        )


def test_an_end_date_before_the_effective_date_is_refused() -> None:
    with pytest.raises(ValueError, match="precedes effective_date"):
        DocumentIdentity(
            policy_id="L1",
            document_type=DocumentType.NCD,
            title="t",
            revision_id="R1",
            scope=PolicyScope.NATIONAL,
            effective_date=date(2024, 1, 1),
            end_date=date(2023, 1, 1),
            source_url="https://example.invalid",
        )


def test_front_matter_must_be_terminated() -> None:
    with pytest.raises(PolicyParseError, match="not terminated"):
        split_front_matter("---\npolicy_id: L1\nstill inside the block\n")


# ------------------------------------------------------------------ structure
def test_canonical_sections_are_recognised_across_document_types() -> None:
    for name, expected in [
        ("NCD-220.1-R1.md", "Indications and Limitations of Coverage"),
        ("LCD-L34567-R4.md", "Coverage Indications, Limitations and/or Medical Necessity"),
        ("ARTICLE-A56789-R2.md", "ICD-10-CM Codes that Support Medical Necessity"),
    ]:
        sections = parse_document(_load(name), SOURCE).sections
        assert expected in [s.path for s in sections], f"{name} missing {expected!r}"
        assert all(s.recognised for s in sections if s.path == expected)


def test_indications_and_limitations_are_separate_sections() -> None:
    """The boundary that must never be spanned by a chunk."""
    sections = parse_document(_load("LCD-L34567-R4.md"), SOURCE).sections
    paths = [s.path for s in sections]

    assert "Limitations" in paths
    indications = next(s for s in sections if s.path.startswith("Coverage Indications"))
    limitations = next(s for s in sections if s.path == "Limitations")
    assert "is not covered" in limitations.text
    assert "is not covered" not in indications.text


def test_wrapped_prose_is_not_mistaken_for_a_heading() -> None:
    """The trap: a wrapped sentence fragment satisfies every lexical heading test.

    Structural evidence - a preceding blank line - is what separates them.
    """
    pages = (
        Page(
            1,
            "Coverage Indications, Limitations and/or Medical Necessity\n"
            "Total knee arthroplasty is considered reasonable and necessary when\n"
            "all of the following criteria are documented in the record.\n"
            "\n"
            "Documentation Requirements\n"
            "The record must contain the imaging report.\n",
        ),
    )
    sections = detect_sections(pages, DocumentType.LCD)

    assert [s.path for s in sections] == [
        "Coverage Indications, Limitations and/or Medical Necessity",
        "Documentation Requirements",
    ]
    assert "Total knee arthroplasty" in sections[0].text


def test_an_unrecognised_layout_is_refused_not_flattened() -> None:
    """Flattening would let a chunk span a boundary that carries meaning."""
    pages = (Page(1, "Some Heading\n\nSome body text that resembles nothing in particular.\n"),)
    with pytest.raises(UnrecognisedLayoutError, match="Refusing to flatten"):
        detect_sections(pages, DocumentType.LCD)


def test_page_ranges_are_preserved_across_a_page_break() -> None:
    pages = (
        Page(1, "Coverage Indications, Limitations and/or Medical Necessity\nFirst page text.\n"),
        Page(2, "More text continuing the section.\n\nRevision History\nR1 effective 2024.\n"),
    )
    sections = detect_sections(pages, DocumentType.LCD)
    coverage = sections[0]
    assert (coverage.page_from, coverage.page_to) == (1, 2)


# ----------------------------------------------------------------- validation
def test_every_fixture_validates() -> None:
    for path in sorted(FIXTURES.glob("*.md")):
        document = parse_document(path.read_text(encoding="utf-8"), SOURCE)
        assert validate_document(document, strict=True).ok, path.name


def test_a_policy_with_no_covered_procedure_is_refused() -> None:
    """It would sit in the corpus looking ingested while unreachable by any request."""
    raw = _load("LCD-L34567-R4.md").replace("link: COVERED_PROCEDURE", "link: SUPPORTING_DIAGNOSIS")
    document = parse_document(raw, SOURCE)
    with pytest.raises(DocumentValidationError, match="no COVERED_PROCEDURE"):
        validate_document(document, strict=True)


def test_an_article_without_a_covered_procedure_only_warns() -> None:
    """Articles are reached through the determination they accompany."""
    document = parse_document(_load("ARTICLE-A56789-R2.md"), SOURCE)
    report = validate_document(document, strict=True)
    assert report.ok
    assert any("only be reached through" in w for w in report.warnings)


def test_duplicate_code_links_are_refused() -> None:
    """Applicability is a set of rows; duplicates would double-count in conflicts."""
    raw = _load("LCD-L34567-R4.md").replace(
        '  - {code: "27447", system: HCPCS, link: COVERED_PROCEDURE}',
        '  - {code: "27447", system: HCPCS, link: COVERED_PROCEDURE}\n'
        '  - {code: "27447", system: HCPCS, link: COVERED_PROCEDURE}',
    )
    document = parse_document(raw, SOURCE)
    with pytest.raises(DocumentValidationError, match="duplicate code link"):
        validate_document(document, strict=True)


def test_a_truncated_document_is_refused() -> None:
    """A short body is usually an error page saved as a document.

    The declared criteria are stripped first: with them present the document is
    refused earlier still, by criterion verification, and this test would pass for
    the wrong reason. What is under test here is the body-length check.
    """
    header = _load("LCD-L34567-R4.md").split("---", 2)[1]
    header = re.sub(r"\ncriteria:\n(?:  .*\n|    .*\n)*", "\n", header)
    truncated = (
        f"---{header}---\n"
        "Coverage Indications, Limitations and/or Medical Necessity\nShort.\n\n"
        "Revision History\nR4.\n"
    )
    document = parse_document(truncated, SOURCE)
    assert not document.criteria
    with pytest.raises(DocumentValidationError, match=r"below the .* minimum"):
        validate_document(document, strict=True)


def test_codes_carry_their_system_and_link_type() -> None:
    document = parse_document(_load("LCD-L34567-R4.md"), SOURCE)
    covered = [c for c in document.codes if c.link_type is LinkType.COVERED_PROCEDURE]
    assert [c.code for c in covered] == ["27447"]
    assert document.covered_procedures == ("27447",)
    assert any(c.link_type is LinkType.SUPPORTING_DIAGNOSIS for c in document.codes)


def test_an_unknown_code_system_is_refused() -> None:
    raw = _load("LCD-L34567-R4.md").replace("system: HCPCS", "system: MADEUP", 1)
    with pytest.raises(PolicyParseError, match="unknown system or link"):
        parse_document(raw, SOURCE)
