"""Parse a policy document into identity, pages and codes.

Identity comes from the document's own declared metadata block, **never from its
filename** (ADR-004, section 5 of the phase brief). A filename records how someone
saved a file; it carries no authority, and two revisions of one policy would be
indistinguishable if identity came from it.

Page boundaries are preserved through the form feed (``\\f``), the convention text
extraction from PDF and HTML both produce. They matter because a citation names a
page, and a reviewer opens the source at that page to check it.

The parser is deliberately format-specific and small. A future ``HtmlParser`` for
real CMS markup implements the same contract and returns the same
:class:`ParsedDocument`; nothing downstream changes.
"""

from __future__ import annotations

from datetime import date, datetime

import yaml

from app.core.errors import MedauthError
from app.core.types import CodeSystem
from app.policy.criteria import CriterionDeclaration, CriterionType, verify_criteria
from app.policy.documents import (
    CodeRef,
    DocumentIdentity,
    Page,
    ParsedDocument,
    SourceRef,
)
from app.policy.models import DocumentType, LinkType, PolicyScope
from app.policy.structure import detect_sections

__all__ = ["PolicyParseError", "parse_document", "split_front_matter"]

FRONT_MATTER_DELIMITER = "---"
PAGE_SEPARATOR = "\f"


class PolicyParseError(MedauthError):
    """The document could not be parsed into a policy with a usable identity."""


def split_front_matter(raw: str) -> tuple[dict[str, object], str]:
    """Separate the declared metadata block from the document body."""
    text = raw.lstrip("﻿").lstrip()
    if not text.startswith(FRONT_MATTER_DELIMITER):
        raise PolicyParseError(
            "document has no metadata block. Policy identity is declared by the "
            "document, never inferred from its filename."
        )
    parts = text.split(FRONT_MATTER_DELIMITER, 2)
    if len(parts) < 3:
        raise PolicyParseError("metadata block is not terminated by '---'")

    try:
        header = yaml.safe_load(parts[1])
    except yaml.YAMLError as exc:
        raise PolicyParseError(f"metadata block is not valid YAML: {exc}") from exc
    if not isinstance(header, dict):
        raise PolicyParseError("metadata block must be a mapping")
    return header, parts[2].lstrip("\n")


def _as_date(value: object, field: str, *, required: bool = True) -> date | None:
    if value is None or value == "":
        if required:
            raise PolicyParseError(f"{field} is required")
        return None
    if isinstance(value, date) and not isinstance(value, datetime):
        return value
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, str):
        try:
            return date.fromisoformat(value)
        except ValueError as exc:
            raise PolicyParseError(f"{field} is not an ISO date: {value!r}") from exc
    raise PolicyParseError(f"{field} is not a date: {value!r}")


def _as_str(header: dict[str, object], field: str, *, required: bool = True) -> str | None:
    value = header.get(field)
    if value is None or (isinstance(value, str) and not value.strip()):
        if required:
            raise PolicyParseError(f"{field} is required")
        return None
    return str(value).strip()


def _identity(header: dict[str, object]) -> DocumentIdentity:
    try:
        document_type = DocumentType(str(header.get("document_type", "")).upper())
    except ValueError as exc:
        raise PolicyParseError(
            f"document_type must be one of {[t.value for t in DocumentType]}, "
            f"got {header.get('document_type')!r}"
        ) from exc
    try:
        scope = PolicyScope(str(header.get("scope", "")).upper())
    except ValueError as exc:
        raise PolicyParseError(
            f"scope must be one of {[s.value for s in PolicyScope]}, got {header.get('scope')!r}"
        ) from exc

    try:
        return DocumentIdentity(
            policy_id=_as_str(header, "policy_id") or "",
            document_type=document_type,
            title=_as_str(header, "title") or "",
            revision_id=_as_str(header, "revision_id") or "",
            scope=scope,
            jurisdiction=_as_str(header, "jurisdiction", required=False),
            effective_date=_as_date(header.get("effective_date"), "effective_date") or date.min,
            end_date=_as_date(header.get("end_date"), "end_date", required=False),
            revision_date=_as_date(header.get("revision_date"), "revision_date", required=False),
            contractor=_as_str(header, "contractor", required=False),
            source_url=_as_str(header, "source_url") or "",
            source_authority=_as_str(header, "source_authority", required=False) or "CMS",
        )
    except ValueError as exc:
        # DocumentIdentity enforces its own invariants; surface them as parse errors.
        raise PolicyParseError(str(exc)) from exc


