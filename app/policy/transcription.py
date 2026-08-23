"""Curated criterion transcriptions, kept apart from the documents they describe.

A regulation is acquired verbatim and never edited. Its criteria are transcribed
**by a human**, into a separate versioned file, and verified against the acquired
text at load time. Two properties follow from that separation:

* Re-acquiring a document cannot silently overwrite a transcription, and a
  transcription cannot silently alter a document.
* The transcription is an artefact with its own provenance - who curated it, when,
  and against which revision - which is what makes "manually verified against
  authoritative text" a checkable statement rather than a claim.

Verification **fails the pipeline**. It never repairs a span, re-anchors a
criterion to a different section, or accepts the nearest match. A transcription
that no longer locates in its stated section means either the document changed or
the transcription was wrong, and both need a person, not a fallback.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any

import yaml

from app.core.errors import MedauthError
from app.policy.criteria import (
    CriterionDeclaration,
    CriterionProvenanceError,
    CriterionType,
    SectionLike,
    VerifiedCriterion,
    verify_criteria,
)

__all__ = [
    "Transcription",
    "TranscriptionError",
    "load_transcription",
    "load_transcriptions",
    "verify_transcription",
]

SCHEMA_VERSION = "1"


class TranscriptionError(MedauthError):
    """A transcription file is malformed or does not match its document."""


@dataclass(frozen=True, slots=True)
class Transcription:
    """One curated criterion set for one policy revision."""

    policy_id: str
    revision_id: str
    source_url: str
    curator: str
    curator_role: str
    curated_at: date
    declarations: tuple[CriterionDeclaration, ...]
    #: PRIMARY establishes coverage subject to its criteria. EXCLUSION_OVERLAY only
    #: removes coverage and declares no required criteria, so it cannot support a
    #: standalone decision - the decision table would reach its totality guard.
    policy_role: str = "PRIMARY"
    notes: str = ""

    @property
    def key(self) -> tuple[str, str]:
        return (self.policy_id, self.revision_id)


#: Exactly the keys a criterion entry may carry. An unknown key is REFUSED rather
#: than ignored: a typo in `normalized_interpretation` silently emptied a field
#: that a reviewer had written by hand, and nothing downstream could tell that
#: from a criterion whose interpretation was deliberately left blank.
DECLARATION_KEYS = frozenset(
    {
        "ordinal",
        "criterion_type",
        "summary",
        "source_section",
        "authoritative_text",
        "fact_key",
        "comparator",
        "threshold",
        "unit",
        "normalized_interpretation",
        "applicability",
    }
)


def _declaration(entry: dict[str, Any], index: int, where: str) -> CriterionDeclaration:
    unknown = sorted(set(entry) - DECLARATION_KEYS)
    if unknown:
        raise TranscriptionError(
            f"{where}: criterion {entry.get('ordinal', index)} carries unknown key(s) "
            f"{unknown}. A misspelled key is silently dropped, so a hand-written "
            "interpretation or an applicability note would vanish without trace."
        )
    try:
        return CriterionDeclaration(
            ordinal=int(entry.get("ordinal", index)),
            criterion_type=CriterionType(str(entry["criterion_type"]).upper()),
            summary=str(entry.get("summary", "")).strip(),
            source_section=str(entry["source_section"]).strip(),
            # Verbatim from the regulation. This is what gets span-verified and
            # what a citation quotes.
            source_text=str(entry["authoritative_text"]).strip(),
            fact_key=str(entry["fact_key"]).strip(),
            comparator=(str(entry["comparator"]) if entry.get("comparator") else None),
            threshold=(str(entry["threshold"]) if entry.get("threshold") is not None else None),
            unit=(str(entry["unit"]) if entry.get("unit") else None),
            normalized_interpretation=str(entry.get("normalized_interpretation", "")).strip(),
            applicability=str(entry.get("applicability", "")).strip(),
        )
    except KeyError as exc:
        raise TranscriptionError(f"{where} criterion {index}: missing {exc}") from exc
    except ValueError as exc:
        raise TranscriptionError(f"{where} criterion {index}: {exc}") from exc


def load_transcription(path: Path | str) -> Transcription:
    file = Path(path)
    try:
        raw = yaml.safe_load(file.read_text(encoding="utf-8"))
    except yaml.YAMLError as exc:
        raise TranscriptionError(f"{file} is not valid YAML: {exc}") from exc
    if not isinstance(raw, dict):
        raise TranscriptionError(f"{file} must be a mapping")

    if str(raw.get("schema_version")) != SCHEMA_VERSION:
        raise TranscriptionError(
            f"{file}: schema_version {raw.get('schema_version')!r} != {SCHEMA_VERSION!r}"
        )

    entries = raw.get("criteria") or []
    if not isinstance(entries, list) or not entries:
        raise TranscriptionError(f"{file}: declares no criteria")

    curated_at = raw.get("curated_at")
    return Transcription(
        policy_id=str(raw["policy_id"]),
        revision_id=str(raw["revision_id"]),
        source_url=str(raw.get("source_url", "")),
        curator=str(raw.get("curator", "")),
        curator_role=str(raw.get("curator_role", "")),
        curated_at=curated_at
        if isinstance(curated_at, date)
        else date.fromisoformat(str(curated_at)),
        declarations=tuple(
            _declaration(entry, index, file.name) for index, entry in enumerate(entries, start=1)
        ),
        policy_role=str(raw.get("policy_role", "PRIMARY")).upper(),
        notes=str(raw.get("notes", "")).strip(),
    )


def load_transcriptions(directory: Path | str) -> dict[tuple[str, str], Transcription]:
    """Load every transcription, keyed by (policy_id, revision_id)."""
    folder = Path(directory)
    if not folder.is_dir():
        return {}
    loaded: dict[tuple[str, str], Transcription] = {}
    for path in sorted(folder.glob("*.yaml")):
        transcription = load_transcription(path)
        if transcription.key in loaded:
            raise TranscriptionError(
                f"{path.name}: a transcription for {transcription.key} already exists. "
                "Two curated criterion sets for one revision would make provenance "
                "ambiguous."
            )
        loaded[transcription.key] = transcription
    return loaded


def verify_transcription(
    transcription: Transcription,
    sections: tuple[SectionLike, ...],
    *,
    document_policy_id: str,
    document_revision_id: str,
) -> tuple[VerifiedCriterion, ...]:
    """Verify a transcription against the document it claims to describe.

    Raises:
        TranscriptionError: the transcription names a different policy or revision.
        CriterionProvenanceError: a criterion's authoritative text is not present in
            the section it cites.
    """
    if transcription.policy_id != document_policy_id:
        raise TranscriptionError(
            f"transcription is for {transcription.policy_id!r} but was verified against "
            f"{document_policy_id!r}"
        )
    if transcription.revision_id != document_revision_id:
        raise TranscriptionError(
            f"{transcription.policy_id}: transcription targets revision "
            f"{transcription.revision_id!r}, document is {document_revision_id!r}. "
            "A criterion transcribed against one revision must be re-verified against "
            "another - the text may have been amended."
        )

    try:
        return verify_criteria(
            transcription.declarations,
            sections,
            policy_id=document_policy_id,
            revision_id=document_revision_id,
        )
    except CriterionProvenanceError as exc:
        raise CriterionProvenanceError(
            f"{transcription.policy_id} rev {transcription.revision_id} "
            f"(curated {transcription.curated_at} by {transcription.curator or 'unknown'}): {exc}"
        ) from exc
