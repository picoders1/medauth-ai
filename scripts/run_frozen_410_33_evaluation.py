"""Run the frozen 26-case 410.33 evaluation. **Once, against a manifest written first.**

```
    MEDAUTH_LIVE_MODEL=1 uv run python scripts/run_frozen_410_33_evaluation.py --write
```

## The order matters more than the code

The manifest is written **before** the first case runs, and it fixes everything that
could otherwise be adjusted once a number appears: dataset digest, case ids, policy
version, encoder, reranker, `top_k`, chunking, prompt ids, model digest, temperature,
token ceiling, abstention configuration, schema version and commit.

A configuration recorded after a run is a configuration that could have been chosen
because of it. Nothing here is tuned, no case is excluded, and a defect discovered
mid-run is **recorded rather than repaired** - repairing it and re-running the
affected case would make the result a measurement of two different systems.

## What this measures, stated so it cannot be quoted as more

**Model-backed system performance on a small frozen engineering gold set.** Not
clinical accuracy. Not validation. 26 synthetic cases, one policy family, one
version, labels derived by construction from the same `decide()` the system runs.

The retrieval configuration is a **pre-registered engineering default**, not a
selection: `retrieval_v3` could not separate any two arms (p >= 0.0625, the minimum
achievable at n=31). It is fixed here so it is not a variable, and no claim about it
may be drawn from this result.
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import os
import platform
import subprocess
import sys
import time
from collections import Counter
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker

from app.config.settings import Settings
from app.contracts.slice import SliceInput
from app.core.identity import PolicyIdentity, PolicyType
from app.core.types import CodeSystem, CriterionKind
from app.database.engine import build_engine
from app.decision.semantics import Attestation, PolicySemantics, SemanticsOrigin
from app.graph.slice import SliceCriterion, SliceRunner
from app.llm.wiring import build_gateway, structured_model_for
from app.policy.logic_loader import load_policy_logic
from app.policy.models import PolicyDocument, PolicyVersion
from app.production_gate import ProductionGate
from app.retrieval.embed import SentenceTransformerEmbedder
from app.retrieval.live_port import LiveRetrieval
from app.retrieval.rerank import CrossEncoderReranker
from eval.official_gate import EvaluationBlocked, OfficialEvaluationGate

REPO = Path(__file__).resolve().parents[1]
GOLD = REPO / "data/gold/cases/gold_v1.jsonl"
FROZEN = REPO / "data/review/eval_410_33_frozen.json"
OUT = REPO / "eval/reports/frozen-410-33"
LIVE_FLAG = "MEDAUTH_LIVE_MODEL"

POLICY_ID = "42 CFR 410.33"
POLICY_VERSION = "2026-08-13"
IDENTITY = PolicyIdentity(
    policy_type=PolicyType.REGULATION, policy_id=POLICY_ID, version=POLICY_VERSION
)
CONFIG_VERSION = "slice.v1"

#: Pre-registered, and labelled for what it is. `retrieval_v3` scored once and could
#: not separate any two arms; this is the default that experiment left standing, not
#: a winner it produced.
RETRIEVAL_CONFIGURATION_STATUS = "ENGINEERING_DEFAULT_UNRESOLVED"
ENCODER = "BAAI/bge-base-en-v1.5"
RERANKER = "cross-encoder/ms-marco-MiniLM-L-6-v2"
TOP_K = 40
RERANK_TOP_N = 5


def _git_commit() -> str:
    try:
        return subprocess.run(
            ["git", "rev-parse", "HEAD"], cwd=REPO, capture_output=True, text=True, check=True
        ).stdout.strip()
    except (OSError, subprocess.CalledProcessError):  # pragma: no cover
        return "unknown"


def _digest(value: str) -> str:
    return f"sha256:{hashlib.sha256(value.encode()).hexdigest()[:12]}"


def _criteria() -> tuple[SliceCriterion, ...]:
    """The five transcribed criteria, read from the inventory - never re-typed here."""
    rows = [
        json.loads(line)
        for line in (REPO / "data/criteria/inventory.jsonl").read_text().splitlines()
        if line
    ]
    mine = sorted(
        (r for r in rows if r["policy_id"] == POLICY_ID and r["policy_version"] == POLICY_VERSION),
        key=lambda r: r["criterion_id"],
    )
    return tuple(
        SliceCriterion(
            criterion_id=r["criterion_id"],
            kind=CriterionKind(r["criterion_type"]),
            authoritative_text=r["authoritative_text"],
            interpretation=r["normalized_interpretation"],
            missing_evidence_hint=r["summary"],
        )
        for r in mine
    )


def _semantics() -> PolicySemantics:
    known = frozenset(
        json.loads(line)["criterion_id"]
        for line in (REPO / "data/criteria/inventory.jsonl").read_text().splitlines()
        if line
    )
    path = REPO / "data/policy_logic/42-CFR-410.33.yaml"
    return PolicySemantics.declared(
        policy_id=POLICY_ID,
        policy_version=POLICY_VERSION,
        logic=load_policy_logic(path, known_criteria=known),
        attestation=Attestation(
            source=str(path.relative_to(REPO)),
            sha256=hashlib.sha256(path.read_bytes()).hexdigest(),
            origin=SemanticsOrigin.DECLARED_LOGIC_FILE,
        ),
    )


def _manifest(settings: Settings, cases: list[dict[str, Any]]) -> dict[str, Any]:
    """Everything frozen, written before the first case runs."""
    raw = GOLD.read_bytes()
    ids = sorted(c["case_id"] for c in cases)
    return {
        "experiment": "frozen-410-33",
        "frozen_at": datetime.now(UTC).isoformat(),
        "status": "MANIFEST_FROZEN_RUN_PENDING",
        "dataset": {
            "id": "gold_v1",
            "version": "gold_v1",
            "path": "data/gold/cases/gold_v1.jsonl",
            "digest": f"sha256:{hashlib.sha256(raw).hexdigest()}",
            "case_ids": ids,
            "case_id_digest": f"sha256:{hashlib.sha256(','.join(ids).encode()).hexdigest()[:16]}",
            "case_count": len(ids),
            "split": "gold (frozen)",
        },
        "policy": {
            "type": IDENTITY.policy_type.value,
            "id": POLICY_ID,
            "version": POLICY_VERSION,
            "identity": str(IDENTITY),
        },
        "retrieval": {
            "status": RETRIEVAL_CONFIGURATION_STATUS,
            "note": (
                "PRE_REGISTERED_ENGINEERING_DEFAULT. retrieval_v3 scored once and "
                "separated no two arms (best p=0.0625, the minimum achievable at "
                "n=31). Fixed here so it is not a variable; NOT optimal, NOT selected."
            ),
            "embedding_model": ENCODER,
            "reranker_model": RERANKER,
            "top_k": TOP_K,
            "rerank_top_n": RERANK_TOP_N,
            "chunking": "section-aware, never crossing a section boundary (Phase 1)",
            "scope": "one policy type, one resolved version, date of service applied",
        },
        "model": {
            "digest": _digest(structured_model_for(settings)),
            "structured_mode": "json_schema",
            "temperature": 0.0,
            "max_output_tokens": {"intake": 1536, "adjudication": 512},
            "max_repair_attempts": 2,
            "max_attempts": settings.llm_max_attempts,
            "timeout_seconds": settings.llm_timeout_seconds,
            "path": "MEDAUTH -> FirewallGateway -> llm-firewall -> provider",
        },
        "prompts": {"intake": "intake.v2", "adjudication": "adjudication.v1"},
        "abstention": {
            "scored_gate": "UNCALIBRATED",
            "note": "No threshold is selected, and none may be calibrated on this set.",
            "structural_states": 9,
        },
        "schema_version": 1,
        "decision_config_version": CONFIG_VERSION,
        "code_commit": _git_commit(),
        "python": platform.python_version(),
        "platform": platform.platform(),
        "prohibitions": [
            "No prompt, model, retrieval or decision parameter may change during the run.",
            "No case may be excluded after seeing its result.",
            "A defect found mid-run is RECORDED, not repaired - repairing it and "
            "re-running the case would measure two different systems.",
        ],
    }


async def _run_case(
    case: dict[str, Any],
    runner: SliceRunner,
    retrieval: LiveRetrieval,
    criteria: tuple[SliceCriterion, ...],
) -> dict[str, Any]:
    retrieval.calls.clear()
    expected = case["expected"]
    note = case["input"]["clinical_note"]
    started = time.perf_counter()
    result = await runner.run(
        SliceInput(
            case_id=case["case_id"],
            clinical_note=note,
            # Read from the case, never defaulted. Date of service governs version
            # selection (ADR-004); a default here would silently resolve every
            # undated request against the same revision.
            procedure_code=case["input"]["requested_procedure"]["code"],
            code_system=CodeSystem(case["input"]["requested_procedure"]["code_system"]),
            date_of_service=date.fromisoformat(case["input"]["date_of_service"]),
            diagnosis_codes=tuple(case["input"].get("diagnosis_codes") or ()),
            jurisdiction=case["input"].get("jurisdiction"),
        )
    )
    wall = (time.perf_counter() - started) * 1000

    expected_states = {c["criterion_id"]: c["state"] for c in expected["criteria"]}
    actual_states = {a.criterion_id: a.assessment.value for a in result.assessments}
    # NOT_APPLICABLE is a policy-logic outcome, never a model state; a gold label of
    # NOT_APPLICABLE has no model counterpart and is scored as such rather than
    # silently mapped onto UNKNOWN.
    comparable = {
        cid: (exp, actual_states.get(cid))
        for cid, exp in expected_states.items()
        if exp in {"SATISFIED", "NOT_SATISFIED", "UNKNOWN"}
    }

    return {
        "case_id": case["case_id"],
        "category": case["category"],
        "borderline": case.get("borderline", False),
        "policy_identity": str(IDENTITY),
        "policy_version": POLICY_VERSION,
        "expected_recommendation": expected["decision"],
        "actual_recommendation": result.outcome.value,
        "decision_correct": result.outcome.value == expected["decision"],
        "expected_rule": expected["decision_rule"],
        "actual_rule": result.recommendation.rule.value,
        "expected_criterion_states": expected_states,
        "actual_criterion_states": actual_states,
        "criterion_correct": sum(1 for e, a in comparable.values() if e == a),
        "criterion_comparable": len(comparable),
        "retrieved_evidence_ids": {cid: list(ch) for cid, ch in retrieval.calls},
        "citations_verified": len(result.citations.verified),
        "citation_failures": [r.value for r in result.citations.failure_reasons],
        "citation_valid": result.citations.passed,
        "contradiction_state": result.contradictions.state.value,
        "abstention_state": result.abstention.reason.value if result.abstention else None,
        "guardrail_state": ("CONTRADICTION" if result.contradictions.is_decisive else "PASSED"),
        "assessments_with_evidence": sum(1 for a in result.assessments if a.evidence_ids),
        "assessments_total": len(result.assessments),
        "model_calls": result.model_calls,
        "tokens": result.tokens,
        "latency_ms": {k: round(v, 1) for k, v in result.timings_ms.items()},
        "wall_ms": round(wall, 1),
        "audit_events": [e.event for e in result.audit],
        "audit_complete": all(e.decision_config_version == CONFIG_VERSION for e in result.audit),
    }


async def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--write", action="store_true")
    parser.add_argument("--limit", type=int, default=0, help="smoke-test a few cases")
    args = parser.parse_args()

    # R-103. The gate that `eval/official_gate.py` calls itself "the sole
    # authorisation boundary" had, until this commit, no call site anywhere outside
    # its own tests. A boundary nobody crosses is documentation.
    #
    # It is checked HERE, first, before the live flag and before any dataset is
    # opened: a run that discovers it was unauthorised after scoring has already
    # scored. `require()` raises rather than returning a boolean because the callers
    # that matter are scripts, and a boolean is something a script forgets.
    try:
        OfficialEvaluationGate.require()
    except EvaluationBlocked as blocked:
        print(f"  REFUSING: {blocked}", file=sys.stderr)
        return 1

    if os.environ.get(LIVE_FLAG) != "1":
        print(f"  refusing: set {LIVE_FLAG}=1 to make real model calls", file=sys.stderr)
        return 1

    gate = ProductionGate(
        admissibility_report=REPO / "data/review/slice_admissibility.json",
        decision_records=(REPO / "data/review/focus_001_decision.json",),
    ).evaluate()
    if not gate.permits_inference:
        print(f"  refusing: production gate is {gate.status.value}", file=sys.stderr)
        return 1

    rows = [json.loads(line) for line in GOLD.read_text().splitlines() if line]
    cases = sorted(
        (
            r
            for r in rows
            if r["expected"]["policy_id"] == POLICY_ID
            and r["expected"]["policy_revision"] == POLICY_VERSION
        ),
        key=lambda r: r["case_id"],
    )
    frozen = json.loads(FROZEN.read_text())
    ids = [c["case_id"] for c in cases]
    if ids != frozen["case_ids"]:
        print("  refusing: case set differs from the frozen manifest", file=sys.stderr)
        return 1

    settings = Settings()
    manifest = _manifest(settings, cases)
    OUT.mkdir(parents=True, exist_ok=True)
    if args.write:
        # WRITTEN BEFORE THE FIRST CASE RUNS. This is the whole point.
        (OUT / "manifest.json").write_text(
            json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )
        print(f"  manifest frozen -> {(OUT / 'manifest.json').relative_to(REPO)}")

    print(f"  policy      {manifest['policy']['identity']}")
    print(f"  cases       {len(cases)}  digest {manifest['dataset']['case_id_digest']}")
    print(f"  retrieval   {RETRIEVAL_CONFIGURATION_STATUS}")
    print(f"  model       {manifest['model']['digest']}  mode json_schema\n")

    criteria = _criteria()
    semantics = _semantics()
    engine = build_engine(settings)
    maker = async_sessionmaker(engine, expire_on_commit=False)
    gateway = build_gateway(settings)
    results: list[dict[str, Any]] = []

    async with maker() as session:
        version_ids = {
            v
            for (v,) in (
                await session.execute(
                    select(PolicyVersion.id)
                    .join(PolicyDocument, PolicyDocument.id == PolicyVersion.document_id)
                    .where(
                        PolicyDocument.policy_id == POLICY_ID,
                        PolicyVersion.revision_id == POLICY_VERSION,
                    )
                )
            ).all()
        }
        if not version_ids:
            print(f"  refusing: {POLICY_ID} rev {POLICY_VERSION} is not ingested", file=sys.stderr)
            return 1

        retrieval = LiveRetrieval(
            session=session,
            embedder=SentenceTransformerEmbedder(ENCODER),
            version_ids=frozenset(version_ids),
            reranker=CrossEncoderReranker(RERANKER),
            top_k=TOP_K,
            rerank_top_n=RERANK_TOP_N,
        )
        runner = SliceRunner(
            gateway=gateway,
            retrieval=retrieval,  # type: ignore[arg-type]
            identity=IDENTITY,
            criteria=criteria,
            semantics=semantics,
            decision_config_version=CONFIG_VERSION,
            gate=gate,
        )

        selected = cases[: args.limit] if args.limit else cases
        for index, case in enumerate(selected, 1):
            row = await _run_case(case, runner, retrieval, criteria)
            results.append(row)
            mark = "ok " if row["decision_correct"] else "NO "
            print(
                f"  [{index:2}/{len(selected)}] {row['case_id']}  {mark} "
                f"exp={row['expected_recommendation']:20} act={row['actual_recommendation']:20} "
                f"crit={row['criterion_correct']}/{row['criterion_comparable']} "
                f"cite={row['citations_verified']}"
            )

    await engine.dispose()

    if args.write:
        (OUT / "per_case.json").write_text(
            json.dumps(results, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )
        manifest["status"] = "RUN_COMPLETE"
        manifest["ran_at"] = datetime.now(UTC).isoformat()
        manifest["cases_attempted"] = len(results)
        (OUT / "manifest.json").write_text(
            json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )
        print(f"\n  written to {OUT.relative_to(REPO)}")

    correct = sum(1 for r in results if r["decision_correct"])
    print(f"\n  decision accuracy  {correct}/{len(results)}")
    print(f"  outcomes           {dict(Counter(r['actual_recommendation'] for r in results))}")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
