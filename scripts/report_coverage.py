"""Re-report a completed run with two denominators instead of one. Parts E, F, H.

    uv run python scripts/report_coverage.py --report-dir eval/reports/phase15-410-33 --write

**This spends no scoring budget and changes no artefact it reads.** It is a
re-analysis of a committed per-case record, not a re-run: no model is called, no case
is re-decided, and the source directory is opened read-only. The output is a new file
beside the originals.

That distinction is the whole reason this exists as a separate script. Phase 15's
figures are sealed and correct; what they lack is a second denominator. Producing one
by re-reading the record is legitimate; producing one by re-running the cases would
be a second scoring of a hold-out.

## What it adds

    operational coverage    assessed / attempted    provider failures INCLUDED
    decision quality        over assessed cases     stated as NOT overall accuracy
    disposition breakdown   six buckets, none of them "the model was wrong"

The disposition of each case is derived from facts the run already recorded - the
abstention reason, the provider-failure flag, the failure record's stage - never from
whether the answer was right. A rule that could see correctness would let a good
score move cases between buckets.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from eval.coverage import CaseDisposition, cost_report, coverage_report

REPO = Path(__file__).resolve().parents[1]


def disposition_for(row: dict[str, Any], failure: dict[str, Any] | None) -> CaseDisposition:
    """One bucket per case, from transport and stage facts only.

    Ordered most-specific first, and **correctness is never consulted**. A case that
    was assessed and answered wrongly is `ASSESSED`: that is a decision-quality fact,
    and moving it into a failure bucket would be exactly the collapse Part F forbids
    in the opposite direction.
    """
    if row.get("provider_failure") or row.get("abstention_state") == "PROVIDER_LIMITATION":
        return CaseDisposition.PROVIDER_FAILURE
    if failure is not None and failure.get("stage_of_failure") == "DATASET_DEFECT":
        return CaseDisposition.DATASET_DEFECT
    if row.get("abstention_state") == "RETRIEVAL_FAILURE":
        return CaseDisposition.RETRIEVAL_FAILURE
    if row.get("contradiction_state") == "CONTRADICTION":
        return CaseDisposition.CONTRADICTION
    if row.get("assessments_total", 0) == 0:
        # Reached no verdict and no bucket above explains why. Ours until proven
        # otherwise: an unexplained gap must not default into the provider's column.
        return CaseDisposition.SYSTEM_FAILURE
    return CaseDisposition.ASSESSED


def _git_commit() -> str:
    try:
        return subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],
            cwd=REPO,
            capture_output=True,
            text=True,
            check=True,
        ).stdout.strip()
    except (OSError, subprocess.CalledProcessError):  # pragma: no cover
        return "unknown"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--report-dir", required=True)
    parser.add_argument("--write", action="store_true")
    args = parser.parse_args()

    run = REPO / args.report_dir
    rows = json.loads((run / "per_case.json").read_text())
    manifest = json.loads((run / "manifest.json").read_text())
    failures = {
        f["case_id"]: f
        for f in json.loads((run / "failures.json").read_text())
        if (run / "failures.json").is_file()
    }
    metrics = json.loads((run / "metrics.json").read_text())

    cases = [
        {**row, "disposition": disposition_for(row, failures.get(row["case_id"])).value}
        for row in rows
    ]
    coverage = coverage_report(cases)
    cost = cost_report(
        prompt_tokens=metrics["operational"]["prompt_tokens"],
        completion_tokens=metrics["operational"]["completion_tokens"],
    )

    decision = metrics["decision"]["accuracy"]
    assessed_ids = [
        c["case_id"] for c in cases if c["disposition"] == CaseDisposition.ASSESSED.value
    ]
    correct_assessed = sum(
        1
        for c in cases
        if c["disposition"] == CaseDisposition.ASSESSED.value and c["decision_correct"]
    )

    report = {
        "analysis": "coverage re-report",
        "source_experiment": manifest.get("experiment"),
        "source_dir": args.report_dir,
        "generated_at": datetime.now(UTC).isoformat(),
        "git_commit": _git_commit(),
        "read_only": (
            "No model was called, no case re-decided, and nothing in the source "
            "directory was modified. This is a re-analysis of a committed record and "
            "spends no scoring budget."
        ),
        "source_digests": {
            name: f"sha256:{hashlib.sha256((run / name).read_bytes()).hexdigest()}"
            for name in ("manifest.json", "per_case.json", "metrics.json", "failures.json")
            if (run / name).is_file()
        },
        "coverage": coverage,
        "decision_quality": {
            "denominator": len(assessed_ids),
            "correct": correct_assessed,
            "assessed_case_ids": assessed_ids,
            "note": (
                "Correct decisions among ASSESSED cases only. **NOT overall system "
                "accuracy.** The whole-run figure is reported beside it, over every "
                "attempted case, and neither substitutes for the other."
            ),
        },
        "whole_run_accuracy": {
            "value": decision["value"],
            "successes": decision["successes"],
            "total": decision["total"],
            "note": (
                "Over every attempted case, provider failures counted as incorrect. "
                "This is the operational figure and understates reasoning; the "
                "decision-quality figure above overstates delivery. Both are real; "
                "neither is 'the accuracy'."
            ),
        },
        "cost": cost,
        "claims_refused": [
            "that either denominator alone is 'system accuracy'",
            "that excluded cases were dropped - every one is counted and named",
            "that a provider failure is a model error",
            "any cost figure, absent a price basis",
        ],
    }

    print(f"  source          {args.report_dir} ({manifest.get('experiment')})")
    print(f"  {coverage['headline']}")
    for name, bucket in coverage["dispositions"].items():
        if bucket["count"]:
            print(f"    {name:<20} {bucket['count']:>3}   {bucket['attributable_to']}")
    print(f"  decision quality  {correct_assessed}/{len(assessed_ids)} on assessed cases")
    print(
        f"  whole-run         {decision['successes']}/{decision['total']} "
        "(provider failures counted as incorrect)"
    )
    print(f"  cost              {cost['status']}")

    if args.write:
        out = run / "coverage.json"
        out.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        print(f"\n  written to {out.relative_to(REPO)}")
    else:
        print("\n  (dry run; pass --write)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
