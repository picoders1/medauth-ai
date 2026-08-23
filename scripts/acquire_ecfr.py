"""Acquire real Medicare coverage regulation from the eCFR API.

    uv run python scripts/acquire_ecfr.py --sections 410.32 410.33 411.15

**This is real, authoritative, public-domain policy text.** 42 CFR is the Code of
Federal Regulations as published by the Office of the Federal Register - a US
Government work, no copyright, no access control, and the API serves any date so
historical versions are retrievable rather than reconstructed.

What it is NOT: an NCD or an LCD. 42 CFR sits *above* those in the coverage
hierarchy - statute, then regulation, then national determinations, then local
ones. Documents are labelled `REGULATION` accordingly, because calling a
regulation an NCD would misstate both its authority and its scope.

Two things this adapter deliberately does not do:

* **It does not invent code linkage.** A regulation states conditions; it does not
  enumerate HCPCS or ICD-10 codes the way an LCD does. Code links are curated
  separately and recorded as curated, never inferred from the text.
* **It does not declare criteria.** Criteria are transcribed by a human into the
  document's front matter and span-verified at parse time. An adapter that
  extracted them would be inventing ground truth.
"""

from __future__ import annotations

import argparse
import hashlib
import html
import re
import sys
import time
from dataclasses import dataclass
from datetime import UTC, date, datetime
from pathlib import Path

import httpx

from app.policy.hierarchy import HierarchyTracker, MarkerLevel

REPO = Path(__file__).resolve().parents[1]
API = "https://www.ecfr.gov/api/versioner/v1/full/{date}/title-{title}.xml"
CITE = "https://www.ecfr.gov/current/title-{title}/section-{section}"

USER_AGENT = "medauth-ai/0.1 (research; policy ingestion)"


@dataclass(frozen=True, slots=True)
class Paragraph:
    marker: str
    heading: str | None
    text: str


def fetch_section(title: int, part: str, section: str, as_of: date) -> str:
    url = API.format(date=as_of.isoformat(), title=title)
    response = httpx.get(
        url,
        params={"part": part, "section": section},
        timeout=60.0,
        headers={"user-agent": USER_AGENT},
        follow_redirects=True,
    )
    response.raise_for_status()
    return response.text


def parse_paragraphs(xml: str) -> tuple[str, list[Paragraph]]:
    """Extract the section heading and its lettered paragraphs."""
    head_match = re.search(r"<HEAD>(.*?)</HEAD>", xml, re.S)
    heading = (
        re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", "", head_match.group(1)))).strip()
        if head_match
        else ""
    )

    paragraphs: list[Paragraph] = []
    for block in re.findall(r"<P[^>]*>(.*?)</P>", xml, re.S):
        italics = re.findall(r"<I>(.*?)</I>", block)
        text = re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", "", block))).strip()
        if not text:
            continue
        marker_match = re.match(r"^\(([a-z0-9ivx]+)\)", text)
        paragraph_heading = None
        if italics:
            candidate = re.sub(
                r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", "", italics[0]))
            ).strip()
            # An italic run is a heading only when it is short and terminal - CFR
            # also italicises defined terms mid-sentence.
            if candidate.endswith(".") and len(candidate.split()) <= 8:
                paragraph_heading = candidate.rstrip(".")
        paragraphs.append(
            Paragraph(
                marker=marker_match.group(1) if marker_match else "",
                heading=paragraph_heading,
                text=text,
            )
        )
    return heading, paragraphs


