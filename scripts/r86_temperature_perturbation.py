"""One variable, six trials: does a little stochasticity change R-86's runaway?

    uv run python scripts/r86_temperature_perturbation.py --freeze-manifest
    MEDAUTH_LIVE_MODEL=1 uv run python scripts/r86_temperature_perturbation.py --write

`r86-temperature-perturbation-001`. A **diagnostic**, and nothing else. It cannot close
R-86, cannot authorise an official evaluation, and cannot change what production runs
at - the registered system is temperature 0.0 and stays there whatever this returns.

## Why the request is provably identical

The messages, the schema and the payload come from
`scripts/r86_gradient._factorial_request(Cell("intake", "gold_note", "long"))` - the
same function the sealed reproducer calls, not a copy of it. A second implementation of
"build the failing request" would agree with the first until it did not, and the whole
value of this experiment is that exactly one field differs.

`verify_against_seal()` is reused unmodified and must return **no differences** before a
single call is made. Note what that checks: `reproducer.TEMPERATURE` is still 0.0, and
it must be. The instrument is unchanged; this runner passes 0.2 at call time as the one
deliberate deviation, and records it as such.

So the deviation is not "the reproducer now runs at 0.2". It is "the reproducer, still
registered at 0.0, was invoked once at 0.2 under its own experiment id".

## Why the manifest is frozen first, and cannot be re-frozen

R-104. A freeze that can be re-taken is not a freeze, and a trial count that can be
changed after seeing three failures is not a trial count. Both are written before the
first call and refused afterwards.

## What this cannot conclude

Part E of the brief, enforced in `classify_outcome()`: one perturbation of one
parameter, six trials. A reduction does not make temperature the root cause; a
persistence does not make temperature irrelevant. The vocabulary has no member that
says either.
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
from dataclasses import asdict
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from app.llm.failure_taxonomy import ResponseShape
from eval.r86_closure import CLOSURE_RULE_ID, trial_succeeds

REPO = Path(__file__).resolve().parents[1]
SEAL = REPO / "data/escalations/r86-reproducer.manifest.json"
OUT = REPO / "eval/experiments/r86-temperature-perturbation-001"
MANIFEST = OUT / "manifest.json"
RESULTS = OUT / "results.json"

EXPERIMENT_ID = "r86-temperature-perturbation-001"
PARENT_EXPERIMENT_ID = "r86-reproducer-001"
LIVE_FLAG = "MEDAUTH_LIVE_MODEL"

#: The one variable. Registered here and read from here by both the manifest and the
#: runner, so "what was frozen" and "what ran" cannot be two different numbers.
REGISTERED_TEMPERATURE = 0.0
PERTURBED_TEMPERATURE = 0.2
TRIALS = 6
CELL = ("intake", "gold_note", "long")

#: Pre-registered before any call. Bands, not a threshold, because this is a diagnostic
#: and there is nothing here to pass or fail.
OUTCOME_BANDS = {
    "RUNAWAY_REDUCED": (0, 2),
    "MIXED": (3, 5),
    "RUNAWAY_PERSISTS": (6, 6),
}


def _digest(value: str, *, salt: str = "") -> str:
    return f"sha256:{hashlib.sha256((salt + value).encode()).hexdigest()[:16]}"


def _git_commit() -> str:
    try:
        out = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=REPO,
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        )
        return out.stdout.strip() or "unknown"
    except (OSError, subprocess.SubprocessError):  # pragma: no cover
        return "unknown"


def classify_outcome(failures: int, trials: int) -> dict[str, Any]:
    """Pre-registered bands, and prose that refuses the two available overreaches.

    Written before the run and read after it. The interpretation strings are part of
    the registration for the same reason the bands are: a sentence chosen once the
    numbers are known is a conclusion looking for its evidence.
    """
    band = next(
        (name for name, (lo, hi) in OUTCOME_BANDS.items() if lo <= failures <= hi),
        "UNCLASSIFIED",
    )
    interpretation = {
        "RUNAWAY_REDUCED": (
            "Temperature perturbation changes the observed failure behaviour. This "
            "does NOT establish temperature as the root cause, and does NOT confirm "
            "greedy decoding as the mechanism - one perturbation of one parameter "
            "cannot carry either claim."
        ),
        "RUNAWAY_PERSISTS": (
            "The failure persists under this temperature perturbation. This does NOT "
            "establish that temperature is unrelated to the root cause - one "
            "perturbation at one value is insufficient to show that."
        ),
        "MIXED": (
            "Temperature perturbation changes failure probability, but the mechanism "
            "remains unresolved. No causal model is fitted to six trials."
        ),
        "UNCLASSIFIED": (
            "The failure count fell outside every pre-registered band, which means "
            "the trial count differed from the registration. The run does not "
            "interpret."
        ),
    }[band]
    return {
        "outcome": band,
        "failures": failures,
        "trials": trials,
        "interpretation": interpretation,
        "claims_refused": [
            "temperature is the root cause",
            "the provider bug is confirmed as greedy decoding",
            "temperature is unrelated to the root cause",
            "any statement about clinical correctness or model quality",
            "anything about whether R-86 is fixed",
        ],
    }


def build_manifest() -> dict[str, Any]:
    """Everything the run will be executed under. Written before the first call."""
    import scripts.r86_gradient as reproducer
    from app.config.settings import Settings
    from app.contracts.slice import IntakeExtraction
    from app.intake.extract import _INSTRUCTIONS, _NOTE_FRAME
    from app.llm.firewall_gateway import _SYSTEM
    from app.llm.schema_call import harden_schema
    from app.llm.wiring import structured_model_for

    settings = Settings()
    structured = structured_model_for(settings)
    schema = harden_schema(IntakeExtraction.model_json_schema())
    seal = json.loads(SEAL.read_text(encoding="utf-8"))

    return {
        "experiment_id": EXPERIMENT_ID,
        "parent_experiment_id": PARENT_EXPERIMENT_ID,
        "parent_seal_sha256": seal["sealed_sha256"],
        "purpose": (
            "Diagnostic only. Test whether a small amount of decoding stochasticity "
            "changes the observed constrained-decoding runaway on the registered "
            "R-86 failing cell. This is not a fix, not an official evaluation, not a "
            "model-quality benchmark, and not a production configuration change."
        ),
        "hypothesis": (
            "The R-86 runaway on intake/gold_note/long is observed under greedy "
            "decoding at temperature 0.0. If a small perturbation changes the "
            "observed behaviour, the failure is sensitive to the decoding path; if it "
            "does not, it is not sensitive AT THIS VALUE. Neither result identifies a "
            "root cause."
        ),
        "failing_cell": "/".join(CELL),
        "digests": {
            "model": _digest(structured),
            "system_prompt": _digest(_SYSTEM),
            "intake_instructions_template": _digest(_INSTRUCTIONS),
            "note_frame": _digest(_NOTE_FRAME),
            "schema": _digest(json.dumps(schema, sort_keys=True)),
            "gateway_configuration": _digest(
                f"{settings.llm_base_url}|{settings.llm_timeout_seconds}|"
                f"{settings.llm_max_attempts}|{settings.llm_fail_closed}|"
                f"{settings.llm_streaming_enabled}|{structured}"
            ),
            "firewall_configuration": _digest(
                f"{settings.llm_base_url}|fail_closed={settings.llm_fail_closed}|"
                f"streaming={settings.llm_streaming_enabled}"
            ),
            "caller_key_id": _digest(
                settings.llm_api_key.get_secret_value(), salt=settings.llm_base_url
            ),
        },
        # Named for what it holds. An earlier draft called this
        # `digests_match_parent_seal` while holding a dict, which reads as a boolean
        # claim and is not one - and the seal's block carries a prose note alongside
        # its digests, so a naive equality against it reports a difference that is not
        # one. The comparison that decides anything is `verify_against_seal()`, run
        # before the first call; this pair is the record a later reader checks by eye.
        "parent_seal_digests": dict(seal["digests"]),
        "digests_agree_with_parent_seal": all(
            seal["digests"].get(name) == value
            for name, value in {
                "model": _digest(structured),
                "system_prompt": _digest(_SYSTEM),
                "intake_instructions_template": _digest(_INSTRUCTIONS),
                "note_frame": _digest(_NOTE_FRAME),
                "schema": _digest(json.dumps(schema, sort_keys=True)),
            }.items()
        ),
        "changed": {
            "field": "temperature",
            "registered": REGISTERED_TEMPERATURE,
            "perturbed": PERTURBED_TEMPERATURE,
            "note": (
                "The ONLY field that differs. The reproducer's own TEMPERATURE "
                "constant remains 0.0 and is asserted to; this runner passes 0.2 at "
                "call time under this experiment id."
            ),
        },
        "unchanged": [
            "model",
            "model digest",
            "prompt",
            "prompt digest",
            "schema",
            "schema digest",
            "input/request shape",
            "gateway",
            "firewall",
            "caller identity",
            "completion ceiling",
            "request mode",
        ],
        "completion_ceiling": reproducer.MAX_OUTPUT_TOKENS,
        "structured_mode": "json_schema",
        "strict": True,
        "stream": False,
        "attempts_per_observation": reproducer.ATTEMPTS,
        "trial_count": TRIALS,
        "trial_count_note": (
            "Fixed before the run. It may not be changed after seeing results; the "
            "runner refuses a count that disagrees with this manifest."
        ),
        "failure_classification": {
            "rule_id": CLOSURE_RULE_ID,
            "note": (
                "A trial fails if it does not satisfy r86-closure.v1: schema-valid, "
                "parsed, closed, not stopped by exhausting the ceiling, and not "
                "whitespace-dominated at the ceiling. The same rule the closure gate "
                "uses, so the two cannot disagree about what a failure is."
            ),
        },
        "success_criterion": {
            "note": (
                "There is none, deliberately. This is a diagnostic and has nothing to "
                "pass. The outcome bands below classify what was observed; they do "
                "not authorise anything."
            ),
            "bands": {k: list(v) for k, v in OUTCOME_BANDS.items()},
        },
        "analysis_plan": [
            "Compare failure rate, valid-JSON rate, termination reason, whitespace "
            "fraction, non-whitespace character count, determinism and output length "
            "against the registered temperature 0.0 observations already committed.",
            "Do not compare clinical correctness. Do not compare model quality.",
            "Classify into exactly one pre-registered band and use its registered "
            "interpretation verbatim.",
        ],
        "cannot_authorise": (
            "This experiment cannot open the official evaluation gate under any "
            "outcome. The official system is registered at temperature 0.0; a result "
            "obtained at 0.2 describes a different decoding path. eval/official_gate.py "
            "reads only sealed revalidations and does not know this experiment exists."
        ),
        "git_commit": _git_commit(),
        "python": platform.python_version(),
        "created_at": datetime.now(UTC).isoformat(),
    }


async def run() -> dict[str, Any]:
    import scripts.r86_gradient as reproducer
    from app.config.settings import Settings
    from app.llm.client import LlmClient
    from app.llm.wiring import structured_model_for
    from scripts.r86_revalidate import verify_against_seal

    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    seal = json.loads(SEAL.read_text(encoding="utf-8"))

    # Part B. Before a single call: everything except temperature must match the
    # seal. A diagnostic run against a drifted configuration measures a system
    # nobody registered, which is the failure this whole regime exists to prevent.
    differences = verify_against_seal(seal)
    if differences:
        return {
            "experiment_id": EXPERIMENT_ID,
            "status": "ABORTED_CONFIGURATION_DRIFT",
            "differences": differences,
            "trials_made": 0,
            "note": (
                "No call was made. The live configuration no longer matches the "
                "sealed reproducer, so a perturbation of it would not be a "
                "perturbation of the registered system."
            ),
        }

    # And the instrument itself must still be registered at 0.0 - if somebody had
    # edited TEMPERATURE, this run would be a comparison of 0.2 against 0.2.
    if float(reproducer.TEMPERATURE) != float(REGISTERED_TEMPERATURE):
        return {
            "experiment_id": EXPERIMENT_ID,
            "status": "ABORTED_INSTRUMENT_TEMPERATURE_MOVED",
            "trials_made": 0,
            "note": (
                f"scripts/r86_gradient.TEMPERATURE is {reproducer.TEMPERATURE}, not "
                f"{REGISTERED_TEMPERATURE}. The registered baseline has moved and "
                "there is nothing to perturb against."
            ),
        }
    if int(manifest["trial_count"]) != TRIALS:
        return {
            "experiment_id": EXPERIMENT_ID,
            "status": "ABORTED_TRIAL_COUNT_DISAGREES_WITH_MANIFEST",
            "trials_made": 0,
        }

    settings = Settings()
    # Constructed exactly as the revalidator constructs it, including
    # `max_attempts=reproducer.ATTEMPTS` - a different retry count would be a second
    # changed variable, and the registration says there is only one.
    client = LlmClient(
        base_url=settings.llm_base_url,
        api_key=settings.llm_api_key.get_secret_value(),
        model=structured_model_for(settings),
        timeout_seconds=settings.llm_timeout_seconds,
        max_attempts=reproducer.ATTEMPTS,
    )

    cell = reproducer.Cell(*CELL)
    observations: list[Any] = []
    try:
        for trial in range(1, TRIALS + 1):
            observations.append(
                await reproducer._observe_cell(
                    client, cell, trial, temperature=PERTURBED_TEMPERATURE
                )
            )
    finally:
        await client.aclose()

    rows: list[dict[str, Any]] = []
    for o in observations:
        shape = ResponseShape(
            finish_reason=o.finish_reason,
            body_chars=o.body_chars,
            whitespace_fraction=o.whitespace_fraction,
            parsed_as_json=o.parsed_as_json,
            satisfied_schema=o.satisfied_schema,
            prompt_tokens=o.prompt_tokens,
            completion_tokens=o.completion_tokens,
        )
        verdict = trial_succeeds(
            satisfied_schema=o.satisfied_schema,
            shape=shape,
            raised=o.status_class != "2xx",
        )
        row = asdict(o)
        row["non_whitespace_chars"] = round(o.body_chars * (1.0 - o.whitespace_fraction))
        row["succeeded_under_closure_rule"] = verdict.succeeded
        row["closure_failure_reasons"] = list(verdict.reasons)
        rows.append(row)

    failures = sum(1 for r in rows if not r["succeeded_under_closure_rule"])
    # Determinism: at temperature 0 the six bodies were byte-identical. A shape
    # signature is enough to say whether that still holds without storing any text.
    signatures = {(r["body_chars"], r["whitespace_fraction"], r["completion_tokens"]) for r in rows}

    return {
        "experiment_id": EXPERIMENT_ID,
        "parent_experiment_id": PARENT_EXPERIMENT_ID,
        "status": "COMPLETE",
        "ran_at": datetime.now(UTC).isoformat(),
        "git_commit": _git_commit(),
        "manifest_sha256": hashlib.sha256(MANIFEST.read_bytes()).hexdigest(),
        "configuration_matches_seal": True,
        "changed_field": "temperature",
        "temperature": PERTURBED_TEMPERATURE,
        "registered_temperature": REGISTERED_TEMPERATURE,
        "cell": "/".join(CELL),
        "trials_planned": TRIALS,
        "trials_made": len(rows),
        "failures": failures,
        "successes": len(rows) - failures,
        "deterministic": len(signatures) == 1,
        "distinct_response_signatures": len(signatures),
        "closure_rule_id": CLOSURE_RULE_ID,
        "classification": classify_outcome(failures, len(rows)),
        "observations": rows,
        "clinical_text_in_this_report": (
            "None. Every field is a count, a flag, a fraction or a digest."
        ),
        "authorises": (
            "Nothing. The official system is registered at temperature 0.0 and this "
            "result describes a different decoding path. R-86 remains VERIFIED_FAILURE "
            "/ PROVIDER_SIDE / UNRESOLVED and the official evaluation remains BLOCKED."
        ),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--freeze-manifest", action="store_true")
    parser.add_argument("--write", action="store_true")
    args = parser.parse_args()

    if args.freeze_manifest:
        # R-104: a freeze that can be re-taken is not a freeze, and this one also
        # fixes the trial count. No flag overrides it.
        if MANIFEST.is_file():
            print(
                f"  REFUSING: {MANIFEST.relative_to(REPO)} is already frozen. "
                "Re-freezing would let the registration follow the result.",
                file=sys.stderr,
            )
            return 1
        OUT.mkdir(parents=True, exist_ok=True)
        manifest = build_manifest()
        MANIFEST.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        print(f"  frozen -> {MANIFEST.relative_to(REPO)}")
        print(f"  changed field   temperature {REGISTERED_TEMPERATURE} -> {PERTURBED_TEMPERATURE}")
        print(f"  trials          {TRIALS}")
        return 0

    if not MANIFEST.is_file():
        print("  REFUSING: no frozen manifest; run --freeze-manifest first", file=sys.stderr)
        return 1
    if os.environ.get(LIVE_FLAG) != "1":
        print(f"  refusing: set {LIVE_FLAG}=1 to make real model calls", file=sys.stderr)
        return 1

    report = asyncio.run(run())
    if report["status"] != "COMPLETE":
        print(f"  {report['status']}: {report.get('note', '')}", file=sys.stderr)
        return 1

    print(f"\n  cell            {report['cell']}")
    print(f"  temperature     {report['registered_temperature']} -> {report['temperature']}")
    print(f"  trials          {report['trials_made']}")
    print(f"  failures        {report['failures']}/{report['trials_made']}")
    print(f"  deterministic   {report['deterministic']}")
    print(f"  outcome         {report['classification']['outcome']}")
    for row in report["observations"]:
        print(
            f"    trial {row['trial']}  ctok={row['completion_tokens']:5}  "
            f"body={row['body_chars']:5}  ws={row['whitespace_fraction']:.4f}  "
            f"nonws={row['non_whitespace_chars']:5}  parsed={row['parsed_as_json']}  "
            f"finish={row['finish_reason']}"
        )

    if args.write:
        RESULTS.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        print(f"\n  written -> {RESULTS.relative_to(REPO)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
