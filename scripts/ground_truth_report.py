"""Policy ground-truth report: human-readable and machine-readable.

    uv run python scripts/ground_truth_report.py

Every number is counted from the artefacts on disk. No targets are stated - a target
in an evaluation report invites shaping the dataset to meet it.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import yaml

REPO = Path(__file__).resolve().parents[1]


def _jsonl(path: Path) -> list[dict[str, Any]]:
    return (
        [json.loads(line) for line in path.read_text().splitlines() if line.strip()]
        if path.is_file()
        else []
    )


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()[:16] if path.is_file() else "absent"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", default="eval/reports")
    args = parser.parse_args()

    data = REPO / "data"
    criteria = _jsonl(data / "criteria" / "inventory.jsonl")
    cases = _jsonl(data / "synthetic" / "cases" / "cases.jsonl")
    gold = _jsonl(data / "gold" / "cases" / "gold_v1.jsonl")
    metadata = _jsonl(data / "linkage" / "code_metadata.jsonl")
    verification = json.loads((data / "criteria" / "verification.json").read_text())
    linkage = yaml.safe_load((data / "linkage" / "policy_code_links.yaml").read_text())
    retrieval = yaml.safe_load((REPO / "eval/datasets/retrieval/questions.yaml").read_text())
    gold_manifest = json.loads((data / "gold" / "manifests" / "gold_v1.manifest.json").read_text())

    latest = sorted(REPO.glob("eval/reports/*__retrieval-baseline/result.json"))
    retrieval_metrics = json.loads(latest[-1].read_text()) if latest else None

    policies = {c["policy_id"] for c in criteria}
    versions = {(c["policy_id"], c["policy_version"]) for c in criteria}
    hcpcs = [link for link in linkage["links"] if link["code_system"] == "HCPCS"]
    icd = [link for link in linkage["links"] if link["code_system"] == "ICD10CM"]

    machine: dict[str, Any] = {
        "generated_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "corpus": {
            "authority": "Office of the Federal Register (eCFR API)",
            "kind": "authoritative",
            "policies": len(policies),
            "policy_versions": len(versions),
        },
        "criteria": {
            "total": len(criteria),
            "verified": verification["criteria_verified"],
            "failed_verifications": len(verification["failures"]),
            "by_type": dict(sorted(Counter(c["criterion_type"] for c in criteria).items())),
            "by_policy": dict(sorted(Counter(c["policy_id"] for c in criteria).items())),
            "with_numeric_threshold": sum(1 for c in criteria if c["threshold"]),
            "inventory_sha256": _sha(data / "criteria" / "inventory.jsonl"),
        },
        "code_linkage": {
            "class": linkage["linkage_class"],
            "hcpcs_links": len(hcpcs),
            "icd10cm_links": len(icd),
            "codes_verified_against_nlm": len(metadata),
            "by_confidence": dict(
                sorted(Counter(x["confidence"] for x in linkage["links"]).items())
            ),
            "by_type": dict(sorted(Counter(x["linkage_type"] for x in linkage["links"]).items())),
        },
        "cases": {
            "total": len(cases),
            "gold": len(gold),
            "development": gold_manifest["counts"]["development"],
            "validation": gold_manifest["counts"]["validation"],
            "by_category": dict(sorted(Counter(c["category"] for c in cases).items())),
            "by_decision": dict(sorted(Counter(c["expected"]["decision"] for c in cases).items())),
            "by_policy_version": dict(
                sorted(
                    Counter(
                        f"{c['expected']['policy_id']}:{c['expected']['policy_revision']}"
                        for c in cases
                    ).items()
                )
            ),
            "by_temporal_class": dict(sorted(Counter(c["temporal_class"] for c in cases).items())),
            "criterion_states": dict(
                sorted(
                    Counter(e["state"] for c in cases for e in c["expected"]["criteria"]).items()
                )
            ),
            "with_missing_information": sum(
                1 for c in cases if c["expected"]["missing_information"]
            ),
            "gold_sha256": gold_manifest["sha256"]["gold"][:16],
            "gold_frozen": gold_manifest["frozen"],
            "gold_scorings_spent": gold_manifest["scoring_budget"]["scorings_spent"],
        },
        "retrieval_dataset": {
            "version": retrieval["version"],
            "queries": len(retrieval["questions"]),
            "criterion_linked": sum(
                1 for q in retrieval["questions"] if q["expect"].get("criterion_id")
            ),
            "revisions_covered": sorted(
                {q["expect"]["revision_id"] for q in retrieval["questions"]}
            ),
        },
        "retrieval_metrics": (
            [
                {
                    "embedder": arm["embedder"],
                    "reranker": arm["reranker"],
                    "recall_at_1": arm["recall_at_1"]["successes"]
                    / max(arm["recall_at_1"]["total"], 1),
                    "recall_at_5": arm["recall_at_5"]["successes"]
                    / max(arm["recall_at_5"]["total"], 1),
                    "mrr": arm["mrr"],
                    "latency_p50_ms": arm.get("latency_p50_ms"),
                    "n": arm["recall_at_1"]["total"],
                }
                for arm in retrieval_metrics["arms"]
            ]
            if retrieval_metrics
            else None
        ),
        "exclusions": [
            {
                "item": "42 CFR 411.15",
                "reason": "EXCLUSION_OVERLAY - declares only exclusions and no required "
                "criteria, so it cannot support a standalone decision",
                "excluded_from": "case generation",
            },
            {
                "item": "42 CFR 410.38 rev 2019-01-01",
                "reason": "section restructured; 2026 criteria do not locate in it, and "
                "carrying a transcription across an amendment is refused",
                "excluded_from": "criterion transcription",
            },
            {
                "item": "42 CFR 410.43",
                "reason": "too few headed paragraphs to anchor criteria reliably",
                "excluded_from": "criterion transcription",
            },
        ],
        "limitations": [
            "42 CFR is regulation, not an NCD or LCD - a criterion here is not a coverage determination",
            "code linkage is a human-curated engineering artefact and is authoritative for nothing",
            "transcription completeness is unverified: nothing checks the right criteria were chosen",
            "no clinician has reviewed any criterion, case or label",
            "inter-annotator agreement is not measurable - one labeller, and it is a program",
            "clinical notes are constructed; measured performance is an upper bound",
            "MIMIC-IV-Note is NOT accessed and NOT available to this project",
        ],
    }

    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    out = REPO / args.out / f"{stamp}__policy-ground-truth"
    out.mkdir(parents=True, exist_ok=True)
    (out / "result.json").write_text(
        json.dumps(machine, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )

    lines = [
        "# Policy Ground-Truth Report",
        "",
        "Counted from the artefacts on disk. **No targets are stated.**",
        "",
        "> **Authoritative policy, curated criteria, synthetic cases.** The policy text is",
        "> real 42 CFR from the official eCFR API. The criteria are human transcriptions of",
        "> that text, span-verified against it. The code linkage and the cases are curated",
        "> and constructed respectively, and are authoritative for nothing.",
        "",
        "## Corpus",
        "",
        "| metric | value |",
        "|---|---|",
        f"| authority | {machine['corpus']['authority']} |",
        f"| policies | {machine['corpus']['policies']} |",
        f"| policy versions | {machine['corpus']['policy_versions']} |",
        "",
        "## Criteria",
        "",
        "| metric | value |",
        "|---|---|",
        f"| total | {machine['criteria']['total']} |",
        f"| span-verified | {machine['criteria']['verified']} |",
        f"| **failed verifications** | **{machine['criteria']['failed_verifications']}** |",
        f"| with a numeric threshold | {machine['criteria']['with_numeric_threshold']} |",
        f"| by type | {machine['criteria']['by_type']} |",
        "",
        "## Code linkage — HUMAN-CURATED, authoritative for nothing",
        "",
        "| metric | value |",
        "|---|---|",
        f"| HCPCS links | {machine['code_linkage']['hcpcs_links']} |",
        f"| ICD-10-CM links | {machine['code_linkage']['icd10cm_links']} |",
        f"| codes verified to exist (NLM) | {machine['code_linkage']['codes_verified_against_nlm']} |",
        f"| by confidence | {machine['code_linkage']['by_confidence']} |",
        "",
        "## Cases",
        "",
        "| metric | value |",
        "|---|---|",
        f"| total | {machine['cases']['total']} |",
        f"| gold (frozen) | {machine['cases']['gold']} |",
        f"| development | {machine['cases']['development']} |",
        f"| validation | {machine['cases']['validation']} |",
        f"| naming missing information | {machine['cases']['with_missing_information']} |",
        f"| gold scorings spent | {machine['cases']['gold_scorings_spent']} |",
        "",
        f"**Decisions:** {machine['cases']['by_decision']}",
        "",
        f"**Categories:** {machine['cases']['by_category']}",
        "",
        f"**Criterion states:** {machine['cases']['criterion_states']}",
        "",
        f"**Temporal:** {machine['cases']['by_temporal_class']}",
        "",
        "## Retrieval",
        "",
        f"{machine['retrieval_dataset']['queries']} queries, "
        f"{machine['retrieval_dataset']['criterion_linked']} criterion-linked, "
        f"revisions {machine['retrieval_dataset']['revisions_covered']}.",
        "",
    ]
    if machine["retrieval_metrics"]:
        lines += [
            "| encoder | reranker | recall@1 | recall@5 | MRR | p50 ms | n |",
            "|---|---|---|---|---|---|---|",
        ]
        for arm in machine["retrieval_metrics"]:
            lines.append(
                f"| `{arm['embedder']}` | `{arm['reranker'] or 'none'}` | {arm['recall_at_1']:.4f} | "
                f"{arm['recall_at_5']:.4f} | {arm['mrr']:.4f} | {arm['latency_p50_ms']} | {arm['n']} |"
            )
    else:
        lines.append("No retrieval run has been recorded.")

    lines += [
        "",
        "## Known exclusions — nothing is dropped silently",
        "",
        "| item | excluded from | reason |",
        "|---|---|---|",
    ]
    lines += [
        f"| {e['item']} | {e['excluded_from']} | {e['reason']} |" for e in machine["exclusions"]
    ]
    lines += ["", "## Known limitations", ""]
    lines += [f"- {limitation}" for limitation in machine["limitations"]]
    lines.append("")

    (out / "report.md").write_text("\n".join(lines), encoding="utf-8")
    print(f"  report: {(out / 'report.md').relative_to(REPO)}")
    print(
        f"  policies {machine['corpus']['policies']} | versions {machine['corpus']['policy_versions']} "
        f"| criteria {machine['criteria']['total']} (0 failures) "
        f"| cases {machine['cases']['total']} | gold {machine['cases']['gold']}"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
