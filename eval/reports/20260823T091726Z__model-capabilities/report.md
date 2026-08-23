# Model Capability Probe

Resolves **OD-1**: which structured-output mechanisms the configured deployment
actually supports. ADR-008 cites this report.

Model identity is a digest, not a name. Concrete model ids and provider hosts are
deployment values held in `.env` and appear nowhere in this repository.

## Provenance

| | |
|---|---|
| generated_at | `2026-08-23T09:17:26+00:00` |
| git_commit | `4b5b411` |
| samples_per_arm | `5` |
| temperature | `0.0` |
| path | `MEDAUTH -> llm-firewall -> provider` |
| python | `3.12.3` |
| platform | `Linux x86_64` |

## Results

`schema-valid` is validation against the real nested per-criterion verdict schema,
not merely 'parsed as JSON'. The distinction is the finding: `json_object`
guarantees only the latter.

| role | digest | mode | supported | http ok | schema-valid | rate | deterministic | median ms |
|---|---|---|---|---|---|---|---|---|
| primary | `sha256:31d69bc24c21` | `json_schema` | yes | 5/5 | 5/5 | 1.0000 | **no** | 1516.2 |
| primary | `sha256:31d69bc24c21` | `tool_call` | **no** | 0/5 | 0/5 | 0.0000 | - | - |
| primary | `sha256:31d69bc24c21` | `json_object` | yes | 5/5 | 0/5 | 0.0000 | **no** | 1697.0 |
| alternate-1 | `sha256:ae0a6a0b7a54` | `json_schema` | **no** | 0/5 | 0/5 | 0.0000 | - | - |
| alternate-1 | `sha256:ae0a6a0b7a54` | `tool_call` | yes | 5/5 | 5/5 | 1.0000 | yes | 1517.8 |
| alternate-1 | `sha256:ae0a6a0b7a54` | `json_object` | **no** | 0/5 | 0/5 | 0.0000 | - | - |

## Unsupported modes

| role | mode | reason |
|---|---|---|
| primary | `tool_call` | UpstreamFailureError: model path failed after 2 attempts: upstream returned 502 |
| alternate-1 | `json_schema` | UpstreamFailureError: model path failed after 2 attempts: upstream returned 502 |
| alternate-1 | `json_object` | UpstreamFailureError: model path failed after 2 attempts: upstream returned 502 |

> The reason is reported as MEDAUTH observes it. The firewall translates an
> upstream 4xx into `502 upstream_error` and suppresses the upstream body, so a
> client-fixable rejection is indistinguishable here from a server fault. That is
> a deliberate non-disclosure choice in the gateway, and it means the *underlying*
> cause has to be established out of band against the provider directly.

## Reading this

- **`json_schema` supported and schema-valid at 1.0000** - conformance is *structural*.
  The decoder enforces the schema, so a prompt injection cannot emit a field that does
  not exist. This is the strongest available guarantee and is preferred wherever offered.
- **`tool_call` supported** - conformance is *learned*, not enforced. Validation and
  bounded repair do real work, and the repair rate must be reported as a metric.
- **`json_object` supported but schema-valid below 1.0000** - expected, and the point:
  it guarantees valid JSON, not *our* JSON. It is the weakest mode.
- **A mode unsupported** - a serving-stack property, not a model-quality statement.
- **`deterministic: no` at temperature 0** - the provider is not byte-reproducible
  on this schema. Reproducibility claims are therefore scoped to the deterministic
  half of the pipeline: resolution, guardrail and `decide()` replay exactly; the
  model half does not (ADR-013).

## What this report does NOT establish

It measures schema conformance on one criterion and one prompt. It says nothing about
reasoning quality, and no model is preferred over another on that basis here. Decision
quality is measured in Phase 6 against the frozen gold corpus.
