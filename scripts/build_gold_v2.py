"""Build gold_v2: applicability that is derivable from structured input. Part B.

    uv run python scripts/build_gold_v2.py            # audit only, writes nothing
    uv run python scripts/build_gold_v2.py --write

**gold_v1 is never touched.** It is read, hashed, and the hash is asserted against
its own manifest before anything is written; the builder refuses to run if the two
disagree. A frozen dataset that a migration can edit was never frozen.

## What this fixes, and what it deliberately does not

R-97: gold_v1's eighteen `POLICY_NOT_APPLICABLE` cases encode their
non-applicability **only in the clinical narrative** - "Requested service: unlisted
procedure 99199" - while their structured `requested_procedure.code` is `R0075`, a
code the corpus genuinely links to 42 CFR 410.33. Deterministic resolution reads the
structured request, correctly resolves, and the gold label of decision-rule 1 is
unreachable from the input as recorded.

That was invisible for four phases because the runtime asserted `RESOLVED` and never
disagreed with anything. Phase 15 made applicability real; the label became
unreachable the same day.

**The fix is a code, not a parser.** Those cases get a procedure code the corpus does
not link (`scripts/fetch_noncovered_codes.py`, verified against NLM). Teaching the
resolver to read the narrative would make applicability depend on prose - a semantic
resolver wearing a deterministic one's clothes, resolving differently for the same
structured request depending on wording (ADR-004).

**No label is re-derived by a model, and no class balance is engineered.** Every
expected decision is recomputed by the same `decide()` the system runs, from the same
criterion states gold_v1 recorded. A case whose recomputed label disagrees with
gold_v1's is a finding and is reported, never silently adopted.

## The audit is the deliverable

Every one of the 156 cases is classified, and the classification is written out with
its reason. A migration that reported only what changed would leave "and the other
138 were fine" as an assertion nobody checked.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
import sys
from collections import Counter
from dataclasses import dataclass
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

import yaml

from app.core.types import CriterionKind, ResolutionStatus, Verdict
from app.decision.logic import evaluate
from app.decision.models import Outcome
from app.decision.table import CriterionOutcome, GuardrailState, ResolutionState, decide
from app.policy.applicability import ApplicabilityReason

REPO = Path(__file__).resolve().parents[1]
GOLD_V1 = REPO / "data/gold/cases/gold_v1.jsonl"
GOLD_V1_MANIFEST = REPO / "data/gold/manifests/gold_v1.manifest.json"
LINKAGE = REPO / "data/linkage/policy_code_links.yaml"
NONCOVERED = REPO / "data/linkage/noncovered_code_metadata.jsonl"
INVENTORY = REPO / "data/criteria/inventory.jsonl"
LOGIC_DIR = REPO / "data/policy_logic"

OUT_CASES = REPO / "data/gold/cases/gold_v2.jsonl"
OUT_MANIFEST = REPO / "data/gold/manifests/gold_v2.manifest.json"
OUT_MIGRATION = REPO / "data/review/gold_v2_migration.json"

SCHEMA_VERSION = "2"
CASE_VERSION = "gold_v2"


class Classification:
    """B3's four buckets. Strings rather than an enum: this is a report vocabulary."""

    UNCHANGED = "UNCHANGED"
    REQUIRES_STRUCTURAL_FIX = "REQUIRES_STRUCTURAL_FIX"
    REQUIRES_LABEL_REVIEW = "REQUIRES_LABEL_REVIEW"
    INVALID_FOR_GOLD_V2 = "INVALID_FOR_GOLD_V2"


@dataclass(frozen=True, slots=True)
class Corpus:
    """Everything the audit needs to know about what the corpus links."""

    #: `(code, code_system)` pairs listed as covered procedures.
    covered: frozenset[tuple[str, str]]
    #: Verified real codes the corpus deliberately does not link.
    noncovered: tuple[tuple[str, str], ...]
    #: `(policy_id, policy_version) -> [criterion rows]`, ordered.
    criteria: dict[tuple[str, str], list[dict[str, Any]]]
    #: `(policy_id, policy_version) -> (effective_date, end_date | None)`.
    windows: dict[tuple[str, str], tuple[date, date | None]]


