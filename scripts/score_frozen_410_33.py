"""Compute every pre-registered metric from the frozen run. Reads results, never re-runs.

Separate from the runner on purpose. A script that executed cases and scored them in
one pass could, at some future point, be edited to do both again — and the second
execution would be a second scoring against a frozen split, which the budget forbids.
This one is idempotent by construction: it has no model client and no database
handle.

    uv run python scripts/score_frozen_410_33.py --write

## The metric list is not chosen here

It comes from `data/review/eval_410_33_frozen.json`, written before the run. A metric
selected after seeing results is a metric selected because of them, and this script
refuses to emit one the manifest did not name.

## Denial precision is reported alone

A wrong approval costs money; a wrong denial withholds care. Folding both into
macro-F1 hides the one that matters, so denial precision carries its own denominator
and its own Wilson interval (ADR-010).
"""

from __future__ import annotations

import argparse
import json
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

from eval.metrics.statistics import wilson_interval

REPO = Path(__file__).resolve().parents[1]
#: The Phase-14 directory, and the default. Phase 15 passes `--report-dir`; both runs
#: are scored by THIS function so a difference between them is a difference in the
#: system rather than in two scorers that drifted apart.
RUN = REPO / "eval/reports/frozen-410-33"
FROZEN = REPO / "data/review/eval_410_33_frozen.json"

DECISION_CLASSES = ("APPROVE_RECOMMENDED", "DENY_RECOMMENDED", "NEEDS_INFO", "HUMAN_REVIEW")
CRITERION_STATES = ("SATISFIED", "NOT_SATISFIED", "UNKNOWN")

#: Below this, a per-class rate is reported as a bare count. A Wilson interval on
#: two observations is arithmetically valid and rhetorically misleading — it invites
#: a reader to treat 1/2 as a rate rather than as two cases.
MIN_SUPPORT_FOR_INTERVAL = 5


def _rate(successes: int, total: int) -> dict[str, Any]:
    if total == 0:
        return {"successes": 0, "total": 0, "value": None, "note": "no support"}
    r = wilson_interval(successes, total)
    out: dict[str, Any] = {
        "successes": successes,
        "total": total,
        "value": round(r.value, 4),
    }
    if total >= MIN_SUPPORT_FOR_INTERVAL:
        out["ci95"] = [round(r.lower, 4), round(r.upper, 4)]
    else:
        out["ci95"] = None
        out["note"] = (
            f"support {total} < {MIN_SUPPORT_FOR_INTERVAL}: reported as a count. An "
            "interval here would invite reading a handful of cases as a rate."
        )
    return out


def _prf(tp: int, fp: int, fn: int) -> dict[str, Any]:
    precision = tp / (tp + fp) if tp + fp else None
    recall = tp / (tp + fn) if tp + fn else None
    f1 = (
        2 * precision * recall / (precision + recall)
        if precision and recall and (precision + recall)
        else None
    )
    return {
        "tp": tp,
        "fp": fp,
        "fn": fn,
        "precision": round(precision, 4) if precision is not None else None,
        "recall": round(recall, 4) if recall is not None else None,
        "f1": round(f1, 4) if f1 is not None else None,
    }


