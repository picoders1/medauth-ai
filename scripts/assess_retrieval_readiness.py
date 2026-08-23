"""Is there a retrieval benchmark trustworthy enough to compare configurations on?

Two things must both hold, and they fail for different reasons:

**Provenance.** Every query can prove `query -> policy -> version -> criterion ->
evidence`. A set containing even one query that cannot is CONTAMINATED, and a
comparison over it reports a rate whose denominator includes measurements that mean
nothing.

**Discrimination.** The set can actually separate configurations. A clean set on
which every arm ties has measured the set, not the systems - which is exactly what
Phase 3 found of v1 and what OD-22 records.

A set can be clean and useless, or discriminating and contaminated. Only a set that
is both is ready, and **if none is, this says so rather than nominating the least
bad one.**

Writes `data/review/retrieval_benchmark_readiness.json`.

    uv run python scripts/assess_retrieval_readiness.py --write
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from pathlib import Path
from typing import Any

import yaml

REPO = Path(__file__).resolve().parents[1]
PROVENANCE = REPO / "data/review/evaluation_provenance.json"
REPORTS = REPO / "eval" / "reports"
OUT = REPO / "data/review/retrieval_benchmark_readiness.json"

SETS = {
    "retrieval_v1": REPO / "eval/datasets/retrieval/questions.yaml",
    "retrieval_v2": REPO / "eval/datasets/retrieval_v2/questions.yaml",
    "retrieval_v3": REPO / "eval/datasets/retrieval_v3/questions.yaml",
}

#: What a set must satisfy before a configuration comparison may be run on it.
CONDITIONS = (
    "provenance_clean",
    "has_been_scored",
    "discriminates_between_arms",
    "covers_every_query_category",
)


def _spread(report_dir: Path) -> float | None:
    """Recall@1 spread across arms in a committed report, if one exists."""
    results = report_dir / "results.json"
    if not results.exists():
        return None
    arms = json.loads(results.read_text(encoding="utf-8")).get("arms") or []
    values = []
    for arm in arms:
        rate = arm.get("recall_at_1")
        if isinstance(rate, dict) and rate.get("total"):
            values.append(rate["successes"] / rate["total"])
    return round(max(values) - min(values), 4) if len(values) > 1 else None


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--write", action="store_true")
    args = parser.parse_args()

    provenance = json.loads(PROVENANCE.read_text(encoding="utf-8"))["sets"]

    # Reports are matched by name so a set cannot inherit another's evidence.
    reports = {
        "retrieval_v1": next(REPORTS.glob("*__retrieval-baseline"), None),
        "retrieval_v2": next(REPORTS.glob("*__retrieval-v2"), None),
        "retrieval_v3": next(REPORTS.glob("*__retrieval-v3"), None),
    }

    assessment: list[dict[str, Any]] = []
    for name, path in SETS.items():
        spec = yaml.safe_load(path.read_text(encoding="utf-8"))
        audit = provenance[name]
        report_dir = reports.get(name)
        spread = _spread(report_dir) if report_dir else None
        categories = Counter(q.get("category", "UNSPECIFIED") for q in spec["questions"])

        checks = {
            "provenance_clean": not audit["contaminated"],
            "has_been_scored": report_dir is not None,
            # A spread of exactly zero means every arm scored the same, which is the
            # definition of a set that cannot discriminate. Unknown (never scored) is
            # NOT treated as passing.
            "discriminates_between_arms": bool(spread) and spread > 0.0,
            "covers_every_query_category": len(categories) >= 10,
        }
        failed = sorted(name for name, ok in checks.items() if not ok)
        assessment.append(
            {
                "set": name,
                "dataset": str(path.relative_to(REPO)),
                "queries": len(spec["questions"]),
                "scorable_queries": audit["scorable"],
                "contaminated": audit["contaminated"],
                "report": str(report_dir.relative_to(REPO)) if report_dir else None,
                "recall_at_1_spread": spread,
                "categories": len(categories),
                "checks": checks,
                "ready": not failed,
                "failed_checks": failed,
            }
        )

    ready = [entry for entry in assessment if entry["ready"]]
    status = "RETRIEVAL_BENCHMARK_READY" if ready else "RETRIEVAL_BENCHMARK_NOT_READY"

    report = {
        "status": status,
        "ready_sets": [entry["set"] for entry in ready],
        "conditions": list(CONDITIONS),
        "assessment": assessment,
        "note": (
            "A set must be BOTH provenance-clean AND able to discriminate. Clean and "
            "useless is not ready; discriminating and contaminated is not ready. If no "
            "set qualifies the status is RETRIEVAL_BENCHMARK_NOT_READY and no "
            "configuration comparison may be run - nominating the least bad set would "
            "manufacture a result. Scoring a set is a deliberate act governed by OD-28, "
            "decided BEFORE the run and not after seeing which set flatters a "
            "configuration."
        ),
    }

    width = max(len(entry["set"]) for entry in assessment)
    print(f"  {'set':<{width}}  queries  scorable  spread   ready  failed")
    for entry in assessment:
        spread = (
            "-" if entry["recall_at_1_spread"] is None else f"{entry['recall_at_1_spread']:.4f}"
        )
        print(
            f"  {entry['set']:<{width}}  {entry['queries']:>7}  {entry['scorable_queries']:>8}  "
            f"{spread:>6}   {'YES' if entry['ready'] else 'no ':<5}  "
            f"{', '.join(entry['failed_checks']) or '-'}"
        )
    print(f"\n  {status}")
    if not ready:
        print("  No configuration comparison may be run. No result is manufactured.")

    if args.write:
        OUT.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        print(f"\n  written to {OUT.relative_to(REPO)}")
    else:
        print("\n  (dry run; pass --write)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
