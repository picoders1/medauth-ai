"""Record what the configured model can actually do (Phase 0 gate, OD-1).

Closed schemas are how the governing invariant is enforced, so *how* the served
model constrains its output is not a detail - it decides whether conformance is
structural (the decoder enforces it) or cooperative (the model usually complies
and we validate afterwards). That must be an observation, never an assumption.

This writes a committed report under ``eval/reports/``. ADR-008 cites the report;
it does not cite a conversation. If the artefact does not exist, the claim is not
made.

Model identity is recorded as a short digest and a role, not a name: concrete
model ids and provider hosts are deployment values that live in ``.env`` and
appear nowhere in this repository.

Usage::

    uv run python scripts/probe_model_capabilities.py
    uv run python scripts/probe_model_capabilities.py --models a,b --samples 8
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import platform
import subprocess
import sys
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, ValidationError

from app.config.settings import Settings
from app.core.errors import LlmError
from app.core.types import Verdict
from app.llm.client import LlmClient
from app.llm.schema_call import StructuredMode, harden_schema

REPO = Path(__file__).resolve().parents[1]


class ProbeCitation(BaseModel):
    model_config = ConfigDict(extra="forbid")
    chunk_id: str
    quote: str


class ProbeVerdict(BaseModel):
    """Shaped like a real per-criterion verdict, nested model included.

    Deliberately realistic: a probe against a flat two-field schema would
    overstate what the model can do on the schema this system actually uses.
    """

    model_config = ConfigDict(extra="forbid")
    criterion_id: str
    verdict: Verdict
    citations: list[ProbeCitation]
    fact_ids: list[str]


PROMPT = [
    {
        "role": "user",
        "content": (
            "Criterion c1: 'A documented BMI of 35 or greater is required.'\n"
            '<policy_data chunk_id="ch-7">Coverage requires a documented BMI of 35 or '
            "greater.</policy_data>\n"
            "Clinical fact f2: 'BMI recorded as 38.1'.\n"
            "Emit the verdict object for criterion c1, citing chunk ch-7 and fact f2."
        ),
    }
]


@dataclass
class ArmResult:
    mode: str
    supported: bool
    http_ok: int
    schema_valid: int
    samples: int
    deterministic: bool | None = None
    median_latency_ms: float | None = None
    failure: str | None = None

    @property
    def schema_valid_rate(self) -> float | None:
        return round(self.schema_valid / self.samples, 4) if self.samples else None


@dataclass
class ModelReport:
    role: str
    digest: str
    arms: list[ArmResult] = field(default_factory=list)

    def arm(self, mode: str) -> ArmResult | None:
        return next((a for a in self.arms if a.mode == mode), None)


def _digest(model_id: str) -> str:
    return "sha256:" + hashlib.sha256(model_id.encode()).hexdigest()[:12]


def _git_commit() -> str:
    try:
        out = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],
            cwd=REPO,
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        )
        return out.stdout.strip() or "unknown"
    except (OSError, subprocess.SubprocessError):
        return "unknown"


def _request_kwargs(mode: StructuredMode, schema: dict[str, Any]) -> dict[str, Any]:
    if mode is StructuredMode.JSON_SCHEMA:
        return {
            "response_format": {
                "type": "json_schema",
                "json_schema": {"name": "ProbeVerdict", "strict": True, "schema": schema},
            }
        }
    if mode is StructuredMode.TOOL_CALL:
        return {
            "tools": [
                {"type": "function", "function": {"name": "ProbeVerdict", "parameters": schema}}
            ],
            "tool_choice": "auto",
        }
    return {"response_format": {"type": "json_object"}}


def _conforms(payload: str) -> bool:
    try:
        ProbeVerdict.model_validate_json(payload)
    except (ValidationError, ValueError):
        return False
    return True


async def _probe_arm(
    client: LlmClient, model: str, mode: StructuredMode, schema: dict[str, Any], samples: int
) -> ArmResult:
    kwargs = _request_kwargs(mode, schema)
    payloads: list[str] = []
    latencies: list[float] = []
    http_ok = schema_valid = 0
    failure: str | None = None

    for _ in range(samples):
        try:
            response = await client.chat(PROMPT, model=model, temperature=0.0, **kwargs)
        except LlmError as exc:
            failure = f"{type(exc).__name__}: {exc}"[:180]
            break
        http_ok += 1
        latencies.append(response.latency_ms)
        payload = response.payload or ""
        payloads.append(payload)
        # Any failure to conform is a failure; the reason is not the finding here.
        if _conforms(payload):
            schema_valid += 1

    latencies.sort()
    return ArmResult(
        mode=mode.value,
        supported=http_ok > 0,
        http_ok=http_ok,
        schema_valid=schema_valid,
        samples=samples,
        deterministic=(len(set(payloads)) == 1) if len(payloads) > 1 else None,
        median_latency_ms=round(latencies[len(latencies) // 2], 1) if latencies else None,
        failure=failure,
    )


async def probe_model(client: LlmClient, model: str, role: str, samples: int) -> ModelReport:
    schema = harden_schema(ProbeVerdict.model_json_schema())
    report = ModelReport(role=role, digest=_digest(model))
    for mode in StructuredMode:
        print(f"  {role:<18} {mode.value:<12} ", end="", flush=True)
        arm = await _probe_arm(client, model, mode, schema, samples)
        report.arms.append(arm)
        if arm.supported:
            print(f"ok {arm.http_ok}/{arm.samples}  schema-valid {arm.schema_valid}/{arm.samples}")
        else:
            print(f"UNSUPPORTED  ({arm.failure})")
    return report


def render(reports: list[ModelReport], meta: dict[str, Any]) -> str:
    lines = [
        "# Model Capability Probe",
        "",
        "Resolves **OD-1**: which structured-output mechanisms the configured deployment",
        "actually supports. ADR-008 cites this report.",
        "",
        "Model identity is a digest, not a name. Concrete model ids and provider hosts are",
        "deployment values held in `.env` and appear nowhere in this repository.",
        "",
        "## Provenance",
        "",
        "| | |",
        "|---|---|",
    ]
    lines += [f"| {k} | `{v}` |" for k, v in meta.items()]
    lines += [
        "",
        "## Results",
        "",
        "`schema-valid` is validation against the real nested per-criterion verdict schema,",
        "not merely 'parsed as JSON'. The distinction is the finding: `json_object`",
        "guarantees only the latter.",
        "",
        "| role | digest | mode | supported | http ok | schema-valid | rate | deterministic | median ms |",
        "|---|---|---|---|---|---|---|---|---|",
    ]
    for report in reports:
        for arm in report.arms:
            det = "-" if arm.deterministic is None else ("yes" if arm.deterministic else "**no**")
            rate = "-" if arm.schema_valid_rate is None else f"{arm.schema_valid_rate:.4f}"
            lines.append(
                f"| {report.role} | `{report.digest}` | `{arm.mode}` | "
                f"{'yes' if arm.supported else '**no**'} | {arm.http_ok}/{arm.samples} | "
                f"{arm.schema_valid}/{arm.samples} | {rate} | {det} | "
                f"{arm.median_latency_ms if arm.median_latency_ms is not None else '-'} |"
            )

    lines += ["", "## Unsupported modes", ""]
    unsupported = [(r.role, a) for r in reports for a in r.arms if not a.supported and a.failure]
    if unsupported:
        lines += ["| role | mode | reason |", "|---|---|---|"]
        lines += [f"| {role} | `{a.mode}` | {a.failure} |" for role, a in unsupported]
        lines += [
            "",
            "> The reason is reported as MEDAUTH observes it. The firewall translates an",
            "> upstream 4xx into `502 upstream_error` and suppresses the upstream body, so a",
            "> client-fixable rejection is indistinguishable here from a server fault. That is",
            "> a deliberate non-disclosure choice in the gateway, and it means the *underlying*",
            "> cause has to be established out of band against the provider directly.",
        ]
    else:
        lines.append("None - every probed mode returned a completion.")

    lines += [
        "",
        "## Reading this",
        "",
        "- **`json_schema` supported and schema-valid at 1.0000** - conformance is *structural*.",
        "  The decoder enforces the schema, so a prompt injection cannot emit a field that does",
        "  not exist. This is the strongest available guarantee and is preferred wherever offered.",
        "- **`tool_call` supported** - conformance is *learned*, not enforced. Validation and",
        "  bounded repair do real work, and the repair rate must be reported as a metric.",
        "- **`json_object` supported but schema-valid below 1.0000** - expected, and the point:",
        "  it guarantees valid JSON, not *our* JSON. It is the weakest mode.",
        "- **A mode unsupported** - a serving-stack property, not a model-quality statement.",
        "- **`deterministic: no` at temperature 0** - the provider is not byte-reproducible",
        "  on this schema. Reproducibility claims are therefore scoped to the deterministic",
        "  half of the pipeline: resolution, guardrail and `decide()` replay exactly; the",
        "  model half does not (ADR-013).",
        "",
        "## What this report does NOT establish",
        "",
        "It measures schema conformance on one criterion and one prompt. It says nothing about",
        "reasoning quality, and no model is preferred over another on that basis here. Decision",
        "quality is measured in Phase 6 against the frozen gold corpus.",
        "",
    ]
    return "\n".join(lines)


async def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--models", help="comma-separated model ids (default: configured model)")
    parser.add_argument("--samples", type=int, default=5, help="samples per arm (default 5)")
    parser.add_argument("--out", default="eval/reports", help="report directory")
    args = parser.parse_args()

    settings = Settings()
    models = (
        [m.strip() for m in args.models.split(",") if m.strip()]
        if args.models
        else [settings.llm_model]
    )

    print(f"probing {len(models)} model(s) via {settings.llm_base_url}, n={args.samples} per arm\n")

    reports: list[ModelReport] = []
    async with LlmClient(
        base_url=settings.llm_base_url,
        api_key=settings.llm_api_key.get_secret_value(),
        model=settings.llm_model,
        timeout_seconds=settings.llm_timeout_seconds,
        max_attempts=2,
    ) as client:
        for index, model in enumerate(models):
            role = "primary" if index == 0 else f"alternate-{index}"
            reports.append(await probe_model(client, model, role, args.samples))

    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    meta = {
        "generated_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "git_commit": _git_commit(),
        "samples_per_arm": args.samples,
        "temperature": 0.0,
        "path": "MEDAUTH -> llm-firewall -> provider",
        "python": platform.python_version(),
        "platform": f"{platform.system()} {platform.machine()}",
    }

    out = REPO / args.out / f"{stamp}__model-capabilities"
    out.mkdir(parents=True, exist_ok=True)
    (out / "report.md").write_text(render(reports, meta), encoding="utf-8")
    (out / "result.json").write_text(
        json.dumps({"meta": meta, "models": [asdict(r) for r in reports]}, indent=2),
        encoding="utf-8",
    )
    print(f"\nreport: {out.relative_to(REPO)}/report.md")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