def _codes(header: dict[str, object]) -> tuple[CodeRef, ...]:
    entries = header.get("codes") or []
    if not isinstance(entries, list):
        raise PolicyParseError("codes must be a list")

    refs: list[CodeRef] = []
    for index, entry in enumerate(entries):
        if not isinstance(entry, dict):
            raise PolicyParseError(f"codes[{index}] must be a mapping")
        try:
            refs.append(
                CodeRef(
                    code=str(entry["code"]).strip(),
                    code_system=CodeSystem(str(entry["system"]).upper()),
                    link_type=LinkType(str(entry["link"]).upper()),
                )
            )
        except KeyError as exc:
            raise PolicyParseError(f"codes[{index}] is missing {exc}") from exc
        except ValueError as exc:
            raise PolicyParseError(f"codes[{index}] has an unknown system or link: {exc}") from exc
    return tuple(refs)


def _criteria(header: dict[str, object]) -> tuple[CriterionDeclaration, ...]:
    """Read declared criteria. Absent is legal; malformed is not.

    A policy may legitimately declare none - a Billing & Coding Article carries
    codes, not tests. But a declaration that is present and unusable is refused,
    because a criterion with weak provenance is worse than no criterion: it looks
    like ground truth.
    """
    entries = header.get("criteria") or []
    if not isinstance(entries, list):
        raise PolicyParseError("criteria must be a list")

    declarations: list[CriterionDeclaration] = []
    for index, entry in enumerate(entries, start=1):
        if not isinstance(entry, dict):
            raise PolicyParseError(f"criteria[{index}] must be a mapping")
        try:
            declarations.append(
                CriterionDeclaration(
                    ordinal=int(entry.get("ordinal", index)),
                    criterion_type=CriterionType(str(entry["type"]).upper()),
                    summary=str(entry["summary"]).strip(),
                    source_section=str(entry["section"]).strip(),
                    source_text=str(entry["source_text"]).strip(),
                    fact_key=str(entry["fact_key"]).strip(),
                    comparator=_as_str(entry, "comparator", required=False),
                    threshold=(
                        str(entry["threshold"]).strip()
                        if entry.get("threshold") is not None
                        else None
                    ),
                    unit=_as_str(entry, "unit", required=False),
                )
            )
        except KeyError as exc:
            raise PolicyParseError(f"criteria[{index}] is missing {exc}") from exc
        except ValueError as exc:
            raise PolicyParseError(f"criteria[{index}] is invalid: {exc}") from exc
    return tuple(declarations)


def _pages(body: str) -> tuple[Page, ...]:
    raw_pages = body.split(PAGE_SEPARATOR)
    return tuple(
        Page(number=index, text=text)
        for index, text in enumerate(raw_pages, start=1)
        if text.strip()
    )


def parse_document(raw: str, source: SourceRef) -> ParsedDocument:
    """Parse one policy document. Raises rather than guessing at anything."""
    header, body = split_front_matter(raw)
    identity = _identity(header)
    pages = _pages(body)
    if not pages:
        raise PolicyParseError(f"{identity.policy_id}: document body is empty")

    sections = detect_sections(pages, identity.document_type)
    declarations = _criteria(header)

    # Verified here, at parse time, so a document with an unlocatable criterion is
    # rejected before anything downstream can treat it as ground truth.
    criteria = verify_criteria(
        declarations,
        sections,
        policy_id=identity.policy_id,
        revision_id=identity.revision_id,
    )

    return ParsedDocument(
        identity=identity,
        source=source,
        pages=pages,
        sections=sections,
        codes=_codes(header),
        criteria=criteria,
    )
