"""Seal the R-86 reproducer into one immutable, exportable manifest. Part A.

    uv run python scripts/seal_r86_reproducer.py            # print, write nothing
    uv run python scripts/seal_r86_reproducer.py --write

The evidence for R-86 currently lives across four artefacts written by three scripts
over two phases. That is fine for a repository and wrong for a handoff: an external
owner should receive **one file** that names every value needed to reproduce the
failing request, and nothing else.

## What "immutable" means here

The manifest carries its own `sealed_sha256` over its content-bearing fields. Once
sealed, re-running this script against a changed configuration produces a **different
digest**, and `eval/official_gate.py` refuses to authorise anything while the live
configuration disagrees with what was sealed. So the seal is not a comment - it is
the thing the gate compares against.

Re-sealing is therefore a deliberate act with a visible consequence, not a refresh.

## What is deliberately absent

No caller key, no provider credential, no base URL, no model id, no clinical text and
no payload. The caller key appears as a **salted digest** so the owner can confirm
"the same key you issued" without the key crossing anything; the salt is the firewall
base URL, which they already know and which never enters the file.

A manifest that cannot be emailed is a manifest that will be paraphrased instead.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parents[1]
RECHECK = REPO / "eval/reports/r86-gate-recheck/results.json"
FACTORIAL = REPO / "eval/reports/r86-gradient/factorial_results.json"
FACTORIAL_PLAN = REPO / "eval/reports/r86-gradient/factorial_preregistration.json"
GRADIENT = REPO / "eval/reports/r86-gradient/results.json"
OUT = REPO / "data/escalations/r86-reproducer.manifest.json"

EXPERIMENT_ID = "r86-reproducer-001"
#: The one cell that fails. Named as a constant because the gate, the revalidation
#: script and this seal must all mean the same cell by it.
FAILING_CELL = "intake/gold_note/long"


def _digest(value: str, *, salt: str = "") -> str:
    return f"sha256:{hashlib.sha256((salt + value).encode()).hexdigest()[:16]}"


def _git_commit() -> str:
    try:
        return subprocess.run(
            ["git", "rev-parse", "HEAD"], cwd=REPO, capture_output=True, text=True, check=True
        ).stdout.strip()
    except (OSError, subprocess.CalledProcessError):  # pragma: no cover
        return "unknown"


def seal_digest(manifest: dict[str, Any]) -> str:
    """A digest over the content-bearing fields, excluding the seal itself.

    `sealed_at` and `git_commit` are excluded deliberately: they record when a seal
    was taken, not what it describes. Including them would make every re-seal look
    like a configuration change and would train a reader to ignore the digest.
    """
    payload = {
        k: v for k, v in manifest.items() if k not in {"sealed_sha256", "sealed_at", "git_commit"}
    }
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def build() -> dict[str, Any]:
    """Everything an external owner needs, and nothing they must not receive."""
    import scripts.r86_gradient as reproducer
    from app.adjudication.assess import ASSESSMENT_PROMPT_ID
    from app.config.settings import Settings
    from app.contracts.slice import IntakeExtraction
    from app.intake.extract import _INSTRUCTIONS, _NOTE_FRAME, INTAKE_PROMPT_ID
    from app.llm.firewall_gateway import _SYSTEM
    from app.llm.schema_call import harden_schema
    from app.llm.wiring import structured_model_for
    from eval.validity import VALIDITY_RULE_ID, ValidityRule

    settings = Settings()
    structured = structured_model_for(settings)
    recheck = json.loads(RECHECK.read_text())
    factorial = json.loads(FACTORIAL.read_text())
    plan = json.loads(FACTORIAL_PLAN.read_text())
    gradient = json.loads(GRADIENT.read_text())

    cell = recheck["cells"][FAILING_CELL]
    observations = cell["observations"]
    failures = cell["r86_signature_rate"]["successes"]
    trials = cell["trials"]

    # The intake schema, hardened exactly as the runtime hardens it. Its digest is
    # what lets the owner confirm they are constraining the same grammar; the schema
    # itself is domain-shaped but carries no clinical content, so it is safe to
    # describe by shape and size.
    schema = harden_schema(IntakeExtraction.model_json_schema())

    # Salted with the firewall base URL, which the owner already has and which never
    # enters this file. It answers "the same key you issued?" without the key.
    caller_key_id = _digest(settings.llm_api_key.get_secret_value(), salt=settings.llm_base_url)

    manifest: dict[str, Any] = {
        "experiment_id": EXPERIMENT_ID,
        "purpose": (
            "The single canonical reproducer for R-86, for the owner of the provider "
            "or the firewall. Every value needed to reproduce the failing request is "
            "here; nothing that must not leave this machine is."
        ),
        "sealed_at": datetime.now(UTC).isoformat(),
        "git_commit": _git_commit(),
        "risk": "R-86",
        "classification": {
            "status": "VERIFIED FAILURE",
            "attribution": "INDETERMINATE",
            "ownership": "OUTSIDE ENGINEERING CONTROL",
            "evaluation_impact": "OFFICIAL EVALUATION BLOCKED",
        },
        # ---- the request shape -------------------------------------------
        "request": {
            "cell": FAILING_CELL,
            "cell_meaning": (
                "production IntakeExtraction schema, a real (synthetic) clinical "
                "note at the longer end of the corpus, sent through the firewall"
            ),
            "endpoint": "POST /v1/chat/completions",
            "structured_mode": "json_schema",
            "strict": True,
            "temperature": reproducer.TEMPERATURE,
            "max_tokens": reproducer.MAX_OUTPUT_TOKENS,
            "stream": False,
            "attempts_per_observation": reproducer.ATTEMPTS,
            "messages": [
                {"role": "system", "content_digest": _digest(_SYSTEM)},
                {"role": "user", "content_digest": "per-note; see prompt_tokens"},
            ],
            "message_roles": ["system", "user"],
            "prompt_tokens_observed": cell["prompt_tokens_max"],
            "prompt_token_range": [cell["prompt_tokens_min"], cell["prompt_tokens_max"]],
        },
        # ---- digests, so the owner can confirm identity without the values -
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
            "caller_key_id": caller_key_id,
            "caller_key_note": (
                "A digest of the caller key salted with the firewall base URL. It "
                "answers 'is this the key you issued?' without the key, the URL or "
                "any credential appearing in this file."
            ),
        },
        "prompt_versions": {"intake": INTAKE_PROMPT_ID, "adjudication": ASSESSMENT_PROMPT_ID},
        "schema_shape": {
            "name": "IntakeExtraction",
            "top_level_arrays": 5,
            "properties": sorted(schema.get("properties", {})),
            "note": (
                "Five sibling arrays of objects. Every array is legal when empty, so "
                "the grammar admits a complete document at any point - which is what "
                "makes 'the schema is satisfied' compatible with 'the document never "
                "closes'."
            ),
        },
        # ---- what was observed --------------------------------------------
        "observed": {
            "trials": trials,
            "failures": failures,
            "successes": trials - failures,
            "failure_rate": round(failures / trials, 4) if trials else None,
            "failure_classification": "SCHEMA_GRAMMAR_FAILURE (R-86 signature)",
            "finish_reason": sorted({o["finish_reason"] for o in observations}),
            "completion_tokens": sorted({o["completion_tokens"] for o in observations}),
            "whitespace_fraction": sorted({o["whitespace_fraction"] for o in observations}),
            "body_chars": sorted({o["body_chars"] for o in observations}),
            "parsed_as_json": sorted({o["parsed_as_json"] for o in observations}),
            "median_latency_ms": cell["latency_ms_median"],
            "attribution": sorted(cell["attributions"]),
            "determinism": {
                "deterministic": cell["deterministic"],
                "evidence": (
                    "Every trial returned the identical completion-token count, "
                    "whitespace fraction and body length at temperature 0."
                ),
            },
        },
        # ---- the contrast that makes it a finding rather than a report -----
        "contrast": {
            "note": (
                "Two comparisons make this a specific defect rather than 'it "
                "sometimes fails'. Both are from the same registered matrix, same "
                "model, same transport, same day."
            ),
            "same_schema_same_length_different_content": {
                "cell": "intake/filler/long",
                "prompt_tokens": factorial["cells"]["intake/filler/long"]["prompt_tokens_max"],
                "failures": factorial["cells"]["intake/filler/long"]["r86_signature_rate"][
                    "successes"
                ],
                "trials": factorial["cells"]["intake/filler/long"]["trials"],
                "reading": (
                    "Ten MORE prompt tokens than the failing cell, identical schema "
                    "and transport, synthetic filler instead of a clinical note: "
                    "zero failures."
                ),
            },
            "length_alone": {
                "experiment": gradient["experiment"],
                "observations": gradient["observations_made"],
                "failures": gradient["overall"]["r86_signature_rate"]["successes"],
                "max_prompt_tokens": max(b["prompt_tokens_max"] for b in gradient["bands"]),
                "reading": (
                    "A seven-band length sweep on a two-field schema produced zero "
                    "failures at up to 908 prompt tokens. Length alone does not "
                    "reproduce it."
                ),
            },
        },
        "ruled_out": [
            "REQUEST_SHAPE as a whole - identical bodies differing only in content succeed",
            "MODEL_CONFIGURATION - temperature, max_tokens and stream are identical across arms",
            "TIMEOUT_HANDLING - the client timeout is not reached; the ceiling is",
            "input length alone - 0/56 up to 908 prompt tokens on a reduced schema",
            "schema shape alone - 0/24 on the production schema with filler content",
            "intermittency - 6/6 identical responses at temperature 0",
        ],
        "still_ambiguous": [
            "PROVIDER_DECODER versus FIREWALL_PROXY - MEDAUTH observes one hop",
        ],
        # ---- the rule that governs closure --------------------------------
        "acceptance": {
            "validity_rule_id": VALIDITY_RULE_ID,
            "max_failure_rate": ValidityRule().max_failure_rate,
            "cells_read": [FAILING_CELL, "intake/gold_note/short"],
            "trials_required": plan["trials_per_cell"],
            "note": (
                "The threshold is the pre-registered one and may not be adjusted to "
                "match observed behaviour. Closure requires the registered shape to "
                "succeed, not a different shape to be substituted."
            ),
        },
        "excluded_from_this_file": [
            "the caller key",
            "any provider credential",
            "the firewall base URL",
            "the model id",
            "clinical text or any note payload",
            "raw response bodies",
        ],
        "source_artefacts": {
            "gate_recheck": "eval/reports/r86-gate-recheck/results.json",
            "factorial": "eval/reports/r86-gradient/factorial_results.json",
            "length_gradient": "eval/reports/r86-gradient/results.json",
            "escalation": "docs/escalations/R-86-unbounded-whitespace.md",
        },
    }
    manifest["sealed_sha256"] = seal_digest(manifest)
    return manifest


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--write", action="store_true")
    args = parser.parse_args()

    manifest = build()
    observed = manifest["observed"]
    print(f"  experiment      {manifest['experiment_id']}")
    print(f"  cell            {manifest['request']['cell']}")
    print(
        f"  observed        {observed['failures']}/{observed['trials']} failures, "
        f"deterministic={observed['determinism']['deterministic']}"
    )
    print(f"  prompt tokens   {manifest['request']['prompt_tokens_observed']}")
    print(f"  finish_reason   {observed['finish_reason']}")
    print(f"  whitespace      {observed['whitespace_fraction']}")
    print(f"  attribution     {observed['attribution']}")
    print(f"  threshold       {manifest['acceptance']['max_failure_rate']}")
    print(f"  seal            sha256:{manifest['sealed_sha256'][:16]}")

    if args.write:
        if OUT.is_file():
            previous = json.loads(OUT.read_text()).get("sealed_sha256")
            if previous and previous != manifest["sealed_sha256"]:
                # Loud, because it means the live configuration no longer matches
                # what the owner was handed - and the gate will refuse until the
                # difference is understood rather than re-sealed away.
                print(
                    f"\n  SEAL CHANGED: was sha256:{previous[:16]}, now "
                    f"sha256:{manifest['sealed_sha256'][:16]}\n"
                    "  The configuration this manifest describes has moved. Anything "
                    "already sent to the owner describes a different system."
                )
        OUT.parent.mkdir(parents=True, exist_ok=True)
        OUT.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        print(f"\n  written to {OUT.relative_to(REPO)}")
    else:
        print("\n  (dry run; pass --write)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
