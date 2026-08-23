"""Plan a gold_v2 for every possible FOCUS-001 outcome. **Creates nothing.**

This script has no write path to gold_v1, gold_v2, or any manifest. It reads the
frozen corpus and emits a description of what a migration would require - for all
four outcomes, not the expected one, because modelling only the likely answer is how
the unlikely answer becomes the expensive surprise.

    uv run python scripts/plan_gold_migration.py --write

Writes `data/review/gold_v2_migration_plan.json`.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from dataclasses import asdict
from pathlib import Path
from typing import Any

from app.review.focus_impact import FocusOutcome
from app.review.migration import plan_migration

REPO = Path(__file__).resolve().parents[1]
GOLD = REPO / "data/gold/cases/gold_v1.jsonl"
OUT = REPO / "data/review/gold_v2_migration_plan.json"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--write", action="store_true")
    args = parser.parse_args()

    before = hashlib.sha256(GOLD.read_bytes()).hexdigest()
    gold = tuple(
        json.loads(line) for line in GOLD.read_text(encoding="utf-8").splitlines() if line.strip()
    )

    plans = {outcome: plan_migration(outcome, gold_cases=gold) for outcome in FocusOutcome}

    # The planner is pure and this proves it on the real corpus rather than on a
    # docstring. If planning ever gained a write path, this catches it here rather
    # than after a frozen dataset has already changed.
    after = hashlib.sha256(GOLD.read_bytes()).hexdigest()
    if before != after:
        print("REFUSING: planning modified gold_v1", file=sys.stderr)
        return 1

    report: dict[str, Any] = {
        "from_version": "gold_v1",
        "gold_v1_sha256": before,
        "gold_v1_unchanged_by_planning": True,
        "plans": {
            outcome.value: {
                **asdict(plan),
                "outcome": plan.outcome.value,
                "summary": plan.summary,
                "cases_unchanged": plan.cases_unchanged,
                "is_additive": plan.is_additive,
            }
            for outcome, plan in plans.items()
        },
        "note": (
            "A PLAN, not an instruction, and nothing here creates gold_v2. Executing "
            "one is a separate deliberate act taken only after a FOCUS-001 decision "
            "is ACCEPTED. Migration is additive: gold_v1, its manifest, the synthetic "
            "corpus and every committed report are left exactly as they are, so a "
            "report describing gold_v1 keeps describing the set it scored."
        ),
    }

    print(f"  gold_v1 sha256   {before[:16]}  ({len(gold)} cases)")
    print(f"  {'outcome':<28} {'required':<9} {'migrated':<9} {'unchanged':<10} additive")
    for outcome, plan in plans.items():
        print(
            f"  {outcome.value:<28} {plan.required!s:<9} "
            f"{len(plan.cases_migrated):<9} {plan.cases_unchanged:<10} {plan.is_additive}"
        )
    print(f"\n  gold_v1 unchanged by planning: {before == after}")

    if args.write:
        OUT.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        print(f"  written to {OUT.relative_to(REPO)}")
    else:
        print("  (dry run; pass --write)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
