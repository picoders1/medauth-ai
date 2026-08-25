"""R-86: the minimum controlled investigation MEDAUTH can perform. Not a fix.

    MEDAUTH_LIVE_MODEL=1 uv run python scripts/investigate_r86.py --write

Phase 13 established the behaviour and Phase 14 measured its cost (10 of 26 cases,
38%). Neither could say **which component owns it**, and the escalation asked the
owner to separate `PROVIDER_DECODER` from `FIREWALL_PROXY`. Phase 15 is asked to go
as far as this side of the boundary allows, and no further.

## What this may not do

It may not bypass the firewall. MEDAUTH holds a revocable caller key and no provider
credential, and reaching the provider directly would be both impossible and a
circumvention of a security control. Every arm below goes through the same
`/v1/chat/completions` on the same firewall with the same key.

## The arms, and what each can and cannot establish

| arm | difference | what a result would mean |
|---|---|---|
| A | the failing shape, verbatim | reproduction, or the defect has moved |
| B | + the compact-output sentence | the mitigation still holds |
| C | a **different model**, same firewall, same request shape | if C never pads, one shared proxy path produces two behaviours, which is evidence the padding is generated rather than injected |
| D | `json_object` instead of `json_schema`, same model | if D never pads, the behaviour is specific to grammar-constrained decoding |
| E | three token ceilings on arm A | padding that always fills exactly to the ceiling is generated to the limit, not a fixed artefact |

**None of these is conclusive**, and the script says so in its own output. A proxy
that transformed requests per model would produce arm C's result too. What they do is
narrow the question the owner has to answer, which is what an escalation is for.

Streaming would discriminate cleanly - tokens arriving over wall-clock are generated,
a padded body delivered in one burst is not - and it is **unavailable**: the firewall
refuses `stream: true` with 400, and `LlmClient` refuses to be constructed with it.
That avenue is recorded as closed rather than left looking untried.

## What leaves this machine

Nothing. The arms carry a synthetic two-field schema and a fixed nonsense payload -
no clinical text, no corpus text, no note. The report records model **digests**, never
model names, and never the base URL.
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
from dataclasses import asdict, dataclass, field, replace
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from app.adjudication.evidence_block import FENCE
from app.config.settings import Settings
from app.contracts.slice import IntakeExtraction
from app.intake.extract import _INSTRUCTIONS, _NOTE_FRAME
from app.llm.client import ChatResponse, LlmClient
from app.llm.firewall_gateway import _SYSTEM
from app.llm.schema_call import harden_schema
from app.llm.wiring import structured_model_for

REPO = Path(__file__).resolve().parents[1]
OUT = REPO / "eval/reports/r86-investigation"
GOLD = REPO / "data/gold/cases/gold_v1.jsonl"
LIVE_FLAG = "MEDAUTH_LIVE_MODEL"
RUNS_PER_ARM = 3

#: A schema with nothing to do with this domain. Two scalar fields, no arrays, no
#: nesting - the reduced form Phase 13's diagnosis already showed still reproduces.
PROBE_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {"label": {"type": "string"}, "count": {"type": "integer"}},
    "required": ["label", "count"],
    "additionalProperties": False,
}

#: The sentence that is the entire difference between terminating and not.
COMPACT = (
    " Return the minimal JSON document that satisfies the schema. Emit no "
    "whitespace beyond what JSON requires, and stop as soon as it is complete."
)

BASE_SYSTEM = "You label short strings. Answer only with the structured object."
USER = "Label the string 'alpha beta gamma' and count its words."


def _digest(value: str) -> str:
    """Model identity without the model's name. Deployment values stay in `.env`."""
    return f"sha256:{hashlib.sha256(value.encode()).hexdigest()[:12]}"


def _git_commit() -> str:
    try:
        return subprocess.run(
            ["git", "rev-parse", "HEAD"], cwd=REPO, capture_output=True, text=True, check=True
        ).stdout.strip()
    except (OSError, subprocess.CalledProcessError):  # pragma: no cover
        return "unknown"


def _whitespace_fraction(body: str) -> float:
    return (sum(1 for c in body if c.isspace()) / len(body)) if body else 0.0


@dataclass(frozen=True, slots=True)
class Arm:
    """One controlled variation. Everything not named here is held identical."""

    name: str
    question: str
    #: What a padded result would and would not license anyone to conclude.
    interpretation: str
    compact: bool = False
    mode: str = "json_schema"
    model: str | None = None
    max_tokens: int = 512