def _load_corpus() -> Corpus:
    linkage = yaml.safe_load(LINKAGE.read_text(encoding="utf-8"))
    covered: set[tuple[str, str]] = set()
    windows: dict[tuple[str, str], tuple[date, date | None]] = {}
    for link in linkage["links"]:
        if str(link.get("link_type", "COVERED_PROCEDURE")) == "COVERED_PROCEDURE":
            covered.add((str(link["code"]), str(link["code_system"])))

    noncovered = tuple(
        (json.loads(line)["code"], json.loads(line)["code_system"])
        for line in NONCOVERED.read_text(encoding="utf-8").splitlines()
        if line.strip()
    )

    criteria: dict[tuple[str, str], list[dict[str, Any]]] = {}
    for line in INVENTORY.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        row = json.loads(line)
        criteria.setdefault((row["policy_id"], row["policy_version"]), []).append(row)
    for rows in criteria.values():
        rows.sort(key=lambda r: int(r["ordinal"]))

    return Corpus(
        covered=frozenset(covered),
        noncovered=noncovered,
        criteria=criteria,
        windows=windows,
    )


def _semantics_for(policy_id: str, policy_version: str, criteria: tuple[CriterionOutcome, ...]):
    """The declared logic where one exists, an attested assumption otherwise.

    Imported lazily and built the same way `eval/replay.py` does, because gold_v1's
    labels were computed under exactly these semantics. Recomputing them under a
    different rule shape would produce a "disagreement" that is really a change of
    question.
    """
    from eval.replay import gold_v1_semantics

    return gold_v1_semantics(criteria, policy_id=policy_id, policy_version=policy_version)


_KIND = {
    "REQUIRED": CriterionKind.REQUIRED,
    "EXCLUSION": CriterionKind.EXCLUSION,
    "INFORMATIONAL": CriterionKind.INFORMATIONAL,
    "EXCEPTION_CONDITION": CriterionKind.EXCEPTION_CONDITION,
}
_VERDICT = {
    "SATISFIED": Verdict.SATISFIED,
    "NOT_SATISFIED": Verdict.NOT_SATISFIED,
    "UNKNOWN": Verdict.INSUFFICIENT_EVIDENCE,
}


def _outcomes(case: dict[str, Any]) -> tuple[CriterionOutcome, ...]:
    """Criterion outcomes exactly as gold_v1 recorded them. Nothing is re-judged."""
    return tuple(
        CriterionOutcome(
            criterion_id=c["criterion_id"],
            kind=_KIND[c["criterion_type"]],
            verdict=_VERDICT[c["state"]],
            # gold_v1's generator sets evidence from the state: an UNKNOWN state has
            # no supporting sentence in the note, so it has nothing behind it.
            has_valid_evidence=c["state"] != "UNKNOWN",
            missing_evidence=(c["criterion_id"],) if c["state"] == "UNKNOWN" else (),
        )
        for c in case["expected"]["criteria"]
    )


def _recompute(case: dict[str, Any], *, applicable: bool) -> tuple[Outcome, int, str]:
    """`(outcome, rule, policy_truth)` from the SAME decide() the system runs.

    ADR-015's requirement, and the reason a gold label is reproducible rather than
    remembered. `applicable` is passed rather than inferred so the recomputation
    mirrors what the case's structured input will actually resolve to.
    """
    outcomes = _outcomes(case)
    semantics = _semantics_for(
        case["expected"]["policy_id"], case["expected"]["policy_revision"], outcomes
    )
    resolution = ResolutionState(
        ResolutionStatus.RESOLVED if applicable else ResolutionStatus.NONE_APPLICABLE,
        version_count=1 if applicable else 0,
    )
    guardrail = (
        GuardrailState.CONTRADICTION
        if case["category"] == "CONFLICTING_EVIDENCE"
        else GuardrailState.PASSED
    )
    recommendation = decide(outcomes, guardrail, resolution, semantics)

    truth = "NOT_EVALUATED"
    if applicable and semantics.logic is not None and outcomes:
        from app.decision.logic import leaf_value

        states = {
            c.criterion_id: leaf_value(
                c.verdict, has_valid_evidence=c.has_valid_evidence, kind=c.kind
            )
            for c in outcomes
        }
        truth = evaluate(
            semantics.logic, states, as_of=date.fromisoformat(case["input"]["date_of_service"])
        ).truth.value
    elif not applicable:
        # No policy governs, so the policy has no truth value. Recorded explicitly
        # rather than defaulted to a member of PolicyTruth that would read as an
        # evaluation somebody performed.
        truth = "NO_APPLICABLE_POLICY"
    return recommendation.outcome, int(recommendation.rule), truth


