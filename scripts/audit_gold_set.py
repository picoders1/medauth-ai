"""Audit the frozen gold set against the coverage matrix (Part C).

    uv run python scripts/audit_gold_set.py

**Changes nothing.** The gold set is frozen; this classifies each case as

    VALID | REQUIRES_REVIEW | INVALID_FOR_GOLD

and writes the audit beside it. A case is never deleted or silently corrected -
if the audit finds a problem, the remedy is a new gold version with a recorded
reason, not an edit.

A case is downgraded when its correctness depends on something this project has
not established: a criterion set whose completeness is unverified, a curated code
mapping that is not authoritative, or a policy that cannot support a standalone
decision.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import yaml

REPO = Path(__file__).resolve().parents[1]


def _jsonl(path: Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--gold", default="data/gold/cases/gold_v1.jsonl")
    parser.add_argument("--matrix", default="data/criteria/coverage_matrix.jsonl")
    parser.add_argument("--criteria", default="data/criteria/inventory.jsonl")
    parser.add_argument("--linkage", default="data/linkage/policy_code_links.yaml")
    parser.add_argument("--out", default="data/gold/manifests/gold_v1.audit.json")
    args = parser.parse_args()

    gold = _jsonl(REPO / args.gold)
    matrix = _jsonl(REPO / args.matrix)
    criteria = {c["criterion_id"]: c for c in _jsonl(REPO / args.criteria)}
    linkage = yaml.safe_load((REPO / args.linkage).read_text())

    # Policy versions carrying provisions that a qualified reviewer has not yet
    # placed. A case against such a policy may be adjudicated against an incomplete
    # criterion set - the case is not wrong, but its sufficiency is unestablished.
    awaiting: Counter[tuple[str, str]] = Counter()
    for row in matrix:
        if row["classification"] == "REQUIRES_HUMAN_REVIEW" and row["substantive"]:
            awaiting[(row["policy_id"], row["policy_version"])] += 1

    confidence: dict[tuple[str, str, str], str] = {}
    for link in linkage["links"]:
        confidence[(link["policy_id"], link["policy_version"], link["code"])] = link["confidence"]

    audited: list[dict[str, Any]] = []
    for case in gold:
        expected = case["expected"]
        key = (expected["policy_id"], expected["policy_revision"])
        findings: list[str] = []
        status = "VALID"

        referenced = [entry["criterion_id"] for entry in expected["criteria"]]
        unknown = [cid for cid in referenced if cid not in criteria]
        if unknown:
            status = "INVALID_FOR_GOLD"
            findings.append(f"references criteria absent from the verified inventory: {unknown}")

        pending = awaiting.get(key, 0)
        if pending:
            status = "REQUIRES_REVIEW" if status == "VALID" else status
            findings.append(
                f"{pending} provision(s) in this policy version await qualified review, so "
                f"the criterion set adjudicating this case is not established as complete"
            )

        code = case["input"]["requested_procedure"]["code"]
        link_confidence = confidence.get((key[0], key[1], code))
        if link_confidence == "low":
            status = "REQUIRES_REVIEW" if status == "VALID" else status
            findings.append(
                f"requested code {code} is linked to this policy at LOW curated confidence; "
                "applicability rests on an engineering judgement, not on the source"
            )
        elif link_confidence is None and case["category"] != "POLICY_NOT_APPLICABLE":
            status = "INVALID_FOR_GOLD"
            findings.append(f"requested code {code} has no curated link to {key[0]} {key[1]}")

        if not referenced and case["category"] != "POLICY_NOT_APPLICABLE":
            status = "INVALID_FOR_GOLD"
            findings.append("no criteria referenced, but the case is not a no-policy case")

        audited.append(
            {
                "case_id": case["case_id"],
                "policy_id": key[0],
                "policy_version": key[1],
                "category": case["category"],
                "expected_decision": expected["decision"],
                "audit_status": status,
                "findings": findings,
            }
        )

    counts = Counter(row["audit_status"] for row in audited)
    by_policy: dict[str, Counter[str]] = {}
    for row in audited:
        by_policy.setdefault(f"{row['policy_id']}:{row['policy_version']}", Counter())[
            row["audit_status"]
        ] += 1

    report = {
        "audited_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "gold_set": args.gold,
        "gold_set_unmodified": True,
        "cases": len(gold),
        "by_status": dict(sorted(counts.items())),
        "by_policy_version": {k: dict(sorted(v.items())) for k, v in sorted(by_policy.items())},
        "note": (
            "The gold set was NOT modified. REQUIRES_REVIEW does not mean a case is wrong; "
            "it means its sufficiency depends on completeness this project has not "
            "established. Any correction must ship as gold_v2 with a recorded reason."
        ),
        "cases_detail": audited,
    }
    (REPO / args.out).write_text(
        json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )

    print(f"  audited {len(gold)} gold cases (unmodified)")
    for status, count in sorted(counts.items()):
        print(f"    {status:<20} {count}")
    print("\n  by policy version:")
    for policy, statuses in sorted(by_policy.items()):
        print(f"    {policy:<34} {dict(statuses)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
