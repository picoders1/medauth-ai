"""Freeze the 26-case 410.33 evaluation set. **Does not run it.**

Phase 13 prepares this evaluation and deliberately stops short of executing it. The
reason is in the regime, not in the schedule: a scoring against a frozen split is a
budgeted act, and the budget is spent by running it — not by planning to.

What this writes is the manifest that a later run must match. It fixes the case ids,
the labels, the policy version, the criteria, the split and the metric list **before**
any number exists, so that the run cannot be shaped by its own result.

    uv run python scripts/freeze_410_33_evaluation.py
    uv run python scripts/freeze_410_33_evaluation.py --write

## What is deliberately absent

No prompt is tuned here, no threshold is chosen, and no retrieval configuration is
selected — that decision is recorded as `RETRIEVAL_CONFIGURATION_UNRESOLVED` and the
configuration is **fixed for the experiment** rather than justified by it.

## Why the labels are not re-derived

Every case's expected decision comes from its criteria-satisfaction pattern through
the same `decide()` the system uses. They were computed once when gold_v1 was frozen
and are read here, never recomputed: a harness that re-derived labels would agree
with itself by construction.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parents[1]
GOLD = REPO / "data/gold/cases/gold_v1.jsonl"
MANIFEST = REPO / "data/gold/manifests/gold_v1.manifest.json"
OUT = REPO / "data/review/eval_410_33_frozen.json"
POLICY_ID = "42 CFR 410.33"
POLICY_VERSION = "2026-08-13"

#: Every metric the run must report, named before any of them has a value.
#:
#: Listed rather than left to the runner because a metric chosen after seeing results
#: is a metric chosen because of them. Denial precision is separate from macro-F1 for
#: the reason it always is here: a wrong approval costs money and a wrong denial
#: withholds care, and averaging them hides the one that matters.
REQUIRED_METRICS: dict[str, tuple[str, ...]] = {
    "decision": (
        "decision_accuracy",
        "macro_f1",
        "confusion_matrix",
        "denial_precision",  # own denominator, own Wilson interval, reported alone
        "approval_precision",
    ),
    "criterion": (
        "satisfied_accuracy",
        "not_satisfied_accuracy",
        "unknown_accuracy",
        "criterion_confusion_matrix",
    ),
    "grounding": (
        "citation_validity",
        "citation_precision",
        "citation_recall",
        "unsupported_claim_rate",
        "evidence_completeness",
    ),
    "abstention": (
        "abstention_precision",
        "abstention_recall",
        "coverage",
        "unsafe_decision_rate",
    ),
    "operational": (
        "p50_latency_ms",
        "p95_latency_ms",
        "model_latency_ms",
        "retrieval_latency_ms",
        "prompt_tokens",
        "completion_tokens",
    ),
}

#: Recorded per failing case, so a failure can be diagnosed without re-running it.
#: **No case may be excluded from this list.** Dropping a hard case is how an
#: evaluation reports a number about an easier corpus than the one it names.
REQUIRED_FAILURE_FIELDS = (
    "case_id",
    "policy_version",
    "expected_outcome",
    "actual_outcome",
    "expected_rule",
    "actual_rule",
    "failed_criterion_ids",
    "evidence_retrieved",
    "evidence_missing",
    "citation_status",
    "model_assessments",
    "guardrail_state",
    "contradiction_state",
    "abstention_reason",
    "reason_for_failure",
)


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
    parser.add_argument("--write", action="store_true")
    args = parser.parse_args()

    raw = GOLD.read_bytes()
    rows: list[dict[str, Any]] = [json.loads(line) for line in raw.decode().splitlines() if line]
    cases = [
        r
        for r in rows
        if r["expected"]["policy_id"] == POLICY_ID
        and r["expected"]["policy_revision"] == POLICY_VERSION
    ]
    if not cases:
        print(f"  no gold cases on {POLICY_ID} rev {POLICY_VERSION}", file=sys.stderr)
        return 1

    case_ids = sorted(r["case_id"] for r in cases)
    criteria = sorted({c["criterion_id"] for r in cases for c in r["expected"]["criteria"]})

    frozen = {
        "frozen_at": datetime.now(UTC).isoformat(),
        "git_commit": _git_commit(),
        "status": "FROZEN_NOT_RUN",
        "note": (
            "The manifest a later run must match. Frozen BEFORE any number exists, so "
            "the run cannot be shaped by its own result. Running it spends a scoring "
            "from the gold_v1 budget and is a separate, deliberate act."
        ),
        "policy_identity": f"REGULATION:{POLICY_ID}:{POLICY_VERSION}",
        "gold_set_version": "gold_v1",
        "gold_sha256": hashlib.sha256(raw).hexdigest(),
        "gold_immutable": True,
        "gold_v2_required": False,
        "gold_v2_note": (
            "FOCUS-001 was answered LEAVE_C03_NOT_ADJUDICABLE, which changes no "
            "criterion, so no label was invalidated and no gold_v2 is required. That "
            "state is recorded explicitly rather than left as an absence."
        ),
        "case_count": len(cases),
        "case_ids": case_ids,
        "case_id_digest": f"sha256:{hashlib.sha256(','.join(case_ids).encode()).hexdigest()[:16]}",
        "criteria": criteria,
        "split": "gold (frozen)",
        "categories": dict(sorted(Counter(r["category"] for r in cases).items())),
        "expected_decisions": dict(
            sorted(Counter(r["expected"]["decision"] for r in cases).items())
        ),
        "expected_rules": dict(
            sorted(Counter(str(r["expected"]["decision_rule"]) for r in cases).items())
        ),
        "borderline_cases": sorted(r["case_id"] for r in cases if r.get("borderline")),
        "expected_criterion_states": dict(
            sorted(Counter(c["state"] for r in cases for c in r["expected"]["criteria"]).items())
        ),
        "required_metrics": {k: list(v) for k, v in REQUIRED_METRICS.items()},
        "required_failure_fields": list(REQUIRED_FAILURE_FIELDS),
        "statistics": {
            "single_rates": "Wilson",
            "paired_comparisons": "exact McNemar",
            "denial_precision": "reported separately, own denominator and interval",
        },
        "configuration_fixed_for_experiment": {
            "retrieval": "RETRIEVAL_CONFIGURATION_UNRESOLVED",
            "retrieval_note": (
                "Not selected on evidence - v3 cannot separate the arms at n=31. The "
                "configuration is FIXED for this experiment so it is not a variable, "
                "and no claim about it may be drawn from the result."
            ),
            "reranker": "engineering default (see retrieval-configuration-decision.md)",
            "confidence_threshold": "UNCALIBRATED - none is selected, and none may be",
            "prompt_ids": ["intake.v2", "adjudication.v1"],
        },
        "prohibitions": [
            "No prompt may be tuned against these cases.",
            "No threshold may be calibrated on them.",
            "No case may be excluded after seeing a result.",
            "No label may be changed.",
            "Running this spends a scoring from the gold_v1 budget (allowed 1).",
        ],
    }

    print(f"  policy            {frozen['policy_identity']}")
    print(f"  cases             {frozen['case_count']}  digest {frozen['case_id_digest']}")
    print(f"  criteria          {len(criteria)}")
    print(f"  categories        {frozen['categories']}")
    print(f"  expected          {frozen['expected_decisions']}")
    print(f"  borderline        {len(frozen['borderline_cases'])}")
    print(
        f"  gold sha256       {frozen['gold_sha256'][:16]}…  immutable={frozen['gold_immutable']}"
    )
    print(f"  metrics required  {sum(len(v) for v in REQUIRED_METRICS.values())}")
    print(f"  status            {frozen['status']}")

    if not args.write:
        print("\n  (dry run; pass --write)")
        return 0
    OUT.write_text(json.dumps(frozen, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(f"\n  written to {OUT.relative_to(REPO)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
