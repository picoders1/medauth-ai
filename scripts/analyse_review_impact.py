"""What would change if a reviewed provision, criterion or policy changed?

gold_v1 is immutable, so a reviewer has no way to see how far a decision reaches
before making it. This answers that and modifies nothing.

    uv run python scripts/analyse_review_impact.py --scope PROVISION --subject <id>
    uv run python scripts/analyse_review_impact.py --all --write

`--all` walks every priority-1 provision and every criterion with a recorded
dependency - the decisions most likely to reach frozen data - and writes
`data/review/gold_impact.json`.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from app.review.impact import ImpactInputs, analyse_impact
from app.review.versioning import ReviewScope

REPO = Path(__file__).resolve().parents[1]
CRITERIA = REPO / "data/criteria/inventory.jsonl"
MATRIX = REPO / "data/criteria/coverage_matrix.jsonl"
DEPENDENCIES = REPO / "data/review/policy_dependencies.json"
REVIEW = REPO / "data/review/od19_review_package.jsonl"
GOLD = REPO / "data/gold/cases/gold_v1.jsonl"
SYNTHETIC = REPO / "data/synthetic/cases/cases.jsonl"
OUT = REPO / "data/review/gold_impact.json"


def _jsonl(path: Path) -> list[dict[str, Any]]:
    return [
        json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()
    ]


def _inputs() -> ImpactInputs:
    dependencies = json.loads(DEPENDENCIES.read_text(encoding="utf-8"))["dependencies"]
    return ImpactInputs(
        criteria={c["criterion_id"]: c for c in _jsonl(CRITERIA)},
        provisions={p["provision_id"]: p for p in _jsonl(MATRIX)},
        dependencies={
            criterion_id: tuple(d["provision_id"] for d in entry["depends_on"])
            for criterion_id, entry in dependencies.items()
        },
        gold_cases=tuple(_jsonl(GOLD)),
        synthetic_cases=tuple(_jsonl(SYNTHETIC)),
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--scope", choices=[s.value for s in ReviewScope])
    parser.add_argument("--subject")
    parser.add_argument("--all", action="store_true")
    parser.add_argument("--write", action="store_true")
    args = parser.parse_args()

    inputs = _inputs()

    if args.scope and args.subject:
        impact = analyse_impact(ReviewScope(args.scope), args.subject, inputs)
        print(f"  {args.scope}  {args.subject}\n")
        print(f"    criteria affected        {len(impact.criteria)}")
        print(f"    policy versions          {', '.join(impact.policy_versions) or '-'}")
        print(f"    GOLD cases affected      {len(impact.gold_cases)}")
        print(f"    synthetic cases affected {len(impact.synthetic_cases)}")
        print(f"    forces a gold_v2         {impact.touches_frozen_data}")
        for note in impact.notes:
            print(f"    note: {note}")
        return 0

    if not args.all:
        parser.error("supply --scope and --subject, or --all")

    subjects: list[tuple[ReviewScope, str]] = [
        (ReviewScope.PROVISION, row["provision_id"])
        for row in _jsonl(REVIEW)
        if row["priority"] == 1
    ]
    subjects += [
        (ReviewScope.CRITERION, criterion_id) for criterion_id in sorted(inputs.dependencies)
    ]

    entries = []
    for scope, subject in subjects:
        impact = analyse_impact(scope, subject, inputs)
        entries.append(
            {
                "scope": scope.value,
                "subject_id": subject,
                "criteria_affected": list(impact.criteria),
                "policy_versions": list(impact.policy_versions),
                "gold_cases_affected": list(impact.gold_cases),
                "synthetic_cases_affected": list(impact.synthetic_cases),
                "evaluation_reports_affected": list(impact.evaluation_reports),
                "forces_gold_v2": impact.touches_frozen_data,
                "notes": list(impact.notes),
            }
        )

    report = {
        "analysed": len(entries),
        "subjects_touching_gold": sum(1 for e in entries if e["forces_gold_v2"]),
        "gold_cases_reachable": len({case for e in entries for case in e["gold_cases_affected"]}),
        "gold_cases_total": len(inputs.gold_cases),
        "entries": entries,
        "note": (
            "Impact is a projection, not an instruction. gold_v1 is immutable and "
            "nothing here modifies it. A subject that reaches gold cases would force a "
            "gold_v2 with a recorded reason - a decision of its own, made deliberately, "
            "not a consequence discovered afterwards."
        ),
    }

    print(f"  subjects analysed              {len(entries)}")
    print(f"  subjects that would reach gold {report['subjects_touching_gold']}")
    print(
        f"  gold cases reachable in total  {report['gold_cases_reachable']} "
        f"of {report['gold_cases_total']}"
    )
    for entry in entries:
        if entry["forces_gold_v2"]:
            print(
                f"    {entry['scope']:<10} {entry['subject_id'][:52]:<52} "
                f"{len(entry['gold_cases_affected']):3d} gold case(s)"
            )

    if args.write:
        OUT.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        print(f"\n  written to {OUT.relative_to(REPO)}")
    else:
        print("\n  (dry run; pass --write)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
