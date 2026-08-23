"""Which criteria depend on provisions nobody has reviewed.

A criterion that invokes a rule it does not contain cannot be adjudicated on its
own evidence. 42 CFR 410.32 C03 is the case: it says "the appropriate level of
supervision" and the levels are set out in paragraph (b)(3), which is not
transcribed. Adjudicating C03 against an evidence set that cannot contain (b)(3)
asks the model a question the evidence cannot answer, and any confident verdict it
returns is unfounded (R-51).

This makes that structural rather than anecdotal: every such criterion is listed,
with the unresolved provisions it depends on and their review status, so a
criterion with an open dependency can never be presented as independently
sufficient.

**Dependencies are not detected.** They are read from `KNOWN_DEPENDENCIES` in
`scripts/build_review_package.py`, each established by individual inspection. A
regex over criterion text found none at all - C03 never writes the words "paragraph
(b)(3)" - and a looser one produced 65 false positives.

Writes `data/review/policy_dependencies.json`.

    uv run python scripts/build_dependency_report.py --write
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import defaultdict
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "scripts"))

from build_review_package import (  # noqa: E402
    DEPENDENCY_RESOLUTION,
    KNOWN_DEPENDENCIES,
)

CRITERIA = REPO / "data/criteria/inventory.jsonl"
MATRIX = REPO / "data/criteria/coverage_matrix.jsonl"
REVIEW = REPO / "data/review/od19_review_package.jsonl"
OUT = REPO / "data/review/policy_dependencies.json"


def _jsonl(path: Path) -> list[dict[str, Any]]:
    return [
        json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()
    ]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--write", action="store_true")
    args = parser.parse_args()

    criteria = {c["criterion_id"]: c for c in _jsonl(CRITERIA)}
    provisions = {p["provision_id"]: p for p in _jsonl(MATRIX)}
    review = {r["provision_id"]: r for r in _jsonl(REVIEW)}

    # criterion -> the provisions it cannot be evaluated without
    edges: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for (policy_id, paragraph_path), criterion_ids in KNOWN_DEPENDENCIES.items():
        matching = [
            p
            for p in provisions.values()
            if p["policy_id"] == policy_id and p["paragraph_path"] == paragraph_path
        ]
        if not matching:
            raise SystemExit(
                f"KNOWN_DEPENDENCIES names {policy_id} {paragraph_path}, which is not "
                "in the coverage matrix. A dependency on a provision that does not "
                "exist is a stale record, not a missing one."
            )
        for provision in matching:
            row = review.get(provision["provision_id"])
            for criterion_id in criterion_ids:
                if criterion_id not in criteria:
                    continue
                resolution, basis = DEPENDENCY_RESOLUTION.get(
                    (policy_id, paragraph_path), ("UNRESOLVED", "")
                )
                edges[criterion_id].append(
                    {
                        "resolution": resolution,
                        "resolution_basis": basis,
                        "provision_id": provision["provision_id"],
                        "policy_id": provision["policy_id"],
                        "policy_version": provision["policy_version"],
                        "paragraph_path": provision["paragraph_path"],
                        "classification": provision["classification"],
                        "review_status": row["review_status"] if row else "NOT_IN_REVIEW_QUEUE",
                        "authoritative_text": provision["text"][:400],
                    }
                )

    # A dependency is closed only when a REVIEWER has closed it. Transcribing the
    # provision moves it from UNRESOLVED to source-verified and no further:
    # treating transcription as permission would let engineering close a review
    # question by doing engineering work.
    blocked = {
        criterion_id: deps
        for criterion_id, deps in edges.items()
        if any(d["resolution"] != "RESOLVED" for d in deps)
    }

    report = {
        "criteria_total": len(criteria),
        "criteria_with_dependencies": len(edges),
        "criteria_blocked_by_unresolved_dependencies": len(blocked),
        "by_resolution": {
            state: sorted(
                {
                    criterion_id
                    for criterion_id, deps in edges.items()
                    if any(d["resolution"] == state for d in deps)
                }
            )
            for state in sorted({d["resolution"] for deps in edges.values() for d in deps})
        },
        "dependencies": {
            criterion_id: {
                "criterion": {
                    "policy_id": criteria[criterion_id]["policy_id"],
                    "policy_version": criteria[criterion_id]["policy_version"],
                    "summary": criteria[criterion_id]["summary"],
                    "criterion_type": criteria[criterion_id]["criterion_type"],
                },
                "independently_adjudicable": criterion_id not in blocked,
                "depends_on": sorted(deps, key=lambda d: d["provision_id"]),
            }
            for criterion_id, deps in sorted(edges.items())
        },
        "note": (
            "A criterion listed here with `independently_adjudicable: false` "
            "references a rule it does not contain. Its evidence set cannot include "
            "that rule, so a verdict on it is unfounded however confident the model "
            "is (R-51). Dependencies are established by inspection, never detected: "
            "a regex over criterion text finds none, because the criteria do not "
            "cite paragraph numbers."
        ),
    }

    print(f"  criteria                              {len(criteria)}")
    print(f"  with a recorded dependency            {len(edges)}")
    print(f"  blocked by an unresolved dependency   {len(blocked)}")
    for criterion_id, deps in sorted(blocked.items()):
        paths = ", ".join(sorted({d["paragraph_path"] for d in deps}))
        print(f"    {criterion_id}  depends on {paths}")

    if args.write:
        OUT.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        print(f"\n  written to {OUT.relative_to(REPO)}")
    else:
        print("\n  (dry run; pass --write)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
