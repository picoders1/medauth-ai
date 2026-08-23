"""Acquire the selected NCDs from the CMS Coverage API.

Reads `data/coverage/ncd_selection.yaml` - written and committed BEFORE any
download - and fetches exactly the NCDs it names. No discovery, no crawling, and no
request to a licence-gated LCD or Article endpoint.

Writes normalised documents to `data/coverage/documents/` (gitignored, per ADR-003)
and a provenance registry to `data/coverage/registry.yaml` (committed). Refusals are
recorded in the registry rather than dropped, so the corpus can say what it does not
contain and why.

    uv run python scripts/acquire_ncd.py --write
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import asdict
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import yaml

from app.coverage.ncd import (
    BASE_URL,
    NcdAcquisitionError,
    NcdDocument,
    NcdRefusal,
    NcdSource,
)
from app.policy.models import TemporalStatus

REPO = Path(__file__).resolve().parents[1]
SELECTION = REPO / "data/coverage/ncd_selection.yaml"
OUT_DIR = REPO / "data/coverage"
DOCUMENTS = OUT_DIR / "documents"
REGISTRY = OUT_DIR / "registry.yaml"

REGISTRY_HEADER = """\
# CMS NCD acquisition registry. GENERATED - do not edit by hand.
#
# Records what was fetched, when, from where, and what it hashed to. The documents
# themselves are NOT committed (ADR-003); this file is the committed record of
# their provenance.
#
# `refusals` lists documents the adapter declined and why. A refusal is evidence
# about the source, not a gap to be quietly filled.
#
# NCD records carry NO procedure-code field. Applicability comes from the curated
# linkage in data/linkage/, never from these documents, and must never be presented
# as CMS-supplied.
"""


def _serialise(document: NcdDocument) -> dict[str, Any]:
    return {
        "ncdid": document.ncdid,
        "policy_id": document.policy_id,
        "display_id": document.display_id,
        "title": document.title,
        "retirement_date_raw": document.retirement_date_raw,
        "versions": [
            {
                **{
                    k: (v.isoformat() if hasattr(v, "isoformat") else v)
                    for k, v in asdict(version).items()
                },
                "temporal_status": version.temporal_status.value,
                "window_derivation": version.window_derivation.value,
            }
            for version in document.versions
        ],
    }


def _content_only(payload: dict[str, Any]) -> str:
    """The document with acquisition timestamps removed.

    Idempotency is judged on CONTENT, not on when we last asked. Including
    `retrieved_at` would make every run rewrite every file, so a genuine change to
    a determination would be one line among many in a diff instead of the only one.
    """
    stripped = json.loads(json.dumps(payload))
    for version in stripped.get("versions", []):
        version.pop("retrieved_at", None)
    return json.dumps(stripped, indent=2, sort_keys=True)


def _write_if_changed(path: Path, payload: dict[str, Any]) -> None:
    """Write only when the determination itself changed.

    When the content matches, the file is left exactly as it was - which preserves
    the ORIGINAL `retrieved_at`. That makes the stored timestamp mean "when this
    content was first retrieved", which is the honest provenance claim; "when we
    last checked" is a property of the run, and lives in the registry's
    `generated_at`.
    """
    rendered = json.dumps(payload, indent=2, sort_keys=True) + "\n"
    if path.exists():
        existing = json.loads(path.read_text(encoding="utf-8"))
        if _content_only(existing) == _content_only(payload):
            return
    path.write_text(rendered, encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--selection", default=str(SELECTION.relative_to(REPO)))
    parser.add_argument("--out", default=str(OUT_DIR.relative_to(REPO)))
    parser.add_argument("--write", action="store_true")
    args = parser.parse_args()

    selection = yaml.safe_load((REPO / args.selection).read_text(encoding="utf-8"))
    ncdids = tuple(int(entry["ncdid"]) for entry in selection["ncds"])
    print(f"  selection        {args.selection} ({len(ncdids)} NCDs)")
    print(f"  source           {BASE_URL}\n")

    source = NcdSource()
    documents: list[NcdDocument] = []
    refusals: list[NcdRefusal] = []
    unreachable: list[dict[str, str]] = []

    for ncdid in ncdids:
        try:
            result = source.fetch_document(ncdid)
        except NcdAcquisitionError as exc:
            # Fail closed for THIS document; the run continues and records it, so a
            # partial corpus can never be mistaken for a complete one.
            unreachable.append({"ncdid": str(ncdid), "error": str(exc)})
            print(f"  UNREACHABLE  ncdid={ncdid}: {exc}")
            continue

        if isinstance(result, NcdRefusal):
            refusals.append(result)
            print(f"  REFUSED      ncdid={ncdid} {result.display_id}: {result.reason}")
            continue

        documents.append(result)
        dated = sum(1 for v in result.versions if v.temporal_status is TemporalStatus.DATED)
        undated = len(result.versions) - dated
        print(
            f"  acquired     {result.policy_id:<14} {len(result.versions)} version(s)  "
            f"{dated} dated, {undated} not"
        )

    version_count = sum(len(d.versions) for d in documents)
    dated_versions = sum(
        1 for d in documents for v in d.versions if v.temporal_status is TemporalStatus.DATED
    )

    print(f"\n  documents acquired     {len(documents)} of {len(ncdids)} selected")
    print(f"  refused                {len(refusals)}")
    print(f"  unreachable            {len(unreachable)}")
    print(f"  versions               {version_count}")
    print(f"  temporally resolvable  {dated_versions} of {version_count}")
    if version_count:
        print(
            f"  unresolvable           {version_count - dated_versions} "
            f"({(version_count - dated_versions) / version_count:.0%})"
        )

    registry = {
        "generated_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "source": BASE_URL,
        "selection_record": args.selection,
        "selected": len(ncdids),
        "acquired": len(documents),
        "refused": len(refusals),
        "unreachable": len(unreachable),
        "versions": version_count,
        "versions_temporally_resolvable": dated_versions,
        "documents": [
            {
                "ncdid": d.ncdid,
                "policy_id": d.policy_id,
                "title": d.title,
                "versions": [
                    {
                        "version": v.version,
                        "temporal_status": v.temporal_status.value,
                        "window_derivation": v.window_derivation.value,
                        "effective_date": v.effective_date.isoformat()
                        if v.effective_date
                        else None,
                        "end_date": v.end_date.isoformat() if v.end_date else None,
                        "effective_date_source": v.effective_date_source,
                        "source_url": v.source_url,
                        "retrieved_at": v.retrieved_at.isoformat() if v.retrieved_at else None,
                        "content_sha256": v.content_sha256,
                    }
                    for v in d.versions
                ],
            }
            for d in sorted(documents, key=lambda d: d.ncdid)
        ],
        "refusals": [asdict(r) for r in refusals],
        "unreachable_documents": unreachable,
        "licence_note": (
            "NCD text is a US Government work. LCD and Billing & Coding Article "
            "endpoints were NOT requested: they sit behind an AMA/ADA/AHA licence "
            "gate and no agreement was accepted (ADR-022, OD-21)."
        ),
    }

    if args.write:
        out = REPO / args.out
        (out / "documents").mkdir(parents=True, exist_ok=True)
        for document in documents:
            path = out / "documents" / f"ncd-{document.ncdid}.json"
            _write_if_changed(path, _serialise(document))
        (out / "registry.yaml").write_text(
            REGISTRY_HEADER + yaml.safe_dump(registry, sort_keys=True, width=100),
            encoding="utf-8",
        )
        print(f"\n  written to {args.out}/")
    else:
        print("\n  (dry run; pass --write)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
