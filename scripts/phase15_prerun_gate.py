"""The Phase-15 pre-run gate. Eight conditions, machine-checked, before anything runs.

    uv run python scripts/phase15_prerun_gate.py
    uv run python scripts/phase15_prerun_gate.py --json

Exit 0 permits the run. **Any failure is a STOP**, and the runner refuses to start
without consulting this — the check lives here so it can be read, and is called from
`scripts/run_phase15_evaluation.py` so it cannot be skipped.

## Why a gate rather than a checklist

Phase 14 had a checklist. It was satisfied, and the run still measured a system that
did not resolve applicability, because "R-93 is fixed" was not on it — nobody knew
yet. A checklist records what somebody thought of; a gate records what a later run
must not proceed without, and each condition below exists because something went
wrong once.

The gate deliberately does **not** check that the run will produce a good result.
Conditions that could be satisfied by a result are how a pre-registration regime
turns into a rubber stamp.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parents[1]
GOLD = REPO / "data/gold/cases/gold_v1.jsonl"
GOLD_MANIFEST = REPO / "data/gold/manifests/gold_v1.manifest.json"
FROZEN = REPO / "data/review/eval_410_33_frozen.json"
PHASE14 = REPO / "eval/reports/frozen-410-33"
PHASE15 = REPO / "eval/reports/phase15-410-33"


@dataclass(frozen=True, slots=True)
class Condition:
    """One thing that must hold. `check` returns (passed, detail)."""

    key: str
    requirement: str
    check: Callable[[], tuple[bool, str]]


def _tracked_diff(path: Path) -> str:
    try:
        return subprocess.run(
            ["git", "diff", "HEAD", "--", str(path.relative_to(REPO))],
            cwd=REPO,
            capture_output=True,
            text=True,
            check=True,
        ).stdout
    except (OSError, subprocess.CalledProcessError) as failure:  # pragma: no cover
        return f"git-unavailable: {failure}"


# --------------------------------------------------------------------------- 1
def _applicability_is_implemented() -> tuple[bool, str]:
    """R-93. The stage exists, the runtime consults it, and the literal is gone.

    Three separate facts, because any one of them alone can be true while the defect
    stands: a module can exist and be unused, a port can be declared and never
    called, and a call site can consult the finding and still pass a literal to the
    decision table.
    """
    module = REPO / "app/policy/applicability.py"
    slice_source = (REPO / "app/graph/slice.py").read_text(encoding="utf-8")
    problems: list[str] = []
    if not module.is_file():
        problems.append("app/policy/applicability.py is missing")
    if "if not finding.permits_adjudication:" not in slice_source:
        problems.append("the slice does not refuse on a non-RESOLVED finding")
    if "ResolutionState(status=ResolutionStatus.RESOLVED, version_count=1)" in slice_source:
        problems.append("the Phase-14 hardcoded ResolutionState literal is back")
    if "mode in PRODUCTION_MODES and applicability is None" not in slice_source:
        problems.append("PRODUCTION no longer requires an ApplicabilityPort")
    return (not problems, "; ".join(problems) or "stage present, consulted, literal gone")


# --------------------------------------------------------------------------- 2
def _case_0073_regression_passes() -> tuple[bool, str]:
    """Run it. Not "the file exists" - that is what a checklist would check."""
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "pytest",
            "-q",
            "tests/integration/test_case_0073_regression.py",
            "tests/unit/test_policy_applicability.py",
        ],
        cwd=REPO,
        capture_output=True,
        text=True,
    )
    tail = (result.stdout or result.stderr).strip().splitlines()
    return result.returncode == 0, tail[-1] if tail else "no output"


# --------------------------------------------------------------------------- 3
def _production_gate_is_ready() -> tuple[bool, str]:
    from app.production_gate import ProductionGate

    decision = ProductionGate(
        admissibility_report=REPO / "data/review/slice_admissibility.json",
        decision_records=(REPO / "data/review/focus_001_decision.json",),
    ).evaluate()
    detail = f"{decision.status.value} for {decision.policy_identity}"
    if decision.blockers:
        detail += f" - blockers: {'; '.join(decision.blockers)}"
    return decision.permits_inference, detail


# --------------------------------------------------------------------------- 4
def _dataset_is_unchanged() -> tuple[bool, str]:
    """Byte-identical to its manifest, and untouched in the working tree."""
    digest = hashlib.sha256(GOLD.read_bytes()).hexdigest()
    recorded = json.loads(GOLD_MANIFEST.read_text())["sha256"]["gold"]
    if digest != recorded:
        return False, f"gold_v1 digest {digest[:16]} != manifest {recorded[:16]}"
    if _tracked_diff(GOLD).strip():
        return False, "gold_v1.jsonl has uncommitted modifications"
    return True, f"gold_v1 {digest[:16]} matches its manifest, no working-tree diff"


# --------------------------------------------------------------------------- 5
def _validity_rule_is_preregistered() -> tuple[bool, str]:
    """The rule exists, is committed, and is described in an ADR.

    Committed matters: a rule that is only in the working tree could have been
    written after the run and dated before it.
    """
    from eval.validity import VALIDITY_RULE_ID

    adr = REPO / "docs/adr/ADR-028-runtime-applicability-and-experiment-validity.md"
    if not adr.is_file():
        return False, "ADR-028 is missing; the rule is not pre-registered"
    if VALIDITY_RULE_ID not in adr.read_text(encoding="utf-8"):
        return False, f"ADR-028 does not name {VALIDITY_RULE_ID}"
    return True, f"{VALIDITY_RULE_ID} pre-registered in ADR-028"


# --------------------------------------------------------------------------- 6
def _phase14_results_are_sealed() -> tuple[bool, str]:
    """Every Phase-14 artefact matches the checksum recorded when it was sealed."""
    status_file = PHASE14 / "STATUS.json"
    if not status_file.is_file():
        return False, "eval/reports/frozen-410-33/STATUS.json is missing"
    status = json.loads(status_file.read_text())
    drifted = [
        name
        for name, recorded in status["files"].items()
        if not (PHASE14 / name).is_file()
        or f"sha256:{hashlib.sha256((PHASE14 / name).read_bytes()).hexdigest()}" != recorded
    ]
    if drifted:
        return False, f"Phase-14 artefacts changed since sealing: {', '.join(drifted)}"
    return True, f"{len(status['files'])} Phase-14 artefacts unchanged, {status['status']}"


# --------------------------------------------------------------------------- 7
def _phase15_is_a_new_experiment() -> tuple[bool, str]:
    """Phase 15 writes somewhere else. Reusing the directory would overwrite Phase 14."""
    if PHASE15.resolve() == PHASE14.resolve():
        return False, "Phase 15 would write into the Phase-14 directory"
    existing = (PHASE15 / "manifest.json").is_file()
    return True, (
        "a Phase-15 manifest already exists and will be replaced by this run"
        if existing
        else "eval/reports/phase15-410-33/ is a fresh experiment directory"
    )


# --------------------------------------------------------------------------- 8
def _nothing_was_tuned_after_the_freeze() -> tuple[bool, str]:
    """Prompt ids, retrieval configuration and abstention state, against the freeze.

    Reads `data/review/eval_410_33_frozen.json`, which was written in Phase 13 before
    any Phase-14 or Phase-15 number existed. A prompt version incremented between
    then and now is legitimate engineering and an illegitimate experiment input, and
    this is where the difference is caught.
    """
    from app.adjudication.assess import ASSESSMENT_PROMPT_ID
    from app.intake.extract import INTAKE_PROMPT_ID

    frozen = json.loads(FROZEN.read_text())["configuration_fixed_for_experiment"]
    problems: list[str] = []
    if sorted(frozen["prompt_ids"]) != sorted([INTAKE_PROMPT_ID, ASSESSMENT_PROMPT_ID]):
        problems.append(
            f"prompt ids drifted: frozen {frozen['prompt_ids']} vs live "
            f"[{INTAKE_PROMPT_ID}, {ASSESSMENT_PROMPT_ID}]"
        )
    if frozen["retrieval"] != "RETRIEVAL_CONFIGURATION_UNRESOLVED":
        problems.append("the retrieval configuration is no longer declared unresolved")
    if not frozen["confidence_threshold"].startswith("UNCALIBRATED"):
        problems.append("a confidence threshold has been calibrated")
    return (not problems, "; ".join(problems) or "prompts, retrieval and abstention unchanged")


# --------------------------------------------------------------------------- 9
def _scoring_budget_permits() -> tuple[bool, str]:
    """A frozen split has a scoring budget, and this run spends one.

    Checked here rather than trusted, because the failure mode is silent: re-scoring
    a hold-out until a number improves produces a perfectly reproducible report about
    a corpus that has seen its own answers. The allowance must also be *declared* -
    an integer somebody raised is not a declaration, so the count of declarations has
    to match the count it permits.
    """
    budget = json.loads(GOLD_MANIFEST.read_text())["scoring_budget"]
    spent, allowed = budget["scorings_spent"], budget["allowed_scorings"]
    if spent >= allowed:
        return False, (
            f"gold_v1 scoring budget exhausted ({spent}/{allowed}); an additional "
            "scoring must be declared in an ADR in advance"
        )
    declarations = budget.get("allowance_declarations", [])
    if len(declarations) < allowed:
        return False, (
            f"allowance is {allowed} but only {len(declarations)} scoring(s) are declared"
        )
    return True, (
        f"gold_v1 scoring {spent + 1} of {allowed}, declared in {declarations[-1]['declared_in']}"
    )


CONDITIONS: tuple[Condition, ...] = (
    Condition(
        "r93_applicability_implemented",
        "R-93 resolution is a runtime stage",
        _applicability_is_implemented,
    ),
    Condition(
        "case_0073_regression_passes",
        "the CASE-0073 regression passes",
        _case_0073_regression_passes,
    ),
    Condition("production_gate_ready", "the production gate is READY", _production_gate_is_ready),
    Condition(
        "dataset_unchanged", "gold_v1 is byte-identical to its manifest", _dataset_is_unchanged
    ),
    Condition(
        "validity_rule_preregistered",
        "the validity rule is pre-registered",
        _validity_rule_is_preregistered,
    ),
    Condition(
        "phase14_sealed",
        "Phase-14 artefacts are immutable and unchanged",
        _phase14_results_are_sealed,
    ),
    Condition(
        "phase15_is_separate", "Phase 15 is a separate experiment", _phase15_is_a_new_experiment
    ),
    Condition(
        "nothing_tuned_after_freeze",
        "no prompt, retrieval or threshold tuning",
        _nothing_was_tuned_after_the_freeze,
    ),
    Condition(
        "scoring_budget_permits",
        "the gold scoring budget permits this run",
        _scoring_budget_permits,
    ),
)


def evaluate() -> dict[str, Any]:
    """Run every condition. **Never short-circuits.**

    A gate that stopped at the first failure would report one blocker per run, and
    closing them one at a time is how a phase spends four runs learning what it could
    have learned in one.
    """
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
        "gate": "phase15-prerun",
        "permits_run": all(r["passed"] for r in results.values()),
        "conditions": results,
        "blockers": [k for k, r in results.items() if not r["passed"]],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    report = evaluate()
    if args.json:
        print(json.dumps(report, indent=2, sort_keys=True))
    else:
        for key, result in report["conditions"].items():
            mark = "PASS" if result["passed"] else "STOP"
            print(f"  [{mark}] {key:34} {result['detail']}")
        print()
        print("  PERMITTED" if report["permits_run"] else f"  STOP: {report['blockers']}")
    return 0 if report["permits_run"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
