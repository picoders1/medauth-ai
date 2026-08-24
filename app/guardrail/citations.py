"""Span verification: the check that makes a citation evidence rather than a claim.

A model that cites is not thereby grounded. The citation has to be checkable, and
checking it is the only step in this system that can distinguish "the policy says
this" from "a model produced a sentence shaped like a policy saying this".

Four things must all hold, and any failure stops the case (R-10):

1. `normalize(quote)` is a substring of `normalize(chunk.text)`
2. the chunk was in **that criterion's** evidence set - not merely in the corpus
3. the chunk's stored hash still matches its text
4. the chunk belongs to the resolved policy identity and version

Derived metadata - `source_url`, `document_title`, `effective_date` - is joined from
the chunk, never accepted from the model (ADR-009). A model that never supplies
provenance cannot assert provenance it lacks.

**When strict matching produces too many refusals, fix normalization or the prompt.
Never the contract.**
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from app.core.identity import PolicyIdentity
from app.retrieval.evidence import Citation, EvidenceChunk

__all__ = [
    "CitationFailure",
    "CitationReport",
    "validate_citations",
]


class CitationFailure(StrEnum):
    """Why one claimed citation was refused. Each is a distinct diagnosis.

    Kept apart rather than collapsed into "invalid": a quote that does not appear
    is a model problem, a chunk outside the evidence set is a retrieval or prompt
    problem, and a hash mismatch is a corpus-integrity problem. One label for all
    three would send every one of them to the same, wrong, fix.
    """

    QUOTE_NOT_FOUND = "QUOTE_NOT_FOUND"
    CHUNK_NOT_IN_EVIDENCE_SET = "CHUNK_NOT_IN_EVIDENCE_SET"
    CHUNK_TAMPERED = "CHUNK_TAMPERED"
    WRONG_POLICY = "WRONG_POLICY"
    WRONG_VERSION = "WRONG_VERSION"


@dataclass(frozen=True, slots=True)
class CitationReport:
    """Every claimed citation, sorted into verified and refused."""

    verified: tuple[Citation, ...] = ()
    failures: tuple[tuple[str, str, CitationFailure], ...] = ()

    @property
    def passed(self) -> bool:
        """Whether every claimed citation verified. One failure stops the case."""
        return not self.failures

    @property
    def failure_reasons(self) -> tuple[CitationFailure, ...]:
        return tuple(dict.fromkeys(reason for _, _, reason in self.failures))


def validate_citations(
    claims: tuple[tuple[str, str], ...],
    *,
    evidence_set: tuple[EvidenceChunk, ...],
    identity: PolicyIdentity,
) -> CitationReport:
    """Verify each `(chunk_id, quote)` claim against the criterion's own evidence.

    `evidence_set` is this criterion's set, not the corpus. Passing the whole corpus
    would make check 2 vacuous, and check 2 is what stops a model citing a genuine
    passage that was never retrieved for the question being asked - the failure that
    every grounding metric passes, because the citation is real.
    """
    by_id = {chunk.chunk_id: chunk for chunk in evidence_set}
    verified: list[Citation] = []
    failures: list[tuple[str, str, CitationFailure]] = []

    for chunk_id, quote in claims:
        chunk = by_id.get(chunk_id)
        if chunk is None:
            failures.append((chunk_id, quote, CitationFailure.CHUNK_NOT_IN_EVIDENCE_SET))
            continue
        if not chunk.is_intact():
            # Checked before the quote: a tampered chunk can be made to contain any
            # quote at all, so verifying against it would confirm whatever the
            # tamperer chose.
            failures.append((chunk_id, quote, CitationFailure.CHUNK_TAMPERED))
            continue
        if chunk.policy_id != identity.policy_id:
            failures.append((chunk_id, quote, CitationFailure.WRONG_POLICY))
            continue
        if chunk.revision_id != identity.version:
            failures.append((chunk_id, quote, CitationFailure.WRONG_VERSION))
            continue

        citation = chunk.cite(quote)
        if citation is None:
            failures.append((chunk_id, quote, CitationFailure.QUOTE_NOT_FOUND))
            continue
        verified.append(citation)

    return CitationReport(verified=tuple(verified), failures=tuple(failures))
