"""Document validation - reject loudly rather than ingest something unusable.

Every check here is a failure that would otherwise surface much later as a
retrieval or citation problem, where it is far harder to attribute. A truncated
document produces a section that ends mid-sentence and a citation that reads as
complete; a document with no covered procedure can never be resolved and silently
becomes a policy that exists but never applies.
"""

from __future__ import annotations

from dataclasses import dataclass

from app.core.errors import MedauthError
from app.policy.documents import ParsedDocument
from app.policy.models import DocumentType, LinkType

__all__ = ["DocumentValidationError", "ValidationReport", "validate_document"]

#: Below this, a "document" is a fragment or a fetch that returned an error page.
MIN_BODY_CHARACTERS = 400


class DocumentValidationError(MedauthError):
    """The document is not fit to ingest."""


@dataclass(frozen=True, slots=True)
class ValidationReport:
    errors: tuple[str, ...] = ()
    warnings: tuple[str, ...] = ()

    @property
    def ok(self) -> bool:
        return not self.errors


def validate_document(document: ParsedDocument, *, strict: bool = True) -> ValidationReport:
    """Check a parsed document. Raises on error when ``strict``."""
    errors: list[str] = []
    warnings: list[str] = []
    identity = document.identity

    body_length = sum(len(p.text) for p in document.pages)
    if body_length < MIN_BODY_CHARACTERS:
        errors.append(
            f"body is {body_length} characters, below the {MIN_BODY_CHARACTERS} minimum - "
            "likely truncated, or an error page saved as a document"
        )

    if not document.sections:
        errors.append("no non-empty sections were detected")

    unrecognised = [s.path for s in document.sections if not s.recognised]
    if unrecognised:
        warnings.append(
            f"{len(unrecognised)} local section heading(s) kept as subsections: "
            f"{', '.join(unrecognised[:5])}"
        )

    # A policy with no covered procedure can never be resolved. It would sit in the
    # corpus looking ingested while being unreachable by any request.
    covered = [c for c in document.codes if c.link_type is LinkType.COVERED_PROCEDURE]
    if not covered:
        if identity.document_type is DocumentType.ARTICLE:
            warnings.append(
                "article declares no covered procedure; it can only be reached through "
                "the LCD it accompanies"
            )
        elif identity.document_type is DocumentType.REGULATION:
            # A regulation states conditions of payment; it does not enumerate
            # procedure codes the way a determination does. Code linkage for a
            # regulation is curated separately and labelled as curated, so its
            # absence here is correct rather than a defect.
            warnings.append(
                "regulation declares no covered procedure; applicability comes from the "
                "curated linkage in data/linkage/, not from the document"
            )
        else:
            errors.append(
                f"{identity.document_type.value} declares no COVERED_PROCEDURE code, so no "
                "request could ever resolve to it"
            )

    duplicates = len(document.codes) - len(
        {(c.code, c.code_system, c.link_type) for c in document.codes}
    )
    if duplicates:
        errors.append(f"{duplicates} duplicate code link(s); applicability would double-count")

    last_page = document.pages[-1].text.rstrip() if document.pages else ""
    if last_page and not last_page.endswith((".", ")", ":", "]", "%")):
        warnings.append("document does not end at a sentence boundary - possibly truncated")

    report = ValidationReport(errors=tuple(errors), warnings=tuple(warnings))
    if strict and not report.ok:
        raise DocumentValidationError(
            f"{identity.policy_id} rev {identity.revision_id} failed validation:\n  - "
            + "\n  - ".join(report.errors)
        )
    return report
