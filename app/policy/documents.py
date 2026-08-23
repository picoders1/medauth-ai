"""Parsed-document value objects, shared by parsing, structuring and chunking."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date

from app.core.types import CodeSystem
from app.policy.criteria import VerifiedCriterion
from app.policy.models import DocumentType, LinkType, PolicyScope

__all__ = ["CodeRef", "DocumentIdentity", "Page", "ParsedDocument", "Section", "SourceRef"]


@dataclass(frozen=True, slots=True)
class SourceRef:
    """Where a document came from, and whether it is real.

    ``synthetic`` is carried all the way into ``registry.yaml`` and into every report
    derived from the corpus, so a measurement taken on constructed policy text can
    never be presented as a measurement on real CMS prose.
    """

    uri: str
    retrieved_at: date
    sha256: str
    licence_note: str = ""
    synthetic: bool = False
    adapter: str = "local"


@dataclass(frozen=True, slots=True)
class DocumentIdentity:
    """Canonical policy identity.

    Derived from the document's own declared metadata, never from its filename. A
    filename is an artefact of how a file was saved and carries no authority; two
    revisions of one policy would be indistinguishable if identity came from it.
    """

    policy_id: str
    document_type: DocumentType
    title: str
    revision_id: str
    scope: PolicyScope
    effective_date: date
    source_url: str
    jurisdiction: str | None = None
    end_date: date | None = None
    revision_date: date | None = None
    contractor: str | None = None
    source_authority: str = "CMS"

    def __post_init__(self) -> None:
        if self.end_date is not None and self.end_date < self.effective_date:
            raise ValueError(
                f"{self.policy_id} rev {self.revision_id}: end_date {self.end_date} "
                f"precedes effective_date {self.effective_date}"
            )
        if self.scope is PolicyScope.JURISDICTIONAL and not self.jurisdiction:
            raise ValueError(
                f"{self.policy_id} rev {self.revision_id}: jurisdictional scope needs a "
                "jurisdiction, otherwise applicability is undecidable"
            )

    @property
    def natural_key(self) -> tuple[str, str, str]:
        """What makes this version distinguishable from another of the same policy."""
        return (self.policy_id, self.document_type.value, self.revision_id)


@dataclass(frozen=True, slots=True)
class CodeRef:
    """A code the document links to, and why."""

    code: str
    code_system: CodeSystem
    link_type: LinkType


@dataclass(frozen=True, slots=True)
class Page:
    number: int
    text: str


@dataclass(frozen=True, slots=True)
class Section:
    """A named region of the document. The unit of meaning, and of chunking."""

    path: str
    text: str
    page_from: int
    page_to: int
    recognised: bool = True

    @property
    def is_empty(self) -> bool:
        return not self.text.strip()


@dataclass(frozen=True, slots=True)
class ParsedDocument:
    identity: DocumentIdentity
    source: SourceRef
    pages: tuple[Page, ...]
    sections: tuple[Section, ...]
    codes: tuple[CodeRef, ...] = field(default_factory=tuple)
    #: Declared by the document and span-verified against it. Never inferred.
    criteria: tuple[VerifiedCriterion, ...] = field(default_factory=tuple)

    @property
    def content_sha256(self) -> str:
        return self.source.sha256

    @property
    def covered_procedures(self) -> tuple[str, ...]:
        return tuple(c.code for c in self.codes if c.link_type is LinkType.COVERED_PROCEDURE)
