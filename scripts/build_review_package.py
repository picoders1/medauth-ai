#!/usr/bin/env python
"""Build the reviewer package for the provisions awaiting qualified review (OD-19).

Phase 3 established the denominator: 246 substantive provisions that engineering
cannot rule on. This does not attempt to rule on them either. It assembles what a
qualified reviewer needs in order to, and orders the work so the provisions that
could change a decision are seen first.

**No reviewer decision is pre-filled.** `reviewer_decision` and
`reviewer_rationale` are empty in every row. A suggested requirement type is
offered - clearly labelled as a suggestion from a lexical scan - because an empty
form is harder to work than a form with a starting point, but the decision field
itself is blank and a test asserts it stays blank.

Priority is by consequence, not by convenience:

    1  cited by an existing criterion        a criterion may be uncheckable without it
    2  alters applicability                  changes WHETHER the policy applies
    3  contains an exception                 the 410.32 defect, generalised
    4  contains an exclusion                 reaches a denial directly
    5  affects timing                        deadline conditions deny quietly
    6  affects eligibility
    7  affects documentation
    8  affects medical necessity
    9  affects code applicability
    10 elaborates a transcribed section      context for a criterion, not cited by it
    11 everything else

Priority 1 requires an EXPLICIT paragraph citation in a criterion's own text -
"paragraph (b)(3)" and the like. Sharing a section with a criterion is a weaker
relationship and ranks at 10, because "this provision sits near a transcribed one"
and "a transcribed criterion cannot be evaluated without this provision" are
different claims and only the second is urgent.

Outputs:
    data/review/od19_review_package.jsonl   one row per provision, ranked
    data/review/od19_summary.json           counts by priority, policy and type
"""

from __future__ import annotations

import argparse
import json
import re
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parents[1]
MATRIX = REPO / "data/criteria/coverage_matrix.jsonl"
INVENTORY = REPO / "data/criteria/inventory.jsonl"
OUT_DIR = REPO / "data/review"

#: Dependencies confirmed by INDIVIDUAL INSPECTION in Phase 3, not by pattern
#: match. Each entry is a provision a transcribed criterion cannot be evaluated
#: without - the criterion's wording invokes a rule the criterion does not
#: contain, so adjudicating it against its own evidence set cannot reach a correct
#: verdict.
#:
#: These are recorded here rather than detected because the dependency is
#: semantic, not textual: 410.32 C03 says "the appropriate level of supervision"
#: and never writes the words "paragraph (b)(3)", so no citation regex can find
#: it. A looser regex was tried and ranked 65 provisions top-priority on a
#: relationship most of them did not have.
KNOWN_DEPENDENCIES: dict[tuple[str, str], tuple[str, ...]] = {
    ("42 CFR 410.32", "(b)(3)"): ("42_CFR_410_32_2026_08_13_C03",),
    ("42 CFR 410.38", "(d)(1)(ii)(A)"): (
        "42_CFR_410_38_2026_08_13_C02",
        "42_CFR_410_38_2026_08_13_C03",
        "42_CFR_410_38_2022_01_01_C02",
        "42_CFR_410_38_2022_01_01_C03",
    ),
    ("42 CFR 410.38", "(d)(1)(ii)(B)"): (
        "42_CFR_410_38_2026_08_13_C02",
        "42_CFR_410_38_2022_01_01_C02",
    ),
}

REVIEW_OUTCOMES = (
    "REPRESENT_AS_CRITERION",
    "NON_DECISION_RELEVANT",
    "MERGE_WITH_EXISTING_CRITERION",
    "REQUIRES_POLICY_INTERPRETATION",
    "REQUIRES_CLINICAL_REVIEW",
)

#: (priority, label, pattern). Order matters: the first match wins, so the most
#: consequential reading of a provision is the one that ranks it.
PRIORITY_RULES: tuple[tuple[int, str, re.Pattern[str]], ...] = (
    (
        2,
        "alters_applicability",
        re.compile(
            r"\b(applies? only|does not apply|for purposes of this (?:section|part)|"
            r"except as (?:otherwise )?provided|this section (?:does not )?applies)\b",
            re.I,
        ),
    ),
    (
        3,
        "contains_exception",
        re.compile(r"\b(exception|notwithstanding|even though|unless|other than)\b", re.I),
    ),
    (
        4,
        "contains_exclusion",
        re.compile(
            r"\b(not covered|excluded|no payment|is not (?:made|paid)|does not (?:cover|include))\b",
            re.I,
        ),
    ),
    (
        5,
        "affects_timing",
        re.compile(
            r"\b(within \d|no later than|before (?:the|delivery|treatment)|prior to|"
            r"preceding|\d+ (?:days?|months?|years?)|effective date)\b",
            re.I,
        ),
    ),
    (
        6,
        "affects_eligibility",
        re.compile(r"\b(eligible|entitled|qualif\w+|beneficiary must|enrolled)\b", re.I),
    ),
    (
        7,
        "affects_documentation",
        re.compile(r"\b(document\w*|record\w*|writing|written|signed|signature|certif\w+)\b", re.I),
    ),
    (
        8,
        "affects_medical_necessity",
        re.compile(
            r"\b(reasonable and necessary|medically necessary|medical necessity|"
            r"diagnos\w+ or treatment)\b",
            re.I,
        ),
    ),
    (
        9,
        "affects_code_applicability",
        re.compile(r"\b(HCPCS|CPT|code|procedure code|modifier|billing)\b", re.I),
    ),
)