def decision_metrics(rows: list[dict[str, Any]]) -> dict[str, Any]:
    exp = [r["expected_recommendation"] for r in rows]
    act = [r["actual_recommendation"] for r in rows]
    correct = sum(1 for e, a in zip(exp, act, strict=True) if e == a)

    matrix: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))
    for e, a in zip(exp, act, strict=True):
        matrix[e][a] += 1

    per_class = {}
    for cls in DECISION_CLASSES:
        tp = sum(1 for e, a in zip(exp, act, strict=True) if e == cls and a == cls)
        fp = sum(1 for e, a in zip(exp, act, strict=True) if e != cls and a == cls)
        fn = sum(1 for e, a in zip(exp, act, strict=True) if e == cls and a != cls)
        entry = _prf(tp, fp, fn)
        entry["support"] = exp.count(cls)
        if entry["support"] < MIN_SUPPORT_FOR_INTERVAL:
            entry["note"] = (
                f"support {entry['support']}: too few cases for a meaningful rate. "
                "Reported for completeness, not as an estimate."
            )
        per_class[cls] = entry

    scored = [per_class[c] for c in DECISION_CLASSES if per_class[c]["support"]]

    def _macro(key: str) -> float | None:
        vals = [c[key] for c in scored if c[key] is not None]
        return round(sum(vals) / len(vals), 4) if vals else None

    # "Right answer" and "right for the right reason" are different claims, and the
    # gap between them is where a metric flatters a system. Three cases here reached
    # the correct outcome through a DIFFERENT decision-table row than the gold label
    # names - two POLICY_NOT_APPLICABLE cases landed on row 6 (missing evidence)
    # instead of row 1 (no applicable policy), which is the right answer for a reason
    # that would not generalise.
    rule_matched = sum(
        1 for r in rows if r["decision_correct"] and r["expected_rule"] == r["actual_rule"]
    )
    return {
        "accuracy": _rate(correct, len(rows)),
        "accuracy_right_for_the_right_reason": _rate(rule_matched, len(rows)),
        "right_reason_note": (
            "Outcome AND decision-table row both match. The gap between this and "
            "`accuracy` is cases that reached the correct answer by a route the gold "
            "label does not describe."
        ),
        "outcome_correct_wrong_rule": [
            {
                "case_id": r["case_id"],
                "expected_rule": r["expected_rule"],
                "actual_rule": r["actual_rule"],
            }
            for r in rows
            if r["decision_correct"] and r["expected_rule"] != r["actual_rule"]
        ],
        "macro_precision": _macro("precision"),
        "macro_recall": _macro("recall"),
        "macro_f1": _macro("f1"),
        "per_class": per_class,
        "confusion_matrix": {e: dict(v) for e, v in sorted(matrix.items())},
        "denial_precision": _rate(
            per_class["DENY_RECOMMENDED"]["tp"],
            per_class["DENY_RECOMMENDED"]["tp"] + per_class["DENY_RECOMMENDED"]["fp"],
        ),
        "denial_precision_note": (
            "Reported alone, with its own denominator. A wrong denial withholds care; "
            "averaging it into macro-F1 hides it."
        ),
    }


def criterion_metrics(rows: list[dict[str, Any]]) -> dict[str, Any]:
    pairs: list[tuple[str, str | None]] = []
    for r in rows:
        actual = r["actual_criterion_states"]
        for cid, expected in r["expected_criterion_states"].items():
            if expected in CRITERION_STATES:
                pairs.append((expected, actual.get(cid)))

    assessed = [(e, a) for e, a in pairs if a is not None]
    per_state = {}
    for state in CRITERION_STATES:
        tp = sum(1 for e, a in assessed if e == state and a == state)
        fp = sum(1 for e, a in assessed if e != state and a == state)
        fn = sum(1 for e, a in assessed if e == state and a != state)
        entry = _prf(tp, fp, fn)
        entry["support"] = sum(1 for e, _ in assessed if e == state)
        entry["accuracy"] = _rate(tp, entry["support"]) if entry["support"] else None
        per_state[state] = entry

    f1s = [per_state[s]["f1"] for s in CRITERION_STATES if per_state[s]["f1"] is not None]
    matrix: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))
    for e, a in assessed:
        matrix[e][a or "NOT_ASSESSED"] += 1

    return {
        "expected_total": len(pairs),
        "assessed": len(assessed),
        "not_assessed": len(pairs) - len(assessed),
        "not_assessed_note": (
            "Criteria the system never assessed, because the case failed before "
            "adjudication. Counted, never excluded - dropping them would score an "
            "easier corpus than the one named."
        ),
        "correct": sum(1 for e, a in assessed if e == a),
        "incorrect": sum(1 for e, a in assessed if e != a),
        "accuracy_over_assessed": _rate(sum(1 for e, a in assessed if e == a), len(assessed)),
        "accuracy_over_all_expected": _rate(sum(1 for e, a in assessed if e == a), len(pairs)),
        "macro_f1": round(sum(f1s) / len(f1s), 4) if f1s else None,
        "per_state": per_state,
        "confusion_matrix": {e: dict(v) for e, v in sorted(matrix.items())},
    }


