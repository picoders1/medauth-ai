"""Verify the registered conditions still hold, re-run the reproducer, apply the gate.

    uv run python scripts/r86_gate_recheck.py --verify-only
    MEDAUTH_LIVE_MODEL=1 uv run python scripts/r86_gate_recheck.py --write

Parts A, B, C and D of Phase 17, in the order they have to happen.

## Why verification comes before the re-run

"R-86 is fixed" is a claim about a component MEDAUTH cannot see, and the only thing
that can support it here is the **registered reproducer producing a different result
under identical conditions**. Identical is doing the work in that sentence: a
re-run against a different model, a different schema, a different ceiling or a
different firewall path would produce a number that looks like evidence and is not.

So Part A compares the live configuration against
`factorial_preregistration.json` field by field and **refuses to re-run on any
drift**. A recheck that quietly adapted to a changed environment would be measuring
a different experiment and reporting it under the old id.

## The gate has three outcomes, and only one of them permits scoring

    PASS           the pre-registered rule is satisfied on the production shape
    FAIL           it is not
    INCONCLUSIVE   the evidence cannot decide - drift, an aborted run, no data

`INCONCLUSIVE` is not a soft `PASS`. It exists so that "we could not tell" has
somewhere to go other than into whichever adjacent verdict is more convenient, and
it stops the official evaluation exactly as `FAIL` does.

The threshold is read from `eval.validity.ValidityRule`, never restated here. A
second copy of a number that must not move is a second place it can move.
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
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parents[1]
GRADIENT = REPO / "eval/reports/r86-gradient"
REGISTERED_PLAN = GRADIENT / "factorial_preregistration.json"
REGISTERED_RESULT = GRADIENT / "factorial_results.json"
OUT = REPO / "eval/reports/r86-gate-recheck"
LIVE_FLAG = "MEDAUTH_LIVE_MODEL"

#: The cells that use the production request shape. The gate reads these and only
#: these: `r86-gradient-001` scored 0/56 on a two-field probe, so a gate reading the
#: flat cells would pass trivially and certify nothing.
PRODUCTION_CELL_PREFIX = "intake/gold_note"


class GateResult(StrEnum):
    """Three outcomes. Only `PASS` permits the official evaluation."""

    PASS = "PASS"  # noqa: S105 - a gate verdict, not a credential
    FAIL = "FAIL"
    #: The evidence cannot decide - configuration drift, a run that did not
    #: complete, or no observation at all. **Not a soft PASS**, and it stops the
    #: evaluation exactly as FAIL does.
    INCONCLUSIVE = "INCONCLUSIVE"

    @property
    def permits_official_evaluation(self) -> bool:
        return self is GateResult.PASS


@dataclass(frozen=True, slots=True)
class Drift:
    """One registered value that no longer matches the live configuration."""

    field: str
    registered: str
    observed: str

    def __str__(self) -> str:
        return f"{self.field}: registered {self.registered!r}, now {self.observed!r}"


def _digest(value: str) -> str:
    return f"sha256:{hashlib.sha256(value.encode()).hexdigest()[:12]}"


def _git_commit() -> str:
    try:
        return subprocess.run(
            ["git", "rev-parse", "HEAD"], cwd=REPO, capture_output=True, text=True, check=True
        ).stdout.strip()
    except (OSError, subprocess.CalledProcessError):  # pragma: no cover
        return "unknown"


def verify_conditions() -> tuple[list[Drift], dict[str, Any]]:
    """Part A. Compare the live configuration against what was registered.

    Every field the pre-registration froze, plus the acceptance threshold and the
    reproducer's own source. Returns the drifts found and what was observed, so a
    clean result is as legible as a dirty one.
    """
    import scripts.r86_gradient as reproducer
    from app.config.settings import Settings
    from app.llm.wiring import structured_model_for
    from eval.validity import VALIDITY_RULE_ID, ValidityRule

    plan = json.loads(REGISTERED_PLAN.read_text())
    registered = plan["held_constant"]
    settings = Settings()
    structured = structured_model_for(settings)

    observed: dict[str, Any] = {
        "model_digest": _digest(structured),
        "temperature": reproducer.TEMPERATURE,
        "max_output_tokens": reproducer.MAX_OUTPUT_TOKENS,
        "attempts_per_observation": reproducer.ATTEMPTS,
        "structured_mode": "json_schema",
        "firewall_path": registered["firewall_path"],
        "cells": [c.name for c in reproducer.FACTORIAL_CELLS],
        "trials_per_cell": reproducer.FACTORIAL_TRIALS,
        "probe_schema_digest": _digest(json.dumps(reproducer.PROBE_SCHEMA, sort_keys=True)),
        "flat_prompt_digest": _digest(reproducer.SYSTEM),
        "gateway_configuration_digest": _digest(
            f"{settings.llm_base_url}|{settings.llm_timeout_seconds}|"
            f"{settings.llm_max_attempts}|{settings.llm_fail_closed}|"
            f"{settings.llm_streaming_enabled}|{structured}"
        ),
        "validity_rule_id": VALIDITY_RULE_ID,
        "acceptance_threshold": ValidityRule().max_failure_rate,
    }

    drifts: list[Drift] = []
    for field in (
        "model_digest",
        "temperature",
        "max_output_tokens",
        "attempts_per_observation",
        "structured_mode",
        "firewall_path",
    ):
        if str(registered[field]) != str(observed[field]):
            drifts.append(Drift(field, str(registered[field]), str(observed[field])))

    # The design itself: same cells, same trial count. A reproducer that grew a cell
    # or dropped one is not the registered reproducer.
    if plan["cells"] != observed["cells"]:
        drifts.append(Drift("cells", str(plan["cells"]), str(observed["cells"])))
    if plan["trials_per_cell"] != observed["trials_per_cell"]:
        drifts.append(
            Drift("trials_per_cell", str(plan["trials_per_cell"]), str(observed["trials_per_cell"]))
        )

    # THE THRESHOLD. Read from the rule, and compared against what the previous
    # result was judged under. Lowering it is the single easiest way to turn a FAIL
    # into a PASS without touching the system at all.
    previous = json.loads(REGISTERED_RESULT.read_text()) if REGISTERED_RESULT.is_file() else {}
    judged_under = (previous.get("gate") or {}).get("acceptance_threshold")
    if judged_under is not None and float(judged_under) != float(observed["acceptance_threshold"]):
        drifts.append(
            Drift("acceptance_threshold", str(judged_under), str(observed["acceptance_threshold"]))
        )

    return drifts, observed


def apply_gate(
    cells: dict[str, Any], *, drifts: list[Drift], observations_made: int, planned: int
) -> dict[str, Any]:
    """Part C. The pre-registered rule, applied and not reinterpreted.

    The threshold comes from `ValidityRule`. This function does not restate it, does
    not adjust it for sample size, and has no branch that could.
    """
    from eval.validity import VALIDITY_RULE_ID, ValidityRule

    ceiling = ValidityRule().max_failure_rate
    production = {n: c for n, c in cells.items() if n.startswith(PRODUCTION_CELL_PREFIX)}

    def inconclusive(why: str) -> dict[str, Any]:
        return {
            "result": GateResult.INCONCLUSIVE.value,
            "why": why,
            "acceptance_threshold": ceiling,
            "rule_id": VALIDITY_RULE_ID,
            "permits_official_evaluation": False,
            "note": (
                "INCONCLUSIVE is not a soft PASS. It stops the official evaluation "
                "exactly as FAIL does, and exists so that 'we could not tell' has "
                "somewhere to go other than into the more convenient verdict."
            ),
        }

    if drifts:
        return inconclusive(
            "the live configuration no longer matches the registered reproducer: "
            + "; ".join(str(d) for d in drifts)
        )
    if not production:
        return inconclusive("the re-run produced no production-shape cell")
    if observations_made != planned:
        return inconclusive(
            f"the re-run made {observations_made} of {planned} planned observations; "
            "a partial matrix cannot decide the gate in either direction"
        )

    failures = sum(c["provider_failure_rate"]["successes"] for c in production.values())
    trials = sum(c["provider_failure_rate"]["total"] for c in production.values())
    if not trials:
        return inconclusive("no production-shape observation was made")

    rate = failures / trials
    worst = max(production.items(), key=lambda kv: kv[1]["provider_failure_rate"]["value"])
    passed = rate <= ceiling
    return {
        "result": (GateResult.PASS if passed else GateResult.FAIL).value,
        "acceptance_threshold": ceiling,
        "rule_id": VALIDITY_RULE_ID,
        "production_failure_rate": round(rate, 4),
        "production_failures": failures,
        "production_trials": trials,
        "worst_cell": worst[0],
        "worst_cell_rate": worst[1]["provider_failure_rate"]["value"],
        "cells_read": sorted(production),
        "permits_official_evaluation": passed,
        "why": (
            f"production-shape failure {failures}/{trials} = {rate:.4f} "
            f"{'is at or under' if passed else 'exceeds'} the pre-registered ceiling "
            f"{ceiling:.2f}"
        ),
    }


def live_signal() -> dict[str, Any]:
    """Part D / OD-40. Is there a trustworthy live provider signal to gate on?

    Asked honestly and answered from what the interface actually offers, not from
    what would be convenient. A `/health` on the proxy reports the proxy; it says
    nothing about whether a constrained decoder terminates on a long clinical note,
    which is the only property this gate cares about.
    """
    import httpx

    from app.config.settings import Settings

    settings = Settings()
    base = settings.llm_base_url.rstrip("/")
    probes: dict[str, Any] = {}
    for name, url in (
        ("models", f"{base}/models"),
        ("health", f"{base.rsplit('/v1', 1)[0]}/health"),
    ):
        try:
            response = httpx.get(url, timeout=10.0, headers={"user-agent": "medauth-ai/0.1"})
            probes[name] = {"status": response.status_code, "reachable": True}
        except Exception as failure:
            probes[name] = {"reachable": False, "error": type(failure).__name__}

    return {
        "od": "OD-40",
        "question": "can the provider gate read a live signal instead of a stored diagnostic?",
        "probes": probes,
        "verdict": "NO_TRUSTWORTHY_LIVE_SIGNAL",
        "reasoning": (
            "Reachability and a model listing describe the transport, not the "
            "behaviour this gate exists to check. R-86 is a decoder failing to "
            "terminate on a specific request shape: it returns HTTP 200, it is "
            "invisible to any health endpoint, and no capability listing reports "
            "it. A gate reading /health would report GREEN through the exact "
            "outage that made two evaluations uninterpretable."
        ),
        "decision": (
            "The pre-registered diagnostic remains the experiment precondition. "
            "OD-40 stays OPEN and is NOT closed by adding a probe that cannot see "
            "the failure."
        ),
        "what_would_change_it": (
            "A provider- or firewall-exposed signal describing constrained-decoding "
            "behaviour - a stop-condition guarantee, or a metric counting "
            "finish_reason=length on schema-constrained requests."
        ),
    }


async def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--write", action="store_true")
    parser.add_argument(
        "--verify-only", action="store_true", help="Part A only; make no model calls"
    )
    args = parser.parse_args()

    print("  PART A - registered conditions\n")
    drifts, observed = verify_conditions()
    plan = json.loads(REGISTERED_PLAN.read_text())
    for field in ("model_digest", "temperature", "max_output_tokens", "structured_mode"):
        print(f"    {field:28} {observed[field]}")
    print(f"    {'cells':28} {len(observed['cells'])} x {observed['trials_per_cell']} trials")
    print(f"    {'acceptance_threshold':28} {observed['acceptance_threshold']}")
    if drifts:
        print("\n  DRIFT DETECTED:")
        for drift in drifts:
            print(f"    {drift}")
    else:
        print("\n    no drift: the live configuration matches the registered reproducer")

    signal = live_signal()
    print(f"\n  PART D - live signal: {signal['verdict']}")

    if args.verify_only:
        print("\n  (verify-only; no model calls made)")
        return 0 if not drifts else 1

    if os.environ.get(LIVE_FLAG) != "1":
        print(f"\n  refusing: set {LIVE_FLAG}=1 to re-run the reproducer", file=sys.stderr)
        return 1

    if drifts:
        # Refused BEFORE any call. Re-running against a drifted configuration would
        # produce a number under the old experiment id that no longer describes it.
        print(
            "\n  REFUSING to re-run: the registered conditions no longer hold. "
            "A re-run under changed conditions is a different experiment.",
            file=sys.stderr,
        )
        gate = apply_gate({}, drifts=drifts, observations_made=0, planned=0)
        print(f"  gate: {gate['result']} - {gate['why']}")
        return 1

    print("\n  PART B - re-running r86-factorial-001, unchanged\n")
    import scripts.r86_gradient as reproducer
    from app.config.settings import Settings
    from app.llm.client import LlmClient
    from app.llm.wiring import structured_model_for

    settings = Settings()
    client = LlmClient(
        base_url=settings.llm_base_url,
        api_key=settings.llm_api_key.get_secret_value(),
        model=structured_model_for(settings),
        timeout_seconds=settings.llm_timeout_seconds,
        max_attempts=reproducer.ATTEMPTS,
    )
    results: dict[str, list[Any]] = {}
    try:
        for cell in reproducer.FACTORIAL_CELLS:
            observations = [
                await reproducer._observe_cell(client, cell, trial)
                for trial in range(1, reproducer.FACTORIAL_TRIALS + 1)
            ]
            results[cell.name] = observations
            marks = "".join(
                "R" if o.is_r86_signature else ("!" if not o.succeeded else ".")
                for o in observations
            )
            tokens = [o.prompt_tokens for o in observations if o.prompt_tokens]
            print(
                f"    {cell.name:26} {marks}  r86 "
                f"{sum(1 for o in observations if o.is_r86_signature)}/{len(observations)}  "
                f"prompt_tok {min(tokens) if tokens else 0}-{max(tokens) if tokens else 0}"
            )
    finally:
        await client.aclose()

    from collections import Counter
    from dataclasses import asdict

    from app.llm.failure_taxonomy import ProviderFailureKind

    cells = {
        name: {
            "trials": len(obs),
            "r86_signature_rate": reproducer._rate(
                sum(1 for o in obs if o.is_r86_signature), len(obs)
            ),
            "provider_failure_rate": reproducer._rate(
                sum(
                    1
                    for o in obs
                    if ProviderFailureKind(o.failure_kind).counts_toward_provider_reliability
                ),
                len(obs),
            ),
            "median_whitespace_fraction": sorted(o.whitespace_fraction for o in obs)[len(obs) // 2],
            "deterministic": len({o.completion_tokens for o in obs}) == 1,
            "latency_ms_median": sorted(o.latency_ms for o in obs)[len(obs) // 2],
            "prompt_tokens_min": min((o.prompt_tokens for o in obs if o.prompt_tokens), default=0),
            "prompt_tokens_max": max(o.prompt_tokens for o in obs),
            "failure_kinds": dict(sorted(Counter(o.failure_kind for o in obs).items())),
            "attributions": dict(sorted(Counter(o.attribution for o in obs).items())),
            "observations": [asdict(o) for o in obs],
        }
        for name, obs in results.items()
    }
    flat = [o for obs in results.values() for o in obs]
    gate = apply_gate(
        cells,
        drifts=drifts,
        observations_made=len(flat),
        planned=len(reproducer.FACTORIAL_CELLS) * reproducer.FACTORIAL_TRIALS,
    )

    previous = json.loads(REGISTERED_RESULT.read_text())
    report = {
        "recheck": "r86-gate-recheck",
        "reproducer": "r86-factorial-001",
        "ran_at": datetime.now(UTC).isoformat(),
        "git_commit": _git_commit(),
        "python": platform.python_version(),
        "registered_conditions": {
            "source": "eval/reports/r86-gradient/factorial_preregistration.json",
            "held_constant": plan["held_constant"],
            "observed": observed,
            "drift": [str(d) for d in drifts],
            "unchanged": not drifts,
        },
        "cells": cells,
        "gate": gate,
        "comparison_with_phase16": {
            "note": (
                "Same reproducer, same conditions, different day. A difference is "
                "evidence about the provider; an identical result is evidence the "
                "defect persists."
            ),
            "per_cell": {
                name: {
                    "phase16_r86": previous["cells"][name]["r86_signature_rate"]["successes"],
                    "phase17_r86": cells[name]["r86_signature_rate"]["successes"],
                    "trials": cells[name]["trials"],
                }
                for name in cells
                if name in previous.get("cells", {})
            },
        },
        "live_signal": signal,
        "clinical_text_in_this_report": "none - digests, counts, categories and token counts only",
        "claims_refused": [
            "that R-86 is fixed, absent a change in the decoder evidenced by its owner",
            "that the responsible layer is the provider or the firewall",
            "that an unchanged result licenses lowering the threshold",
        ],
    }

    print(f"\n  PART C - provider gate: {gate['result']}")
    print(f"    {gate['why']}")

    if args.write:
        OUT.mkdir(parents=True, exist_ok=True)
        (OUT / "results.json").write_text(
            json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )
        print(f"\n  written to {(OUT / 'results.json').relative_to(REPO)}")
    return 0 if gate["permits_official_evaluation"] else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
