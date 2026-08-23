"""Build the policy-criteria coverage matrix (OD-19, Part A).

    uv run python scripts/build_coverage_matrix.py

Enumerates every provision in every policy version and pairs it with the criterion
representing it, if any. Provisions with no criterion are emitted as
``UNCLASSIFIED`` and **must** be classified by a human into exactly one of:

    REPRESENTED_CRITERION | NON_DECISION_RELEVANT | REQUIRES_HUMAN_REVIEW

Classifications live in ``data/criteria/coverage_classifications.yaml``, keyed by
provision id, each with a reason. This script never invents one: an unclassified
provision stays unclassified and is counted as such, because a completeness report
whose denominator quietly excluded what nobody looked at would be worse than no
report.
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

from app.core.normalize import normalize_text
from app.policy.acquire import LocalDirectorySource
from app.policy.documents import ParsedDocument
from app.policy.parse import parse_document
from app.policy.provisions import Provision, extract_provisions

REPO = Path(__file__).resolve().parents[1]

VALID_CLASSES = {
    "REPRESENTED_CRITERION",
    "NON_DECISION_RELEVANT",
    "REQUIRES_HUMAN_REVIEW",
}


def _criteria_by_version(path: Path) -> dict[tuple[str, str], list[dict[str, Any]]]:
    index: dict[tuple[str, str], list[dict[str, Any]]] = {}
    for line in path.read_text().splitlines():
        if not line.strip():
            continue
        row = json.loads(line)
        index.setdefault((row["policy_id"], row["policy_version"]), []).append(row)
    return index


def _match_criteria(provision: Provision, criteria: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Every criterion whose authoritative text lies inside this provision.

    Containment, not similarity. A criterion was verified against a span of the
    source; the provision containing that span is the one it represents. Matching
    on resemblance would let a criterion appear to cover a provision it never cited.

    **A provision may represent several criteria.** 42 CFR 410.61's plan-content
    sentence carries two distinct requirements - the parameters to prescribe, and
    the diagnosis and goals to state - and an earlier version of this matcher
    returned only the first, leaving four criteria looking unrepresented.
    """
    body = normalize_text(provision.text)
    return [
        criterion
        for criterion in criteria
        if criterion["source_section"] == provision.section_path
        and normalize_text(criterion["authoritative_text"]) in body
    ]


