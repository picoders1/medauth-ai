"""Which policy versions production can adjudicate, and what that costs the datasets.

Phase 5 made unverified policy semantics fail closed. That is a safety improvement
and it is also a coverage loss, and the loss must be a measured number rather than a
sentence in a document that can drift from the data.

Reads the policy logic inventory and every case corpus, and reports per policy
version whether production can adjudicate it, plus how many gold and synthetic cases
sit on versions it cannot.

Writes `data/policy_logic/production_coverage.json`. A test asserts the counts
against the datasets, so the documentation cannot drift from what is true.

    uv run python scripts/report_adjudicability.py --write
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from pathlib import Path
from typing import Any

from app.core.types import CriterionKind, Verdict
from app.decision.table import CriterionOutcome
from app.policy.logic_loader import load_semantics_source, semantics_for

REPO = Path(__file__).resolve().parents[1]
INVENTORY = REPO / "data/policy_logic/inventory.json"
LOGIC_DIR = REPO / "data/policy_logic"
CRITERIA = REPO / "data/criteria/inventory.jsonl"
DEPENDENCIES = REPO / "data/review/policy_dependencies.json"
OUT = LOGIC_DIR / "production_coverage.json"

CORPORA = {
    "gold_v1": REPO / "data/gold/cases/gold_v1.jsonl",
    "synthetic": REPO / "data/synthetic/cases/cases.jsonl",
}


def _jsonl(path: Path) -> list[dict[str, Any]]:
    return [
        json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()
    ]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--write", action="store_true")
    args = parser.parse_args()

    known = frozenset(c["criterion_id"] for c in _jsonl(CRITERIA))
    source = load_semantics_source(INVENTORY, LOGIC_DIR, known_criteria=known)

    # One placeholder criterion: `semantics_for` needs criteria only to build an
    # assumed conjunction, and adjudicability does not depend on which criteria a
    # particular case carries.
    placeholder = (
        CriterionOutcome("placeholder", CriterionKind.REQUIRED, Verdict.SATISFIED, True),
    )

    # Semantics is necessary and not sufficient. A policy whose logic is DECLARED
    # can still contain a criterion that invokes a rule it lacks, and a verdict on
    # that criterion is unfounded however sound the policy's shape is (R-51).
    # Reporting semantics alone let 42 CFR 410.32 read as adjudicable while 23 gold
    # cases referencing C03 would have produced exactly such a verdict.
    dependency_report = json.loads(DEPENDENCIES.read_text(encoding="utf-8"))["dependencies"]
    blocked_criteria = {
        criterion_id
        for criterion_id, entry in dependency_report.items()
        if not entry["independently_adjudicable"]
    }
    criteria_by_version: dict[tuple[str, str], set[str]] = {}
    for criterion in _jsonl(CRITERIA):
        criteria_by_version.setdefault(
            (criterion["policy_id"], criterion["policy_version"]), set()
        ).add(criterion["criterion_id"])

    versions: list[dict[str, Any]] = []
    adjudicable: set[tuple[str, str]] = set()
    for key in sorted(source.inventory):
        policy_id, policy_version = key
        semantics = semantics_for(
            source, policy_id=policy_id, policy_version=policy_version, criteria=placeholder
        )
        blocked_here = sorted(criteria_by_version.get(key, set()) & blocked_criteria)
        fully_adjudicable = semantics.is_executable and not blocked_here
        if fully_adjudicable:
            adjudicable.add(key)
        versions.append(
            {
                "policy_id": policy_id,
                "policy_version": policy_version,
                "inventory_form": source.inventory[key],
                "semantics_status": semantics.status.value,
                "semantics_executable": semantics.is_executable,
                "dependency_blocked_criteria": blocked_here,
                "adjudicable_in_production": fully_adjudicable,
                "reason": [
                    *semantics.notes,
                    *(
                        [
                            f"{len(blocked_here)} criterion/criteria invoke a provision "
                            "that is not transcribed, so a verdict on them would be "
                            f"unfounded (R-51): {', '.join(blocked_here)}"
                        ]
                        if blocked_here
                        else []
                    ),
                ],
            }
        )

    corpora: dict[str, Any] = {}
    for name, path in CORPORA.items():
        cases = _jsonl(path)
        by_status: Counter[str] = Counter()
        blocked_versions: Counter[str] = Counter()
        for case in cases:
            expected = case["expected"]
            key = (expected["policy_id"], expected["policy_revision"])
            ok = key in adjudicable
            by_status["adjudicable" if ok else "blocked"] += 1
            if not ok:
                blocked_versions[f"{key[0]} {key[1]}"] += 1
        corpora[name] = {
            "cases": len(cases),
            "adjudicable_in_production": by_status["adjudicable"],
            "blocked_by_policy_semantics": by_status["blocked"],
            "blocked_by_version": dict(sorted(blocked_versions.items())),
        }

    report = {
        "inventory": str(INVENTORY.relative_to(REPO)),
        "inventory_sha256": source.inventory_digest,
        "versions": versions,
        "versions_total": len(versions),
        "versions_adjudicable": len(adjudicable),
        "versions_semantics_executable": sum(1 for v in versions if v["semantics_executable"]),
        "versions_blocked_by_dependency": sum(
            1 for v in versions if v["semantics_executable"] and v["dependency_blocked_criteria"]
        ),
        "corpora": corpora,
        "note": (
            "Adjudicability is semantics AND dependencies. A policy whose logic is "
            "DECLARED but which contains a criterion invoking an untranscribed "
            "provision is NOT adjudicable: the verdict on that criterion would be "
            "unfounded (R-51). Reporting semantics alone let 42 CFR 410.32 read as "
            "adjudicable while 23 gold cases referencing C03 would have produced "
            "exactly such a verdict. "
            "Blocked cases are NOT invalid. Their labels remain correct records of "
            "what the system decided under the semantics they were built with. What "
            "changed is that production no longer executes those semantics, so those "
            "cases cannot be used to validate production behaviour. Reproducing them "
            "requires eval/replay.py, which production refuses. See "
            "docs/evaluation/phase5-impact.md."
        ),
    }

    print(f"  policy versions        {len(versions)}")
    print(f"  adjudicable            {len(adjudicable)}")
    for row in versions:
        mark = "yes" if row["adjudicable_in_production"] else "NO "
        print(
            f"    {mark}  {row['policy_id']:16s} {row['policy_version']}  {row['semantics_status']}"
        )
    print()
    for name, stats in corpora.items():
        print(
            f"  {name:12s} {stats['cases']:4d} cases  "
            f"{stats['adjudicable_in_production']:4d} adjudicable  "
            f"{stats['blocked_by_policy_semantics']:4d} blocked"
        )

    if args.write:
        OUT.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        print(f"\n  written to {OUT.relative_to(REPO)}")
    else:
        print("\n  (dry run; pass --write)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
