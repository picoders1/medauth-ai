"""Section detection over CMS coverage documents.

CMS material is templated - NCDs, LCDs and Billing & Coding Articles each use a
known set of headings - and this module exploits that rather than guessing. When it
meets a layout it does not recognise it **fails loudly**, because the alternative is
worse than an error: silently flattening an unrecognised document produces chunks
that span what should have been section boundaries, and a chunk spanning
"Indications" and "Limitations" can yield a citation that is textually exact and
semantically inverted (ADR-006).

Unknown headings *alongside* recognised ones are kept as subsections rather than
rejected. Real documents carry local headings, and refusing them would make the
parser brittle in the direction that loses information.
"""

from __future__ import annotations

import re

from app.core.errors import MedauthError
from app.policy.documents import Page, Section
from app.policy.models import DocumentType

__all__ = ["CANONICAL_SECTIONS", "UnrecognisedLayoutError", "detect_sections"]


class UnrecognisedLayoutError(MedauthError):
    """The document does not look like the policy type it claims to be."""


#: Headings CMS uses, per document type. Matching is case-insensitive and tolerant
#: of trailing punctuation, but not of paraphrase - a heading that merely resembles
#: one of these is treated as a local subsection, not silently mapped onto it.
CANONICAL_SECTIONS: dict[DocumentType, tuple[str, ...]] = {
    # 42 CFR paragraph headings are authored per section rather than drawn from a
    # fixed template, so the acquisition adapter emits them as explicit headings
    # and these act as the anchors that prove the layout was understood.
    DocumentType.REGULATION: (
        "Statutory basis",
        "Scope",
        "Definitions",
        "General rule",
        "Conditions",
        "Exceptions",
        "Limitations",
        "Excluded services",
        "Documentation",
        "Applicability",
    ),
    DocumentType.NCD: (
        "Benefit Category",
        "Item/Service Description",
        "Indications and Limitations of Coverage",
        "Transmittal Information",
        "Cross Reference",
        "Claims Processing Instructions",
    ),
    DocumentType.LCD: (
        "Coverage Guidance",
        "Coverage Indications, Limitations and/or Medical Necessity",
        "Summary of Evidence",
        "Analysis of Evidence",
        "General Information",
        "Associated Information",
        "Documentation Requirements",
        "Utilization Guidelines",
        "Sources of Information",
        "Revision History",
    ),
    DocumentType.ARTICLE: (
        "Article Guidance",
        "Article Text",
        "CPT/HCPCS Codes",
        "ICD-10-CM Codes that Support Medical Necessity",
        "ICD-10-CM Codes that DO NOT Support Medical Necessity",
        "Bill Type Codes",
        "Revenue Codes",
        "General Information",
        "Revision History",
    ),
}

#: A CFR top-level paragraph marker: "(a)", "(b)". Used as the structural evidence
#: that a preceding line is a real section heading in a REGULATION.
_CFR_MARKER = re.compile(r"^\(([a-z])\)\s")


#: A local heading: short, title-cased, unpunctuated. Applied ONLY with the
#: surrounding-blank-line evidence below - on its own this pattern also matches
#: every wrapped line of ordinary prose, which is the trap it exists to avoid.
_LOCAL_HEADING = re.compile(r"^[A-Z][A-Za-z0-9 ,/&()'-]{2,60}$")

#: A local heading may not be this long. Canonical headings are exempt.
_MAX_HEADING_WORDS = 8


def _canonical(document_type: DocumentType, title: str) -> str | None:
    folded = title.strip().rstrip(":").casefold()
    for known in CANONICAL_SECTIONS[document_type]:
        if folded == known.casefold():
            return known
    return None