SUGGESTED_TYPE: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("order_prescription", re.compile(r"\b(order|prescription|prescrib\w+)\b", re.I)),
    ("supervision", re.compile(r"\bsupervis\w+\b", re.I)),
    ("timing", re.compile(r"\b(within \d|no later than|prior to|preceding)\b", re.I)),
    ("documentation", re.compile(r"\b(document\w*|record\w*|written|signed)\b", re.I)),
    ("qualification", re.compile(r"\b(qualif\w+|licens\w+|certif\w+|credential\w*)\b", re.I)),
    ("setting", re.compile(r"\b(home|residence|hospital|facility|institution)\b", re.I)),
    ("exclusion", re.compile(r"\b(not covered|excluded|no payment)\b", re.I)),
)


def _jsonl(path: Path) -> list[dict[str, Any]]:
    return [
        json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()
    ]


def _cited_by_criterion(provision: dict[str, Any], criteria: list[dict[str, Any]]) -> list[str]:
    """Criteria whose own text EXPLICITLY cites this provision's paragraph.

    A criterion that cites a paragraph it does not contain cannot be adjudicated
    on its own evidence - 410.32 C03 and paragraph (b)(3) are the known case
    (R-51). Those provisions are reviewed first because a criterion already in use
    depends on them.

    The citation must be explicit. An earlier version of this function also counted
    "same section, deeper level", which linked every sub-provision of a section to
    every criterion drawn from it - 65 provisions ranked top priority on a
    relationship most of them did not have, each carrying a review question that
    asserted a dependency which was not there. A form that tells a reviewer
    something false is worse than one that tells them nothing.
    """
    path = provision["paragraph_path"]
    if not path:
        return []
    hits = list(KNOWN_DEPENDENCIES.get((provision["policy_id"], path), ()))
    for criterion in criteria:
        if criterion["policy_id"] != provision["policy_id"]:
            continue
        blob = " ".join(
            str(criterion.get(field, ""))
            for field in ("normalized_interpretation", "applicability", "summary")
        )
        if re.search(rf"paragraph\s*{re.escape(path)}\b", blob, re.I):
            hits.append(criterion["criterion_id"])
    return sorted(set(hits))


def _same_section_criteria(provision: dict[str, Any], criteria: list[dict[str, Any]]) -> list[str]:
    """Criteria transcribed from the same section. Context, not dependency."""
    return sorted(
        c["criterion_id"]
        for c in criteria
        if c["policy_id"] == provision["policy_id"]
        and c["policy_version"] == provision["policy_version"]
        and c.get("source_section") == provision["section_path"]
    )


def _classify(
    provision: dict[str, Any], cited_by: list[str], same_section: list[str]
) -> tuple[int, str]:
    if cited_by:
        return 1, "cited_by_existing_criterion"
    for priority, label, pattern in PRIORITY_RULES:
        if pattern.search(provision["text"]):
            return priority, label
    if same_section:
        return 10, "elaborates_a_transcribed_section"
    return 11, "remaining"


def _suggest_type(text: str) -> str | None:
    for name, pattern in SUGGESTED_TYPE:
        if pattern.search(text):
            return name
    return None


