#!/usr/bin/env python
"""Inventory each policy version's decision logic, and what remains unresolved.

Phase 3 established that the engine was applying one shape - conjunction - to
every policy, and that 42 CFR 410.32 does not have that shape. This script asks
the question for the whole corpus: for each policy version, is a conjunction the
right reading, and if nobody knows, does the record say so?

**It does not decide.** It surfaces evidence - the provisions that carry
exception, alternative, conditional or exclusion language - and classifies a
policy as REVIEW_REQUIRED whenever that evidence exists and no logic has been
declared. Inferring a policy's logic from the presence of the word "except" is
exactly the kind of guess that produced the 410.32 defect in the first place.

Output: data/policy_logic/inventory.json and a printed summary.
"""

from __future__ import annotations

import argparse
import json
import re
from collections import defaultdict
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parents[1]
MATRIX = REPO / "data/criteria/coverage_matrix.jsonl"
INVENTORY = REPO / "data/criteria/inventory.jsonl"
LOGIC_DIR = REPO / "data/policy_logic"
OUT = LOGIC_DIR / "inventory.json"

#: Wording that indicates a policy's logic may not be a plain conjunction. These
#: are search terms for a human, not a classifier: "except" inside a sentence that
#: merely cross-references another section means nothing on its own.
SIGNALS: dict[str, re.Pattern[str]] = {
    "exception": re.compile(
        r"\b(except|exception|notwithstanding|even though|other than|unless)\b", re.I
    ),
    # "one of the following" was MISSING until Phase 6 and is the commonest way a
    # regulation writes a disjunction. 42 CFR 410.61(b) - "established before
    # treatment is begun by one of the following" over five practitioner types -
    # scanned clean because of it, and the policy was classified
    # ASSUMED_CONJUNCTION on that false negative. Found by reading the regulation,
    # not by the scan, which is the whole reason the inventory calls these search
    # terms rather than findings.
    "alternative": re.compile(
        r"\b(either"
        r"|or\s+(?:any|one|more)"
        r"|(?:any|one|each|all)\s+of\s+the\s+following"
        r"|whichever)\b",
        re.I,
    ),
    "conditional": re.compile(
        r"\b(only if|if\s+the|when\s+the|applies?\s+only|in\s+the\s+case\s+of)\b", re.I
    ),
    "exclusion": re.compile(
        r"\b(not covered|excluded|no payment|does not (?:cover|apply|include))\b", re.I
    ),
    "threshold": re.compile(
        r"\b(at least|no more than|not to exceed|minimum of|within\s+\d)\b", re.I
    ),
}


def _jsonl(path: Path) -> list[dict[str, Any]]:
    return [
        json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()
    ]


def _declared() -> dict[tuple[str, str], dict[str, Any]]:
    declared: dict[tuple[str, str], dict[str, Any]] = {}
    for path in sorted(LOGIC_DIR.glob("*.yaml")):
        import yaml

        spec = yaml.safe_load(path.read_text(encoding="utf-8"))
        declared[(spec["policy_id"], str(spec["policy_version"]))] = {
            "file": str(path.relative_to(REPO)),
            "form": spec.get("form", "DECLARED"),
            "review_notes": [str(n).strip() for n in spec.get("review_notes", [])],
            "source_provision": spec.get("source_provision"),
        }
    return declared


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--write", action="store_true", help="write the inventory file")
    args = parser.parse_args()

    provisions = _jsonl(MATRIX)
    criteria = _jsonl(INVENTORY)
    declared = _declared()

    by_version: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    for p in provisions:
        by_version[(p["policy_id"], p["policy_version"])].append(p)

    crit_by_version: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    for c in criteria:
        crit_by_version[(c["policy_id"], c["policy_version"])].append(c)

    rows: list[dict[str, Any]] = []
    for key in sorted(set(by_version) | set(crit_by_version)):
        policy_id, version = key
        these = by_version.get(key, [])
        those = crit_by_version.get(key, [])

        signals: dict[str, list[str]] = defaultdict(list)
        for p in these:
            if not p["substantive"]:
                continue
            for name, pattern in SIGNALS.items():
                if pattern.search(p["text"]):
                    signals[name].append(p["paragraph_path"] or p["section_path"])

        kinds = defaultdict(list)
        for c in those:
            kinds[c["criterion_type"]].append(c["criterion_id"])

        spec = declared.get(key)
        awaiting = sum(1 for p in these if p["classification"] == "REQUIRES_HUMAN_REVIEW")

        if spec is not None:
            form = spec["form"]
            notes = list(spec["review_notes"])
        elif not those:
            form = "NO_CRITERIA"
            notes = ["No criteria transcribed for this version; nothing to evaluate."]
        else:
            form = "REVIEW_REQUIRED" if signals else "ASSUMED_CONJUNCTION"
            notes = []
            if signals:
                notes.append(
                    "Provisions in this version carry "
                    + ", ".join(sorted(signals))
                    + " language, so a plain conjunction may misread it. No logic has "
                    "been declared and none is inferred here."
                )
            else:
                notes.append(
                    "No exception, alternative or conditional wording was found. That "
                    "is weak evidence, not a finding: the search is lexical and the "
                    f"{awaiting} provisions awaiting review have not been read."
                )

        rows.append(
            {
                "policy_id": policy_id,
                "policy_version": version,
                "logic_form": form,
                "declared_in": spec["file"] if spec else None,
                "criteria": {k: sorted(v) for k, v in sorted(kinds.items())},
                "criteria_count": len(those),
                "provisions_total": len(these),
                "provisions_awaiting_review": awaiting,
                "signals": {k: sorted(set(v)) for k, v in sorted(signals.items())},
                "unresolved_semantics": notes,
            }
        )

    summary = {
        "generated_from": {
            "coverage_matrix": str(MATRIX.relative_to(REPO)),
            "criteria_inventory": str(INVENTORY.relative_to(REPO)),
        },
        "by_form": {
            form: sum(1 for r in rows if r["logic_form"] == form)
            for form in sorted({r["logic_form"] for r in rows})
        },
        "declared": sum(1 for r in rows if r["declared_in"]),
        "policies": rows,
        "note": (
            "Signals are search terms for a reviewer, not classifications. A policy "
            "marked ASSUMED_CONJUNCTION has not been confirmed to be conjunctive - it "
            "means no signal was found by a lexical scan that cannot read meaning."
        ),
    }

    for row in rows:
        print(
            f"  {row['policy_id']:18s} {row['policy_version']}  {row['logic_form']:20s} "
            f"{row['criteria_count']:2d} criteria, {len(row['signals'])} signal type(s)"
        )
    print()
    for form, n in summary["by_form"].items():
        print(f"    {form:24s} {n}")

    if args.write:
        OUT.write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        print(f"\n  written to {OUT.relative_to(REPO)}")
    else:
        print("\n  (dry run; pass --write)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
