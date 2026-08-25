"""The `phase16-evaluation-001` pre-run gate, and its frozen manifest. Part D, G.

    uv run python scripts/phase16_prerun_gate.py
    uv run python scripts/phase16_prerun_gate.py --freeze-manifest

Ten conditions. Exit 0 permits the run; any failure is a STOP.

**One condition is new and it is the point of Phase 16.** Alongside the Phase-15
conditions - applicability implemented, regression passing, gold immutable, nothing
tuned - this gate asks whether the **provider path is reliable enough for the run to
mean anything**:

    the most recent provider diagnostic, in the PRODUCTION request shape, must show
    a failure rate at or below the validity rule's ceiling

A gate that only checked our own house would happily authorise a run whose result was
predetermined by an outage. Phase 14 and Phase 15 both produced exactly that, and
both spent a hold-out scoring to learn it afterwards.

## The manifest is frozen by this script, not by the runner

`--freeze-manifest` writes `eval/reports/phase16-410-33/manifest.json` and stops.
Freezing here rather than inside a runner is what lets the manifest exist while the
run does not: the configuration is fixed and public, and the gate independently says
whether it may be executed.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parents[1]
GOLD_V1 = REPO / "data/gold/cases/gold_v1.jsonl"
GOLD_V1_MANIFEST = REPO / "data/gold/manifests/gold_v1.manifest.json"
GOLD_V2 = REPO / "data/gold/cases/gold_v2.jsonl"
GOLD_V2_MANIFEST = REPO / "data/gold/manifests/gold_v2.manifest.json"
MIGRATION = REPO / "data/review/gold_v2_migration.json"
RETRIEVAL_V4 = REPO / "eval/datasets/retrieval_v4/questions.yaml"
RETRIEVAL_PROVENANCE = REPO / "data/review/retrieval_v4_provenance.json"
FACTORIAL = REPO / "eval/reports/r86-gradient/factorial_results.json"
PHASE15 = REPO / "eval/reports/phase15-410-33"
OUT = REPO / "eval/reports/phase16-410-33"

EXPERIMENT_ID = "phase16-evaluation-001"
APPLICABILITY_VERSION = "applicability.v1"


@dataclass(frozen=True, slots=True)
class Condition:
    key: str
    requirement: str
    check: Callable[[], tuple[bool, str]]


def _digest(value: str) -> str:
    return f"sha256:{hashlib.sha256(value.encode()).hexdigest()[:12]}"


def _file_digest(path: Path) -> str:
    return f"sha256:{hashlib.sha256(path.read_bytes()).hexdigest()}"


def _git_commit() -> str:
    try:
        return subprocess.run(
            ["git", "rev-parse", "HEAD"], cwd=REPO, capture_output=True, text=True, check=True
        ).stdout.strip()
    except (OSError, subprocess.CalledProcessError):  # pragma: no cover
        return "unknown"


# --------------------------------------------------------------------------- 1
def _provider_reliability() -> tuple[bool, str]:
    """THE Phase-16 condition. Is the model path good enough for a run to mean anything?

    Read from `r86-factorial-001`, and specifically from the cell that uses the
    **production** request shape - the intake schema over a real gold note. A
    diagnostic that only exercised a two-field probe would pass this trivially and
    tell nobody anything: `r86-gradient-001` returned 0/56 on exactly that.
    """
    from eval.validity import ValidityRule

    if not FACTORIAL.is_file():
        return False, "no provider diagnostic exists; run scripts/r86_gradient.py --factorial"

    report = json.loads(FACTORIAL.read_text())
    production_cells = {
        name: cell for name, cell in report["cells"].items() if name.startswith("intake/gold_note")
    }
    if not production_cells:
        return False, "the diagnostic contains no production-shape cell"

    ceiling = ValidityRule().max_failure_rate
    failures = sum(c["provider_failure_rate"]["successes"] for c in production_cells.values())
    trials = sum(c["provider_failure_rate"]["total"] for c in production_cells.values())
    rate = failures / trials if trials else 1.0
    worst = max(production_cells.items(), key=lambda kv: kv[1]["provider_failure_rate"]["value"])
    if rate > ceiling:
        return False, (
            f"provider failure {failures}/{trials} = {rate:.4f} in the production "
            f"request shape exceeds the validity ceiling {ceiling:.2f}; worst cell "
            f"{worst[0]} at {worst[1]['provider_failure_rate']['value']:.4f}. "
            "R-86 is unresolved and OUTSIDE ENGINEERING CONTROL"
        )
    return True, f"provider failure {failures}/{trials} = {rate:.4f}, at or under {ceiling:.2f}"


# --------------------------------------------------------------------------- 2
def _gold_v1_immutable() -> tuple[bool, str]:
    digest = hashlib.sha256(GOLD_V1.read_bytes()).hexdigest()
    recorded = json.loads(GOLD_V1_MANIFEST.read_text())["sha256"]["gold"]
    if digest != recorded:
        return False, f"gold_v1 digest {digest[:16]} != manifest {recorded[:16]}"
    return True, f"gold_v1 {digest[:16]} byte-identical to its manifest"


# --------------------------------------------------------------------------- 3
def _gold_v2_exists_and_matches() -> tuple[bool, str]:
    if not GOLD_V2.is_file():
        return False, "gold_v2 does not exist; run scripts/build_gold_v2.py --write"
    digest = hashlib.sha256(GOLD_V2.read_bytes()).hexdigest()
    manifest = json.loads(GOLD_V2_MANIFEST.read_text())
    if digest != manifest["sha256"]["gold"]:
        return False, f"gold_v2 digest {digest[:16]} != manifest {manifest['sha256']['gold'][:16]}"
    return True, f"gold_v2 {digest[:16]}, {manifest['case_count']} cases"


# --------------------------------------------------------------------------- 4
def _r97_is_fixed() -> tuple[bool, str]:
    """Every gold_v2 case's applicability must follow from its structured input.

    Re-derived here from the case and the committed linkage - not read from the
    case's own assertion, which would check that the file agrees with itself.
    """
    import yaml

    linkage = yaml.safe_load((REPO / "data/linkage/policy_code_links.yaml").read_text())
    covered = {
        (str(link["code"]), str(link["code_system"]))
        for link in linkage["links"]
        if str(link.get("link_type", "COVERED_PROCEDURE")) == "COVERED_PROCEDURE"
    }
    mismatched: list[str] = []
    for line in GOLD_V2.read_text().splitlines():
        if not line.strip():
            continue
        case = json.loads(line)
        service = case["input"]["requested_service"]
        resolves = (str(service["procedure_code"]), str(service["code_system"])) in covered
        expected = case["expected"]["applicability"]["state"]
        if resolves != (expected == "RESOLVED"):
            mismatched.append(case["case_id"])
    if mismatched:
        return (
            False,
            f"{len(mismatched)} case(s) whose applicability does not follow: {mismatched[:5]}",
        )
    return True, "every gold_v2 case's applicability is derivable from its structured input"


# --------------------------------------------------------------------------- 5
def _gold_v2_budget_permits() -> tuple[bool, str]:
    """Read through `eval.schema`, not by re-parsing the manifest here.

    This function used to reach into `["scoring_budget"]["scorings_spent"]` itself,
    and `scripts/score_retrieval_v4_baseline.py` did the same arithmetic against a
    differently-shaped file with `dataset.get("scoring_budget", 1)` - a default that
    would have granted a free scoring to any dataset that forgot to declare one.
    Two implementations of "may this be scored" is how they come to disagree (R-103).
    """
    from eval.schema import budget_for

    budget = budget_for(GOLD_V2_MANIFEST)
    if not budget.permits_scoring:
        return False, f"gold_v2 scoring budget exhausted ({budget.spent}/{budget.allowed})"
    return True, f"gold_v2 scoring {budget.spent + 1} of {budget.allowed}, declared in ADR-029"


# --------------------------------------------------------------------------- 6
def _retrieval_benchmark_is_clean() -> tuple[bool, str]:
    if not RETRIEVAL_PROVENANCE.is_file():
        return False, "no retrieval_v4 provenance audit exists"
    audit = json.loads(RETRIEVAL_PROVENANCE.read_text())
    invalid = audit["counts"]["invalid_for_scoring"]
    if invalid:
        return False, f"{invalid} retrieval_v4 queries are INVALID_FOR_SCORING"
    empty = audit["categories_empty"]
    if empty:
        return False, f"retrieval_v4 categories are empty: {empty}"
    return (
        True,
        f"retrieval_v4 provenance clean, {audit['counts']['scorable']} queries, 10 categories",
    )


# --------------------------------------------------------------------------- 7
def _applicability_is_a_runtime_stage() -> tuple[bool, str]:
    source = (REPO / "app/graph/slice.py").read_text(encoding="utf-8")
    problems = [
        message
        for present, message in (
            (
                "if not finding.permits_adjudication:" in source,
                "the slice does not refuse on a non-RESOLVED finding",
            ),
            (
                "mode in PRODUCTION_MODES and applicability is None" in source,
                "PRODUCTION no longer requires an ApplicabilityPort",
            ),
            (
                "ResolutionState(status=ResolutionStatus.RESOLVED, version_count=1)" not in source,
                "the Phase-14 hardcoded ResolutionState literal is back",
            ),
        )
        if not present
    ]
    return (not problems, "; ".join(problems) or "applicability runs before intake, R-93 closed")


# --------------------------------------------------------------------------- 8
def _regressions_pass() -> tuple[bool, str]:
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "pytest",
            "-q",
            "tests/integration/test_case_0073_regression.py",
            "tests/unit/test_policy_applicability.py",
            "tests/unit/test_provider_failure_taxonomy.py",
            "tests/evaluation/test_gold_v2.py",
        ],
        cwd=REPO,
        capture_output=True,
        text=True,
    )
    tail = (result.stdout or result.stderr).strip().splitlines()
    return result.returncode == 0, tail[-1] if tail else "no output"


# --------------------------------------------------------------------------- 9
def _production_gate_ready() -> tuple[bool, str]:
    from app.production_gate import ProductionGate

    decision = ProductionGate(
        admissibility_report=REPO / "data/review/slice_admissibility.json",
        decision_records=(REPO / "data/review/focus_001_decision.json",),
    ).evaluate()
    detail = f"{decision.status.value} for {decision.policy_identity}"
    if decision.blockers:
        detail += f" - blockers: {'; '.join(decision.blockers)}"
    return decision.permits_inference, detail


# -------------------------------------------------------------------------- 10
def _nothing_tuned_since_the_freeze() -> tuple[bool, str]:
    """Prompt ids and retrieval configuration, against the Phase-13 freeze.

    The dataset changed - that is the point of gold_v2 - and nothing else may have.
    A prompt incremented between then and now is legitimate engineering and an
    illegitimate experiment input, and this is where the difference is caught.
    """
    from app.adjudication.assess import ASSESSMENT_PROMPT_ID
    from app.intake.extract import INTAKE_PROMPT_ID

    frozen = json.loads((REPO / "data/review/eval_410_33_frozen.json").read_text())
    fixed = frozen["configuration_fixed_for_experiment"]
    problems: list[str] = []
    if sorted(fixed["prompt_ids"]) != sorted([INTAKE_PROMPT_ID, ASSESSMENT_PROMPT_ID]):
        problems.append(
            f"prompt ids drifted: frozen {fixed['prompt_ids']} vs live "
            f"[{INTAKE_PROMPT_ID}, {ASSESSMENT_PROMPT_ID}]"
        )
    if fixed["retrieval"] != "RETRIEVAL_CONFIGURATION_UNRESOLVED":
        problems.append("the retrieval configuration is no longer declared unresolved")
    if not fixed["confidence_threshold"].startswith("UNCALIBRATED"):
        problems.append("a confidence threshold has been calibrated")
    return (not problems, "; ".join(problems) or "prompts, retrieval and abstention unchanged")


CONDITIONS: tuple[Condition, ...] = (
    Condition(
        "provider_reliability",
        "the model path is reliable enough to measure",
        _provider_reliability,
    ),
    Condition("gold_v1_immutable", "gold_v1 is byte-identical", _gold_v1_immutable),
    Condition("gold_v2_exists", "gold_v2 matches its manifest", _gold_v2_exists_and_matches),
    Condition("r97_fixed", "applicability follows from structured input", _r97_is_fixed),
    Condition(
        "gold_v2_budget", "gold_v2's scoring budget permits this run", _gold_v2_budget_permits
    ),
    Condition("retrieval_clean", "retrieval_v4 provenance is clean", _retrieval_benchmark_is_clean),
    Condition(
        "applicability_runtime",
        "applicability is a runtime stage",
        _applicability_is_a_runtime_stage,
    ),
    Condition("regressions_pass", "the load-bearing regressions pass", _regressions_pass),
    Condition("production_gate_ready", "the production gate is READY", _production_gate_ready),
    Condition(
        "nothing_tuned", "no prompt, retrieval or threshold tuning", _nothing_tuned_since_the_freeze
    ),
)


def evaluate() -> dict[str, Any]:
    """Run every condition. Never short-circuits - see `phase15_prerun_gate`."""
    results: dict[str, Any] = {}
    for condition in CONDITIONS:
        try:
            passed, detail = condition.check()
        except Exception as failure:  # a condition that raises has not passed
            passed, detail = False, f"{type(failure).__name__}: {failure}"
        results[condition.key] = {
            "requirement": condition.requirement,
            "passed": passed,
            "detail": detail,
        }
    return {
        "gate": "phase16-prerun",
        "experiment": EXPERIMENT_ID,
        "permits_run": all(r["passed"] for r in results.values()),
        "conditions": results,
        "blockers": [k for k, r in results.items() if not r["passed"]],
    }


def freeze_manifest() -> dict[str, Any]:
    """Everything the run would be executed under. Written before it is authorised.

    Freezing a manifest for a run that may not start is not a contradiction: the
    configuration is a commitment, and committing it while the gate says STOP is
    what makes "we did not run it, and here is exactly what we would have run"
    checkable rather than asserted.
    """
    from app.config.settings import Settings
    from app.llm.wiring import structured_model_for
    from eval.validity import VALIDITY_RULE_ID, ValidityRule

    settings = Settings()
    gold = json.loads(GOLD_V2_MANIFEST.read_text())
    rule = ValidityRule()
    structured = structured_model_for(settings)
    gate = evaluate()

    return {
        "experiment": EXPERIMENT_ID,
        "frozen_at": datetime.now(UTC).isoformat(),
        "status": "MANIFEST_FROZEN_RUN_NOT_AUTHORISED"
        if not gate["permits_run"]
        else "MANIFEST_FROZEN_RUN_PENDING",
        "preregistered_in": "docs/adr/ADR-029-phase16-experiment-preregistration.md",
        "not_a_continuation_of": ["frozen-410-33", "phase15-410-33"],
        "comparability_note": (
            "Different dataset, different code and different applicability semantics "
            "from both earlier runs. Its figures are NOT comparable with theirs."
        ),
        "dataset": {
            "id": "gold_v2",
            "path": "data/gold/cases/gold_v2.jsonl",
            "digest": f"sha256:{gold['sha256']['gold']}",
            "case_count": gold["case_count"],
            "case_ids": gold["case_ids"],
            "resolves": gold["resolves"],
            "derived_from": gold["derived_from"],
            "exclusions": "NONE. All 156 cases, no subset and no stratified sample.",
        },
        "applicability": {
            "implementation": "app.policy.live_applicability.LiveApplicability",
            "version": APPLICABILITY_VERSION,
            "digest": _digest(
                (REPO / "app/policy/applicability.py").read_text()
                + (REPO / "app/policy/live_applicability.py").read_text()
            ),
            "mode": "PRODUCTION",
            "states": 6,
        },
        "retrieval": {
            "status": "ENGINEERING_DEFAULT_UNRESOLVED",
            "embedding_model": "BAAI/bge-base-en-v1.5",
            "reranker_model": "cross-encoder/ms-marco-MiniLM-L-6-v2",
            "top_k": 40,
            "rerank_top_n": 5,
            "chunking": "section-aware, never crossing a section boundary (Phase 1)",
            "baseline": "eval/reports/retrieval-v4-baseline/results.json",
            "note": (
                "Fixed so it is not a variable. NOT selected on evidence; no claim "
                "about it may be drawn from this run."
            ),
        },
        "prompts": {"intake": "intake.v2", "adjudication": "adjudication.v1"},
        "model": {
            "digest": _digest(structured),
            "structured_mode": "json_schema",
            "temperature": 0.0,
            "max_output_tokens": {"intake": 1536, "adjudication": 512},
            "max_repair_attempts": 2,
            "max_attempts": settings.llm_max_attempts,
            "timeout_seconds": settings.llm_timeout_seconds,
        },
        "gateway": {
            "path": "MEDAUTH -> FirewallGateway -> llm-firewall -> provider",
            "configuration_digest": _digest(
                f"{settings.llm_base_url}|{settings.llm_timeout_seconds}|"
                f"{settings.llm_max_attempts}|{settings.llm_fail_closed}|"
                f"{settings.llm_streaming_enabled}|{structured}"
            ),
            "fail_closed": settings.llm_fail_closed,
            "streaming": settings.llm_streaming_enabled,
        },
        "experiment_validity_rule": {
            "id": VALIDITY_RULE_ID,
            "preregistered_in": "docs/adr/ADR-028-runtime-applicability-and-experiment-validity.md",
            "max_failure_rate": rule.max_failure_rate,
            "demote_on_class_erasure": rule.demote_on_class_erasure,
            "concentration_multiple": rule.concentration_multiple,
            "concentration_floor": rule.concentration_floor,
            "direction": "demote-only; no evidence promotes",
            "may_not_consult": "accuracy, in any form",
            "expected_outcome": (
                "DEGRADED_BY_PROVIDER_FAILURE. R-86 reproduces 6/6 in the production "
                "intake shape (r86-factorial-001), so a run today would exceed the "
                "ceiling on condition 1. Recorded BEFORE the run: if it happens it is "
                "a confirmed prediction, not a discovery."
            ),
        },
        "reporting": {
            "denominators": ["operational coverage", "decision quality"],
            "implementation": "eval/coverage.py",
            "rule": (
                "Neither may be presented as the other. Cases excluded from decision "
                "quality are counted in coverage and named by disposition; no case is "
                "ever dropped."
            ),
            "dispositions": [
                "ASSESSED",
                "PROVIDER_FAILURE",
                "DATASET_DEFECT",
                "CONTRADICTION",
                "SYSTEM_FAILURE",
                "RETRIEVAL_FAILURE",
            ],
            "cost": "COST_NOT_AVAILABLE - no price basis is recorded for this deployment",
        },
        "code_commit": _git_commit(),
        "source_digests": {
            "gold_v2": _file_digest(GOLD_V2),
            "gold_v2_manifest": _file_digest(GOLD_V2_MANIFEST),
            "gold_v2_migration": _file_digest(MIGRATION),
            "retrieval_v4": _file_digest(RETRIEVAL_V4),
            "retrieval_v4_provenance": _file_digest(RETRIEVAL_PROVENANCE),
        },
        "prerun_gate": gate,
        "prohibitions": [
            "No case may be excluded after seeing its result.",
            "No prompt, model, retrieval or decision parameter may change after this freeze.",
            "No threshold may be calibrated on gold_v2.",
            "Neither denominator may be presented as 'the accuracy'.",
            "A second scoring of gold_v2 requires its own ADR, in advance.",
        ],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--freeze-manifest", action="store_true")
    args = parser.parse_args()

    if args.freeze_manifest:
        # R-104. A freeze that can be re-taken is not a freeze. `AUTHORISATION.json`
        # records the digest of the manifest it decided ABOUT; re-running this
        # command would rewrite the manifest, silently invalidate that digest, and
        # leave an authorisation pointing at a configuration nobody authorised.
        #
        # Refused rather than versioned, because the correct response to "the
        # configuration changed" is a NEW experiment id with its own manifest and its
        # own authorisation - not the old experiment wearing new numbers. There is no
        # flag to override this; a flag would be the thing being prevented.
        if (OUT / "manifest.json").is_file():
            print(
                f"  REFUSING: {(OUT / 'manifest.json').relative_to(REPO)} is already "
                "frozen. Re-freezing would invalidate the digest recorded in "
                "AUTHORISATION.json and silently change what was authorised. A "
                "changed configuration needs a new experiment id, not a refreshed "
                "freeze.",
                file=sys.stderr,
            )
            return 1
        manifest = freeze_manifest()
        OUT.mkdir(parents=True, exist_ok=True)
        (OUT / "manifest.json").write_text(
            json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )
        print(f"  manifest frozen -> {(OUT / 'manifest.json').relative_to(REPO)}")
        print(f"  status          {manifest['status']}")
        return 0

    report = evaluate()
    if args.json:
        print(json.dumps(report, indent=2, sort_keys=True))
        return 0 if report["permits_run"] else 1

    for key, result in report["conditions"].items():
        print(f"  [{'PASS' if result['passed'] else 'STOP'}] {key:24} {result['detail']}")
    print()
    if report["permits_run"]:
        print("  PERMITTED")
    else:
        print(f"  STOP: {report['blockers']}")
        print(
            "\n  The dataset, the benchmark, the manifest and the validity rule are "
            "ready.\n  The provider path is not, and that is not an engineering task "
            "in this repository."
        )
    return 0 if report["permits_run"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
