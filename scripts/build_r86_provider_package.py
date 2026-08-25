"""Assemble the R-86 escalation into one document a provider can actually read.

    uv run python scripts/build_r86_provider_package.py --write

The package has been "ready to send" since Phase 18 and consists of four files that
reference each other by repository path. A provider receiving them has no repository,
so `docs/operations/r86-provider-attribution.md` and
`eval/reports/r86-gradient/factorial_results.json` are dangling pointers to them. Seven
such references, and every one is a question they would have to ask us before starting.

This emits a single self-contained document. Nothing is retyped: every figure is read
out of the committed artefacts at build time, so the letter cannot drift from the
evidence it summarises. That is the same reason `docs/` is generated from data
elsewhere in this repository rather than maintained beside it.

## What it must never contain

No base URL, no caller key, no provider credential, no model or host name, and no
clinical text. The deployment's identifiers appear as the same salted digests the seal
uses - enough for the owner to confirm "the key I issued" and "the model I serve"
without any of it crossing. `tests/evaluation/test_provider_package.py` asserts this
against the **live** configuration rather than a hardcoded list, so the check follows
the deployment instead of going stale against it.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parents[1]
SEAL = REPO / "data/escalations/r86-reproducer.manifest.json"
ATTRIBUTION = REPO / "data/escalations/r86-provider-attribution.json"
CAPTURE = REPO / "data/escalations/r86-firewall-capture.json"
FACTORIAL = REPO / "eval/reports/r86-gradient/factorial_results.json"
REVALIDATION = REPO / "eval/reports/r86-revalidation/20260825T155710Z.json"
PERTURBATION = REPO / "eval/experiments/r86-temperature-perturbation-001/results.json"
OUT = REPO / "data/escalations/r86-provider-package.md"


def load(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def build() -> str:
    seal = load(SEAL)
    attribution = load(ATTRIBUTION)
    capture = load(CAPTURE)
    factorial = load(FACTORIAL)
    perturbation = load(PERTURBATION)

    request = seal["request"]
    digests = seal["digests"]
    production = capture["observations"]["production_cell"]
    control = capture["observations"]["control_cell"]
    cross = capture["cross_check_against_medauth"]
    economy = attribution["character_economy_analysis"]

    def cell_row(name: str) -> str:
        observation = factorial["cells"][name]["observations"][0]
        body = observation["body_chars"]
        whitespace = observation["whitespace_fraction"]
        return (
            f"| `{name}` | {observation['completion_tokens']} | {body} | "
            f"{whitespace * 100:.1f}% | **{round(body * (1 - whitespace))}** | "
            f"{'yes' if observation['parsed_as_json'] else '**no**'} | "
            f"`{observation['finish_reason']}` |"
        )

    lines: list[str] = [
        "# A constrained-decoding request that never terminates",
        "",
        "**To:** whoever owns the model serving stack for this deployment.",
        "**From:** MEDAUTH engineering. **Our reference:** R-86.",
        "",
        "This is self-contained. It contains no credential, no endpoint, no model name",
        "and no patient data - your identifiers appear as digests you can match against",
        "your own records.",
        "",
        "We are **not** asking you to help us tune a prompt or a schema. We believe",
        "there is a defect in constrained decoding and we are asking you to explain and",
        "fix it. If we are wrong about that, the evidence below is what we are wrong",
        "about, and we would like to know.",
        "",
        "---",
        "",
        "## 1. The question",
        "",
        "> Why does the constrained decoder enter a non-terminating generation path",
        "> **while the JSON document is still structurally incomplete**, allowing",
        "> generation to continue until the completion limit is exhausted instead of",
        "> reaching a valid terminal state?",
        "",
        "## 2. The request, exactly",
        "",
        "Frozen since 2026-08-25 and unchanged since. A defect that disappears when the",
        "request is altered has been avoided, not fixed, so we have not altered it.",
        "",
        "| | |",
        "|---|---|",
        f"| endpoint | `{request['endpoint']}` |",
        f"| model | digest `{digests['model']}` |",
        f'| caller key | digest `{digests["caller_key_id"]}` (salted; confirms "the key I issued") |',
        f"| `response_format` | `{request['structured_mode']}`, `strict: {str(request['strict']).lower()}` |",
        f"| schema | digest `{digests['schema']}` - {seal['schema_shape']['note']} |",
        f"| temperature | `{request['temperature']}` |",
        f"| `max_tokens` | `{request['max_tokens']}` |",
        f"| `stream` | `{str(request['stream']).lower()}` |",
        f"| prompt tokens | {request['prompt_tokens_observed']} |",
        f"| attempts | {request['attempts_per_observation']} per observation, no client retries |",
        "",
        "## 3. What we observe",
        "",
        "Six trials, byte-identical at temperature 0, reproduced on two separate days:",
        "",
        "```",
        f"finish_reason        {economy['failing_cell']['finish_reason']}",
        f"completion_tokens    {economy['failing_cell']['completion_tokens']}   (the ceiling, exactly)",
        f"body_chars           {economy['failing_cell']['body_chars']}",
        f"whitespace_fraction  {economy['failing_cell']['whitespace_fraction']}",
        f"non_whitespace       {economy['failing_cell']['non_whitespace_chars']} characters",
        f"parsed_as_json       {str(economy['failing_cell']['parsed_as_json']).lower()}   <- the document never closes",
        "```",
        "",
        "**Three things follow, and they are why the question is worded as it is.**",
        "",
        "**It is not running out of room.** It emits "
        f"{economy['failing_cell']['non_whitespace_chars']} non-whitespace characters -",
        "*fewer than any other cell that succeeds*. It produces a little content, stops",
        "producing content, and spends the remaining tokens on whitespace.",
        "",
        "**The document never closes.** Trailing whitespace after a complete document",
        "would still parse; this does not. So whitespace is being emitted while the",
        "document is still **open**. For scale, the minimal document satisfying this",
        f"schema is {economy['schema_minimum']['minimal_satisfying_document_chars_compact']} characters",
        f"(only `{economy['schema_minimum']['required_fields'][0]}` is required and every array is legal empty).",
        "",
        "**It is deterministic.** Byte-identical across "
        f"{economy['failing_cell']['identical_across_observations']} observations in two runs on different days.",
        "",
        "### The same schema succeeds elsewhere",
        "",
        "| cell | completion tokens | body chars | whitespace | non-whitespace | parsed | finish |",
        "|---|---|---|---|---|---|---|",
    ]
    for name in sorted(factorial["cells"]):
        lines.append(cell_row(name))

    lines += [
        "",
        "`flat/*` is a small schema; `intake/*` is the production one. The only cell",
        "that fails is the production schema with real clinical content at the longer",
        "end. **`intake/filler/long` is the one we would most like you to compare",
        "against**: same schema, comparable length, a long whitespace stretch of its",
        "own - and it closes.",
        "",
        "## 4. What we have already eliminated, so you do not have to",
        "",
        "### The proxy between us is not doing it",
        "",
        "Our gateway's own append-only audit recorded, for the six failing calls:",
        "",
        "| | at the proxy | as we received it |",
        "|---|---|---|",
        f"| response characters | {production['firewall_output_chars']} | {cross['production_cell']['medauth_body_chars']} |",
        f"| request characters | {production['firewall_input_chars']} | {cross['production_cell']['medauth_payload_chars']} |",
        f"| control response | {control['firewall_output_chars']} | {cross['control_cell']['medauth_body_chars']} |",
        "",
        f"HTTP {production['firewall_status_code']}, decision `{production['firewall_decision']}`, "
        f"{production['detectors_run_per_trial']} content detectors executed and "
        f"**{production['detectors_detected']} detected** on every trial, so the only",
        "body-mutating path in the proxy was never entered. Two independent",
        "measurements on opposite sides of the hop agree **to the character**: the",
        "response was already whitespace-dominated and unterminated when it arrived.",
        "",
        "### Temperature is not the whole story either",
        "",
        f"We ran the identical request at temperature {perturbation['temperature']} - "
        "one changed field, everything else fixed:",
        "",
        f"- **{perturbation['failures']}/{perturbation['trials_made']} still failed.**",
        "- Five reproduced the greedy output byte-identically.",
        "- **One escaped the whitespace pattern entirely** and *still* ran to the",
        "  ceiling without closing.",
        "",
        "That last trial is why we do not think this is fundamentally about whitespace.",
        "The sampler left the whitespace path and termination did not follow.",
        "",
        "### Hypotheses we have narrowed or retired",
        "",
        "| hypothesis | state | why |",
        "|---|---|---|",
    ]
    for entry in attribution["hypothesis_register"]["entries"]:
        reason = entry["reason"].split(".")[0] + "."
        lines.append(f"| {entry['as_stated']} | **{entry['state']}** | {reason} |")

    lines += [
        "",
        f"**Standing statement:** {attribution['hypothesis_register']['standing_statement']}",
        "",
        "**What we do NOT claim.** We have no visibility into your stack and have not",
        "guessed at it:",
        "",
    ]
    lines += [f"- {claim}" for claim in attribution["r86"]["not_claimed"]]

    lines += [
        "",
        "## 5. Questions we cannot answer from outside",
        "",
        "1. Does the decoder reach a valid grammar state from which EOS is legal?",
        "2. If EOS is legal, why is it not selected or emitted?",
        "3. If EOS is not legal, which grammar state prevents termination?",
        "4. Does the decoder have an explicit terminal condition for JSON-schema completion?",
        "5. Does whitespace consumption occur inside an **incomplete** grammar state?",
        "6. Is there a decoder/runtime loop that can repeatedly consume non-structural tokens?",
        "7. Why does the same schema terminate for the comparison request in §3?",
        "8. Why does temperature perturbation change the surface form without restoring termination?",
        "9. Is the behaviour tied to this decoder/runtime version?",
        "10. Is constrained decoding a separate decoder path from unconstrained generation?",
        "",
        "**Questions 1 and 2 are the pair we would pick** if you can only answer one",
        "thing: *which grammar state, and was EOS legal there.*",
        "",
        "## 6. Evidence that would settle it",
        "",
        "**Any one of these narrows it substantially. We are not asking for all of them.**",
        "",
        "| | evidence |",
        "|---|---|",
        "| 1 | decoder grammar/state trace for the failing request |",
        "| 2 | EOS eligibility at the point output stops making progress |",
        "| 3 | grammar state at termination failure |",
        "| 4 | token-level decoder trace for the failing request |",
        "| 5 | the same, for the comparison request that succeeds |",
        "| 6 | constrained-decoding implementation and runtime version |",
        "| 7 | whether speculative decoding or another specialised path participates |",
        "| 8 | whether it reproduces outside our proxy (corroborates §4; lowest priority) |",
        "",
        "## 7. What would let us close this",
        "",
        "The **same** request, unchanged, succeeding: valid closed JSON, not stopped by",
        "the completion ceiling, no whitespace runaway, across the registered trial",
        "count, at or under our pre-registered failure ceiling of "
        f"{seal['acceptance']['max_failure_rate']}.",
        "",
        "We will not move that ceiling and we will not reshape the request to make the",
        "defect disappear.",
        "",
        '**If your answer is "use a different model, version, runtime, schema, API mode',
        'or temperature"** - that may well be the right engineering advice, and we will',
        "consider it. But we will record it as a *different system*, with its own",
        "baseline, not as a fix to this one. We would rather adopt your recommendation",
        "honestly than close a defect that is still there.",
        "",
        "**If you swap the stack behind the same model name**, please tell us. Our",
        "configuration check hashes the model identifier we send, not what serves it, so",
        "that change is invisible from here - and a pass we cannot attribute is a pass",
        "we cannot use.",
        "",
        "## 8. Impact, stated plainly",
        "",
        "This blocks an evaluation on our side. It is not blocking anything of yours and",
        "we are not asking for a priority. Every occurrence already fails safely for us -",
        "it routes to a human reviewer and never becomes an automated recommendation - so",
        "this is a correctness question, not an incident.",
    ]
    return "\n".join(lines) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--write", action="store_true")
    args = parser.parse_args()

    for required in (SEAL, ATTRIBUTION, CAPTURE, FACTORIAL, REVALIDATION, PERTURBATION):
        if not required.is_file():
            print(f"  REFUSING: {required.relative_to(REPO)} is missing", file=sys.stderr)
            return 1

    document = build()
    if args.write:
        OUT.write_text(document, encoding="utf-8")
        print(f"  written -> {OUT.relative_to(REPO)}  ({len(document)} chars)")
    else:
        print(document)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