def _evidence_refs(corpus: Corpus, policy_id: str, version: str, criterion_id: str) -> list[str]:
    """Stable, human-readable chunk references from the criteria inventory.

    `policy:version:ordinal`, never a database UUID. Chunk ids are assigned at
    ingest and change when the corpus is re-ingested; a gold set carrying them would
    be ground truth about one database rather than about the regulation.
    """
    for row in corpus.criteria.get((policy_id, version), []):
        if row["criterion_id"] == criterion_id:
            refs = row.get("source_chunk_refs") or "[]"
            try:
                parsed = refs if isinstance(refs, list) else json.loads(refs.replace("'", '"'))
            except (ValueError, TypeError):
                return []
            return [str(r) for r in parsed]
    return []


def _noncovered_for(case_id: str, corpus: Corpus) -> tuple[str, str]:
    """Deterministic assignment, so a rebuild produces the same case bytes."""
    index = int(hashlib.sha256(case_id.encode()).hexdigest()[:8], 16) % len(corpus.noncovered)
    return corpus.noncovered[index]


def audit(case: dict[str, Any], corpus: Corpus) -> dict[str, Any]:
    """Classify one case, with the reason. Every case is audited, not just the broken."""
    code = str(case["input"]["requested_procedure"]["code"])
    system = str(case["input"]["requested_procedure"]["code_system"])
    resolves = (code, system) in corpus.covered
    not_applicable = case["category"] == "POLICY_NOT_APPLICABLE"
    findings: list[str] = []

    classification = Classification.UNCHANGED
    if not_applicable and resolves:
        classification = Classification.REQUIRES_STRUCTURAL_FIX
        findings.append(
            f"R-97: the case expects NO applicable policy, and its structured code "
            f"{system} {code} IS linked as a covered procedure. The non-applicability "
            f"exists only in the clinical narrative, where a deterministic resolver "
            f"may not look."
        )
    elif not not_applicable and not resolves:
        classification = Classification.INVALID_FOR_GOLD_V2
        findings.append(
            f"the case expects an applicable policy and its code {system} {code} is "
            f"not linked; the label is unreachable and cannot be repaired by adding "
            f"structure"
        )

    if not case["expected"]["criteria"] and not not_applicable:
        classification = Classification.INVALID_FOR_GOLD_V2
        findings.append("no criterion states recorded, but the case expects adjudication")

    # The label is recomputed by the same function that produced it. A disagreement
    # is a finding about gold_v1 and is never silently adopted.
    recomputed, rule, truth = _recompute(case, applicable=not not_applicable)
    if (
        recomputed.value != case["expected"]["decision"]
        or rule != case["expected"]["decision_rule"]
    ):
        if classification == Classification.UNCHANGED:
            classification = Classification.REQUIRES_LABEL_REVIEW
        findings.append(
            f"recomputing with decide() gives {recomputed.value}/rule {rule}; gold_v1 "
            f"recorded {case['expected']['decision']}/rule {case['expected']['decision_rule']}"
        )

    return {
        "case_id": case["case_id"],
        "classification": classification,
        "findings": findings,
        "recomputed_decision": recomputed.value,
        "recomputed_rule": rule,
        "recomputed_policy_truth": truth,
        "code_resolves_in_corpus": resolves,
    }