def _review_question(
    provision: dict[str, Any], reason: str, cited_by: list[str], same_section: list[str]
) -> str:
    """The specific question this provision poses, not a generic prompt."""
    where = provision["paragraph_path"] or provision["section_path"]
    if reason == "cited_by_existing_criterion":
        return (
            f"Criterion(s) {', '.join(cited_by)} cite {where} explicitly. Can that "
            "criterion be adjudicated without this provision transcribed, or must this "
            "provision become a criterion in its own right?"
        )
    if reason == "elaborates_a_transcribed_section":
        return (
            f"{where} sits in a section from which criteria were already transcribed "
            f"({', '.join(same_section[:3])}). Does it add a condition those criteria "
            "do not already carry?"
        )
    if reason == "contains_exception":
        return (
            f"Does {where} create an alternative pathway through a requirement stated "
            "elsewhere in this policy? If so, which requirement, and under exactly what "
            "conditions is it relieved?"
        )
    if reason == "alters_applicability":
        return (
            f"Does {where} change whether this policy applies to a case at all, rather "
            "than whether a case satisfies it?"
        )
    if reason == "contains_exclusion":
        return f"Does {where} state a condition under which payment is refused outright?"
    if reason == "affects_timing":
        return (
            f"Does {where} impose a deadline or interval that a case can fail? If so, "
            "measured from what event, and to what?"
        )
    return (
        f"Is {where} a condition a case can satisfy or fail, or is it structural text "
        "that bears on no decision?"
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--write", action="store_true")
    args = parser.parse_args()

    provisions = _jsonl(MATRIX)
    criteria = _jsonl(INVENTORY)
    pending = [p for p in provisions if p["classification"] == "REQUIRES_HUMAN_REVIEW"]

    rows: list[dict[str, Any]] = []
    for provision in pending:
        cited_by = _cited_by_criterion(provision, criteria)
        same_section = _same_section_criteria(provision, criteria)
        priority, reason = _classify(provision, cited_by, same_section)
        rows.append(
            {
                "provision_id": provision["provision_id"],
                "priority": priority,
                "priority_reason": reason,
                "policy_id": provision["policy_id"],
                "policy_version": provision["policy_version"],
                "section_path": provision["section_path"],
                "paragraph_path": provision["paragraph_path"],
                "hierarchy_level": provision["level"],
                "authoritative_text": provision["text"],
                "source_page": provision["page"],
                "current_classification": provision["classification"],
                "obligation_markers": provision["obligation_markers"],
                "cited_by_criteria": cited_by,
                "same_section_criteria": same_section,
                "suggested_requirement_type": _suggest_type(provision["text"]),
                "suggestion_basis": (
                    "Lexical scan of the provision text. A SUGGESTION ONLY - it reflects "
                    "which words appear, not what the provision means."
                ),
                "review_question": _review_question(provision, reason, cited_by, same_section),
                "permitted_decisions": list(REVIEW_OUTCOMES),
                "reviewer_decision": None,
                "reviewer_rationale": None,
                "reviewer_id": None,
                "reviewed_at": None,
            }
        )

    rows.sort(
        key=lambda r: (
            r["priority"],
            r["policy_id"],
            r["policy_version"],
            r["paragraph_path"] or "",
            r["provision_id"],
        )
    )

    by_priority = Counter(r["priority_reason"] for r in rows)
    by_policy: dict[str, Counter[str]] = defaultdict(Counter)
    for row in rows:
        by_policy[row["policy_id"]][row["priority_reason"]] += 1

    summary = {
        "provisions_awaiting_review": len(rows),
        "by_priority_reason": dict(sorted(by_priority.items())),
        "by_policy": {k: dict(sorted(v.items())) for k, v in sorted(by_policy.items())},
        "by_priority_rank": dict(sorted(Counter(r["priority"] for r in rows).items())),
        "permitted_decisions": list(REVIEW_OUTCOMES),
        "prefilled_decisions": sum(1 for r in rows if r["reviewer_decision"] is not None),
        "note": (
            "Priority is a work ordering, not a finding. A provision ranked 10 is not "
            "established as unimportant - it is one no lexical signal flagged, which is "
            "weak evidence from a scan that cannot read meaning. Nothing here reduces the "
            "denominator: all provisions require review, and the ranking only decides "
            "which are seen first."
        ),
    }

    print(f"  provisions awaiting review: {len(rows)}")
    for rank, n in sorted(Counter(r["priority"] for r in rows).items()):
        label = next((r["priority_reason"] for r in rows if r["priority"] == rank), "?")
        print(f"    priority {rank:2d}  {label:36s} {n:4d}")
    print(f"\n  pre-filled reviewer decisions: {summary['prefilled_decisions']}")

    if args.write:
        OUT_DIR.mkdir(parents=True, exist_ok=True)
        (OUT_DIR / "od19_review_package.jsonl").write_text(
            "\n".join(json.dumps(r, sort_keys=True) for r in rows) + "\n", encoding="utf-8"
        )
        (OUT_DIR / "od19_summary.json").write_text(
            json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )
        print(f"  written to {OUT_DIR.relative_to(REPO)}")
    else:
        print("\n  (dry run; pass --write)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
