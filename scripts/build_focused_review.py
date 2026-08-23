"""The one question a reviewer should answer next.

The OD-19 queue holds 244 provisions. Working it is a project. But exactly one
decision stands between this corpus and an admissible vertical slice, and burying it
in a queue of 244 makes it no more likely to be answered than the other 243.

**A defect this package exists to fix.** Transcribing 42 CFR 410.32(b)(3) in Phase 7
reclassified it from REQUIRES_HUMAN_REVIEW to REPRESENTED_CRITERION, which removed
it from the OD-19 queue - *while the dependency it blocks remained unresolved*. The
question changed from "should this be a criterion?" to "does the criterion drawn
from it make C03 adjudicable?", and that second question had nowhere to live.
Transcription silently retiring a review item is precisely the kind of quiet
progress that leaves a gap where nobody looks.

Three tiers, and the first has one item.

Writes `data/review/focused_review.jsonl` and `data/review/focused_review.md`.

    uv run python scripts/build_focused_review.py --write
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parents[1]
CRITERIA = REPO / "data/criteria/inventory.jsonl"
MATRIX = REPO / "data/criteria/coverage_matrix.jsonl"
DEPENDENCIES = REPO / "data/review/policy_dependencies.json"
OD19 = REPO / "data/review/od19_review_package.jsonl"
ADMISSIBILITY = REPO / "data/review/slice_admissibility.json"
OUT_JSONL = REPO / "data/review/focused_review.jsonl"
OUT_MD = REPO / "data/review/focused_review.md"

REVIEW_STATES = (
    "PENDING",
    "IN_REVIEW",
    "QUALIFIED_REVIEWED",
    "QUALIFIED_REVIEW_REJECTED",
    "QUALIFIED_REVIEW_INCONCLUSIVE",
)


def _jsonl(path: Path) -> list[dict[str, Any]]:
    return [
        json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()
    ]


def _row(
    *,
    review_id: str,
    priority: int,
    provision: dict[str, Any],
    criterion: dict[str, Any] | None,
    question: str,
    why: str,
    options: list[str],
    context: list[dict[str, str]],
) -> dict[str, Any]:
    return {
        "review_id": review_id,
        "priority": priority,
        "source": {
            "policy_id": provision["policy_id"],
            "policy_version": provision["policy_version"],
            "section_path": provision["section_path"],
            "hierarchy_path": provision["paragraph_path"],
            "source_page": provision["page"],
            "provision_id": provision["provision_id"],
        },
        "exact_text": provision["text"],
        "context": context,
        "criterion": criterion,
        "why_this_is_asked": why,
        "review_question": question,
        "answer_options": options,
        "permitted_states": list(REVIEW_STATES),
        "review_status": "PENDING",
        "reviewer_decision": None,
        "reviewer_rationale": None,
        "reviewer_id": None,
        "reviewed_at": None,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--write", action="store_true")
    args = parser.parse_args()

    provisions = {p["provision_id"]: p for p in _jsonl(MATRIX)}
    by_path = {
        (p["policy_id"], p["policy_version"], p["paragraph_path"]): p for p in provisions.values()
    }
    criteria = {c["criterion_id"]: c for c in _jsonl(CRITERIA)}
    dependencies = json.loads(DEPENDENCIES.read_text(encoding="utf-8"))["dependencies"]
    admissibility = json.loads(ADMISSIBILITY.read_text(encoding="utf-8"))

    rows: list[dict[str, Any]] = []
    key = ("42 CFR 410.32", "2026-08-13")
    b3 = by_path[(*key, "(b)(3)")]
    c03 = criteria["42_CFR_410_32_2026_08_13_C03"]
    c07 = criteria["42_CFR_410_32_2026_08_13_C07"]

    # ------------------------------------------------------------ priority 1
    rows.append(
        _row(
            review_id="FOCUS-001",
            priority=1,
            provision=b3,
            criterion={
                "criterion_id": c03["criterion_id"],
                "summary": c03["summary"],
                "authoritative_text": c03["authoritative_text"],
                "normalized_interpretation": c03["normalized_interpretation"],
                "dependency_resolution": dependencies[c03["criterion_id"]]["depends_on"][0][
                    "resolution"
                ],
            },
            why=(
                "This is the single decision standing between 42 CFR 410.32 and an "
                "admissible first AI vertical slice. Every other admissibility "
                "condition for that policy passes. Phase 7 transcribed (b)(3) and "
                "span-verified it as criterion C07 (the baseline: at least general "
                "supervision), so the question is no longer whether the provision "
                "should be transcribed - it is whether that transcription makes C03 "
                "adjudicable."
            ),
            question=(
                "Criterion C03 says a test must be furnished under 'the appropriate "
                "level of supervision'. (b)(3) sets a floor of at least general "
                "supervision and says some tests require direct or personal instead - "
                "but WHICH tests is set by the physician fee schedule's supervision "
                "indicator, which is not in 42 CFR and is not in this corpus.\n\n"
                "Can C03 be adjudicated from this regulation alone?"
            ),
            options=[
                "NARROW_C03_TO_BASELINE - restate C03 as the floor (at least general "
                "supervision), which IS determinable from the regulation, and record "
                "that the per-test level is out of scope",
                "SPLIT_C03 - keep a baseline criterion and add a separate criterion "
                "for the escalation, marked not determinable from this corpus",
                "LEAVE_C03_NOT_ADJUDICABLE - the criterion as written needs data this "
                "corpus does not have; 410.32 stays inadmissible until that data exists",
                "OTHER - state the reading in the rationale",
            ],
            context=[
                {
                    "label": "C07, transcribed in Phase 7 from this provision",
                    "text": c07["authoritative_text"],
                },
                {
                    "label": "What is NOT in the regulation",
                    "text": (
                        "Which supervision level applies to a specific test. That is "
                        "the physician fee schedule supervision indicator, published "
                        "separately from 42 CFR and absent from this corpus."
                    ),
                },
            ],
        )
    )

    # ------------------------------------------------------------ priority 2
    for path, label in (
        ("(b)(3)(i)", "definition of general supervision"),
        ("(b)(3)(ii)", "definition of direct supervision"),
        ("(b)(3)(iii)", "definition of personal supervision"),
        ("(b)(4)", "exception permitting direct in place of personal for RRA/RPA"),
    ):
        provision = by_path.get((*key, path))
        if provision is None:
            continue
        rows.append(
            _row(
                review_id=f"FOCUS-{path.replace('(', '').replace(')', '')}",
                priority=2,
                provision=provision,
                criterion=None,
                why=(
                    f"Directly required by C03: this provision is the {label}. It is "
                    "retrievable as evidence today; the question is whether it also "
                    "needs to be a criterion."
                ),
                question=(
                    "Is this a condition a case can satisfy or fail, or is it "
                    "definitional context that belongs in an evidence set but not in "
                    "the criteria tree?"
                ),
                options=[
                    "REPRESENT_AS_CRITERION",
                    "EVIDENCE_ONLY - definitional; nothing can satisfy or fail it",
                    "MERGE_WITH_EXISTING_CRITERION",
                    "REQUIRES_POLICY_INTERPRETATION",
                ],
                context=[],
            )
        )

    pending = len(_jsonl(OD19))
    summary = {
        "priority_1": sum(1 for r in rows if r["priority"] == 1),
        "priority_2": sum(1 for r in rows if r["priority"] == 2),
        "priority_3_deferred_to_od19": pending,
        "blocks_admissibility_of": admissibility["nearest_candidate"],
        "admissibility_blockers": admissibility["nearest_candidate_blockers"],
        "prefilled_decisions": sum(1 for r in rows if r["reviewer_decision"] is not None),
    }

    lines = [
        "# Focused Review — the next decision",
        "",
        f"**{summary['priority_1']} question at priority 1.** Answering it is what stands "
        f"between `{summary['blocks_admissibility_of']}` and an admissible first AI "
        "vertical slice.",
        "",
        "Priority 2 holds "
        f"{summary['priority_2']} supporting provisions. Priority 3 is the existing "
        f"OD-19 queue of {pending} provisions, unchanged and not urgent for this "
        "decision.",
        "",
        "Machine-readable: `data/review/focused_review.jsonl`. Decision fields are "
        "empty and nothing in the pipeline fills them.",
        "",
    ]
    for row in rows:
        lines += [
            f"## {row['review_id']} — priority {row['priority']}",
            "",
            f"**{row['source']['policy_id']} {row['source']['hierarchy_path']}** "
            f"(version {row['source']['policy_version']}, "
            f"section *{row['source']['section_path']}*, page {row['source']['source_page']})",
            "",
            "> " + row["exact_text"].replace("\n", "\n> "),
            "",
            f"*Why this is asked:* {row['why_this_is_asked']}",
            "",
            "**Question**",
            "",
            row["review_question"],
            "",
            "**Options**",
            "",
            *[f"- `{option}`" for option in row["answer_options"]],
            "",
        ]
        for item in row["context"]:
            lines += [f"*{item['label']}:* {item['text']}", ""]

    print(f"  priority 1   {summary['priority_1']}")
    print(f"  priority 2   {summary['priority_2']}")
    print(f"  priority 3   {pending} (the existing OD-19 queue, unchanged)")
    print(f"  pre-filled decisions  {summary['prefilled_decisions']}")

    if args.write:
        OUT_JSONL.write_text(
            "\n".join(json.dumps(r, sort_keys=True) for r in rows) + "\n", encoding="utf-8"
        )
        OUT_MD.write_text("\n".join(lines), encoding="utf-8")
        print(f"\n  written to {OUT_JSONL.relative_to(REPO)} and {OUT_MD.relative_to(REPO)}")
    else:
        print("\n  (dry run; pass --write)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