def build_case(case: dict[str, Any], verdict: dict[str, Any], corpus: Corpus) -> dict[str, Any]:
    """One gold_v2 record. Input and expected stay separate objects.

    Nothing under `expected` may appear inside `input`: the production system is
    handed `input` only, and a gold value leaking across would make the evaluation a
    measurement of its own answer key.
    """
    policy_id = case["expected"]["policy_id"]
    version = case["expected"]["policy_revision"]
    not_applicable = case["category"] == "POLICY_NOT_APPLICABLE"

    code = str(case["input"]["requested_procedure"]["code"])
    system = str(case["input"]["requested_procedure"]["code_system"])
    structural_fix = verdict["classification"] == Classification.REQUIRES_STRUCTURAL_FIX
    note = case["input"]["clinical_note"]
    if structural_fix:
        code, system = _noncovered_for(case["case_id"], corpus)
        # The narrative named a CPT code the structured request never carried. Now
        # that the structured code is the load-bearing one, the sentence is aligned
        # to it - so the two halves of the case agree instead of contradicting.
        #
        # This is a CONSISTENCY repair on synthetic filler, not a clinical edit: the
        # line is generator boilerplate, and leaving it would preserve exactly the
        # narrative/structure disagreement gold_v2 exists to remove.
        # Matched case-insensitively and mid-line: the note renderer sometimes
        # prefixes a sentence ("As above: requested service: ..."), and a
        # startswith() check missed three cases when this was first written.
        note = re.sub(
            r"requested service:[^.\n]*\.",
            f"requested service: {code}.",
            note,
            flags=re.IGNORECASE,
        )

    resolves = (code, system) in corpus.covered
    if not_applicable:
        state = ResolutionStatus.NONE_APPLICABLE.value
        reason = ApplicabilityReason.NO_POLICY_LISTS_THE_PROCEDURE.value
    else:
        state = ResolutionStatus.RESOLVED.value
        reason = ApplicabilityReason.DESIGNATED_POLICY_APPLIES.value

    criteria = case["expected"]["criteria"]
    return {
        "case_id": case["case_id"],
        "case_version": CASE_VERSION,
        "schema_version": SCHEMA_VERSION,
        "provenance": "synthetic",
        "derived_from": {"dataset": "gold_v1", "case_id": case["case_id"]},
        "scenario_type": case["category"],
        "temporal_class": case["temporal_class"],
        "borderline": case.get("borderline", False),
        "partition": case["partition"],
        # ---- what the system is handed. NO gold values. -------------------
        "input": {
            "patient": case["input"]["patient"],
            "requested_service": {
                "procedure_code": code,
                "code_system": system,
            },
            "diagnosis_codes": list(case["input"].get("diagnosis_codes") or []),
            "jurisdiction": case["input"].get("jurisdiction"),
            "date_of_service": case["input"]["date_of_service"],
            "clinical_note": note,
        },
        # ---- what it should conclude, and from what --------------------------
        "expected": {
            "policy_type": "REGULATION",
            "policy_id": policy_id,
            "policy_version": version,
            "policy_title": case["expected"]["policy_title"],
            # THE R-97 FIX. Every fact below is readable from `input` plus the
            # committed linkage - no narrative, no fixture behaviour, no test-only
            # assumption. `tests/evaluation/test_gold_v2.py` re-derives the state
            # from those two sources and fails if it disagrees.
            "applicability": {
                "state": state,
                "reason": reason,
                "structured_facts": {
                    "procedure_code_linked_to_policy": resolves,
                    "code_system_stated": True,
                    "date_of_service_stated": True,
                    "jurisdiction_stated": case["input"].get("jurisdiction") is not None,
                },
                "derivable_from_structured_input": True,
                "derivation": (
                    f"({system} {code}) "
                    f"{'appears' if resolves else 'does not appear'} in "
                    "data/linkage/policy_code_links.yaml as a covered procedure"
                ),
            },
            "criterion_states": {c["criterion_id"]: c["state"] for c in criteria},
            "criterion_kinds": {c["criterion_id"]: c["criterion_type"] for c in criteria},
            "policy_truth": verdict["recomputed_policy_truth"],
            "recommendation": verdict["recomputed_decision"],
            "decision_rule": verdict["recomputed_rule"],
            "missing_information": list(case["expected"].get("missing_information") or []),
            # Stable references, not database ids. See `_evidence_refs`.
            "evidence_refs": {
                c["criterion_id"]: _evidence_refs(corpus, policy_id, version, c["criterion_id"])
                for c in criteria
            },
            "evidence_ground_truth": (
                "SECTION_LEVEL. Per-criterion source chunk references from the "
                "criteria inventory. Chunk-level ground truth is NOT established: "
                "chunk ids are assigned at ingest and would tie this dataset to one "
                "database. Recording invented ids would be fabricated ground truth."
            ),
            "labelling": (
                "derived by construction via app.decision.table.decide from the "
                "criterion states, under gold_v1's replay semantics. NOT a clinical "
                "judgement and NOT a model's opinion."
            ),
        },
    }


def _git_commit() -> str:
    try:
        return subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],
            cwd=REPO,
            capture_output=True,
            text=True,
            check=True,
        ).stdout.strip()
    except (OSError, subprocess.CalledProcessError):  # pragma: no cover
        return "unknown"