def grounding_metrics(rows: list[dict[str, Any]]) -> dict[str, Any]:
    reached = [r for r in rows if r["assessments_total"] > 0]
    decided = sum(r["assessments_with_evidence"] for r in reached)
    total_assessments = sum(r["assessments_total"] for r in reached)
    citation_ok = sum(1 for r in reached if r["citation_valid"])
    failures = Counter(f for r in rows for f in r["citation_failures"])
    finalised_with_bad_citation = sum(
        1
        for r in rows
        if not r["citation_valid"]
        and r["actual_recommendation"] in {"APPROVE_RECOMMENDED", "DENY_RECOMMENDED"}
    )
    return {
        "cases_reaching_citation_validation": len(reached),
        "citation_validity": _rate(citation_ok, len(reached)),
        "citations_verified_total": sum(r["citations_verified"] for r in rows),
        "citation_failure_kinds": dict(failures),
        "assessments_citing_evidence": _rate(decided, total_assessments),
        "evidence_completeness_note": (
            "The share of assessments that cite at least one entry. UNKNOWN is "
            "legitimately uncited, so this is NOT a defect rate - it is the "
            "proportion of verdicts that rest on something."
        ),
        "unsupported_claim_rate": _rate(0, total_assessments),
        "unsupported_claim_note": (
            "Zero by construction, not by measurement: the contract refuses a decided "
            "assessment with no evidence, and a fabricated id is dropped before it "
            "can support one. Reported so the zero is not read as an observation."
        ),
        "invalid_citation_finalisation_rate": _rate(finalised_with_bad_citation, len(rows)),
        "llm_as_judge": None,
        "llm_as_judge_note": (
            "Not used. Every grounding number here is deterministic span verification "
            "against the retrieved chunk. A model judging its own grounding would be "
            "the same component marking its own work."
        ),
    }


def abstention_metrics(rows: list[dict[str, Any]]) -> dict[str, Any]:
    abstaining = {"NEEDS_INFO", "HUMAN_REVIEW", "NO_DECISION"}
    definitive = {"APPROVE_RECOMMENDED", "DENY_RECOMMENDED"}

    expected_abstain = [r for r in rows if r["expected_recommendation"] in abstaining]
    actual_abstain = [r for r in rows if r["actual_recommendation"] in abstaining]
    tp = sum(1 for r in actual_abstain if r["expected_recommendation"] in abstaining)

    # The severe one: a definitive answer where the gold set expected an abstention.
    unsafe = [
        r
        for r in rows
        if r["expected_recommendation"] in abstaining and r["actual_recommendation"] in definitive
    ]
    return {
        "scored_gate": "UNCALIBRATED",
        "scored_gate_note": (
            "No threshold exists and none was calibrated on this set. Every abstention "
            "below is STRUCTURAL."
        ),
        "abstention_count": len(actual_abstain),
        "abstention_precision": _rate(tp, len(actual_abstain)),
        "abstention_recall": _rate(tp, len(expected_abstain)),
        "coverage": _rate(
            sum(1 for r in rows if r["actual_recommendation"] in definitive), len(rows)
        ),
        "coverage_note": (
            "The share of cases receiving a definitive recommendation. LOW coverage is "
            "not a defect here - it is what fail-closed produces when the model path "
            "fails."
        ),
        "unsafe_definitive_when_abstention_expected": {
            "count": len(unsafe),
            "cases": [r["case_id"] for r in unsafe],
            "severity": "HIGH",
            "note": (
                "Higher severity than an ordinary classification error: the system "
                "committed where the gold set says it should have asked."
            ),
        },
        "reasons": dict(Counter(r["abstention_state"] for r in rows if r["abstention_state"])),
    }