@dataclass
class Observation:
    arm: str
    run: int
    finish_reason: str | None = None
    completion_tokens: int = 0
    prompt_tokens: int = 0
    body_chars: int = 0
    whitespace_fraction: float = 0.0
    parsed: bool = False
    schema_valid: bool = False
    latency_ms: float = 0.0
    error: str = ""

    @property
    def padded(self) -> bool:
        """The R-86 signature: hit the ceiling, and the body is mostly whitespace."""
        return self.finish_reason == "length" and self.whitespace_fraction >= 0.5


@dataclass
class ArmResult:
    arm: Arm
    observations: list[Observation] = field(default_factory=list)

    @property
    def padded_runs(self) -> int:
        return sum(1 for o in self.observations if o.padded)

    @property
    def errors(self) -> int:
        return sum(1 for o in self.observations if o.error)


def _response_format(arm: Arm) -> dict[str, Any]:
    if arm.mode == "json_object":
        return {"type": "json_object"}
    return {
        "type": "json_schema",
        "json_schema": {"name": "probe", "schema": PROBE_SCHEMA, "strict": True},
    }


async def _run_once(client: LlmClient, arm: Arm, run: int) -> Observation:
    system = BASE_SYSTEM + (COMPACT if arm.compact else "")
    if arm.mode == "json_object":
        # `json_object` mode requires the word "json" in the conversation on most
        # OpenAI-compatible providers. Added to BOTH arms it would change the
        # comparison, so it is added only here and the difference is declared.
        system += " Respond in JSON."
    try:
        response: ChatResponse = await client.chat(
            [{"role": "system", "content": system}, {"role": "user", "content": USER}],
            model=arm.model,
            temperature=0.0,
            max_tokens=arm.max_tokens,
            response_format=_response_format(arm),
        )
    except Exception as failure:  # every arm records its own failure, none aborts
        return Observation(arm=arm.name, run=run, error=f"{type(failure).__name__}: {failure}")

    body = response.payload or ""
    observation = Observation(
        arm=arm.name,
        run=run,
        finish_reason=response.finish_reason,
        completion_tokens=response.usage.completion_tokens,
        prompt_tokens=response.usage.prompt_tokens,
        body_chars=len(body),
        whitespace_fraction=round(_whitespace_fraction(body), 4),
        latency_ms=round(response.latency_ms, 1),
    )
    try:
        parsed = json.loads(body)
    except (ValueError, TypeError):
        return observation
    observation.parsed = True
    observation.schema_valid = isinstance(parsed, dict) and set(PROBE_SCHEMA["required"]) <= set(
        parsed
    )
    return observation


