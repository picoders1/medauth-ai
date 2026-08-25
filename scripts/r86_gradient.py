"""R-86 reproduction harness and the pre-registered length gradient. Parts A2, A3.

    MEDAUTH_LIVE_MODEL=1 uv run python scripts/r86_gradient.py --write
    uv run python scripts/r86_gradient.py --plan          # the matrix, no calls

Phase 15 found the behaviour is input-length dependent from **three observations at
two lengths**. That is enough to know the schema was never the axis and nowhere near
enough to state a rate. This is the controlled version: one variable, seven bands,
declared before execution.

## Pre-registration

Fixed here, in code, and echoed into the report before the first call:

| held constant | varied |
|---|---|
| model, prompt, schema, caller key, temperature, gateway, firewall path, token ceiling, attempts | **payload length, and nothing else** |

Seven bands x 8 repetitions = 56 observations. The band edges are chosen to bracket
the Phase-15 evidence (clean below ~430 prompt tokens, padding around ~500) with
headroom on both sides, and are fixed before any of them is measured.

**The payload is synthetic and non-clinical.** Lorem-style filler assembled from a
fixed word list with a fixed seed, so a band is reproducible byte-for-byte and no
note text leaves this machine. Using real notes would confound length with content
and would put clinical text one bug away from a committed report.

## What this may not conclude

- **Not causation.** Length is confounded with everything that grows with it -
  attention span, KV-cache size, the decoder's own state. The claim available here
  is *association*, at a stated sample size.
- **Not a regression.** Seven points, eight trials each, on a binary outcome. The
  report gives per-band rates with Wilson intervals and stops. A fitted curve
  through this would be a decoration with a confidence band.
- **Not a layer.** `PROVIDER_DECODER` and `FIREWALL_PROXY` stay indistinguishable
  from this side, as they were in Phase 15.

## The follow-up, and why it exists

`r86-gradient-001` came back **0/56**: no failure at any band, up to 908 prompt
tokens - well past the ~510 where Phase 15's real intake calls padded. **The
pre-registered hypothesis is not supported.** Length alone does not reproduce it.

Phase 15's arms varied length *and* schema *and* content at once, so "input-length
dependent" was the reading available from an under-controlled comparison. It is
withdrawn here rather than defended.

`--factorial` runs `r86-factorial-001`, a **separate experiment with its own
pre-registration**, written after the null result and labelled as such. It crosses the
three factors Phase 15 confounded:

    schema  in {flat two-field, IntakeExtraction}
    payload in {synthetic filler, real gold note}
    length  in {short, long}

2 x 2 x 2 cells, 6 trials each. Real gold notes are sent (they are synthetic by
construction and already cross this boundary in every evaluation); **their text never
enters the report** - only a digest, a length and token counts.

## What leaves this machine

Per-observation: band, trial index, prompt tokens, completion tokens, finish reason,
whitespace fraction, latency, failure kind. **No payload text, no clinical text, no
model id, no base URL.** A test asserts it.
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import os
import platform
import random
import subprocess
import sys
from collections import Counter
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from app.config.settings import Settings
from app.llm.client import LlmClient
from app.llm.failure_taxonomy import (
    ProviderFailureKind,
    ResponseShape,
    classify_provider_failure,
)
from app.llm.wiring import structured_model_for
from eval.metrics.statistics import wilson_interval

REPO = Path(__file__).resolve().parents[1]
OUT = REPO / "eval/reports/r86-gradient"
LIVE_FLAG = "MEDAUTH_LIVE_MODEL"

# -- PRE-REGISTERED. Do not edit after a run without a new experiment id. --------

EXPERIMENT_ID = "r86-gradient-001"

#: Target payload word counts. Chosen to bracket the Phase-15 evidence with headroom
#: below (where it was clean) and above (where it padded), on a roughly geometric
#: spacing so the bands are comparable in ratio rather than in difference.
BANDS: tuple[int, ...] = (25, 60, 120, 200, 320, 480, 700)

#: Per band. Eight is what makes a 0/8 and an 8/8 distinguishable at a glance while
#: keeping the whole matrix inside one sitting; it is not a power calculation and the
#: report does not pretend otherwise.
TRIALS_PER_BAND = 8

#: Held constant across every observation.
MAX_OUTPUT_TOKENS = 1536
TEMPERATURE = 0.0
ATTEMPTS = 1  # one attempt per observation; retries would hide which trial padded
SEED = 20260825

#: The schema. Two scalars, no arrays, no nesting - so schema size cannot be the
#: variable. Identical in every band.
PROBE_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {"topic": {"type": "string"}, "word_count": {"type": "integer"}},
    "required": ["topic", "word_count"],
    "additionalProperties": False,
}

#: Identical in every band. Deliberately carries no compact-output instruction: the
#: production mitigation is measured separately, and including it here would measure
#: the mitigation rather than the defect.
SYSTEM = (
    "You summarise documents. Answer only with the structured object: a one-word "
    "topic and the number of words you were given."
)

#: A fixed, non-clinical word list. Synthetic filler, seeded, reproducible.
_WORDS = (
    "alpha bravo charlie delta echo foxtrot golf hotel india juliet kilo lima mike "
    "november oscar papa quebec romeo sierra tango uniform victor whiskey xray "
    "yankee zulu meadow lantern harbour compass thicket gravel orchard pebble "
    "cinder willow marble tunnel ribbon anchor"
).split()


def payload(words: int) -> str:
    """`words` words of deterministic filler. Same band, same bytes, every run.

    Seeded rather than cryptographic on purpose: the point is that a band is
    byte-reproducible from the seed alone, so a later reader can rebuild the exact
    payload without it being committed anywhere.
    """
    rng = random.Random(SEED + words)  # noqa: S311 - reproducibility, not secrecy
    return " ".join(rng.choice(_WORDS) for _ in range(words))


# -------------------------------------------------------------------------------


def _digest(value: str) -> str:
    return f"sha256:{hashlib.sha256(value.encode()).hexdigest()[:12]}"


def _git_commit() -> str:
    try:
        return subprocess.run(
            ["git", "rev-parse", "HEAD"], cwd=REPO, capture_output=True, text=True, check=True
        ).stdout.strip()
    except (OSError, subprocess.CalledProcessError):  # pragma: no cover
        return "unknown"


def _rate(successes: int, total: int) -> dict[str, Any]:
    """A rate with its denominator and a Wilson interval, never a bare float.

    An interval on 0/8 is [0.0000, 0.3671] - wide, and the width is the point. A
    band that reports 0.0 with no denominator invites "it does not happen here",
    which eight trials cannot support.
    """
    interval = wilson_interval(successes, total)
    return {
        "value": round(interval.value, 4),
        "successes": successes,
        "total": total,
        "ci95": [round(interval.lower, 4), round(interval.upper, 4)],
    }


def _whitespace_fraction(body: str) -> float:
    return (sum(1 for c in body if c.isspace()) / len(body)) if body else 0.0


@dataclass
class Observation:
    """One call. Every field is a count, a flag or a category. **No text.**"""

    band_words: int
    trial: int
    #: sha256 of the payload, so a band is checkable without publishing its bytes.
    payload_digest: str
    payload_chars: int
    prompt_tokens: int = 0
    completion_tokens: int = 0
    finish_reason: str | None = None
    body_chars: int = 0
    whitespace_fraction: float = 0.0
    parsed_as_json: bool = False
    satisfied_schema: bool = False
    latency_ms: float = 0.0
    status_class: str = "none"
    failure_kind: str = ProviderFailureKind.NONE.value
    attribution: str = "NONE"
    is_r86_signature: bool = False
    succeeded: bool = False
    #: Factorial only. `schema/content/length`, and the payload's label - a gold
    #: case id or a filler band. A LABEL, never the text.
    cell: str | None = None
    payload_label: str | None = None


@dataclass
class Band:
    words: int
    observations: list[Observation] = field(default_factory=list)

    @property
    def failures(self) -> int:
        """Provider-attributable failures. A 403 or a 400 is not one of them."""
        return sum(
            1
            for o in self.observations
            if ProviderFailureKind(o.failure_kind).counts_toward_provider_reliability
        )

    @property
    def r86(self) -> int:
        return sum(1 for o in self.observations if o.is_r86_signature)

    @property
    def median_whitespace(self) -> float:
        values = sorted(o.whitespace_fraction for o in self.observations if o.body_chars)
        return values[len(values) // 2] if values else 0.0


def _status_class(status: int | None) -> str:
    if status is None:
        return "none"
    return f"{status // 100}xx"


async def _observe(client: LlmClient, words: int, trial: int) -> Observation:
    text = payload(words)
    observation = Observation(
        band_words=words,
        trial=trial,
        payload_digest=_digest(text),
        payload_chars=len(text),
    )
    try:
        response = await client.chat(
            [
                {"role": "system", "content": SYSTEM},
                {"role": "user", "content": text},
            ],
            temperature=TEMPERATURE,
            max_tokens=MAX_OUTPUT_TOKENS,
            response_format={
                "type": "json_schema",
                "json_schema": {"name": "probe", "schema": PROBE_SCHEMA, "strict": True},
            },
        )
    except Exception as failure:
        status = getattr(failure, "status_code", None)
        classified = classify_provider_failure(failure, status_code=status)
        observation.status_class = _status_class(status)
        observation.failure_kind = classified.kind.value
        observation.attribution = classified.attribution.value
        return observation

    body = response.payload or ""
    parsed: Any = None
    try:
        parsed = json.loads(body)
    except (ValueError, TypeError):
        parsed = None

    shape = ResponseShape(
        finish_reason=response.finish_reason,
        body_chars=len(body),
        whitespace_fraction=round(_whitespace_fraction(body), 4),
        parsed_as_json=parsed is not None,
        satisfied_schema=isinstance(parsed, dict) and set(PROBE_SCHEMA["required"]) <= set(parsed),
        prompt_tokens=response.usage.prompt_tokens,
        completion_tokens=response.usage.completion_tokens,
    )

    # A 200 that did not yield a usable object is still a response-path failure, and
    # it is classified through the SAME function the runtime uses rather than by a
    # second rule written here. Two classifiers that mostly agree is worse than one.
    if not shape.satisfied_schema:
        from app.core.errors import SchemaValidationError

        classified = classify_provider_failure(
            SchemaValidationError("probe response did not satisfy the schema", attempts=1),
            status_code=200,
            shape=shape,
        )
    else:
        classified = classify_provider_failure(None, status_code=200, shape=shape)

    observation.prompt_tokens = shape.prompt_tokens
    observation.completion_tokens = shape.completion_tokens
    observation.finish_reason = shape.finish_reason
    observation.body_chars = shape.body_chars
    observation.whitespace_fraction = shape.whitespace_fraction
    observation.parsed_as_json = shape.parsed_as_json
    observation.satisfied_schema = shape.satisfied_schema
    observation.latency_ms = round(response.latency_ms, 1)
    observation.status_class = "2xx"
    observation.failure_kind = classified.kind.value
    observation.attribution = classified.attribution.value
    observation.is_r86_signature = classified.is_r86_signature
    observation.succeeded = shape.satisfied_schema
    return observation


def _preregistration(settings: Settings) -> dict[str, Any]:
    """Everything fixed before the first call. Written to the report first."""
    structured = structured_model_for(settings)
    return {
        "experiment": EXPERIMENT_ID,
        "hypothesis": (
            "The rate of R-86 (schema-satisfying, non-terminating responses) is "
            "associated with input length, holding model, prompt, schema, "
            "temperature, ceiling and transport constant."
        ),
        "varied": ["payload_length_words"],
        "held_constant": {
            "model_digest": _digest(structured),
            "prompt": _digest(SYSTEM),
            "schema": _digest(json.dumps(PROBE_SCHEMA, sort_keys=True)),
            "temperature": TEMPERATURE,
            "max_output_tokens": MAX_OUTPUT_TOKENS,
            "attempts_per_observation": ATTEMPTS,
            "structured_mode": "json_schema",
            "gateway_configuration_digest": _digest(
                f"{settings.llm_base_url}|{settings.llm_timeout_seconds}|"
                f"{settings.llm_max_attempts}|{settings.llm_fail_closed}|"
                f"{settings.llm_streaming_enabled}|{structured}"
            ),
            "firewall_path": "MEDAUTH -> firewall -> provider (no bypass, one caller key)",
            "payload_seed": SEED,
        },
        "bands_words": list(BANDS),
        "trials_per_band": TRIALS_PER_BAND,
        "observations_planned": len(BANDS) * TRIALS_PER_BAND,
        "outcome_measure": (
            "per-band provider-failure rate, and per-band R-86 signature rate "
            "(finish_reason=length AND whitespace >= 0.5)"
        ),
        "statistics": "Wilson intervals on single rates. No curve is fitted.",
        "prohibitions": [
            "No band may be dropped after seeing its result.",
            "No threshold may be chosen from these numbers and then presented as pre-registered.",
            "Causation may not be claimed: length is confounded with everything "
            "that grows with it.",
            "No regression may be fitted through seven points.",
        ],
        "payload": "synthetic, seeded, non-clinical filler; no note text is sent",
        "clinical_text_in_this_report": "none - digests, counts and categories only",
    }


# ===============================================================================
# r86-factorial-001 - the follow-up. A SEPARATE experiment.
# ===============================================================================
#
# Pre-registered AFTER `r86-gradient-001` returned 0/56 and BEFORE any factorial
# observation was made. Saying so plainly matters: a follow-up prompted by a null
# result is ordinary science, and presenting it as though it had been planned all
# along would make the gradient's refutation disappear.
#
# Phase 15's failing arm differed from the gradient's passing arm in THREE ways at
# once. This crosses them.

FACTORIAL_ID = "r86-factorial-001"
FACTORIAL_TRIALS = 6

#: Two length points, chosen to straddle Phase 15's observed boundary rather than to
#: sweep. The gradient already established that length alone sweeps nothing.
FACTORIAL_LENGTHS = {"short": 45, "long": 130}


def _gold_notes_by_length() -> dict[str, tuple[str, str]]:
    """The shortest and longest 410.33 gold notes, as `(case_id, note)`.

    Real cases, synthetic by construction. Chosen by length rather than at random so
    the two content arms sit at comparable lengths to the two filler arms.
    """
    rows = [
        json.loads(line)
        for line in (REPO / "data/gold/cases/gold_v1.jsonl").read_text().splitlines()
        if line
    ]
    notes = sorted(
        (
            (r["case_id"], r["input"]["clinical_note"])
            for r in rows
            if r["expected"]["policy_id"] == "42 CFR 410.33"
            and r["expected"]["policy_revision"] == "2026-08-13"
        ),
        key=lambda pair: len(pair[1]),
    )
    return {"short": notes[0], "long": notes[-1]}


@dataclass(frozen=True, slots=True)
class Cell:
    """One combination of the three factors."""

    schema: str  # "flat" | "intake"
    content: str  # "filler" | "gold_note"
    length: str  # "short" | "long"

    @property
    def name(self) -> str:
        return f"{self.schema}/{self.content}/{self.length}"


FACTORIAL_CELLS: tuple[Cell, ...] = tuple(
    Cell(schema=s, content=c, length=length)
    for s in ("flat", "intake")
    for c in ("filler", "gold_note")
    for length in ("short", "long")
)


def _factorial_request(cell: Cell) -> tuple[list[dict[str, str]], dict[str, Any], str, str]:
    """`(messages, response_format, payload_digest, case_or_band_label)`.

    The `intake` arm is assembled from the PRODUCTION modules - `_SYSTEM`, the
    `intake.v2` instructions, the fenced note frame, the hardened schema - so a cell
    that fails is evidence about production rather than about a reconstruction of it.
    """
    from app.adjudication.evidence_block import FENCE
    from app.contracts.slice import IntakeExtraction
    from app.intake.extract import _INSTRUCTIONS, _NOTE_FRAME
    from app.llm.firewall_gateway import _SYSTEM
    from app.llm.schema_call import harden_schema

    if cell.content == "gold_note":
        label, body = _gold_notes_by_length()[cell.length]
    else:
        label, body = f"filler-{cell.length}", payload(FACTORIAL_LENGTHS[cell.length])

    if cell.schema == "flat":
        messages = [
            {"role": "system", "content": SYSTEM},
            {"role": "user", "content": body},
        ]
        response_format = {
            "type": "json_schema",
            "json_schema": {"name": "probe", "schema": PROBE_SCHEMA, "strict": True},
        }
    else:
        instructions = _INSTRUCTIONS.format(case_id=label, requested_service="R0075")
        messages = [
            {"role": "system", "content": f"{_SYSTEM}\n\n{instructions}"},
            {
                "role": "user",
                "content": (
                    f"{_NOTE_FRAME}\n\n{FENCE}\n"
                    f"{body.replace(FENCE, '[fence-delimiter-removed]')}\n"
                    f"{FENCE}"
                ),
            },
        ]
        response_format = {
            "type": "json_schema",
            "json_schema": {
                "name": "IntakeExtraction",
                "strict": True,
                "schema": harden_schema(IntakeExtraction.model_json_schema()),
            },
        }
    return messages, response_format, _digest(body), label


async def _observe_cell(
    client: LlmClient, cell: Cell, trial: int, *, temperature: float = TEMPERATURE
) -> Observation:
    """One observation of one cell.

    `temperature` defaults to the registered `TEMPERATURE` and exists so
    `scripts/r86_temperature_perturbation.py` can vary exactly that one field while
    building the request through **this** function rather than a copy of it. A second
    implementation of "build the failing request" would agree with this one until it
    did not, and the whole value of that experiment is that one field differs.

    The default is asserted by test, so the registered path cannot drift through it.
    """
    from app.core.errors import SchemaValidationError

    messages, response_format, digest, label = _factorial_request(cell)
    body_in = messages[-1]["content"]
    observation = Observation(
        band_words=FACTORIAL_LENGTHS[cell.length],
        trial=trial,
        payload_digest=digest,
        payload_chars=len(body_in),
    )
    observation.cell = cell.name
    observation.payload_label = label

    try:
        response = await client.chat(
            messages,
            temperature=temperature,
            max_tokens=MAX_OUTPUT_TOKENS,
            response_format=response_format,
        )
    except Exception as failure:
        status = getattr(failure, "status_code", None)
        classified = classify_provider_failure(failure, status_code=status)
        observation.status_class = _status_class(status)
        observation.failure_kind = classified.kind.value
        observation.attribution = classified.attribution.value
        return observation

    out = response.payload or ""
    try:
        parsed: Any = json.loads(out)
    except (ValueError, TypeError):
        parsed = None

    valid = isinstance(parsed, dict) and (
        set(PROBE_SCHEMA["required"]) <= set(parsed)
        if cell.schema == "flat"
        else "clinical_facts" in parsed
    )
    shape = ResponseShape(
        finish_reason=response.finish_reason,
        body_chars=len(out),
        whitespace_fraction=round(_whitespace_fraction(out), 4),
        parsed_as_json=parsed is not None,
        satisfied_schema=valid,
        prompt_tokens=response.usage.prompt_tokens,
        completion_tokens=response.usage.completion_tokens,
    )
    classified = (
        classify_provider_failure(None, status_code=200, shape=shape)
        if valid
        else classify_provider_failure(
            SchemaValidationError("response did not satisfy the schema", attempts=1),
            status_code=200,
            shape=shape,
        )
    )

    observation.prompt_tokens = shape.prompt_tokens
    observation.completion_tokens = shape.completion_tokens
    observation.finish_reason = shape.finish_reason
    observation.body_chars = shape.body_chars
    observation.whitespace_fraction = shape.whitespace_fraction
    observation.parsed_as_json = shape.parsed_as_json
    observation.satisfied_schema = valid
    observation.latency_ms = round(response.latency_ms, 1)
    observation.status_class = "2xx"
    observation.failure_kind = classified.kind.value
    observation.attribution = classified.attribution.value
    observation.is_r86_signature = classified.is_r86_signature
    observation.succeeded = valid
    return observation


def _factorial_preregistration(settings: Settings) -> dict[str, Any]:
    structured = structured_model_for(settings)
    return {
        "experiment": FACTORIAL_ID,
        "follows": EXPERIMENT_ID,
        "why_it_exists": (
            "r86-gradient-001 returned 0/56 and did not support its hypothesis. "
            "Phase 15's failing arm differed from the gradient's passing arm in "
            "THREE ways simultaneously - schema shape, content and length - so no "
            "single factor was isolated. This crosses them. Written AFTER the null "
            "result and BEFORE any factorial observation."
        ),
        "hypothesis": (
            "At least one of {schema shape, content, length} is associated with the "
            "R-86 signature. Direction is not predicted."
        ),
        "factors": {
            "schema": ["flat two-field probe", "production IntakeExtraction"],
            "content": ["synthetic seeded filler", "real gold clinical note"],
            "length": ["short", "long"],
        },
        "cells": [c.name for c in FACTORIAL_CELLS],
        "trials_per_cell": FACTORIAL_TRIALS,
        "observations_planned": len(FACTORIAL_CELLS) * FACTORIAL_TRIALS,
        "held_constant": {
            "model_digest": _digest(structured),
            "temperature": TEMPERATURE,
            "max_output_tokens": MAX_OUTPUT_TOKENS,
            "attempts_per_observation": ATTEMPTS,
            "structured_mode": "json_schema",
            "firewall_path": "MEDAUTH -> firewall -> provider (no bypass, one caller key)",
        },
        "clinical_text_in_this_report": (
            "none. Gold notes are SENT - they are synthetic by construction and "
            "already cross this boundary in every evaluation - and only their "
            "digest, character count and token counts are recorded."
        ),
        "prohibitions": [
            "No cell may be dropped after seeing its result.",
            "Causation may not be claimed from 6 trials per cell.",
            "The responsible layer may not be inferred: provider and firewall stay "
            "indistinguishable from this side whatever the factors say.",
        ],
    }


async def _run_factorial(settings: Settings, write: bool) -> int:
    plan = _factorial_preregistration(settings)
    OUT.mkdir(parents=True, exist_ok=True)
    if write:
        (OUT / "factorial_preregistration.json").write_text(
            json.dumps(plan, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )
        print(
            "  pre-registration frozen -> "
            f"{(OUT / 'factorial_preregistration.json').relative_to(REPO)}\n"
        )

    client = LlmClient(
        base_url=settings.llm_base_url,
        api_key=settings.llm_api_key.get_secret_value(),
        model=structured_model_for(settings),
        timeout_seconds=settings.llm_timeout_seconds,
        max_attempts=ATTEMPTS,
    )
    results: dict[str, list[Observation]] = {}
    try:
        for cell in FACTORIAL_CELLS:
            observations = [
                await _observe_cell(client, cell, trial) for trial in range(1, FACTORIAL_TRIALS + 1)
            ]
            results[cell.name] = observations
            marks = "".join(
                "R" if o.is_r86_signature else ("!" if not o.succeeded else ".")
                for o in observations
            )
            tokens = [o.prompt_tokens for o in observations if o.prompt_tokens]
            print(
                f"  {cell.name:28} {marks}  r86 "
                f"{sum(1 for o in observations if o.is_r86_signature)}/{len(observations)}  "
                f"prompt_tok {min(tokens) if tokens else 0}-{max(tokens) if tokens else 0}"
            )
    finally:
        await client.aclose()

    flat = [o for obs in results.values() for o in obs]

    def _by(factor: str, value: str) -> list[Observation]:
        index = {"schema": 0, "content": 1, "length": 2}[factor]
        return [o for o in flat if (o.cell or "").split("/")[index] == value]

    margins = {
        f"{factor}={value}": _rate(
            sum(1 for o in _by(factor, value) if o.is_r86_signature), len(_by(factor, value))
        )
        for factor, values in (
            ("schema", ("flat", "intake")),
            ("content", ("filler", "gold_note")),
            ("length", ("short", "long")),
        )
        for value in values
    }

    report = {
        "experiment": FACTORIAL_ID,
        "ran_at": datetime.now(UTC).isoformat(),
        "git_commit": _git_commit(),
        "preregistration": plan,
        "observations_made": len(flat),
        "cells": {
            name: {
                "trials": len(obs),
                "r86_signature_rate": _rate(sum(1 for o in obs if o.is_r86_signature), len(obs)),
                "provider_failure_rate": _rate(
                    sum(
                        1
                        for o in obs
                        if ProviderFailureKind(o.failure_kind).counts_toward_provider_reliability
                    ),
                    len(obs),
                ),
                "median_whitespace_fraction": sorted(o.whitespace_fraction for o in obs)[
                    len(obs) // 2
                ],
                "prompt_tokens_min": min(
                    (o.prompt_tokens for o in obs if o.prompt_tokens), default=0
                ),
                "prompt_tokens_max": max(o.prompt_tokens for o in obs),
                "failure_kinds": dict(sorted(Counter(o.failure_kind for o in obs).items())),
                "observations": [asdict(o) for o in obs],
            }
            for name, obs in results.items()
        },
        # Marginal rates, NOT an ANOVA. At 24 observations per margin an interaction
        # term would be a decoration; the marginals are what six trials per cell can
        # honestly carry.
        "marginal_r86_rates": margins,
        "instrument_note": (
            "The first execution of this matrix exposed a defect in the classifier "
            "rather than in the system: `classify_provider_failure` tested "
            "'body did not parse' before 'whitespace runaway', so every R-86 "
            "occurrence - which by definition never closes its document and "
            "therefore never parses - was reported as MALFORMED_RESPONSE with "
            "is_r86_signature false. The ordering was corrected and the matrix "
            "re-executed unchanged: same cells, same trials, same factors, same "
            "pre-registration. A measuring device was repaired; no hypothesis, "
            "threshold or cell was altered after seeing a result."
        ),
        "interpretation": {
            "claim_permitted": (
                "Per-cell and marginal R-86 rates, with denominators and Wilson "
                "intervals, over three crossed factors."
            ),
            "claims_refused": [
                "an interaction effect - the design has 6 trials per cell",
                "causation",
                "the responsible layer",
            ],
        },
    }

    print()
    for key, rate in margins.items():
        print(f"  {key:24} r86 {rate['successes']}/{rate['total']}")

    if write:
        (OUT / "factorial_results.json").write_text(
            json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )
        print(f"\n  written to {(OUT / 'factorial_results.json').relative_to(REPO)}")
    return 0


async def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--write", action="store_true")
    parser.add_argument("--plan", action="store_true", help="print the matrix, make no calls")
    parser.add_argument(
        "--factorial",
        action="store_true",
        help="run r86-factorial-001 instead: schema x content x length",
    )
    args = parser.parse_args()

    settings = Settings()
    plan = _factorial_preregistration(settings) if args.factorial else _preregistration(settings)

    if args.plan:
        print(json.dumps(plan, indent=2, sort_keys=True))
        return 0

    if os.environ.get(LIVE_FLAG) != "1":
        print(f"  refusing: set {LIVE_FLAG}=1 to make real model calls", file=sys.stderr)
        return 1

    if args.factorial:
        return await _run_factorial(settings, args.write)

    OUT.mkdir(parents=True, exist_ok=True)
    if args.write:
        # WRITTEN BEFORE THE FIRST CALL. Same discipline as an evaluation manifest:
        # a matrix recorded afterwards is a matrix that could have been chosen.
        (OUT / "preregistration.json").write_text(
            json.dumps(plan, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )
        print(f"  pre-registration frozen -> {(OUT / 'preregistration.json').relative_to(REPO)}\n")

    client = LlmClient(
        base_url=settings.llm_base_url,
        api_key=settings.llm_api_key.get_secret_value(),
        model=structured_model_for(settings),
        timeout_seconds=settings.llm_timeout_seconds,
        max_attempts=ATTEMPTS,
    )
    bands: list[Band] = []
    try:
        for words in BANDS:
            band = Band(words=words)
            for trial in range(1, TRIALS_PER_BAND + 1):
                band.observations.append(await _observe(client, words, trial))
            bands.append(band)
            marks = "".join(
                "R" if o.is_r86_signature else ("!" if not o.succeeded else ".")
                for o in band.observations
            )
            tokens = [o.prompt_tokens for o in band.observations if o.prompt_tokens]
            print(
                f"  {words:>4} words  {marks}  fail {band.failures}/{len(band.observations)}  "
                f"r86 {band.r86}  prompt_tok "
                f"{min(tokens) if tokens else 0}-{max(tokens) if tokens else 0}  "
                f"ws_median {band.median_whitespace:.4f}"
            )
    finally:
        await client.aclose()

    observations = [o for band in bands for o in band.observations]
    total_failures = sum(band.failures for band in bands)
    report = {
        "experiment": EXPERIMENT_ID,
        "ran_at": datetime.now(UTC).isoformat(),
        "git_commit": _git_commit(),
        "python": platform.python_version(),
        "preregistration": plan,
        "observations_made": len(observations),
        "observations_planned": plan["observations_planned"],
        "bands": [
            {
                "words": band.words,
                "trials": len(band.observations),
                "provider_failures": band.failures,
                "failure_rate": _rate(band.failures, len(band.observations)),
                "r86_signature_rate": _rate(band.r86, len(band.observations)),
                "r86_signature_count": band.r86,
                "median_whitespace_fraction": band.median_whitespace,
                "prompt_tokens_min": min(
                    (o.prompt_tokens for o in band.observations if o.prompt_tokens), default=0
                ),
                "prompt_tokens_max": max(o.prompt_tokens for o in band.observations),
                "failure_kinds": dict(
                    sorted(Counter(o.failure_kind for o in band.observations).items())
                ),
                "observations": [asdict(o) for o in band.observations],
            }
            for band in bands
        ],
        "overall": {
            "provider_failure_rate": _rate(total_failures, len(observations)),
            "r86_signature_rate": _rate(
                sum(1 for o in observations if o.is_r86_signature), len(observations)
            ),
            "failure_kinds": dict(sorted(Counter(o.failure_kind for o in observations).items())),
            "attributions": dict(sorted(Counter(o.attribution for o in observations).items())),
        },
        "interpretation": {
            "claim_permitted": (
                "Per-band provider-failure and R-86 rates on a synthetic payload, at "
                f"{TRIALS_PER_BAND} trials per band, with Wilson intervals."
            ),
            "claims_refused": [
                "that input length CAUSES the failure",
                "that any threshold separates safe from unsafe input",
                "that the responsible layer is the provider or the firewall",
                "that this measures clinical notes - the payload is synthetic filler",
            ],
        },
    }

    print()
    print(f"  overall provider failure  {total_failures}/{len(observations)}")
    print(f"  kinds                     {report['overall']['failure_kinds']}")

    if args.write:
        (OUT / "results.json").write_text(
            json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )
        print(f"\n  written to {(OUT / 'results.json').relative_to(REPO)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