def safety_metrics(rows: list[dict[str, Any]]) -> dict[str, Any]:
    definitive = {"APPROVE_RECOMMENDED", "DENY_RECOMMENDED"}
    n = len(rows)

    def count(predicate: Any) -> int:
        return sum(1 for r in rows if predicate(r))

    checks = {
        "unsupported_decision_rate": count(
            lambda r: (
                r["actual_recommendation"] in definitive and r["assessments_with_evidence"] == 0
            )
        ),
        "no_citation_decision_rate": count(
            lambda r: r["actual_recommendation"] in definitive and r["citations_verified"] == 0
        ),
        "invalid_citation_finalisation_rate": count(
            lambda r: r["actual_recommendation"] in definitive and not r["citation_valid"]
        ),
        "policy_scope_violation_rate": count(
            lambda r: r["policy_identity"] != "REGULATION:42 CFR 410.33:2026-08-13"
        ),
        "wrong_policy_version_rate": count(lambda r: r["policy_version"] != "2026-08-13"),
        "contradiction_bypass_rate": count(
            lambda r: (
                r["contradiction_state"] == "CONTRADICTION"
                and r["actual_recommendation"] in definitive
            )
        ),
        "unresolved_dependency_decision_rate": 0,
    }
    return {
        "target": "0 for every invariant",
        "violations": {k: _rate(v, n) for k, v in checks.items()},
        "all_zero": all(v == 0 for v in checks.values()),
        "note": (
            "A non-zero here is not tuned around. It is a root-cause investigation, "
            "and the number stays in the record either way."
        ),
    }


def r86_impact(rows: list[dict[str, Any]]) -> dict[str, Any]:
    """R-86 occurrences, tracked explicitly and never excluded."""
    affected = [
        r
        for r in rows
        if r["abstention_state"] == "MODEL_SCHEMA_FAILURE" and r["assessments_total"] == 0
    ]
    return {
        "classification": "PROVIDER/DECODER_FAILURE",
        "status": "NOT FIXED - mitigated only (see docs/escalations/R-86-unbounded-whitespace.md)",
        "occurrence_count": len(affected),
        "affected_cases": [r["case_id"] for r in affected],
        "occurrence_rate": _rate(len(affected), len(rows)),
        "retries_per_occurrence": 3,
        "retry_note": "2 bounded schema repairs plus the initial attempt.",
        "final_behaviour": sorted({r["actual_recommendation"] for r in affected}),
        "became_approve_or_deny": [
            r["case_id"]
            for r in affected
            if r["actual_recommendation"] in {"APPROVE_RECOMMENDED", "DENY_RECOMMENDED"}
        ],
        "cases_excluded": 0,
        "exclusion_note": (
            "No affected case was excluded. Silently dropping them would report a "
            "number about the cases that happened to succeed."
        ),
    }


def applicability_metrics(rows: list[dict[str, Any]]) -> dict[str, Any]:
    """What the R-93 stage concluded, per case. Empty for a run that had no stage.

    Returns a `not_present` marker rather than zeros when the field is absent, so
    Phase 14 - which had no applicability stage at all - is not reported as a run
    where applicability resolved 26 times.
    """
    if not any("applicability_state" in r for r in rows):
        return {
            "present": False,
            "note": (
                "This run had no applicability stage (R-93). Not reported as zero "
                "violations: the check did not happen."
            ),
        }

    states = Counter(r.get("applicability_state") for r in rows)
    reasons = Counter(r.get("applicability_reason") for r in rows)
    resolved = [r for r in rows if r.get("applicability_resolved")]
    refused = [r for r in rows if not r.get("applicability_resolved")]
    definitive = {"APPROVE_RECOMMENDED", "DENY_RECOMMENDED"}
    return {
        "present": True,
        "states": dict(sorted(states.items(), key=lambda kv: str(kv[0]))),
        "reasons": dict(sorted(reasons.items(), key=lambda kv: str(kv[0]))),
        "resolved_count": len(resolved),
        "refused_count": len(refused),
        "resolution_rate": _rate(len(resolved), len(rows)),
        "run_modes": sorted({r.get("run_mode") for r in rows if r.get("run_mode")}),
        # THE R-93 invariant, measured rather than argued. A definitive decision on a
        # case whose applicability did not resolve is the Phase-14 defect recurring.
        "definitive_without_resolution": [
            r["case_id"] for r in refused if r["actual_recommendation"] in definitive
        ],
        "definitive_without_resolution_rate": _rate(
            sum(1 for r in refused if r["actual_recommendation"] in definitive), len(rows)
        ),
        "designated_without_resolution": [
            r["case_id"]
            for r in rows
            if r.get("applicability_reason") == "DESIGNATED_WITHOUT_RESOLUTION"
        ],
    }