def _change_record(
    original: dict[str, Any], built: dict[str, Any], verdict: dict[str, Any]
) -> dict[str, Any]:
    """B4. What changed, in which field, and whether it moved the answer."""
    old_code = (
        f"{original['input']['requested_procedure']['code_system']} "
        f"{original['input']['requested_procedure']['code']}"
    )
    new_code = (
        f"{built['input']['requested_service']['code_system']} "
        f"{built['input']['requested_service']['procedure_code']}"
    )
    decision_changed = built["expected"]["recommendation"] != original["expected"]["decision"]
    rule_changed = built["expected"]["decision_rule"] != original["expected"]["decision_rule"]
    return {
        "case_id": original["case_id"],
        "classification": verdict["classification"],
        "gold_v1_reference": f"gold_v1:{original['case_id']}",
        "gold_v2_reference": f"gold_v2:{built['case_id']}",
        "policy": f"{original['expected']['policy_id']}:{original['expected']['policy_revision']}",
        "affected_criteria": sorted(built["expected"]["criterion_states"]),
        "changed_fields": sorted(
            field
            for field, changed in (
                ("input.requested_service.procedure_code", old_code != new_code),
                ("input.clinical_note", old_code != new_code),
                ("expected.applicability", True),
                ("expected.recommendation", decision_changed),
                ("expected.decision_rule", rule_changed),
            )
            if changed
        ),
        "procedure_code_before": old_code,
        "procedure_code_after": new_code,
        "applicability_before": (
            "narrative only - no structured signal"
            if original["category"] == "POLICY_NOT_APPLICABLE"
            else "structured (code resolves)"
        ),
        "applicability_after": built["expected"]["applicability"]["state"],
        "applicability_changed": old_code != new_code,
        "decision_before": original["expected"]["decision"],
        "decision_after": built["expected"]["recommendation"],
        "decision_changed": decision_changed,
        "rule_before": original["expected"]["decision_rule"],
        "rule_after": built["expected"]["decision_rule"],
        "reason": verdict["findings"]
        or ["no defect found; carried forward with structured applicability added"],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--write", action="store_true")
    args = parser.parse_args()

    raw = GOLD_V1.read_bytes()
    digest = hashlib.sha256(raw).hexdigest()
    recorded = json.loads(GOLD_V1_MANIFEST.read_text())["sha256"]["gold"]
    if digest != recorded:
        # A migration that can run against a modified source is a migration that can
        # launder one. Refused before anything is read further.
        print(
            f"  REFUSING: gold_v1 digest {digest[:16]} != manifest {recorded[:16]}",
            file=sys.stderr,
        )
        return 1

    corpus = _load_corpus()
    cases = [json.loads(line) for line in raw.decode().splitlines() if line]

    audits = [audit(case, corpus) for case in cases]
    by_classification = Counter(a["classification"] for a in audits)

    admitted = [
        (case, verdict)
        for case, verdict in zip(cases, audits, strict=True)
        if verdict["classification"] != Classification.INVALID_FOR_GOLD_V2
    ]
    built = [build_case(case, verdict, corpus) for case, verdict in admitted]
    changes = [
        _change_record(case, record, verdict)
        for (case, verdict), record in zip(admitted, built, strict=True)
    ]

    print(f"  gold_v1            {len(cases)} cases, digest {digest[:16]} (unchanged)")
    for name, count in sorted(by_classification.items()):
        print(f"  {name:<26} {count}")
    print(f"  gold_v2            {len(built)} cases")
    print(f"  decisions          {dict(Counter(b['expected']['recommendation'] for b in built))}")
    print(
        f"  applicability      "
        f"{dict(Counter(b['expected']['applicability']['state'] for b in built))}"
    )
    changed = [c for c in changes if c["changed_fields"] != ["expected.applicability"]]
    print(f"  cases changed      {len(changed)} of {len(built)}")

    if not args.write:
        print("\n  (audit only; pass --write)")
        return 0

    payload = "\n".join(json.dumps(b, sort_keys=True) for b in built) + "\n"
    OUT_CASES.write_text(payload, encoding="utf-8")
    v2_digest = hashlib.sha256(payload.encode()).hexdigest()

    manifest = {
        "gold_set_version": "gold_v2",
        "schema_version": SCHEMA_VERSION,
        "frozen": True,
        "frozen_at": datetime.now(UTC).isoformat(),
        "git_commit": _git_commit(),
        "sha256": {"gold": v2_digest},
        "derived_from": {
            "dataset": "gold_v1",
            "sha256": digest,
            "immutable": True,
            "note": "gold_v1 is read and hashed; this builder refuses to run if it moved",
        },
        "case_count": len(built),
        "case_ids": sorted(b["case_id"] for b in built),
        "resolves": ["R-97"],
        "supersedes": "gold_v1",
        "supersedes_reason": (
            "R-97. gold_v1's eighteen POLICY_NOT_APPLICABLE cases encode their "
            "non-applicability only in the clinical narrative while carrying a "
            "procedure code the corpus links as covered, so their expected "
            "decision-rule-1 label is unreachable from the structured input a "
            "deterministic resolver reads. Recorded here because a gold version "
            "created without a stated reason lets a relabelling look like a "
            "regeneration (Phase 4's guard)."
        ),
        "what_changed": (
            "Applicability is now derivable from structured input alone. The "
            "eighteen POLICY_NOT_APPLICABLE cases carry a verified HCPCS code the "
            "corpus does not link, instead of encoding non-applicability in prose."
        ),
        "labelling": {
            "method": "derived by construction via app.decision.table.decide",
            "clinically_validated": False,
            "human_reviewed": False,
            "note": (
                "Labels are recomputed from gold_v1's criterion states by the same "
                "function the system uses, under gold_v1's replay semantics. They "
                "are NOT expert clinical judgements."
            ),
        },
        "partition_rule": json.loads(GOLD_V1_MANIFEST.read_text())["partition_rule"],
        "partition_note": (
            "Inherited from gold_v1 case by case rather than recomputed. Recomputing "
            "would re-partition every case and invalidate every committed report "
            "that names a gold_v1 split."
        ),
        "distribution": {
            "scenario_type": dict(sorted(Counter(b["scenario_type"] for b in built).items())),
            "recommendation": dict(
                sorted(Counter(b["expected"]["recommendation"] for b in built).items())
            ),
            "decision_rule": dict(
                sorted(Counter(str(b["expected"]["decision_rule"]) for b in built).items())
            ),
            "applicability_state": dict(
                sorted(Counter(b["expected"]["applicability"]["state"] for b in built).items())
            ),
            "policy_version": dict(
                sorted(
                    Counter(
                        f"{b['expected']['policy_id']}:{b['expected']['policy_version']}"
                        for b in built
                    ).items()
                )
            ),
            "temporal_class": dict(sorted(Counter(b["temporal_class"] for b in built).items())),
        },
        "balance_note": (
            "The distribution is inherited, not engineered. No case was added, "
            "dropped or relabelled to shape it."
        ),
        "scoring_budget": {
            "allowed_scorings": 1,
            "scorings_spent": 0,
            "spent_by": [],
            "note": (
                "A fresh budget for a fresh dataset. Additional scorings must be "
                "declared in an ADR in advance."
            ),
        },
        "known_limitations": [
            "synthetic cases; no real clinical note has ever entered this project",
            "labels derived by construction from the same decide() the system runs",
            "no clinical validation and no qualified clinical review",
            "chunk-level evidence ground truth is NOT established (section-level only)",
            "one policy family (42 CFR 410) across six versions",
        ],
    }
    OUT_MANIFEST.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    migration = {
        "migration": "gold_v1 -> gold_v2",
        "generated_at": datetime.now(UTC).isoformat(),
        "git_commit": _git_commit(),
        "resolves": ["R-97"],
        "gold_v1": {"sha256": digest, "case_count": len(cases), "immutable": True},
        "gold_v2": {"sha256": v2_digest, "case_count": len(built)},
        "classification_counts": dict(sorted(by_classification.items())),
        "admitted": len(built),
        "excluded": len(cases) - len(built),
        "excluded_case_ids": [
            a["case_id"]
            for a in audits
            if a["classification"] == Classification.INVALID_FOR_GOLD_V2
        ],
        "audits": audits,
        "changes": changes,
        "review_note": (
            "Every case is listed, including the unchanged ones. A migration report "
            "that showed only the edits would leave 'the rest were fine' as an "
            "assertion nobody checked."
        ),
    }
    OUT_MIGRATION.write_text(
        json.dumps(migration, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )

    print(f"\n  gold_v2 sha256     {v2_digest[:16]}")
    print(f"  written            {OUT_CASES.relative_to(REPO)}")
    print(f"                     {OUT_MANIFEST.relative_to(REPO)}")
    print(f"                     {OUT_MIGRATION.relative_to(REPO)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
