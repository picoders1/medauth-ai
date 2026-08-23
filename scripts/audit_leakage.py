#!/usr/bin/env python
"""Audit dataset independence: development, validation, gold, retrieval (Part G).

Two different questions, and conflating them would let a real problem hide behind
a clean answer to the easy one.

**Split leakage.** Does a case appear in more than one split? The split rule is
deterministic - `int(sha256(normalised_key(text))[:8], 16) % 100`, dev if < 20 -
so this is checked by recomputing it, not by trusting the recorded partition.

**Construction leakage.** Is the retrieval benchmark built from the same artefacts
that determine the production retrieval result? This is the subtler one and it is
where v1 was weak: its queries were authored against the linkage table, so
resolution accuracy of 1.0000 measured that the table was self-consistent rather
than that resolution works.

Where overlap is unavoidable it is reported, not hidden. A retrieval benchmark for
a policy corpus must reference the policies in that corpus; the question is whether
it references *the artefact that decides the answer*.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
from collections import Counter
from pathlib import Path
from typing import Any

import yaml

REPO = Path(__file__).resolve().parents[1]
GOLD = REPO / "data/gold/cases/gold_v1.jsonl"
CASES = REPO / "data/synthetic/cases/cases.jsonl"
DEV = REPO / "data/synthetic/cases/development.jsonl"
VALIDATION = REPO / "data/synthetic/cases/validation.jsonl"
RETRIEVAL_V1 = REPO / "eval/datasets/retrieval/questions.yaml"
RETRIEVAL_V2 = REPO / "eval/datasets/retrieval_v2/questions.yaml"
LINKAGE = REPO / "data/linkage/policy_code_links.yaml"
OUT = REPO / "data/review/leakage_audit.json"

#: Mirrors scripts/build_gold_set.py. Reproduced, not imported, so that a change
#: there is caught here rather than blessed by it.
DEV_FRACTION = 0.18
VALIDATION_FRACTION = 0.10


def _jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    return [
        json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()
    ]


def _normalised_key(text: str) -> str:
    """The project's split key. Reproduced here so drift in it is detectable."""
    return re.sub(r"\s+", " ", text.strip().lower())


def _bucket(text: str) -> int:
    return int(hashlib.sha256(_normalised_key(text).encode()).hexdigest()[:8], 16) % 100