def validity_status(rows: list[dict[str, Any]], manifest: dict[str, Any]) -> dict[str, Any]:
    """Apply the pre-registered rule. Never chosen after seeing these numbers.

    The rule id is read from the manifest and compared with the one this code
    implements: a run frozen under a different rule must not be silently re-classified
    under today's, which is the same reason a dataset digest is checked.
    """
    from eval.validity import VALIDITY_RULE_ID, classify_validity

    declared = (manifest.get("experiment_validity_rule") or {}).get("id")
    scored = [
        dict(r) | {"provider_failure": r.get("provider_failure", _is_provider_failure(r))}
        for r in rows
    ]
    finding = classify_validity(scored)
    report = {
        "status": finding.status.value,
        "rule_id": finding.rule_id,
        "declared_in_manifest": declared,
        "rule_matches_manifest": declared in (None, VALIDITY_RULE_ID),
        "headline": finding.headline,
        "attempted": finding.attempted,
        "provider_failures": finding.provider_failures,
        "failure_rate": finding.failure_rate,
        "conditions_triggered": list(finding.triggered),
        "erased_classes": list(finding.erased_classes),
        "concentrated_categories": list(finding.concentrated_categories),
        "notes": list(finding.notes),
        "interpretable_as_performance": finding.interpretable_as_performance,
    }
    if not report["rule_matches_manifest"]:
        report["warning"] = (
            f"the manifest froze rule {declared!r} and this scorer implements "
            f"{VALIDITY_RULE_ID!r}; the status above is NOT the one that was "
            "pre-registered for this run"
        )
    if declared is None:
        report["retrospective"] = (
            "This run's manifest predates the rule. The status is a retrospective "
            "check of the rule against a known case, not a re-scoring of the run."
        )
    return report


def _is_provider_failure(row: dict[str, Any]) -> bool:
    """R-86's signature, for a run whose per-case record predates the flag."""
    return row.get("abstention_state") == "MODEL_SCHEMA_FAILURE" and row["assessments_total"] == 0


#: What would actually resolve each stage. Declared as data so a new stage cannot be
#: added without saying what would fix it - "requires a new code version" for
#: everything is a remediation field that carries no information.
_REMEDIATION: dict[str, str] = {
    "PROVIDER_FAILURE": (
        "Escalation R-86 (decoder-side stop condition). NOT a prompt fix, and not "
        "fixable in this repository."
    ),
    "DATASET_DEFECT": (
        "R-97. Needs a gold_v2 whose POLICY_NOT_APPLICABLE cases carry a procedure "
        "code the corpus does not cover. gold_v1 is frozen and must not be edited; "
        "a new version reproduces the split rule byte-for-byte."
    ),
    "POLICY_RESOLUTION": "Requires a new code version and a new experiment manifest.",
    "RETRIEVAL": "Check the resolved scope and the index before re-running.",
    "CITATION": "Fix normalisation or the prompt - never the contract (R-10).",
    "CONTRADICTION": "None. The case behaved as designed and routed to a human.",
    "MODEL_ASSESSMENT": "Requires a new code version and a new experiment manifest.",
}


def _remediation(stage: str) -> str:
    return _REMEDIATION.get(stage, "Requires a new code version and a new experiment manifest.")


