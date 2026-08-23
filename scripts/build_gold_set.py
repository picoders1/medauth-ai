"""Partition the case corpus and freeze the gold set.

    uv run python scripts/build_gold_set.py

Three partitions with different permissions:

============ ======= ==========================================================
development  ~15%    prompt, retrieval, threshold and model selection
validation   ~10%    intermediate checks during a phase
gold         ~75%    FROZEN. Scored under a budget. Never used for any tuning.
============ ======= ==========================================================

Assignment is **stratified and deterministic**: within each
(policy version x category) stratum, cases are ordered by a hash of their id and
split by rank. Hashing alone would be reproducible but could starve a small
stratum; ranking within strata makes proportions exact by construction, so the
gold set cannot silently lose a category. Neither depends on iteration order or a
clock, so the split is identical on any machine.

The gold set is frozen on write. A labelling error is corrected by publishing a
new version with a recorded reason - never by editing labels in place, which would
destroy the record of every evaluation already run against them.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from collections import Counter, defaultdict
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parents[1]

#: Target share of each partition, applied as an exact COUNT within every stratum.
#:
#: An earlier version assigned by rank percentile, which rounds badly on small
#: strata: in a stratum of seven, ranks 0 and 1 both fall below the 15th
#: percentile, so development took 29% while validation was starved. Exact counts
#: keep the proportions stable whatever the stratum size.
DEV_FRACTION = 0.18
VALIDATION_FRACTION = 0.10

FORBIDDEN_IN_INPUT = (
    "APPROVE_RECOMMENDED",
    "DENY_RECOMMENDED",
    "NEEDS_INFO",
    "HUMAN_REVIEW",
    "NO_DECISION",
    "SATISFIED",
    "NOT_SATISFIED",
    "UNKNOWN",
)


def _rank_key(case_id: str) -> int:
    """Stable ordering key. The [:8] slice and the modulus both matter: using the
    full digest, or a different width, silently moves cases between partitions."""
    return int(hashlib.sha256(case_id.encode()).hexdigest()[:8], 16)


def _partition(records: list[dict[str, Any]]) -> dict[str, str]:
    """Assign each case to a partition, stratified by policy version and category."""
    strata: dict[tuple[str, str, str], list[str]] = defaultdict(list)
    for record in records:
        key = (
            record["expected"]["policy_id"],
            record["expected"]["policy_revision"],
            record["category"],
        )
        strata[key].append(record["case_id"])

    assignment: dict[str, str] = {}
    for case_ids in strata.values():
        ordered = sorted(case_ids, key=_rank_key)
        total = len(ordered)
        n_dev = round(total * DEV_FRACTION)
        n_val = round(total * VALIDATION_FRACTION)
        # Never let tuning partitions consume a whole stratum: gold coverage of a
        # category matters more than hitting a fraction exactly.
        if n_dev + n_val >= total:
            n_dev, n_val = (1, 0) if total > 1 else (0, 0)
        for index, case_id in enumerate(ordered):
            if index < n_dev:
                assignment[case_id] = "development"
            elif index < n_dev + n_val:
                assignment[case_id] = "validation"
            else:
                assignment[case_id] = "gold"
    return assignment


def _leakage(record: dict[str, Any]) -> list[str]:
    """Any gold vocabulary appearing in the input the system will actually see."""
    blob = json.dumps(record["input"])
    return [token for token in FORBIDDEN_IN_INPUT if token in blob]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cases", default="data/synthetic/cases/cases.jsonl")
    parser.add_argument("--out", default="data")
    parser.add_argument("--version", default="1")
    args = parser.parse_args()

    cases_path = REPO / args.cases
    records = [json.loads(line) for line in cases_path.read_text().splitlines() if line.strip()]

    # --------------------------------------------------------------- integrity
    ids = [r["case_id"] for r in records]
    if len(ids) != len(set(ids)):
        print("duplicate case ids", file=sys.stderr)
        return 1

    leaks = {r["case_id"]: _leakage(r) for r in records}
    leaking = {k: v for k, v in leaks.items() if v}
    if leaking:
        print(f"gold labels leaked into input for {len(leaking)} case(s)", file=sys.stderr)
        for case_id, tokens in list(leaking.items())[:5]:
            print(f"  {case_id}: {tokens}", file=sys.stderr)
        return 1

    # -------------------------------------------------------------- partition
    assignment = _partition(records)
    for record in records:
        record["partition"] = assignment[record["case_id"]]

    gold = [r for r in records if r["partition"] == "gold"]
    development = [r for r in records if r["partition"] == "development"]
    validation = [r for r in records if r["partition"] == "validation"]

    out = REPO / args.out
    (out / "gold" / "cases").mkdir(parents=True, exist_ok=True)
    (out / "gold" / "manifests").mkdir(parents=True, exist_ok=True)
    (out / "synthetic" / "cases").mkdir(parents=True, exist_ok=True)

    def write(rows: list[dict[str, Any]], path: Path) -> str:
        path.write_text(
            "\n".join(json.dumps(r, sort_keys=True) for r in rows) + "\n", encoding="utf-8"
        )
        return hashlib.sha256(path.read_bytes()).hexdigest()

    gold_path = out / "gold" / "cases" / f"gold_v{args.version}.jsonl"
    gold_sha = write(gold, gold_path)
    dev_sha = write(development, out / "synthetic" / "cases" / "development.jsonl")
    val_sha = write(validation, out / "synthetic" / "cases" / "validation.jsonl")

    # -------------------------------------------------- coverage, not a target
    def distribution(rows: list[dict[str, Any]], key: Any) -> dict[str, int]:
        return dict(sorted(Counter(key(r) for r in rows).items()))

    criterion_states: Counter[str] = Counter()
    for record in gold:
        for criterion in record["expected"]["criteria"]:
            criterion_states[criterion["state"]] += 1

    manifest = {
        "gold_set_version": args.version,
        "frozen": True,
        "frozen_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "source_cases": args.cases,
        "source_cases_sha256": hashlib.sha256(cases_path.read_bytes()).hexdigest(),
        "provenance": "synthetic",
        "partition_rule": {
            "method": "rank of sha256(case_id)[:8] within (policy_version x category) stratum",
            "development_fraction": DEV_FRACTION,
            "validation_fraction": VALIDATION_FRACTION,
        },
        "counts": {
            "total": len(records),
            "development": len(development),
            "validation": len(validation),
            "gold": len(gold),
        },
        "sha256": {"gold": gold_sha, "development": dev_sha, "validation": val_sha},
        "gold_distribution": {
            "category": distribution(gold, lambda r: r["category"]),
            "decision": distribution(gold, lambda r: r["expected"]["decision"]),
            "policy_version": distribution(
                gold, lambda r: f"{r['expected']['policy_id']}:{r['expected']['policy_revision']}"
            ),
            "temporal_class": distribution(gold, lambda r: r["temporal_class"]),
            "criterion_state": dict(sorted(criterion_states.items())),
            "with_missing_information": sum(
                1 for r in gold if r["expected"]["missing_information"]
            ),
            "borderline": sum(1 for r in gold if r["borderline"]),
        },
        "scoring_budget": {
            "allowed_scorings": 1,
            "scorings_spent": 0,
            "note": (
                "Additional scorings must be declared in an ADR in advance. "
                "Re-scoring a frozen split until a number improves is how an "
                "evaluation becomes fiction."
            ),
        },
        "labelling": {
            "method": "derived by construction via app.decision.table.decide",
            "human_reviewed": False,
            "clinically_validated": False,
            "note": (
                "Labels are computed from criterion states by the same function the "
                "system uses. They are NOT expert clinical judgements."
            ),
        },
    }
    (out / "gold" / "manifests" / f"gold_v{args.version}.manifest.json").write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )

    print(
        f"  total {len(records)}  ->  dev {len(development)} | val {len(validation)} | gold {len(gold)}"
    )
    print(f"  gold decisions   {manifest['gold_distribution']['decision']}")
    print(f"  gold categories  {manifest['gold_distribution']['category']}")
    print(f"  gold policies    {manifest['gold_distribution']['policy_version']}")
    print(f"  criterion states {manifest['gold_distribution']['criterion_state']}")
    print(
        f"  missing-info {manifest['gold_distribution']['with_missing_information']}  "
        f"borderline {manifest['gold_distribution']['borderline']}"
    )
    print(f"  gold sha256 {gold_sha[:16]}...  FROZEN")
    return 0


if __name__ == "__main__":
    sys.exit(main())