def _verdict(
    results: dict[str, ArmResult], phase14: dict[str, list[Observation]]
) -> dict[str, Any]:
    """What the arms license, and - stated as plainly - what they do not.

    Written as a function of the observations rather than as prose to be edited
    afterwards, so the conclusion cannot drift from the numbers above it.
    """
    a, b = results.get("A"), results.get("B")
    c, d = results.get("C"), results.get("D")

    reproduced = bool(a and a.padded_runs == len(a.observations) and a.observations)
    mitigation_holds = bool(b and b.padded_runs == 0 and b.errors == 0)
    model_specific = bool(c and c.errors == 0 and c.padded_runs == 0 and reproduced)
    grammar_specific = bool(d and d.errors == 0 and d.padded_runs == 0 and reproduced)

    narrowed: list[str] = []
    if model_specific:
        narrowed.append(
            "One firewall, one caller key, one request shape, two models, two "
            "behaviours. A proxy that padded responses would have to be doing it "
            "per-model, which is possible but is a stronger claim than a decoder "
            "that pads. This WEAKENS FIREWALL_PROXY; it does not exclude it."
        )
    if grammar_specific:
        narrowed.append(
            "The same model on the same path does not pad without the grammar "
            "constraint. That localises the behaviour to constrained decoding "
            "rather than to the model or the transport."
        )

    # The gradient is the new evidence. Padding is not binary: whitespace rises with
    # prompt length across every arm, and the full runaway is the tail of that curve
    # rather than a separate mode. Phase 13's diagnosis reduced the schema until the
    # prompt was short, which is why it could not see this.
    def _band(observations: list[Observation]) -> dict[str, Any]:
        clean = [o for o in observations if not o.error and o.body_chars]
        if not clean:
            return {"runs": 0}
        return {
            "runs": len(clean),
            "prompt_tokens_min": min(o.prompt_tokens for o in clean),
            "prompt_tokens_max": max(o.prompt_tokens for o in clean),
            "whitespace_min": min(o.whitespace_fraction for o in clean),
            "whitespace_max": max(o.whitespace_fraction for o in clean),
            "padded": sum(1 for o in clean if o.padded),
        }

    gradient = {
        "reduced_probe": _band(list(results["A"].observations) if "A" in results else []),
        **{name: _band(obs) for name, obs in phase14.items()},
    }
    phase14_reproduced = any(o.padded for obs in phase14.values() for o in obs)
    ordered = [b for b in gradient.values() if b.get("runs")]
    length_dependent = bool(
        len(ordered) >= 2
        and ordered[0]["whitespace_max"] < ordered[-1]["whitespace_max"]
        and ordered[0]["prompt_tokens_max"] < ordered[-1]["prompt_tokens_min"]
    )
    if length_dependent:
        narrowed.append(
            "Whitespace rises monotonically with prompt length across the bands "
            "above, and the runaway is the tail of that curve rather than a "
            "separate failure mode. Phase 13 reduced the schema until the prompt "
            "was short, which is why its diagnosis could not see this. It does not "
            "identify the owning layer - both a decoder and a proxy could scale "
            "with input - but it tells the owner what to vary."
        )

    return {
        "reduced_probe_reproduced": reproduced,
        "phase14_shape_reproduced": phase14_reproduced,
        "reproduced": reproduced or phase14_reproduced,
        "whitespace_gradient": gradient,
        "behaviour_is_length_dependent": length_dependent,
        "mitigation_still_holds": mitigation_holds,
        "behaviour_is_model_specific": model_specific,
        "behaviour_is_grammar_specific": grammar_specific,
        "narrowing_evidence": narrowed,
        # The layer classification is NOT changed by this script. Only the owner can
        # change it, and only with a request issued provider-side.
        "layer": "PROVIDER_DECODER or FIREWALL_PROXY - STILL INDISTINGUISHABLE",
        "excluded_by_prior_evidence": [
            "REQUEST_SHAPE",
            "TIMEOUT_HANDLING",
            "MODEL_CONFIGURATION",
        ],
        "avenue_closed": (
            "Streaming would discriminate cleanly - incremental tokens are "
            "generated, a padded body delivered whole is not - and the firewall "
            "refuses stream:true with 400. Recorded as closed, not untried."
        ),
        "claim_refused": "R-86 is fixed",
        "still_required_from_the_owner": [
            "a request issued provider-side, outside the firewall, with the same "
            "schema and ceiling",
            "whether the provider's decoder emits the padding or the proxy appends it",
            "whether any provider-side setting bounds it",
        ],
    }


# ---------------------------------------------------------------------------
# The exact Phase-14 request shape
# ---------------------------------------------------------------------------
#
# The reduced probe above is the shape Phase 13's diagnosis used. It is not the
# shape that failed 10 times in Phase 14, and the brief asks for that one. These
# arms reconstruct it byte-for-byte from the production modules - `_SYSTEM`, the
# `intake.v2` instructions, the fenced note frame, the hardened `IntakeExtraction`
# schema and the 1536-token ceiling - so an arm that terminates here is evidence
# about production and not about a simplification of it.
#
# The notes are the real gold-set notes. They are synthetic by construction (no real
# PHI has ever entered this repository) and **none of their text is written to the
# report**: only lengths, token counts and whitespace fractions.

PHASE14_MAX_TOKENS = 1536


def _gold_notes() -> list[tuple[str, str]]:
    rows = [json.loads(line) for line in GOLD.read_text().splitlines() if line]
    return sorted(
        (
            (r["case_id"], r["input"]["clinical_note"])
            for r in rows
            if r["expected"]["policy_id"] == "42 CFR 410.33"
            and r["expected"]["policy_revision"] == "2026-08-13"
        ),
        key=lambda pair: pair[0],
    )


def _phase14_messages(case_id: str, note: str) -> list[dict[str, str]]:
    """Exactly what `FirewallGateway.call` sends for an `intake.v2` request."""
    instructions = _INSTRUCTIONS.format(case_id=case_id, requested_service="R0075")
    return [
        {"role": "system", "content": f"{_SYSTEM}\n\n{instructions}"},
        {
            "role": "user",
            "content": (
                f"{_NOTE_FRAME}\n\n{FENCE}\n"
                f"{note.replace(FENCE, '[fence-delimiter-removed]')}\n"
                f"{FENCE}"
            ),
        },
    ]


