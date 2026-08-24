"""Record FOCUS-001 as a formal decision gate, and precompute every outcome.

Two artefacts, and neither answers the question.

`data/review/focus_001_decision.json` is the decision record: the question, the
option set, who is affected, and reviewer fields that are empty and stay empty until
a qualified reviewer fills them. **Nothing in this script can advance it.** The gate
type has no constructor that yields an accepted decision, and this writes a
`PENDING` one.

`data/review/focus_001_impact.json` is the four-way impact table, computed for every
option before any answer exists. It is presented flat and deliberately does not
recommend: some options cost more than others, which is a fact about the options and
not an argument for the cheap one.

    uv run python scripts/build_focus_decision.py --write
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import asdict
from pathlib import Path
from typing import Any

from app.review.decision_gate import DecisionGate
from app.review.focus_impact import FocusOutcome, analyse_focus_001

REPO = Path(__file__).resolve().parents[1]
GOLD = REPO / "data/gold/cases/gold_v1.jsonl"
SYNTHETIC = REPO / "data/synthetic/cases/cases.jsonl"
ADMISSIBILITY = REPO / "data/review/slice_admissibility.json"
FOCUSED = REPO / "data/review/focused_review.jsonl"
OUT_DECISION = REPO / "data/review/focus_001_decision.json"
OUT_IMPACT = REPO / "data/review/focus_001_impact.json"

C03 = "42_CFR_410_32_2026_08_13_C03"
POLICY_ID = "42 CFR 410.32"
POLICY_VERSION = "2026-08-13"


class DecisionResetRefused(RuntimeError):
    """A rebuild would have destroyed a recorded decision."""


#: Any status other than PENDING means a person has acted. Rebuilding over one
#: replaces their answer with a template, and the rebuild is silent - the script
#: prints the same success line either way.
_ANSWERED = ("SUBMITTED", "ACCEPTED", "REJECTED", "SUPERSEDED")


def refuse_destructive_rebuild(
    existing: str | None, rebuilt: str, *, archive_to: Path | None
) -> None:
    """Refuse a rebuild that would overwrite a decision. Raises or returns None.

    There is no `--force`. A flag whose whole purpose is to destroy the audit record
    would be reached for exactly when someone is in a hurry, which is when the record
    matters most. The only way past a non-identical rebuild is `--archive-to`, which
    preserves the existing record first - so history accumulates rather than being
    traded away for convenience.
    """
    if existing is None:
        return

    status = str(json.loads(existing).get("status", "UNKNOWN"))

    if status in _ANSWERED:
        raise DecisionResetRefused(
            f"the existing record is {status}: a person has answered FOCUS-001, and "
            "rebuilding would replace their decision and its attribution with a blank "
            "template. This script cannot do that at all - a superseding answer is "
            "recorded as a new decision_version beside the old one, never over it."
        )

    # PENDING. A byte-identical rebuild changes nothing and is always safe.
    if existing == rebuilt:
        return

    if archive_to is None:
        raise DecisionResetRefused(
            "the existing PENDING record differs from the rebuild. Rebuilding would "
            "discard whatever it currently says. Pass --archive-to PATH to preserve it "
            "first; there is deliberately no flag that simply overwrites."
        )


def _jsonl(path: Path) -> tuple[dict[str, Any], ...]:
    return tuple(
        json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--write", action="store_true")
    parser.add_argument(
        "--archive-to",
        metavar="PATH",
        help="preserve the existing PENDING record here before rebuilding over it",
    )
    args = parser.parse_args()

    gold = _jsonl(GOLD)
    synthetic = _jsonl(SYNTHETIC)
    focused = {row["review_id"]: row for row in _jsonl(FOCUSED)}["FOCUS-001"]
    admissibility = json.loads(ADMISSIBILITY.read_text(encoding="utf-8"))

    # What would STILL block 410.32 after this decision, read from the gate rather
    # than assumed empty. If the gate grows a condition this policy also fails, it
    # shows up in the impact table instead of at the moment the slice is attempted.
    candidate = next(
        c
        for c in admissibility["assessment"]
        if c["policy_id"] == POLICY_ID and c["policy_version"] == POLICY_VERSION
    )
    # The checks FOCUS-001 itself controls. Both are excluded from "other blockers"
    # because including either makes the analysis circular: it would tell the reviewer
    # that even after answering, the policy stays blocked by the answer not existing.
    #
    # `domain_decisions_resolved` leaked in when the admissibility gate grew its
    # eleventh check, silently flipping NARROW_C03_TO_BASELINE's consequence from
    # "admissible: yes" to "no" in the reviewer's own packet.
    RESOLVED_BY_THIS_DECISION = ("no_unresolved_dependency", "domain_decisions_resolved")
    other_blockers = tuple(
        check for check in candidate["failed_checks"] if check not in RESOLVED_BY_THIS_DECISION
    )

    affected = tuple(
        sorted(
            case["case_id"]
            for case in gold
            if any(entry["criterion_id"] == C03 for entry in case["expected"]["criteria"])
        )
    )

    gate = DecisionGate.pending(
        focus_id="FOCUS-001",
        question=focused["review_question"],
        policy_id=POLICY_ID,
        policy_version=POLICY_VERSION,
        permitted_decisions=tuple(outcome.value for outcome in FocusOutcome),
        affected_criteria=(C03,),
        affected_cases=affected,
        source_references=(
            # The packet the reviewer is actually handed must be citable, or a
            # correctly-cited submission gets refused for naming its own source.
            "docs/review/FOCUS-001.md",
            "42 CFR 410.32(b)(3) — data/cms/CFR-410_32-2026-08-13.md",
            "https://www.ecfr.gov/current/title-42/section-410.32",
            "docs/data/410-32-b3-review.md",
        ),
    )

    impacts = analyse_focus_001(
        gold_cases=gold,
        synthetic_cases=synthetic,
        other_blockers=other_blockers,
        c03_id=C03,
        policy_id=POLICY_ID,
        policy_version=POLICY_VERSION,
    )

    decision_record = {
        **{k: v for k, v in asdict(gate).items() if k != "notes"},
        "status": gate.status.value,
        "reviewer_identity": None,
        "reviewer_qualification": None,
        # Carried from the start, null, so the key set does not change as the record
        # advances. A record whose shape depends on its status is harder to schema-check
        # and hides a missing field behind "that status does not have one".
        "submitted_at": gate.review_timestamp,
        "separation_of_duties": gate.separation_of_duties.value,
        "is_resolved": gate.is_resolved,
        "blocks_production": gate.blocks_production,
        "note": (
            "This is a DOMAIN decision. No heuristic, similarity score or model output "
            "may answer it, and no code path in this repository can advance it: the "
            "gate type has no constructor that yields an accepted decision, submission "
            "and acceptance are separate acts, and only ACCEPTED resolves it. "
            "Production stays blocked while it is unresolved."
        ),
    }

    impact_record = {
        "focus_id": "FOCUS-001",
        "computed_before_any_decision": True,
        "other_blockers_after_this_decision": list(other_blockers),
        "outcomes": [
            {
                **asdict(impact),
                "outcome": impact.outcome.value,
                "gold_cases_affected_count": impact.gold_cases_affected_count,
            }
            for impact in impacts
        ],
        "note": (
            "The table does NOT recommend an outcome. Some options cost more than "
            "others; that is a fact about the options, not an argument for the cheap "
            "one. Choosing the cheapest reading of a regulation because it needs no "
            "gold_v2 would be exactly the wrong reason. OTHER is deliberately not "
            "modelled - precomputing an impact for an unstated reading would mean "
            "inventing the reading."
        ),
    }

    print(f"  FOCUS-001 status      {gate.status.value}")
    print(f"  resolved              {gate.is_resolved}")
    print(f"  blocks production     {gate.blocks_production}")
    print(f"  affected gold cases   {len(affected)}")
    print(f"  other blockers        {list(other_blockers) or 'none'}\n")
    print(f"  {'outcome':<28} {'admissible':<11} {'gold_v2':<8} {'cases':<6} unblocks")
    for impact in impacts:
        print(
            f"  {impact.outcome.value:<28} {impact.policy_admissible_after!s:<11} "
            f"{impact.gold_v2_required!s:<8} {impact.gold_cases_affected_count:<6} "
            f"{len(impact.unblocks)}"
        )

    if args.write:
        rebuilt = json.dumps(decision_record, indent=2, sort_keys=True, default=str) + "\n"
        existing = OUT_DECISION.read_text(encoding="utf-8") if OUT_DECISION.exists() else None
        archive_to = Path(args.archive_to) if args.archive_to else None
        try:
            refuse_destructive_rebuild(existing, rebuilt, archive_to=archive_to)
        except DecisionResetRefused as exc:
            print(f"  REFUSED: {exc}", file=sys.stderr)
            return 1
        if archive_to is not None and existing is not None and existing != rebuilt:
            archive_to.parent.mkdir(parents=True, exist_ok=True)
            archive_to.write_text(existing, encoding="utf-8")
            print(f"  archived the existing record to {archive_to}")
        OUT_DECISION.write_text(
            json.dumps(decision_record, indent=2, sort_keys=True, default=str) + "\n",
            encoding="utf-8",
        )
        OUT_IMPACT.write_text(
            json.dumps(impact_record, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )
        print(f"\n  written to {OUT_DECISION.relative_to(REPO)} and {OUT_IMPACT.relative_to(REPO)}")
    else:
        print("\n  (dry run; pass --write)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