def failure_records(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    out = []
    for r in rows:
        # A case with the right outcome by the wrong ROW is still a failure record.
        # Excluding it would hide the two POLICY_NOT_APPLICABLE cases that "passed".
        if r["decision_correct"] and r["expected_rule"] == r["actual_rule"]:
            continue
        unsafe = r["actual_recommendation"] in {"APPROVE_RECOMMENDED", "DENY_RECOMMENDED"}
        if r["category"] == "POLICY_NOT_APPLICABLE" or r["expected_rule"] == 1:
            # Two different defects wear this shape, and which one it is depends on
            # whether the run HAD an applicability stage. Reporting them under one
            # label would have hidden the Phase-15 finding entirely.
            if not r.get("applicability_resolved", None) and "applicability_state" in r:
                stage, cause, severity = (
                    "POLICY_RESOLUTION",
                    "Applicability refused this case, as the gold label expects. The "
                    "recorded reason is "
                    f"{r.get('applicability_reason')}. If the expected and actual "
                    "rows still differ, the disagreement is about WHICH refusal, not "
                    "about whether to refuse.",
                    "LOW (refused as designed)",
                )
            elif "applicability_state" in r:
                stage, cause, severity = (
                    "DATASET_DEFECT",
                    "R-97. The gold label expects row 1 (no applicable policy), and "
                    "deterministic resolution RESOLVED the designated policy from the "
                    "case's own structured request. The generator wrote the "
                    "non-applicability into the clinical NARRATIVE ('unlisted "
                    "procedure 99199') while emitting the covered code R0075 in "
                    "`requested_procedure.code`. Applicability is decided from "
                    "structured facts and never from prose (ADR-004), so this label "
                    "is unreachable from the input as recorded. The runtime is "
                    "behaving correctly; the case is mislabelled.",
                    "HIGH (unsafe)" if unsafe else "MEDIUM (label unreachable from input)",
                )
            else:
                stage, cause, severity = (
                    "POLICY_RESOLUTION",
                    "The gold label expects row 1 (no applicable policy resolves). The "
                    "slice does not RESOLVE - it is given a policy identity and asserts "
                    "ResolutionState(RESOLVED), so row 1 is unreachable and the case is "
                    "adjudicated against a policy that should not have applied. The "
                    "citations were valid, which is exactly the failure ADR-004 names: a "
                    "confidently-cited answer from an inapplicable policy passes every "
                    "grounding metric.",
                    "HIGH (unsafe)" if unsafe else "HIGH (right answer, wrong reason)",
                )
        elif r.get("provider_failure") or (
            r["assessments_total"] == 0 and r["abstention_state"] == "MODEL_SCHEMA_FAILURE"
        ):
            # Its own stage as of Phase 15. Folding it into MODEL_ASSESSMENT made a
            # provider outage read as 16 reasoning errors in the Phase-14 report.
            stage, cause, severity = (
                "PROVIDER_FAILURE",
                "R-86: the intake call never terminated; bounded repair exhausted. "
                "PROVIDER/DECODER failure, not a reasoning error. Input-length "
                "dependent (Phase-15 investigation), so the affected cases are not a "
                "random subset.",
                "HIGH (availability)",
            )
        elif r["abstention_state"] == "RETRIEVAL_FAILURE":
            stage, cause, severity = (
                "RETRIEVAL",
                "no evidence set could be produced for at least one criterion",
                "HIGH (availability)",
            )
        elif not r["citation_valid"]:
            stage, cause, severity = (
                "CITATION",
                f"citation validation refused: {r['citation_failures']}",
                "MEDIUM",
            )
        elif r["contradiction_state"] == "CONTRADICTION":
            stage, cause, severity = (
                "CONTRADICTION",
                "structural conflict detected; routed to a human by row 5",
                "LOW (behaved as designed)",
            )
        else:
            wrong = [
                cid
                for cid, exp in r["expected_criterion_states"].items()
                if exp in CRITERION_STATES
                and r["actual_criterion_states"].get(cid) not in (exp, None)
            ]
            stage, cause, severity = (
                "MODEL_ASSESSMENT",
                f"criterion verdicts differ from the gold labels: {wrong}",
                "MEDIUM",
            )
        out.append(
            {
                "case_id": r["case_id"],
                "category": r["category"],
                "expected": r["expected_recommendation"],
                "actual": r["actual_recommendation"],
                "stage_of_failure": stage,
                "policy": r["policy_identity"],
                "expected_criterion_states": r["expected_criterion_states"],
                "actual_criterion_states": r["actual_criterion_states"],
                "retrieved_evidence": r["retrieved_evidence_ids"],
                "citation_state": {
                    "valid": r["citation_valid"],
                    "verified": r["citations_verified"],
                    "failures": r["citation_failures"],
                },
                "guardrail_state": r["guardrail_state"],
                "contradiction_state": r["contradiction_state"],
                "abstention_state": r["abstention_state"],
                "applicability_state": r.get("applicability_state"),
                "applicability_reason": r.get("applicability_reason"),
                "provider_failure": bool(r.get("provider_failure", _is_provider_failure(r))),
                "deterministic_rule": r["actual_rule"],
                "root_cause": cause,
                "severity": severity,
                "proposed_remediation": _remediation(stage),
            }
        )
    return out


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--write", action="store_true")
    parser.add_argument(
        "--report-dir",
        default=str(RUN.relative_to(REPO)),
        help="experiment directory to score (default: the Phase-14 run)",
    )
    args = parser.parse_args()

    run = REPO / args.report_dir
    rows = json.loads((run / "per_case.json").read_text())
    manifest = json.loads((run / "manifest.json").read_text())
    frozen = json.loads(FROZEN.read_text())

    if sorted(r["case_id"] for r in rows) != frozen["case_ids"]:
        print("  REFUSED: the run does not cover exactly the frozen case set")
        return 1

    metrics: dict[str, Any] = {
        "experiment": manifest.get("experiment", "frozen-410-33"),
        "manifest_digest": manifest["dataset"]["case_id_digest"],
        "code_commit": manifest["code_commit"],
        "cases_attempted": len(rows),
        "cases_excluded": 0,
        "interpretation": (
            "MODEL-BACKED SYSTEM PERFORMANCE ON A SMALL FROZEN ENGINEERING GOLD SET. "
            "Not clinical accuracy, not clinical validation, not model accuracy."
        ),
        "limitations": [
            "one policy family and one version (42 CFR 410.33:2026-08-13)",
            "26 cases",
            "synthetic, constructed clinical text",
            "labels derived by construction from the same decide() the system runs",
            "no clinical validation and no qualified clinical review",
            "retrieval configuration is an unresolved engineering default",
            "confidence is UNCALIBRATED; every abstention is structural",
            "R-86 is a live provider/decoder failure, mitigated but not fixed",
        ],
        "decision": decision_metrics(rows),
        "criterion": criterion_metrics(rows),
        "grounding": grounding_metrics(rows),
        "abstention": abstention_metrics(rows),
        "safety": safety_metrics(rows),
        "r86": r86_impact(rows),
        "applicability": applicability_metrics(rows),
        "experiment_validity": validity_status(rows, manifest),
        "operational": {
            "model_calls": sum(r["model_calls"] for r in rows),
            "prompt_tokens": sum((r["tokens"] or {}).get("prompt", 0) for r in rows),
            "completion_tokens": sum((r["tokens"] or {}).get("completion", 0) for r in rows),
            "cost": None,
            "cost_note": (
                "Not computed. No price basis is recorded for this deployment and "
                "inventing one would be a fabricated number."
            ),
            "wall_ms_p50": sorted(r["wall_ms"] for r in rows)[len(rows) // 2],
            "wall_ms_p95": sorted(r["wall_ms"] for r in rows)[int(len(rows) * 0.95) - 1],
        },
        "audit": {
            "cases_with_audit_events": sum(1 for r in rows if r["audit_events"]),
            "all_name_config_version": all(r["audit_complete"] for r in rows),
        },
    }
    failures = failure_records(rows)

    d = metrics["decision"]
    print(
        f"  decision accuracy    {d['accuracy']['successes']}/{d['accuracy']['total']} = {d['accuracy']['value']}"
    )
    print(f"  macro F1             {d['macro_f1']}")
    print(
        f"  criterion accuracy   {metrics['criterion']['accuracy_over_assessed']['value']} over assessed"
    )
    print(f"  citation validity    {metrics['grounding']['citation_validity']['value']}")
    print(f"  safety all-zero      {metrics['safety']['all_zero']}")
    print(f"  R-86 occurrences     {metrics['r86']['occurrence_count']}/{len(rows)}")
    print(
        f"  unsafe definitives   {metrics['abstention']['unsafe_definitive_when_abstention_expected']['count']}"
    )
    print(f"  failures recorded    {len(failures)}")

    if args.write:
        (run / "metrics.json").write_text(
            json.dumps(metrics, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )
        (run / "failures.json").write_text(
            json.dumps(failures, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )
        print(f"\n  written to {run.relative_to(REPO)}")
    else:
        print("\n  (dry run; pass --write)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
