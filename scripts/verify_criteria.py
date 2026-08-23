"""Verify every curated criterion against the authoritative document it cites.

    uv run python scripts/verify_criteria.py

**This is a pipeline gate.** Any failure exits non-zero and writes nothing. It does
not repair a span, re-anchor a criterion to a nearer section, or accept a close
match - a transcription that no longer locates means either the regulation was
amended or the transcription is wrong, and both need a person.

On success it writes the criteria inventory: every criterion with its policy,
revision, section, page, character span and covering chunk ids.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

from app.core.errors import MedauthError
from app.policy.acquire import LocalDirectorySource
from app.policy.chunk import chunk_sections
from app.policy.criteria import CriterionProvenanceError
from app.policy.parse import parse_document
from app.policy.transcription import load_transcriptions, verify_transcription

REPO = Path(__file__).resolve().parents[1]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--corpus", default="data/cms")
    parser.add_argument("--transcriptions", default="data/criteria/transcriptions")
    parser.add_argument("--out", default="data/criteria/inventory.jsonl")
    parser.add_argument("--report", default="data/criteria/verification.json")
    args = parser.parse_args()

    transcriptions = load_transcriptions(REPO / args.transcriptions)
    if not transcriptions:
        print("no transcriptions found", file=sys.stderr)
        return 1

    documents = list(LocalDirectorySource(REPO / args.corpus).documents())
    parsed_by_key: dict[tuple[str, str], Any] = {}
    for acquired in documents:
        try:
            parsed = parse_document(acquired.raw, acquired.source)
        except MedauthError as exc:
            print(f"  UNPARSEABLE  {Path(acquired.source.uri).name}: {exc}", file=sys.stderr)
            return 1
        parsed_by_key[(parsed.identity.policy_id, parsed.identity.revision_id)] = (parsed, acquired)

    inventory: list[dict[str, Any]] = []
    failures: list[str] = []
    verified_count = 0

    print(
        f"  verifying {len(transcriptions)} transcription(s) against {len(documents)} document(s)\n"
    )

    for key, transcription in sorted(transcriptions.items()):
        policy_id, revision_id = key
        entry = parsed_by_key.get(key)
        if entry is None:
            failures.append(
                f"{policy_id} rev {revision_id}: no acquired document. A transcription "
                f"cannot be verified against a document that is not present."
            )
            print(f"  FAIL  {policy_id:<18} rev {revision_id}  no matching document")
            continue

        parsed, acquired = entry
        try:
            criteria = verify_transcription(
                transcription,
                parsed.sections,
                document_policy_id=policy_id,
                document_revision_id=revision_id,
            )
        except (CriterionProvenanceError, MedauthError) as exc:
            failures.append(str(exc))
            print(f"  FAIL  {policy_id:<18} rev {revision_id}  {str(exc)[:80]}")
            continue

        chunks = chunk_sections(parsed.sections)
        for criterion in criteria:
            covering = [
                f"{policy_id}:{revision_id}:{chunk.ordinal}"
                for chunk in chunks
                if chunk.section_path == criterion.source_section
            ]
            if not covering:
                failures.append(
                    f"{criterion.id}: section {criterion.source_section!r} produced no "
                    f"chunk, so the criterion's evidence would be unretrievable"
                )
                continue
            inventory.append(
                {
                    "criterion_id": criterion.id,
                    "policy_id": criterion.policy_id,
                    "policy_version": criterion.revision_id,
                    "ordinal": criterion.ordinal,
                    "criterion_type": criterion.criterion_type.value,
                    "fact_key": criterion.fact_key,
                    "summary": criterion.summary,
                    "authoritative_text": criterion.source_text,
                    "normalized_interpretation": criterion.normalized_interpretation,
                    "applicability": criterion.applicability,
                    "source_section": criterion.source_section,
                    "source_page": criterion.source_page,
                    "source_span": [criterion.span_start, criterion.span_end],
                    "source_chunk_refs": covering,
                    "comparator": criterion.comparator,
                    "threshold": criterion.threshold,
                    "unit": criterion.unit,
                    "source_url": transcription.source_url,
                    "source_authority": "Office of the Federal Register",
                    "document_sha256": acquired.source.sha256,
                    "curator": transcription.curator,
                    "curator_role": "non-clinician engineering transcription",
                    "curated_at": transcription.curated_at.isoformat(),
                    "provenance": "authoritative-source; human-transcribed; span-verified",
                }
            )
        verified_count += len(criteria)
        print(f"  OK    {policy_id:<18} rev {revision_id}  {len(criteria)} criteria verified")

    ids = [row["criterion_id"] for row in inventory]
    duplicates = {i for i in ids if ids.count(i) > 1}
    if duplicates:
        failures.append(f"duplicate criterion ids: {sorted(duplicates)}")

    report = {
        "verified_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "corpus": args.corpus,
        "transcriptions": len(transcriptions),
        "documents": len(documents),
        "criteria_verified": verified_count,
        "criteria_written": len(inventory),
        "failures": failures,
        "passed": not failures,
    }

    if failures:
        print(f"\n  VERIFICATION FAILED - {len(failures)} problem(s):", file=sys.stderr)
        for failure in failures:
            print(f"    - {failure}", file=sys.stderr)
        print("\n  Nothing was written. Spans are never auto-repaired.", file=sys.stderr)
        (REPO / args.report).write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
        return 1

    out = REPO / args.out
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(
        "\n".join(json.dumps(row, sort_keys=True) for row in inventory) + "\n", encoding="utf-8"
    )
    report["inventory_sha256"] = hashlib.sha256(out.read_bytes()).hexdigest()
    (REPO / args.report).write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")

    print(f"\n  {len(inventory)} criteria verified and written to {args.out}")
    print(f"  inventory sha256 {report['inventory_sha256'][:16]}")
    print(f"  as of {date.today().isoformat()}: 0 failures")
    return 0


if __name__ == "__main__":
    sys.exit(main())