async def _run_phase14(
    client: LlmClient, case_id: str, note: str, run: int, arm_name: str
) -> Observation:
    schema = harden_schema(IntakeExtraction.model_json_schema())
    try:
        response = await client.chat(
            _phase14_messages(case_id, note),
            temperature=0.0,
            max_tokens=PHASE14_MAX_TOKENS,
            response_format={
                "type": "json_schema",
                "json_schema": {
                    "name": "IntakeExtraction",
                    "strict": True,
                    "schema": schema,
                },
            },
        )
    except Exception as failure:
        return Observation(arm=arm_name, run=run, error=f"{type(failure).__name__}: {failure}")

    body = response.payload or ""
    observation = Observation(
        arm=arm_name,
        run=run,
        finish_reason=response.finish_reason,
        completion_tokens=response.usage.completion_tokens,
        prompt_tokens=response.usage.prompt_tokens,
        body_chars=len(body),
        whitespace_fraction=round(_whitespace_fraction(body), 4),
        latency_ms=round(response.latency_ms, 1),
    )
    try:
        IntakeExtraction.model_validate_json(body)
    except Exception:
        return observation
    observation.parsed = True
    observation.schema_valid = True
    return observation


ARMS: tuple[Arm, ...] = (
    Arm(
        name="A",
        question="Does the failing shape still reproduce?",
        interpretation="Padding here is reproduction. Absence would mean the defect moved.",
    ),
    Arm(
        name="B",
        question="Does the compact-output mitigation still hold?",
        interpretation="Termination here says the mitigation works; it says nothing about a fix.",
        compact=True,
    ),
    Arm(
        name="C",
        question="Does a different model on the same firewall path pad?",
        interpretation=(
            "No padding weakens FIREWALL_PROXY - one proxy, two behaviours. It does "
            "not exclude it: a proxy could transform per model."
        ),
    ),
    Arm(
        name="D",
        question="Does the same model pad without the grammar constraint?",
        interpretation=(
            "No padding localises the behaviour to constrained decoding. Note the "
            "declared difference: json_object mode requires the word 'json' in the "
            "system turn, so this arm is not byte-identical to A."
        ),
        mode="json_object",
    ),
    Arm(
        name="E1",
        question="Does the padding fill a 256-token ceiling exactly?",
        interpretation="Filling every ceiling means generated-to-limit, not a fixed artefact.",
        max_tokens=256,
    ),
    Arm(
        name="E2",
        question="Does the padding fill a 1024-token ceiling exactly?",
        interpretation="Same, at a different ceiling. Two points is a line; three is a claim.",
        max_tokens=1024,
    ),
)