def _is_regulation_heading(line: str, following: str | None) -> bool:
    """Whether ``line`` heads a lettered paragraph of a CFR section.

    CFR sections author their own paragraph headings rather than drawing them from
    a template, so a fixed vocabulary cannot recognise them. The evidence used
    instead comes from the document's own structure: a heading is immediately
    followed by a top-level lettered paragraph. That is a fact about the source,
    not a guess about the wording - which is the same standard applied to CMS
    local headings, using the marker CFR provides in place of a blank line.
    """
    stripped = line.strip()
    if not stripped or stripped != line or len(stripped.split()) > 10:
        return False
    if stripped.endswith((".", ",", ";")):
        return False
    # A heading names a paragraph; it is not itself one. Without this, a body line
    # such as "(4) The procedures are covered when" that happens to precede a
    # lettered paragraph becomes a section name, and a criterion citing that
    # section would be anchored to prose rather than to structure.
    if re.match(r"^\([A-Za-z0-9]{1,5}\)", stripped):
        return False
    return bool(following and _CFR_MARKER.match(following.strip()))


def _is_local_heading(line: str, previous: str | None, following: str | None) -> bool:
    """Whether ``line`` is a document-local heading rather than wrapped prose.

    The decisive evidence is **structural, not lexical**: a heading is preceded by a
    blank line (or begins the page) and followed by content. Without that check a
    wrapped sentence fragment - "Total knee arthroplasty is considered reasonable"
    - satisfies every lexical test for a heading, and the section tree fills up with
    body text masquerading as structure.
    """
    stripped = line.strip()
    if not stripped or stripped != line.rstrip():
        return False
    if line != line.lstrip():
        return False
    if stripped.endswith((".", ",", ";", ":")):
        return False
    if len(stripped.split()) > _MAX_HEADING_WORDS:
        return False
    if previous is not None and previous.strip():
        return False
    if following is None or not following.strip():
        return False
    return bool(_LOCAL_HEADING.match(stripped))


def detect_sections(
    pages: tuple[Page, ...], document_type: DocumentType, *, min_recognised: int = 2
) -> tuple[Section, ...]:
    """Split ``pages`` into sections, preserving page ranges.

    Raises:
        UnrecognisedLayoutError: fewer than ``min_recognised`` canonical headings
            were found. The document is not flattened into one section, because that
            would let a chunk span a boundary that carries meaning.
    """
    if not pages:
        raise UnrecognisedLayoutError("document has no pages")

    current_title = "Preamble"
    current_lines: list[str] = []
    current_from = pages[0].number
    current_recognised = False
    sections: list[Section] = []
    recognised_count = 0

    def flush(page_to: int) -> None:
        body = "\n".join(current_lines).strip()
        if body:
            sections.append(
                Section(
                    path=current_title,
                    text=body,
                    page_from=current_from,
                    page_to=page_to,
                    recognised=current_recognised,
                )
            )

    last_page = pages[0].number
    for page in pages:
        last_page = page.number
        lines = page.text.splitlines()
        for index, line in enumerate(lines):
            previous = lines[index - 1] if index else None
            following = lines[index + 1] if index + 1 < len(lines) else None
            # The evidence a CFR heading needs is the lettered paragraph that
            # follows it, which a blank line may separate from it.
            following_content = next(
                (candidate for candidate in lines[index + 1 :] if candidate.strip()), None
            )

            canonical = _canonical(document_type, line)
            if document_type is DocumentType.REGULATION:
                # A CFR heading is proven by the lettered paragraph that follows it.
                regulation_heading = _is_regulation_heading(line, following_content)
                is_heading = canonical is not None or regulation_heading
                recognised_here = canonical is not None or regulation_heading
            else:
                # Canonical headings are unambiguous and need no structural
                # evidence. Local headings do, because prose imitates them.
                is_heading = canonical is not None or (
                    recognised_count > 0 and _is_local_heading(line, previous, following)
                )
                recognised_here = canonical is not None
            if is_heading:
                flush(page.number)
                current_title = canonical or line.strip().rstrip(":")
                current_lines = []
                current_from = page.number
                current_recognised = recognised_here
                if recognised_here:
                    recognised_count += 1
                continue

            current_lines.append(line)
    flush(last_page)

    if recognised_count < min_recognised:
        raise UnrecognisedLayoutError(
            f"only {recognised_count} recognised {document_type.value} section heading(s) "
            f"found (need {min_recognised}). Refusing to flatten an unrecognised layout: "
            "a chunk spanning what should have been a section boundary can produce a "
            "citation that verifies while inverting the policy's meaning."
        )

    return tuple(s for s in sections if not s.is_empty)
