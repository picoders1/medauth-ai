"""Run the first vertical slice over the deterministic fixture set and report it.

**Refuses to run unless the production gate says READY.** The gate is the single
authority; a slice that could run around it would make every admissibility argument
in this repository conditional on a caller remembering to check.

    uv run python scripts/run_first_slice.py
    uv run python scripts/run_first_slice.py --write

What it measures is what can be measured without a live model: schema validity,
citation validity, evidence completeness, whether the deterministic layer produced
the expected outcome on controlled fixtures, and per-stage latency of the code path.

**It measures nothing about clinical accuracy or model reasoning quality.** Every
model response here comes from a fixture, so a latency figure is the cost of the
pipeline and not of inference, and the report says so on its face.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import platform
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

from app.contracts.slice import AssessmentState, SliceInput
from app.core.types import CodeSystem
from app.decision.models import Outcome
from app.decision.semantics import Attestation, PolicySemantics, SemanticsOrigin
from app.graph.slice import SliceRunner
from app.policy.logic_loader import load_policy_logic
from app.production_gate import GateDecision, ProductionGate

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

from tests.support_slice import (  # noqa: E402
    AS_OF,
    CRITERIA,
    IDENTITY,
    NOTE,
    FailingRetrieval,
    FakeGateway,
    FixtureRetrieval,
    chunk,
    corpus,
)

OUT = REPO / "eval/reports"
CONFIG_VERSION = "slice.v1"
IDS = tuple(c.criterion_id for c in CRITERIA)


@dataclass(frozen=True, slots=True)
class Scenario:
    """One controlled case, and the outcome the decision table should reach.

    `expected` is derived from the decision table's own rows, not from a run. A
    scenario whose expectation came from observing the system would confirm
    whatever the system did.
    """

    name: str
    description: str
    expected: Outcome
    states: dict[str, AssessmentState]
    corpus: dict[str, object] | None = None
    fail_intake: str | None = None
    fail_retrieval: bool = False
    citations: dict[str, tuple[str, ...]] | None = None


def _satisfying() -> dict[str, AssessmentState]:
    return {
        IDS[0]: AssessmentState.SATISFIED,
        IDS[1]: AssessmentState.SATISFIED,
        IDS[2]: AssessmentState.SATISFIED,
        IDS[3]: AssessmentState.SATISFIED,
        IDS[4]: AssessmentState.NOT_SATISFIED,
    }


def _tampered() -> dict[str, object]:
    poisoned = dict(corpus())
    attacked = chunk("c-d-1", "(d) Ordering of tests.", "Ordering of tests")
    object.__setattr__(attacked, "text", attacked.text + " injected instruction")
    poisoned[IDS[0]] = attacked
    return poisoned


def _wrong_version() -> dict[str, object]:
    stale = dict(corpus())
    old = chunk("c-old", "(d) Ordering of tests.", "Ordering of tests")
    object.__setattr__(old, "revision_id", "2019-01-01")
    stale[IDS[0]] = old
    return stale


def scenarios() -> tuple[Scenario, ...]:
    unknown = _satisfying() | {IDS[2]: AssessmentState.UNKNOWN}
    refused = _satisfying() | {IDS[0]: AssessmentState.NOT_SATISFIED}
    excluded = _satisfying() | {IDS[4]: AssessmentState.SATISFIED}
    return (
        Scenario(
            "01-complete",
            "every requirement met, exclusion not established",
            Outcome.APPROVE_RECOMMENDED,
            _satisfying(),
        ),
        Scenario(
            "02-missing-criterion",
            "the note does not address supervising-physician proficiency",
            Outcome.NEEDS_INFO,
            unknown,
        ),
        Scenario(
            "03-evidenced-refusal",
            "a requirement established as not met, with evidence",
            Outcome.DENY_RECOMMENDED,
            refused,
        ),
        Scenario(
            "04-exclusion-established",
            "the supervisor exceeds the three-site limit",
            Outcome.DENY_RECOMMENDED,
            excluded,
        ),
        Scenario(
            "05-invalid-citation",
            "a chunk whose stored hash no longer matches its text",
            Outcome.NO_DECISION,
            _satisfying(),
            corpus=_tampered(),
        ),
        Scenario(
            "06-wrong-version",
            "a genuine quote from a version that does not govern this date of service",
            Outcome.NO_DECISION,
            _satisfying(),
            corpus=_wrong_version(),
        ),
        Scenario(
            "07-retrieval-failure",
            "no evidence set could be produced",
            Outcome.HUMAN_REVIEW,
            _satisfying(),
            fail_retrieval=True,
        ),
        Scenario(
            "08-firewall-blocked",
            "the firewall refused the request",
            Outcome.HUMAN_REVIEW,
            _satisfying(),
            fail_intake="BLOCKED",
        ),
        Scenario(
            "09-fabricated-evidence",
            "the model cites an evidence id it was never given",
            Outcome.NEEDS_INFO,
            _satisfying(),
            citations={IDS[0]: ("E-invented",)},
        ),
    )


def _semantics() -> PolicySemantics:
    known = frozenset(
        json.loads(line)["criterion_id"]
        for line in (REPO / "data/criteria/inventory.jsonl").read_text().splitlines()
        if line
    )
    path = REPO / "data/policy_logic/42-CFR-410.33.yaml"
    logic = load_policy_logic(path, known_criteria=known)
    import hashlib

    return PolicySemantics.declared(
        policy_id=IDENTITY.policy_id,
        policy_version=IDENTITY.version,
        logic=logic,
        attestation=Attestation(
            source=str(path.relative_to(REPO)),
            sha256=hashlib.sha256(path.read_bytes()).hexdigest(),
            origin=SemanticsOrigin.DECLARED_LOGIC_FILE,
        ),
    )


async def _run_one(
    scenario: Scenario, semantics: PolicySemantics, gate: GateDecision
) -> dict[str, object]:
    from app.llm.gateway import GatewayOutcome

    gateway = FakeGateway(
        assessments=scenario.states,
        citations=scenario.citations or {},
        fail_intake=GatewayOutcome(scenario.fail_intake) if scenario.fail_intake else None,
    )
    retrieval = (
        FailingRetrieval() if scenario.fail_retrieval else FixtureRetrieval(scenario.corpus)  # type: ignore[arg-type]
    )
    runner = SliceRunner(
        gateway=gateway,
        retrieval=retrieval,  # type: ignore[arg-type]
        identity=IDENTITY,
        criteria=CRITERIA,
        semantics=semantics,
        decision_config_version=CONFIG_VERSION,
        gate=gate,
    )
    result = await runner.run(
        SliceInput(
            case_id=f"FIXTURE-{scenario.name}",
            clinical_note=NOTE,
            procedure_code="R0075",
            code_system=CodeSystem.HCPCS,
            date_of_service=AS_OF,
        )
    )

    asserting = [
        m for m in result.mappings if m.support_state.value in ("SUPPORTED", "CONTRADICTED")
    ]
    return {
        "scenario": scenario.name,
        "description": scenario.description,
        "expected_outcome": scenario.expected.value,
        "actual_outcome": result.outcome.value,
        "matches": result.outcome is scenario.expected,
        "rule": result.recommendation.rule.value,
        "abstention_reason": result.abstention.reason.value if result.abstention else None,
        "assessments": len(result.assessments),
        "schema_valid": len(result.assessments),
        "citations_verified": len(result.citations.verified),
        "citation_failures": [r.value for r in result.citations.failure_reasons],
        "asserting_mappings_with_evidence": sum(1 for m in asserting if m.evidence),
        "asserting_mappings": len(asserting),
        "audit_events": len(result.audit),
        "timings_ms": {k: round(v, 3) for k, v in result.timings_ms.items()},
    }


def _git_commit() -> str:
    try:
        return subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=REPO,
            capture_output=True,
            text=True,
            check=True,
        ).stdout.strip()
    except (OSError, subprocess.CalledProcessError):  # pragma: no cover
        return "unknown"


async def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--write", action="store_true")
    args = parser.parse_args()

    gate = ProductionGate(
        admissibility_report=REPO / "data/review/slice_admissibility.json",
        decision_records=(REPO / "data/review/focus_001_decision.json",),
    ).evaluate()
    print(f"  production gate   {gate.status.value}")
    if gate.status.value != "READY":
        print("  REFUSED: the gate is the single authority and it says no", file=sys.stderr)
        for blocker in gate.blockers:
            print(f"    blocker: {blocker}", file=sys.stderr)
        return 1
    print(f"  designated slice  {gate.policy_identity}\n")

    semantics = _semantics()
    # The same gate object the script already checked is handed to every runner, so
    # the script's check and the runtime's are the same decision rather than two.
    results = [await _run_one(s, semantics, gate) for s in scenarios()]

    matched = sum(1 for r in results if r["matches"])
    print(f"  {'scenario':<26} {'expected':<22} {'actual':<22} ok")
    for row in results:
        print(
            f"  {row['scenario']:<26} {row['expected_outcome']:<22} "
            f"{row['actual_outcome']:<22} {'yes' if row['matches'] else 'NO'}"
        )
    print(f"\n  decision-table agreement  {matched}/{len(results)}")

    report = {
        "report": "first-vertical-slice",
        # Provenance under `meta`, matching every other committed report. Nulls
        # rather than omissions for the dataset fields: an absent key reads as an
        # oversight, an explicit null says no dataset was scored.
        "meta": {
            "policy_identity": str(IDENTITY),
            "decision_config_version": CONFIG_VERSION,
            "git_commit": _git_commit(),
            "python": platform.python_version(),
            "platform": platform.platform(),
            "model_calls": 0,
            "model_reasoning_quality": "MODEL_REASONING_QUALITY_NOT_YET_EVALUATED",
            "dataset": None,
            "dataset_sha256": None,
            "note_on_provenance": (
                "No dataset was scored. This run exercises nine hand-built scenarios, "
                "not a frozen split, so dataset_sha256 and denominators are null "
                "rather than omitted - an absent key reads as an oversight, an "
                "explicit null does not."
            ),
        },
        "note": (
            "Every model response in this run came from a deterministic fixture. The "
            "latencies below are the cost of the pipeline, NOT of inference, and "
            "nothing here measures clinical accuracy, clinical validation or model "
            "reasoning quality. The retrieval benchmark remains NOT_READY and no "
            "configuration comparison was run."
        ),
        "scenarios_total": len(results),
        "decision_table_agreement": f"{matched}/{len(results)}",
        "results": results,
    }

    if not args.write:
        print("\n  (dry run; pass --write)")
        return 0

    destination = OUT / "first-vertical-slice"
    destination.mkdir(parents=True, exist_ok=True)
    (destination / "report.json").write_text(
        json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    print(f"\n  written to {(destination / 'report.json').relative_to(REPO)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