def render_document(
    *,
    section: str,
    heading: str,
    paragraphs: list[Paragraph],
    as_of: date,
    amended_on: date,
    end_date: date | None = None,
) -> str:
    """Render into the repository's document format, headings made explicit.

    Top-level paragraphs carry a heading in the source; those become section
    headings so the existing section-aware chunker can enforce its boundary rule.
    A top-level paragraph without one becomes 'Paragraph (x)', which is accurate
    rather than invented.
    """
    title_number = section.split(".")[0]
    body: list[str] = []
    current: list[str] = []

    def flush() -> None:
        if current:
            body.append("\n".join(current))
            current.clear()

    # Depth comes from HierarchyTracker, which resolves the (i)-as-letter versus
    # (i)-as-roman ambiguity from sequence within a known parent. A marker read in
    # isolation cannot carry that, and assuming it can produced two sections both
    # named "Paragraph (i)" in real 42 CFR 410.38.
    tracker = HierarchyTracker()
    for paragraph in paragraphs:
        classified = tracker.classify(paragraph.text)
        top_level = classified is not None and classified[1] is MarkerLevel.TOP
        if top_level:
            flush()
            label = paragraph.heading or f"Paragraph ({paragraph.marker})"
            body.append(label)
            current.append(paragraph.text)
        else:
            current.append(paragraph.text)
    flush()

    front = "\n".join(
        [
            "---",
            f'policy_id: "42 CFR {section}"',
            "document_type: REGULATION",
            f'title: "{heading.replace(chr(34), chr(39))}"',
            f'revision_id: "{amended_on.isoformat()}"',
            "scope: NATIONAL",
            f"effective_date: {amended_on.isoformat()}",
            f"end_date: {end_date.isoformat() if end_date else 'null'}",
            f"source_url: {CITE.format(title=42, section=section)}",
            "source_authority: Office of the Federal Register",
            f"# Retrieved {as_of.isoformat()} from the eCFR API. Public domain (US Government work).",
            f"# Part {title_number}. Code links are NOT declared here: a regulation states",
            "# conditions and does not enumerate procedure codes. Curate them separately.",
            "codes: []",
            "criteria: []  # transcribed by a human, then span-verified at parse time",
            "---",
            "",
        ]
    )
    return front + "\n\n".join(body) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--sections", nargs="+", default=["410.32", "410.33", "410.38", "411.15"])
    parser.add_argument("--as-of", default=date.today().isoformat())
    parser.add_argument("--out", default="data/cms")
    parser.add_argument("--title", type=int, default=42)
    parser.add_argument(
        "--end-date",
        default=None,
        help="close this revision's effective window; omit for the revision in force",
    )
    args = parser.parse_args()

    as_of = date.fromisoformat(args.as_of)
    end_date = date.fromisoformat(args.end_date) if args.end_date else None
    out = REPO / args.out
    out.mkdir(parents=True, exist_ok=True)
    written: list[tuple[str, int, str]] = []

    for section in args.sections:
        part = section.split(".")[0]
        try:
            xml = fetch_section(args.title, part, section, as_of)
        except httpx.HTTPError as exc:
            print(f"  {section:<10} FAILED  {type(exc).__name__}: {exc}", file=sys.stderr)
            continue

        heading, paragraphs = parse_paragraphs(xml)
        if not heading or len(paragraphs) < 3:
            print(f"  {section:<10} SKIPPED  unrecognised structure", file=sys.stderr)
            continue

        document = render_document(
            section=section,
            heading=heading,
            paragraphs=paragraphs,
            as_of=as_of,
            amended_on=as_of,
            end_date=end_date,
        )
        path = out / f"CFR-{section.replace('.', '_')}-{as_of.isoformat()}.md"
        path.write_text(document, encoding="utf-8")
        written.append((section, len(document), hashlib.sha256(path.read_bytes()).hexdigest()[:12]))
        print(
            f"  {section:<10} {len(paragraphs):>3} paragraphs  {len(document):>6} bytes  -> {path.name}"
        )
        time.sleep(0.5)  # courtesy rate limit; the API asks for nothing but deserves it

    print(f"\n  {len(written)} section(s) written to {args.out}")
    print(f"  retrieved {datetime.now(UTC).isoformat(timespec='seconds')} from the eCFR API")
    print("  PUBLIC DOMAIN - US Government work. Real, authoritative regulation.")
    print("  Criteria are NOT declared: transcribe them by hand, then ingest.")
    return 0 if written else 1


if __name__ == "__main__":
    sys.exit(main())
