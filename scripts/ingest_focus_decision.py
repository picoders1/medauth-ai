"""Ingest an externally supplied FOCUS-001 decision, or refuse it.

Two separate commands, because submission and acceptance are two separate acts:

    uv run python scripts/ingest_focus_decision.py --submit path/to/decision.json
    uv run python scripts/ingest_focus_decision.py --accept path/to/acceptance.json

**Neither this script nor anything it calls can answer FOCUS-001.** `--submit`
records what a reviewer supplied and produces `SUBMITTED`, which unblocks nothing.
`--accept` is a second command requiring a different identity. A malformed or forged
submission stops at the first step.

The validator checks the ENVELOPE - identity, standing, a rationale, the packet
cited, timestamps - and says nothing about whether the answer is right. That is the
question engineering cannot settle.

Submission payload:

    {"focus_id": "FOCUS-001", "reviewer_identity": "...",
     "reviewer_qualification": "...", "decision": "NARROW_C03_TO_BASELINE",
     "rationale": "...", "source_reference": "docs/review/FOCUS-001.md",
     "submitted_at": "2026-09-01"}

Acceptance payload:

    {"accepted_by": "...", "accepted_at": "2026-09-02"}
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import asdict
from pathlib import Path
from typing import Any

from app.review.decision_gate import DecisionGate, DecisionStatus, ReviewerIdentity
from app.review.ingest import (
    IngestError,
    accept_decision,
    ingest_submission,
    validate_submission,
)

REPO = Path(__file__).resolve().parents[1]
RECORD = REPO / "data/review/focus_001_decision.json"


def _load_gate(record: dict[str, Any]) -> DecisionGate:
    """Rebuild the gate from its committed record, preserving whatever state it is
    in. A reconstruction that always produced PENDING would let a second submission
    overwrite an accepted decision."""
    reviewer = record.get("reviewer")
    return DecisionGate(
        focus_id=record["focus_id"],
        question=record["question"],
        policy_id=record["policy_id"],
        policy_version=record["policy_version"],
        permitted_decisions=tuple(record["permitted_decisions"]),
        affected_criteria=tuple(record["affected_criteria"]),
        affected_cases=tuple(record["affected_cases"]),
        source_references=tuple(record["source_references"]),
        decision_version=record["decision_version"],
        status=DecisionStatus(record["status"]),
        reviewer=(
            ReviewerIdentity(
                reviewer_id=reviewer["reviewer_id"], qualification=reviewer["qualification"]
            )
            if reviewer
            else None
        ),
        reviewer_decision=record.get("reviewer_decision"),
        reviewer_rationale=record.get("reviewer_rationale"),
        accepted_by=record.get("accepted_by"),
    )


def _write(gate: DecisionGate, record: dict[str, Any]) -> None:
    updated = {
        **record,
        **{k: v for k, v in asdict(gate).items() if k != "notes"},
        "status": gate.status.value,
        "reviewer_identity": gate.reviewer.reviewer_id if gate.reviewer else None,
        "reviewer_qualification": gate.reviewer.qualification if gate.reviewer else None,
        "is_resolved": gate.is_resolved,
        "blocks_production": gate.blocks_production,
    }
    RECORD.write_text(
        json.dumps(updated, indent=2, sort_keys=True, default=str) + "\n", encoding="utf-8"
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--submit", metavar="PATH", help="a reviewer's decision payload")
    group.add_argument("--accept", metavar="PATH", help="an acceptance payload")
    group.add_argument("--validate", metavar="PATH", help="check a submission without writing")
    parser.add_argument("--write", action="store_true")
    args = parser.parse_args()

    record = json.loads(RECORD.read_text(encoding="utf-8"))
    gate = _load_gate(record)
    print(f"  gate            {gate.focus_id} is {gate.status.value}")
    print(f"  blocks prod     {gate.blocks_production}\n")

    payload_path = Path(args.submit or args.accept or args.validate)
    payload = json.loads(payload_path.read_text(encoding="utf-8"))

    if args.validate or args.submit:
        issues = validate_submission(
            payload, gate=gate, expected_source_references=tuple(gate.source_references)
        )
        if issues:
            print(f"  REFUSED - {len(issues)} issue(s):", file=sys.stderr)
            for issue in issues:
                print(f"    {issue.field}: {issue.problem}", file=sys.stderr)
                print(f"      remedy: {issue.remedy}", file=sys.stderr)
            return 1
        print("  envelope is valid (this says NOTHING about whether the answer is right)")

    if args.validate:
        return 0

    try:
        if args.submit:
            gate = ingest_submission(
                payload, gate=gate, expected_source_references=tuple(gate.source_references)
            )
            print(f"  -> {gate.status.value}. Acceptance is a SEPARATE act and is not done here.")
        else:
            gate = accept_decision(gate, payload)
            print(f"  -> {gate.status.value}. Production admissibility may now be re-evaluated.")
    except IngestError as exc:
        print(f"  REFUSED: {exc}", file=sys.stderr)
        return 1

    print(f"  resolved        {gate.is_resolved}")
    print(f"  blocks prod     {gate.blocks_production}")

    if args.write:
        _write(gate, record)
        print(f"\n  written to {RECORD.relative_to(REPO)}")
        print("  re-run scripts/assess_slice_admissibility.py to re-evaluate the gate")
    else:
        print("\n  (dry run; pass --write)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