def _requirement_type(provision: Provision) -> str:
    """A first-pass label from the provision's own language.

    Advisory only. It orders a reviewer's attention; it does not decide relevance,
    and the matrix records it separately from the human classification so the two
    are never confused.
    """
    text = provision.text.lower()
    checks: list[tuple[str, tuple[str, ...]]] = [
        ("exclusion", ("not covered", "excluded from coverage", "may not be", "does not apply")),
        ("documentation", ("documented", "documentation", "record must", "maintain")),
        ("order_prescription", ("written order", "prescription", "ordered by", "order must")),
        ("timing", ("within", "preceding", "prior to", "before treatment", "days", "months")),
        ("frequency_duration", ("no more than", "frequency", "duration", "per year")),
        ("setting", ("in the home", "place of residence", "institution", "facility")),
        ("eligibility", ("eligible", "qualif", "entitled")),
        ("personnel", ("supervis", "physician", "practitioner", "technician", "personnel")),
        ("diagnostic_finding", ("diagnosis", "findings", "examination", "test result")),
        ("prior_treatment", ("conservative", "prior treatment", "failed", "trial of")),
        ("definition", ("means", "as used in this section", "has the same meaning")),
        ("limitation", ("limited to", "limitation", "restrict")),
        ("prerequisite", ("only if", "only when", "provided that", "conditions")),
    ]
    for label, terms in checks:
        if any(term in text for term in terms):
            return label
    return "other"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--corpus", default="data/cms")
    parser.add_argument("--criteria", default="data/criteria/inventory.jsonl")
    parser.add_argument("--classifications", default="data/criteria/coverage_classifications.yaml")
    parser.add_argument("--out", default="data/criteria/coverage_matrix.jsonl")
    args = parser.parse_args()

    criteria_index = _criteria_by_version(REPO / args.criteria)

    classifications: dict[str, dict[str, Any]] = {}
    classification_path = REPO / args.classifications
    if classification_path.is_file():
        loaded = yaml.safe_load(classification_path.read_text(encoding="utf-8")) or {}
        classifications = loaded.get("provisions", {}) or {}
        bad = {
            pid: entry.get("classification")
            for pid, entry in classifications.items()
            if entry.get("classification") not in VALID_CLASSES
        }
        if bad:
            print(f"invalid classification(s): {bad}", file=sys.stderr)
            return 1
        missing_reason = [pid for pid, e in classifications.items() if not e.get("reason")]
        if missing_reason:
            print(
                f"{len(missing_reason)} classification(s) have no reason: {missing_reason[:5]}",
                file=sys.stderr,
            )
            return 1

    rows: list[dict[str, Any]] = []
    for acquired in LocalDirectorySource(REPO / args.corpus).documents():
        document: ParsedDocument = parse_document(acquired.raw, acquired.source)
        identity = document.identity
        key = (identity.policy_id, identity.revision_id)
        criteria = criteria_index.get(key, [])

        for provision in extract_provisions(
            document.sections, policy_id=key[0], policy_version=key[1]
        ):
            matched = _match_criteria(provision, criteria)
            declared = classifications.get(provision.id, {})

            if matched:
                classification = "REPRESENTED_CRITERION"
                reason = (
                    f"{len(matched)} verified criterion/criteria have authoritative text "
                    "within this provision"
                )
            elif declared:
                classification = str(declared["classification"])
                reason = str(declared["reason"])
            else:
                classification = "UNCLASSIFIED"
                reason = ""

            rows.append(
                {
                    "provision_id": provision.id,
                    "policy_id": provision.policy_id,
                    "policy_version": provision.policy_version,
                    "section_path": provision.section_path,
                    "paragraph_path": provision.path,
                    "level": provision.level,
                    "page": provision.page,
                    "requirement_type": _requirement_type(provision),
                    "criterion_ids": [c["criterion_id"] for c in matched],
                    "decision_relevant": classification == "REPRESENTED_CRITERION"
                    or (classification == "REQUIRES_HUMAN_REVIEW"),
                    "transcribed": bool(matched),
                    "verified": bool(matched),
                    "classification": classification,
                    "reason": reason,
                    "reviewer_status": "NOT_REVIEWED",
                    "substantive": provision.is_substantive,
                    "obligation_markers": list(provision.obligation_markers),
                    "text": provision.text[:400],
                }
            )

    out = REPO / args.out
    out.write_text("\n".join(json.dumps(r, sort_keys=True) for r in rows) + "\n", encoding="utf-8")

    by_class = Counter(r["classification"] for r in rows)
    substantive = [r for r in rows if r["substantive"]]
    unclassified = [r for r in substantive if r["classification"] == "UNCLASSIFIED"]

    needs_review = [r for r in substantive if r["classification"] == "REQUIRES_HUMAN_REVIEW"]

    summary = {
        "generated_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "provisions_total": len(rows),
        "provisions_substantive": len(substantive),
        "by_classification": dict(sorted(by_class.items())),
        "unclassified_substantive": len(unclassified),
        # Every provision carries a classification. This is a property of the WALK
        # being exhaustive, and says nothing about whether the classifications are
        # right.
        "walk_exhaustive": not unclassified,
        "provisions_awaiting_review": len(needs_review),
        # Completeness is verified only when a qualified reviewer has resolved every
        # REQUIRES_HUMAN_REVIEW provision. Equating "everything has a label" with
        # "completeness proven" would convert an unknown into a pass, which is the
        # single easiest way to make this analysis worthless.
        "completeness_verified": not unclassified and not needs_review,
        "completeness_blocked_by": (
            f"{len(needs_review)} provision(s) awaiting qualified review" if needs_review else None
        ),
    }
    (REPO / "data/criteria/coverage_summary.json").write_text(
        json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )

    print(f"  provisions            {len(rows)} ({len(substantive)} substantive)")
    for label, count in sorted(by_class.items()):
        print(f"    {label:<26} {count}")
    print(f"  unclassified substantive: {len(unclassified)}")
    print(f"  walk exhaustive:          {summary['walk_exhaustive']}")
    print(f"  awaiting qualified review: {summary['provisions_awaiting_review']}")
    print(
        f"  COMPLETENESS VERIFIED:    {summary['completeness_verified']}"
        + (
            f"  ({summary['completeness_blocked_by']})"
            if summary["completeness_blocked_by"]
            else ""
        )
    )
    if unclassified:
        print("\n  highest-signal unclassified provisions:")
        for row in sorted(unclassified, key=lambda r: -len(r["obligation_markers"]))[:12]:
            print(
                f"    {row['provision_id']:<52} {row['requirement_type']:<18} "
                f"{len(row['obligation_markers'])} markers"
            )
    return 0


if __name__ == "__main__":
    sys.exit(main())