def _case_text(case: dict[str, Any]) -> str:
    payload = case.get("input", {})
    return str(
        payload.get("clinical_note") or payload.get("note") or json.dumps(payload, sort_keys=True)
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--write", action="store_true")
    args = parser.parse_args()

    findings: list[dict[str, Any]] = []

    # --- 1. Case identity overlap between splits ---------------------------
    splits = {
        "gold": _jsonl(GOLD),
        "development": _jsonl(DEV),
        "validation": _jsonl(VALIDATION),
    }
    ids = {name: {c["case_id"] for c in cases} for name, cases in splits.items() if cases}
    overlaps = {}
    for a in ids:
        for b in ids:
            if a < b:
                shared = ids[a] & ids[b]
                if shared:
                    overlaps[f"{a}|{b}"] = sorted(shared)
    findings.append(
        {
            "check": "case_id_overlap_between_splits",
            "status": "FAIL" if overlaps else "PASS",
            "detail": overlaps or "no case_id appears in more than one split",
            "sizes": {k: len(v) for k, v in ids.items()},
        }
    )

    # --- 2. Note-text overlap, which case ids would not catch ---------------
    texts = {
        name: Counter(_normalised_key(_case_text(c)) for c in cases)
        for name, cases in splits.items()
        if cases
    }
    text_overlaps = {}
    for a in texts:
        for b in texts:
            if a < b:
                shared = set(texts[a]) & set(texts[b])
                if shared:
                    text_overlaps[f"{a}|{b}"] = len(shared)
    findings.append(
        {
            "check": "note_text_overlap_between_splits",
            "status": "FAIL" if text_overlaps else "PASS",
            "detail": text_overlaps or "no normalised note text appears in more than one split",
            "note": (
                "Checked separately from case ids because a regenerated case can carry a "
                "new id and identical text, which is leakage that an id check cannot see."
            ),
        }
    )

    # --- 3. Does the recorded partition match the deterministic rule? -------
    #
    # The rule is `scripts/build_gold_set.py:_partition`: within each stratum
    # (policy, revision, category), order by sha256(case_id)[:8] and take exact
    # counts. It is reproduced here rather than imported, so that a change to the
    # generator is caught by this audit instead of being silently blessed by it.
    #
    # Note this is NOT the hash-bucket rule that governs `eval/datasets/**`
    # corpora. Two different splits exist in this project and applying either
    # rule to the other's data reports a fault that is not there - which is what
    # the first version of this check did.
    all_cases = _jsonl(CASES)
    strata: dict[tuple[str, str, str], list[str]] = {}
    for case in all_cases:
        key = (
            case["expected"]["policy_id"],
            case["expected"]["policy_revision"],
            case["category"],
        )
        strata.setdefault(key, []).append(case["case_id"])

    expected_assignment: dict[str, str] = {}
    for case_ids in strata.values():
        ordered = sorted(
            case_ids, key=lambda cid: int(hashlib.sha256(cid.encode()).hexdigest()[:8], 16)
        )
        total = len(ordered)
        n_dev, n_val = round(total * DEV_FRACTION), round(total * VALIDATION_FRACTION)
        if n_dev + n_val >= total:
            n_dev, n_val = (1, 0) if total > 1 else (0, 0)
        for index, case_id in enumerate(ordered):
            expected_assignment[case_id] = (
                "development"
                if index < n_dev
                else "validation"
                if index < n_dev + n_val
                else "gold"
            )

    # `cases.jsonl` carries no partition - the assignment lives in the split
    # files, which is where a mis-partitioned case would actually do harm.
    recorded = {case["case_id"]: name for name, cases in splits.items() for case in cases}
    mismatches = [
        {
            "case_id": case_id,
            "recorded": name,
            "rule_implies": expected_assignment.get(case_id),
        }
        for case_id, name in sorted(recorded.items())
        if expected_assignment.get(case_id) != name
    ]
    findings.append(
        {
            "check": "partition_matches_the_deterministic_split_rule",
            "status": "PASS" if not mismatches else "FAIL",
            "detail": mismatches[:10]
            or f"all {len(recorded)} split cases sit where the rule puts them",
            "rule": (
                "stratified by (policy_id, revision, category); within a stratum order by "
                f"int(sha256(case_id)[:8], 16) and take dev={DEV_FRACTION}, "
                f"validation={VALIDATION_FRACTION} as exact counts"
            ),
            "note": (
                "The [:8] slice matters: using the full digest reorders every stratum and "
                "silently moves cases between partitions."
            ),
        }
    )

    # --- 4. Construction leakage: retrieval sets vs the linkage table -------
    linkage = yaml.safe_load(LINKAGE.read_text(encoding="utf-8"))
    linked_codes = {str(link["code"]) for link in linkage["links"]}

    retrieval: dict[str, dict[str, Any]] = {}
    for label, path in (("v1", RETRIEVAL_V1), ("v2", RETRIEVAL_V2)):
        if not path.exists():
            continue
        spec = yaml.safe_load(path.read_text(encoding="utf-8"))
        questions = spec["questions"]
        codes = {str(q["procedure_code"]) for q in questions}
        retrieval[label] = {
            "queries": len(questions),
            "distinct_codes": len(codes),
            "codes_from_linkage_table": len(codes & linked_codes),
            "codes_not_in_linkage_table": sorted(codes - linked_codes),
        }
    findings.append(
        {
            "check": "retrieval_queries_reuse_the_linkage_table",
            "status": "KNOWN_LIMITATION",
            "detail": retrieval,
            "note": (
                "UNAVOIDABLE AND REPORTED. Deterministic resolution is a lookup on the "
                "linkage table, so any query that must resolve has to use a code the table "
                "contains - there is no code outside it that could resolve to anything. The "
                "consequence is precise: **resolution accuracy on either retrieval set "
                "measures the table's self-consistency, not whether resolution generalises.** "
                "It is not evidence that resolution works on codes nobody curated. Ranking "
                "quality is unaffected, because the ranking target is the section, which the "
                "linkage table says nothing about."
            ),
        }
    )

    # --- 5. Does the retrieval benchmark reuse gold case text? --------------
    gold_texts = {_normalised_key(_case_text(c)) for c in splits.get("gold", [])}
    shared_with_gold = {}
    for label, path in (("v1", RETRIEVAL_V1), ("v2", RETRIEVAL_V2)):
        if not path.exists():
            continue
        spec = yaml.safe_load(path.read_text(encoding="utf-8"))
        hits = [q["id"] for q in spec["questions"] if _normalised_key(str(q["text"])) in gold_texts]
        if hits:
            shared_with_gold[label] = hits
    findings.append(
        {
            "check": "retrieval_query_text_reused_from_gold_cases",
            "status": "FAIL" if shared_with_gold else "PASS",
            "detail": shared_with_gold or "no retrieval query text appears in any gold case",
        }
    )

    # --- 6. Are v1 and v2 independent of each other? -----------------------
    independence: dict[str, Any] = {"status": "NOT_APPLICABLE"}
    if RETRIEVAL_V1.exists() and RETRIEVAL_V2.exists():
        v1 = {
            _normalised_key(str(q["text"]))
            for q in yaml.safe_load(RETRIEVAL_V1.read_text(encoding="utf-8"))["questions"]
        }
        v2 = {
            _normalised_key(str(q["text"]))
            for q in yaml.safe_load(RETRIEVAL_V2.read_text(encoding="utf-8"))["questions"]
        }
        shared = sorted(v1 & v2)
        independence = {
            "shared_query_text": shared,
            "v1_queries": len(v1),
            "v2_queries": len(v2),
        }
    findings.append(
        {
            "check": "retrieval_v2_is_independent_of_v1",
            "status": "FAIL" if independence.get("shared_query_text") else "PASS",
            "detail": independence,
            "note": (
                "v2 must not inherit v1's queries, or a comparison between the two would "
                "measure the shared subset twice and the numbers would not be independent."
            ),
        }
    )

    report = {
        "findings": findings,
        "overall": (
            "FAIL"
            if any(f["status"] == "FAIL" for f in findings)
            else "PASS_WITH_KNOWN_LIMITATION"
            if any(f["status"] == "KNOWN_LIMITATION" for f in findings)
            else "PASS"
        ),
    }

    for finding in findings:
        print(f"  {finding['status']:20s} {finding['check']}")
    print(f"\n  overall: {report['overall']}")

    if args.write:
        OUT.parent.mkdir(parents=True, exist_ok=True)
        OUT.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        print(f"  written to {OUT.relative_to(REPO)}")
    else:
        print("\n  (dry run; pass --write)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
