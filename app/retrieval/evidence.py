"""Evidence and citation objects - the output of Phase 1.

A citation is only worth anything if it can be checked, so these carry the fields
ADR-009 requires and mark clearly which of them a model may ever supply. The
**derived** fields - ``document_title``, ``effective_date``, ``source_url`` - are
joined from the database here and are never accepted from a model. A model cannot
fabricate a source URL because it is never asked for one; the field is not in its
schema.

``EvidenceChunk`` is what a later phase hands to an adjudicator. It carries the
verbatim text so a quote can be span-verified against it, and the provenance so the
resulting citation can be assembled without a second query.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import date

from app.core.normalize import Span, find_span, normalize_text

__all__ = ["Citation", "EvidenceChunk", "content_hash"]


def content_hash(text: str) -> str:
    """Hash of the *normalized* text.

    Normalizing first means a chunk re-ingested with different whitespace or
    typography hashes identically, while a chunk whose words changed does not - so
    the hash detects tampering rather than reformatting (threat T-06).
    """
    return hashlib.sha256(normalize_text(text).encode("utf-8")).hexdigest()


@dataclass(frozen=True, slots=True)
class EvidenceChunk:
    """One retrieved passage with everything needed to cite and verify it."""

    chunk_id: str
    policy_version_id: str
    policy_id: str
    document_type: str
    document_title: str
    revision_id: str
    section_path: str
    page_from: int
    page_to: int
    text: str
    text_sha256: str
    effective_date: date
    end_date: date | None
    source_url: str
    jurisdiction: str | None = None
    similarity: float | None = None
    rerank_score: float | None = None

    def verify_quote(self, quote: str) -> Span | None:
        """Locate ``quote`` in this chunk under normalization, or ``None``.

        The whole citation contract rests on this returning ``None`` for a quote
        whose words differ, and a real span for one that differs only in whitespace,
        case or typography.
        """
        return find_span(quote, self.text)

    def is_intact(self) -> bool:
        """Whether the stored hash still matches the text.

        A mismatch means the chunk changed after ingest. That is a poisoning signal,
        not a cache-invalidation problem.
        """
        return content_hash(self.text) == self.text_sha256

    def cite(self, quote: str) -> Citation | None:
        """Build a citation for ``quote``, or ``None`` if it does not verify."""
        span = self.verify_quote(quote)
        if span is None:
            return None
        return Citation(
            chunk_id=self.chunk_id,
            quote=span.slice(self.text),
            policy_id=self.policy_id,
            policy_version=self.revision_id,
            section_path=self.section_path,
            page=self.page_from,
            document_title=self.document_title,
            effective_date=self.effective_date,
            source_url=self.source_url,
            span_start=span.start,
            span_end=span.end,
        )


@dataclass(frozen=True, slots=True)
class Citation:
    """A verified citation. Only constructible from a quote that was found.

    Fields below the line are **derived** - joined from the corpus, never supplied
    by a model (ADR-009).
    """

    chunk_id: str
    quote: str
    policy_id: str
    policy_version: str
    section_path: str
    page: int
    # ---- derived ----
    document_title: str
    effective_date: date
    source_url: str
    # ---- provenance of the match itself ----
    span_start: int
    span_end: int
