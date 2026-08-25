"""Revalidate R-86 against the sealed configuration. Part E.

    uv run python scripts/r86_revalidate.py --verify-only
    MEDAUTH_LIVE_MODEL=1 uv run python scripts/r86_revalidate.py --write

**This is the script to run when the provider owner says it is fixed.** It is written
to be run by somebody who was not here when the defect was found, so it explains its
own refusals and needs no arguments to do the right thing.

## What it does, in order

1. Loads `data/escalations/r86-reproducer.manifest.json` and checks the seal against
   its own digest. A hand-edited manifest attests to nothing.
2. Compares the **live** configuration against the sealed one - model, prompt,
   schema, gateway and firewall digests, temperature, ceiling, caller key id. Any
   difference is `INCONCLUSIVE` and no call is made.
3. Runs the sealed production-shaped cell, unmodified, for the registered trial count.
4. Applies the pre-registered threshold, read from `eval.validity.ValidityRule`.
5. Writes one timestamped run under `eval/reports/r86-revalidation/`.

## What it will not do

- **Not modify the configuration.** Every value comes from the seal or from the live
  system; there is no flag that changes one.
- **Not alter the threshold.** It is read, never restated, and a revalidation whose
  threshold disagrees with the seal is `INCONCLUSIVE` rather than judged.
- **Not silently drop a failing trial.** Every observation is written out, and a run
  that made fewer than the registered number of trials cannot decide the gate in
  either direction.
- **Not authorise anything by itself.** It records a result;
  `eval/official_gate.py` decides what that permits.

## Why runs accumulate rather than overwrite

Each run lands in its own timestamped file. "It passed on the third try" and "it
passed" are different facts, and a directory that keeps only the latest cannot tell
them apart.
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
from collections import Counter
from dataclasses import asdict
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from app.llm.failure_taxonomy import ResponseShape
from eval.r86_closure import CLOSURE_RULE_ID, TrialVerdict, trial_succeeds

REPO = Path(__file__).resolve().parents[1]
SEAL = REPO / "data/escalations/r86-reproducer.manifest.json"
OUT = REPO / "eval/reports/r86-revalidation"
LIVE_FLAG = "MEDAUTH_LIVE_MODEL"

#: Both production-shaped cells are run: the short one is the control. A run that
#: showed the long cell passing while the short one broke would be a different
#: system, not a fix.
PRODUCTION_CELLS = ("intake/gold_note/short", "intake/gold_note/long")


def _digest(value: str, *, salt: str = "") -> str:
    return f"sha256:{hashlib.sha256((salt + value).encode()).hexdigest()[:16]}"


def _git_commit() -> str:
    try:
        return subprocess.run(
            ["git", "rev-parse", "HEAD"], cwd=REPO, capture_output=True, text=True, check=True
        ).stdout.strip()
    except (OSError, subprocess.CalledProcessError):  # pragma: no cover
        return "unknown"


def _seal_digest(manifest: dict[str, Any]) -> str:
    payload = {
        k: v for k, v in manifest.items() if k not in {"sealed_sha256", "sealed_at", "git_commit"}
    }
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def verify_against_seal(seal: dict[str, Any]) -> list[str]:
    """Every sealed value against the live one. Returns the differences.

    A revalidation is only evidence if it ran against the system the seal describes.
    A PASS obtained after the model, the schema or the transport moved is a PASS for
    something else, and it is the most convincing way to be wrong available here.
    """
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
    sealed = seal["digests"]
    request = seal["request"]

    live = {
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
    }

    differences = [
        f"{name}: sealed {sealed[name]}, live {value}"
        for name, value in live.items()
        if sealed.get(name) != value
    ]
    for name, sealed_value, live_value in (
        ("temperature", request["temperature"], reproducer.TEMPERATURE),
        ("max_tokens", request["max_tokens"], reproducer.MAX_OUTPUT_TOKENS),
        ("attempts_per_observation", request["attempts_per_observation"], reproducer.ATTEMPTS),
    ):
        if str(sealed_value) != str(live_value):
            differences.append(f"{name}: sealed {sealed_value}, live {live_value}")
    return differences


def _closure_verdict(observation: Any) -> TrialVerdict:
    """One observation's verdict under `r86-closure.v1`.

    The observation is a flat record from the gradient harness, so the shape is
    rebuilt from its fields rather than carried through. Only the termination-bearing
    fields are needed; none of them can hold text.
    """
    shape = ResponseShape(
        finish_reason=observation.finish_reason,
        body_chars=observation.body_chars,
        whitespace_fraction=observation.whitespace_fraction,
        parsed_as_json=observation.parsed_as_json,
        satisfied_schema=observation.satisfied_schema,
        prompt_tokens=observation.prompt_tokens,
        completion_tokens=observation.completion_tokens,
    )
    return trial_succeeds(
        satisfied_schema=observation.satisfied_schema,
        shape=shape,
        raised=observation.status_class != "2xx",
    )


def apply_threshold(
    cells: dict[str, Any], seal: dict[str, Any], *, differences: list[str], made: int, planned: int
) -> dict[str, Any]:
    """The pre-registered rule. Read from `ValidityRule`, never restated.

    Deliberately the same shape as `scripts/r86_gate_recheck.apply_gate`: three
    outcomes, `INCONCLUSIVE` for anything that cannot decide, and no branch that
    could adjust the ceiling for sample size or for how close the result came.
    """
    from eval.validity import VALIDITY_RULE_ID, ValidityRule

    ceiling = ValidityRule().max_failure_rate
    sealed_ceiling = seal["acceptance"]["max_failure_rate"]

    def inconclusive(why: str) -> dict[str, Any]:
        return {
            "result": "INCONCLUSIVE",
            "why": why,
            "acceptance_threshold": ceiling,
            "rule_id": VALIDITY_RULE_ID,
            "permits_official_evaluation": False,
            "note": (
                "INCONCLUSIVE blocks exactly as FAIL does. 'We could not tell' is "
                "not permission, and it must not drift into whichever adjacent "
                "verdict is more convenient."
            ),
        }

    if float(ceiling) != float(sealed_ceiling):
        # The single most effective way to fake a fix: leave the system alone and
        # move the line. Refused before the numbers are even read.
        return inconclusive(
            f"the live threshold {ceiling} disagrees with the sealed {sealed_ceiling}; "
            "a threshold that moved is not a system that improved"
        )
    if differences:
        return inconclusive(
            "the live configuration no longer matches the sealed reproducer: "
            + "; ".join(differences)
        )
    if made != planned:
        return inconclusive(
            f"{made} of {planned} registered trials were made; a partial run cannot "
            "decide the gate in either direction"
        )

    production = {n: c for n, c in cells.items() if n in PRODUCTION_CELLS}
    if len(production) != len(PRODUCTION_CELLS):
        return inconclusive(
            f"expected {len(PRODUCTION_CELLS)} production-shaped cells, ran {len(production)}"
        )

    failures = sum(c["failures"] for c in production.values())
    trials = sum(c["trials"] for c in production.values())
    rate = failures / trials if trials else 1.0
    worst = max(production.items(), key=lambda kv: kv[1]["failure_rate"])
    passed = rate <= ceiling
    return {
        "result": "PASS" if passed else "FAIL",
        "acceptance_threshold": ceiling,
        "rule_id": VALIDITY_RULE_ID,
        "production_failure_rate": round(rate, 4),
        "production_failures": failures,
        "production_trials": trials,
        "worst_cell": worst[0],
        "worst_cell_rate": worst[1]["failure_rate"],
        "cells_read": sorted(production),
        "permits_official_evaluation": passed,
        "why": (
            f"production-shape failure {failures}/{trials} = {rate:.4f} "
            f"{'is at or under' if passed else 'exceeds'} the pre-registered ceiling "
            f"{ceiling:.2f}"
        ),
    }


async def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--write", action="store_true")
    parser.add_argument(
        "--verify-only", action="store_true", help="check the seal and configuration; make no calls"
    )
    args = parser.parse_args()

    if not SEAL.is_file():
        print(f"  refusing: no sealed reproducer at {SEAL.relative_to(REPO)}", file=sys.stderr)
        return 1
    seal = json.loads(SEAL.read_text())

    print(f"  seal            {seal['experiment_id']}  sha256:{seal['sealed_sha256'][:16]}")
    if _seal_digest(seal) != seal["sealed_sha256"]:
        print(
            "\n  REFUSING: the sealed manifest does not match its own digest. It has "
            "been edited by hand and attests to nothing.",
            file=sys.stderr,
        )
        return 1
    print("  seal intact     yes")

    differences = verify_against_seal(seal)
    if differences:
        print("\n  CONFIGURATION DRIFT:")
        for difference in differences:
            print(f"    {difference}")
    else:
        print("  configuration   matches the seal")

    if args.verify_only:
        print("\n  (verify-only; no model calls made)")
        return 0 if not differences else 1

    if os.environ.get(LIVE_FLAG) != "1":
        print(f"\n  refusing: set {LIVE_FLAG}=1 to run the reproducer", file=sys.stderr)
        return 1

    import scripts.r86_gradient as reproducer

    planned = len(PRODUCTION_CELLS) * reproducer.FACTORIAL_TRIALS
    if differences:
        # Refused BEFORE any call: a number produced under a drifted configuration
        # would be reported under the sealed experiment id and would not describe it.
        verdict = apply_threshold({}, seal, differences=differences, made=0, planned=planned)
        print(f"\n  result: {verdict['result']} - {verdict['why']}")
        return 1

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
    cells: dict[str, Any] = {}
    made = 0
    print("\n  running the sealed production-shaped cells\n")
    try:
        for cell in reproducer.FACTORIAL_CELLS:
            if cell.name not in PRODUCTION_CELLS:
                continue
            observations = [
                await reproducer._observe_cell(client, cell, trial)
                for trial in range(1, reproducer.FACTORIAL_TRIALS + 1)
            ]
            made += len(observations)
            # R-106. This used to be the taxonomy alone, which decides by asking
            # whether the call RAISED - so a response that closed its document and
            # then padded whitespace to the ceiling counted as a SUCCESS, and six of
            # those would have opened the official evaluation on a provider path that
            # still never terminates. `eval.r86_closure` adds the two termination
            # conditions Part F names. It can only ever add failures, and zero of the
            # 164 committed observations change under it.
            verdicts = [_closure_verdict(o) for o in observations]
            failures = sum(1 for v in verdicts if not v.succeeded)
            cells[cell.name] = {
                "trials": len(observations),
                "failures": failures,
                "successes": len(observations) - failures,
                "failure_rate": round(failures / len(observations), 4),
                "r86_signatures": sum(1 for o in observations if o.is_r86_signature),
                "closure_rule_id": CLOSURE_RULE_ID,
                "closure_failure_reasons": sorted({r for v in verdicts for r in v.reasons}),
                "deterministic": len({o.completion_tokens for o in observations}) == 1,
                "median_whitespace_fraction": sorted(o.whitespace_fraction for o in observations)[
                    len(observations) // 2
                ],
                "prompt_tokens_max": max(o.prompt_tokens for o in observations),
                "failure_kinds": dict(
                    sorted(Counter(o.failure_kind for o in observations).items())
                ),
                # EVERY observation, including the failing ones. A run that reported
                # only its successes would be a run that dropped trials.
                "observations": [asdict(o) for o in observations],
            }
            marks = "".join(
                "R" if o.is_r86_signature else ("!" if not o.succeeded else ".")
                for o in observations
            )
            print(
                f"    {cell.name:26} {marks}  failures {failures}/{len(observations)}  "
                f"prompt_tok {cells[cell.name]['prompt_tokens_max']}"
            )
    finally:
        await client.aclose()

    verdict = apply_threshold(cells, seal, differences=differences, made=made, planned=planned)
    report = {
        "revalidation": "r86-revalidation",
        "seal_experiment_id": seal["experiment_id"],
        "seal_sha256": seal["sealed_sha256"],
        "ran_at": datetime.now(UTC).isoformat(),
        "git_commit": _git_commit(),
        "python": platform.python_version(),
        "configuration_matches_seal": not differences,
        "configuration_differences": differences,
        "trials_planned": planned,
        "trials_made": made,
        "cells": cells,
        "gate": verdict,
        "clinical_text_in_this_report": "none - digests, counts and token counts only",
        "what_this_does_and_does_not_authorise": (
            "This records a result. eval/official_gate.py decides what it permits, "
            "and it is the only thing that may."
        ),
        "claims_refused": [
            "that R-86 is fixed, absent a PASS under the sealed configuration",
            "that the responsible layer is the provider or the firewall",
            "that a near miss justifies adjusting the threshold",
        ],
    }

    print(f"\n  result: {verdict['result']}")
    print(f"    {verdict['why']}")

    if args.write:
        OUT.mkdir(parents=True, exist_ok=True)
        stamp = report["ran_at"].replace(":", "").replace("-", "").split(".")[0]
        path = OUT / f"{stamp}Z.json"
        path.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        print(f"\n  written to {path.relative_to(REPO)}")
        print(
            "  runs accumulate; 'it passed on the third try' is a different fact from 'it passed'"
        )
    return 0 if verdict["permits_official_evaluation"] else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
