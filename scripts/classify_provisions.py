"""Draft classifications for every unrepresented provision (OD-19, Part A3).

    uv run python scripts/classify_provisions.py --write

Emits a classification for each substantive provision that no criterion represents,
using explicit rules that each carry their own reason. The output is a **draft**:
rules encode a non-clinician's judgement about what bears on a prior-authorization
decision, and that judgement is exactly what OD-19 says is unverified.

Two properties make the draft honest rather than a rubber stamp:

* Every rule states its reason, and the reason is recorded per provision - so a
  reviewer sees *why* something was set aside, not just that it was.
* Anything a rule cannot confidently place becomes ``REQUIRES_HUMAN_REVIEW``
  rather than ``NON_DECISION_RELEVANT``. The default is "someone must look", not
  "probably fine".

Hand-written overrides in ``manual_overrides`` take precedence and are the record
of provisions inspected individually.
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

#: Provisions inspected individually. These are the ones where a rule would have
#: been wrong, and each is a judgement recorded in the open.
MANUAL_OVERRIDES: dict[str, tuple[str, str]] = {
    # --- 42 CFR 410.38: real requirements NOT transcribed ---------------------
    "42_CFR_410_38_20260813_ConditionsofPayment_d1iiA": (
        "REQUIRES_HUMAN_REVIEW",
        "GAP: requires the written order to reach the supplier PRIOR TO DELIVERY for "
        "items on the face-to-face list. A distinct timing requirement, checkable "
        "against a submission, and not represented by any transcribed criterion.",
    ),
    "42_CFR_410_38_20260813_ConditionsofPayment_d1iiB": (
        "REQUIRES_HUMAN_REVIEW",
        "GAP: for all other DMEPOS the order must reach the supplier prior to claim "
        "submission. Second timing requirement, not transcribed.",
    ),
    "42_CFR_410_38_20260813_ConditionsofPayment_d3": (
        "REQUIRES_HUMAN_REVIEW",
        "GAP: supplier must maintain the order and supporting documentation and make "
        "it available to CMS. A documentation-retention requirement; whether it is "
        "decision-relevant at authorisation time or only at audit is precisely the "
        "judgement a qualified reviewer should make.",
    ),
    "42_CFR_410_38_20260813_ConditionsofPayment_d3ii": (
        "REQUIRES_HUMAN_REVIEW",
        "GAP: the face-to-face encounter must be documented in the medical record with "
        "beneficiary-specific subjective and objective information. Transcribed "
        "criterion C04 covers the encounter's TIMING but not its DOCUMENTATION.",
    ),
    "42_CFR_410_38_20260813_ConditionsofPayment_d2i": (
        "REQUIRES_HUMAN_REVIEW",
        "GAP: the encounter must be for the purpose of diagnosing, treating or managing "
        "the condition the item is ordered for. A purpose requirement distinct from "
        "timing, and not transcribed.",
    ),
    # Same provisions in the 2022 revision.
    "42_CFR_410_38_20220101_ConditionsofPayment_d1iiA": (
        "REQUIRES_HUMAN_REVIEW",
        "GAP: prior-to-delivery timing requirement, as in the 2026 revision.",
    ),
    "42_CFR_410_38_20220101_ConditionsofPayment_d1iiB": (
        "REQUIRES_HUMAN_REVIEW",
        "GAP: prior-to-claim-submission timing requirement, as in the 2026 revision.",
    ),
    # --- 42 CFR 410.32 --------------------------------------------------------
    "42_CFR_410_32_20260813_Orderingdiagnosticte_a3": (
        "REQUIRES_HUMAN_REVIEW",
        "GAP: nonphysician practitioners may order tests under stated conditions. "
        "Affects who may legitimately order, which criterion C01 addresses only for "
        "physicians.",
    ),
    "42_CFR_410_32_20260813_Paragraphb_b3": (
        "REQUIRES_HUMAN_REVIEW",
        "GAP: defines the supervision LEVELS (general, direct, personal). Criterion C03 "
        "requires 'the appropriate level' without capturing which level applies to "
        "which test - so the criterion is not checkable on its own.",
    ),
    # --- 42 CFR 410.33 --------------------------------------------------------
    "42_CFR_410_33_20260813_Applicationcertifica_g6": (
        "NON_DECISION_RELEVANT",
        "IDTF supplier enrolment and certification standards. Governs whether a facility "
        "may bill Medicare at all, not whether a particular request meets medical "
        "necessity. A prior-authorization decision does not re-adjudicate enrolment.",
    ),
    "42_CFR_410_33_20260813_Applicationcertifica_g6i": (
        "NON_DECISION_RELEVANT",
        "Enrolment documentation retained by the supplier; same reasoning as (g)(6).",
    ),
}

#: Rules applied in order. The first match wins, and its reason is recorded.
RULES: list[tuple[str, tuple[str, ...], str, str]] = [
    (
        "definition",
        ("means ", "has the same meaning", "as used in this section", "as used in this paragraph"),
        "NON_DECISION_RELEVANT",
        "Definitional. Fixes the meaning of a term used by other provisions; adds no "
        "requirement a submission could satisfy or fail on its own.",
    ),
    (
        "cross_reference",
        ("of this chapter", "of the Act", "see §", "subpart", "part 4"),
        "REQUIRES_HUMAN_REVIEW",
        "Incorporates requirements from another part by reference. Whether the "
        "incorporated text carries a decision-relevant condition cannot be settled "
        "without reading that part, which is outside the ingested corpus.",
    ),
    (
        "cms_authority",
        ("CMS may", "at any time and without", "the Secretary may", "CMS will"),
        "NON_DECISION_RELEVANT",
        "Grants administrative discretion to CMS. Describes what the agency may do, not "
        "a condition a request satisfies.",
    ),
    (
        "refill_delivery",
        (
            "refill",
            "shipping date",
            "delivery slip",
            "date of service for",
            "retrieved for delivery",
        ),
        "NON_DECISION_RELEVANT",
        "Governs refills, delivery and date-of-service assignment after an item is "
        "authorised. Out of scope for an initial authorisation decision.",
    ),
    (
        "supplier_enrolment",
        (
            "supplier number",
            "enrol",
            "accreditation",
            "certification standards",
            "billing privileges",
        ),
        "NON_DECISION_RELEVANT",
        "Supplier enrolment and standards. Determines who may bill, not whether this "
        "request is medically necessary.",
    ),
    (
        "payment_mechanics",
        ("fee schedule", "payment amount", "reimbursed", "carriers will pay", "payment is made"),
        "NON_DECISION_RELEVANT",
        "Payment methodology. Concerns how much is paid once coverage is established.",
    ),
    (
        "exclusion_enumeration",
        ("not covered", "excluded from coverage", "does not apply", "are excluded"),
        "REQUIRES_HUMAN_REVIEW",
        "States an exclusion. Exclusions are decision-relevant by nature; whether this "
        "one applies to the procedures in scope needs a qualified reading.",
    ),
    (
        "obligation",
        ("must", "shall", "required", "only if", "only when"),
        "REQUIRES_HUMAN_REVIEW",
        "Carries obligation language and is not represented by any transcribed "
        "criterion. Whether it is decision-relevant for the procedures in scope is "
        "exactly the judgement OD-19 says is unverified.",
    ),
]


def classify(text: str) -> tuple[str, str]:
    lowered = text.lower()
    for _, terms, classification, reason in RULES:
        if any(term.lower() in lowered for term in terms):
            return classification, reason
    return (
        "REQUIRES_HUMAN_REVIEW",
        "No rule placed this provision confidently. Defaulting to review rather than "
        "to 'not relevant', because the cost of a wrong dismissal is an invisible gap.",
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--matrix", default="data/criteria/coverage_matrix.jsonl")
    parser.add_argument("--out", default="data/criteria/coverage_classifications.yaml")
    parser.add_argument("--write", action="store_true")
    args = parser.parse_args()

    rows = [
        json.loads(line) for line in (REPO / args.matrix).read_text().splitlines() if line.strip()
    ]
    provisions: dict[str, dict[str, Any]] = {}

    for row in rows:
        if row["criterion_ids"]:
            continue  # already represented
        if not row["substantive"]:
            provisions[row["provision_id"]] = {
                "classification": "NON_DECISION_RELEVANT",
                "reason": "Structural fragment below the substantive length threshold - a "
                "heading echo, a list stub or a cross-reference tail. Enumerated "
                "rather than dropped so the denominator stays complete.",
                "method": "rule:fragment",
            }
            continue
        if row["provision_id"] in MANUAL_OVERRIDES:
            classification, reason = MANUAL_OVERRIDES[row["provision_id"]]
            provisions[row["provision_id"]] = {
                "classification": classification,
                "reason": reason,
                "method": "manual",
            }
            continue
        classification, reason = classify(row["text"])
        provisions[row["provision_id"]] = {
            "classification": classification,
            "reason": reason,
            "method": "rule",
        }

    payload = {
        "schema_version": "1",
        "generated_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "classifier": "engineering (non-clinician), rule-assisted with manual overrides",
        "caveat": (
            "These classifications are a non-clinician's judgement about what bears on a "
            "prior-authorization decision. That judgement is what OD-19 identifies as "
            "unverified. REQUIRES_HUMAN_REVIEW entries are not deferred work items - they "
            "are the honest state of the analysis."
        ),
        "provisions": provisions,
    }

    counts = Counter(entry["classification"] for entry in provisions.values())
    methods = Counter(entry["method"] for entry in provisions.values())
    print(f"  classified {len(provisions)} unrepresented provisions")
    for label, count in sorted(counts.items()):
        print(f"    {label:<26} {count}")
    print(f"  by method: {dict(methods)}")

    if args.write:
        (REPO / args.out).write_text(
            yaml.safe_dump(payload, sort_keys=False, allow_unicode=True, width=100),
            encoding="utf-8",
        )
        print(f"  written to {args.out}")
    else:
        print("  (dry run; pass --write)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