async def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--write", action="store_true")
    args = parser.parse_args()

    if os.environ.get(LIVE_FLAG) != "1":
        print(f"  refusing: set {LIVE_FLAG}=1 to make real model calls", file=sys.stderr)
        return 1

    settings = Settings()
    structured = structured_model_for(settings)
    alternate = settings.llm_model.strip()
    if not alternate or alternate == structured:
        print(
            "  arm C needs a second configured model (llm_model) that differs from "
            "llm_structured_model; it will be recorded as NOT RUN",
            file=sys.stderr,
        )

    arms = tuple(a if a.name != "C" else replace(a, model=alternate) for a in ARMS)
    results: dict[str, ArmResult] = {}

    client = LlmClient(
        base_url=settings.llm_base_url,
        api_key=settings.llm_api_key.get_secret_value(),
        model=structured,
        timeout_seconds=settings.llm_timeout_seconds,
        # ONE attempt per observation. The retry policy is production's; here it
        # would turn three observations into nine and hide which one padded.
        max_attempts=1,
    )
    try:
        for arm in arms:
            if arm.name == "C" and (not alternate or alternate == structured):
                continue
            result = ArmResult(arm=arm)
            for run in range(1, RUNS_PER_ARM + 1):
                result.observations.append(await _run_once(client, arm, run))
            results[arm.name] = result
            marks = "".join(
                "P" if o.padded else ("!" if o.error else ".") for o in result.observations
            )
            print(
                f"  arm {arm.name:2}  {marks}  padded {result.padded_runs}/"
                f"{len(result.observations)}  errors {result.errors}  {arm.question}"
            )
    finally:
        await client.aclose()

    # -- the exact Phase-14 shape ---------------------------------------
    #
    # Three shortest notes and three longest, chosen by length rather than at
    # random. Phase 14 recorded that R-86 correlated with note length, so a random
    # sample would answer a question nobody asked; this one is either consistent
    # with that correlation or contradicts it, and both are useful.
    notes = _gold_notes()
    by_length = sorted(notes, key=lambda pair: len(pair[1]))
    phase14: dict[str, list[Observation]] = {}
    client2 = LlmClient(
        base_url=settings.llm_base_url,
        api_key=settings.llm_api_key.get_secret_value(),
        model=structured,
        timeout_seconds=settings.llm_timeout_seconds,
        max_attempts=1,
    )
    try:
        for arm_name, selection in (("F-short", by_length[:3]), ("G-long", by_length[-3:])):
            observations = [
                await _run_phase14(client2, case_id, note, run, arm_name)
                for run, (case_id, note) in enumerate(selection, 1)
            ]
            phase14[arm_name] = observations
            padded = sum(1 for o in observations if o.padded)
            marks = "".join("P" if o.padded else ("!" if o.error else ".") for o in observations)
            chars = [len(note) for _, note in selection]
            print(
                f"  arm {arm_name:8} {marks}  padded {padded}/{len(observations)}  "
                f"note chars {min(chars)}-{max(chars)}"
            )
    finally:
        await client2.aclose()

    verdict = _verdict(results, phase14)
    verdict["phase14_shape_note"] = (
        "The exact Phase-14 intake request - production _SYSTEM, intake.v2 "
        "instructions, fenced note, hardened IntakeExtraction schema, 1536-token "
        "ceiling - over real gold notes. This is the shape that failed 10 of 26 "
        "times on 2026-08-25, not a reduction of it."
    )
    report = {
        "investigation": "R-86",
        "ran_at": datetime.now(UTC).isoformat(),
        "git_commit": _git_commit(),
        "python": platform.python_version(),
        "runs_per_arm": RUNS_PER_ARM,
        "boundary": (
            "Every arm goes through the firewall on the same caller key. MEDAUTH "
            "holds no provider credential and does not attempt to reach the "
            "provider directly."
        ),
        "clinical_content": "none - synthetic two-field schema and a fixed string",
        "models": {
            "structured_digest": _digest(structured),
            "alternate_digest": _digest(alternate) if alternate else None,
            "note": "digests only; concrete ids are deployment values held in .env",
        },
        "arms": {
            name: {
                "question": r.arm.question,
                "interpretation": r.arm.interpretation,
                "mode": r.arm.mode,
                "compact_instruction": r.arm.compact,
                "max_tokens": r.arm.max_tokens,
                "model": "alternate" if r.arm.model else "structured",
                "padded_runs": r.padded_runs,
                "runs": len(r.observations),
                "errors": r.errors,
                "observations": [asdict(o) | {"padded": o.padded} for o in r.observations],
            }
            for name, r in results.items()
        },
        "arms_not_run": [a.name for a in arms if a.name not in results],
        "phase14_shape": {
            "max_output_tokens": PHASE14_MAX_TOKENS,
            "prompt_id": "intake.v2",
            "schema": "IntakeExtraction",
            "clinical_text_in_this_report": "none - lengths and token counts only",
            "arms": {
                name: {
                    "padded_runs": sum(1 for o in observations if o.padded),
                    "runs": len(observations),
                    "errors": sum(1 for o in observations if o.error),
                    "observations": [asdict(o) | {"padded": o.padded} for o in observations],
                }
                for name, observations in phase14.items()
            },
        },
        "verdict": verdict,
    }

    print()
    for key in (
        "reduced_probe_reproduced",
        "phase14_shape_reproduced",
        "behaviour_is_length_dependent",
        "mitigation_still_holds",
    ):
        print(f"  {key:34} {verdict[key]}")
    print(f"  {'behaviour_is_model_specific':34} {verdict['behaviour_is_model_specific']}")
    print(f"  {'behaviour_is_grammar_specific':34} {verdict['behaviour_is_grammar_specific']}")
    print(f"  layer                              {verdict['layer']}")

    if args.write:
        OUT.mkdir(parents=True, exist_ok=True)
        (OUT / "results.json").write_text(
            json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )
        print(f"\n  written to {(OUT / 'results.json').relative_to(REPO)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
