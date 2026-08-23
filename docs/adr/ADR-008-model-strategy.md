# ADR-008: Model Strategy and the Gateway Contract

**Status:** Accepted · **Date:** 2026-08-23 · **Phase:** Planning
**Amended:** Phase 0, on evidence. See [Amendment](#amendment-phase-0-capability-probe).

## Context

Two model-bearing steps: intake extraction and per-criterion adjudication. Both must return
**schema-valid structured output** — that requirement is not negotiable, because closed schemas are
how ADR-001's invariant is enforced.

The brief proposed API models for development and self-hosted Llama/Qwen on vLLM for production.

## Problem

Which model, how is it reached, and how much of the architecture depends on the answer?

## Options

| # | Option | Assessment |
|---|---|---|
| A | Hosted OpenAI-compatible endpoint | Strong instruction following and structured output; per-token cost; egress. |
| B | Local Ollama, small model | Free, offline. **4 GB VRAM** on the reference machine means a ~3B model with CPU offload — slow, and weaker at exactly the structured output this design depends on. |
| C | Self-hosted vLLM (Llama / Qwen) | Production-grade throughput and control. Needs GPU capacity that does not exist here. |
| D | Provider SDK directly (Anthropic, OpenAI) | Best-in-class options; a non-OpenAI shape adds a translation seam the firewall exists to avoid. |

## Decision

**Option A, reached through the LLM Firewall.**

| | |
|---|---|
| Model | Any model the provider serves; set by `MEDAUTH_LLM_MODEL` |
| Endpoint | Any OpenAI-compatible endpoint; set by `MEDAUTH_LLM_BASE_URL` |
| Path | MEDAUTH → `llm-firewall :8005/v1` → provider |
| Credential | Provider key held by the **firewall**; MEDAUTH holds only a firewall caller key |
| Streaming | Never used; refused by the firewall (`400`) and meaningless for schema-validated output |
| Abstraction | **`base_url`.** No bespoke gateway interface (ADR-016) |

**Structured output strategy is decided by measurement, not assumption.** Phase 0's
`scripts/probe_model_capabilities.py` determines whether the endpoint supports
`response_format: json_schema`, `json_object`, or tool calling; how it behaves on schema violation;
and whether it is deterministic at `temperature=0`. The result amends this ADR. The fallback, if
none of the strong modes exist, is `json_object` plus strict Pydantic validation plus bounded
repair, with **the repair rate reported as a first-class metric** from Phase 4 rather than hidden.

**vLLM is a documented deployment target, not a validated one.** No claim that this system runs on
self-hosted vLLM may be made until a served model with measured latency exists (OD-2). The reference
machine's RTX 3050 with 4 GB VRAM cannot serve a useful model at the context this system needs —
policy chunks plus clinical facts plus schema.

## Rationale

**Structured output reliability is the selection criterion**, ahead of reasoning quality. If the
model cannot reliably fill a closed schema, ADR-001's containment weakens into a repair loop, and
the repair rate becomes a safety metric rather than an efficiency one.

**OpenAI-compatibility is what makes the firewall free.** The firewall *is* the OpenAI API. A
compatible provider means routing every model call through a security boundary costs one
configuration value. A provider SDK with a different shape would require a translation layer whose
only job is to undo that compatibility.

**The 4 GB VRAM constraint is a fact, not a preference.** Recording it here prevents a future
session from assuming local serving is available, and prevents the project from claiming a
self-hosted deployment it has never run.

**Portability is preserved without an abstraction layer.** vLLM, Ollama, Together, Groq and
OpenRouter all speak the same contract. Switching is a `base_url` change. Building an internal
interface to achieve portability that the protocol already provides would add a layer and remove
nothing.

**Determinism is measured, not assumed.** `temperature=0` is not a guarantee across providers. What
determinism exists is recorded in the probe report, and reproducibility claims are scoped to the
deterministic half of the pipeline (ADR-013).

## Consequences

**Positive.** No provider credential in MEDAUTH. Every model call is screened, rate-limited and
independently audited. Provider switching is configuration. No GPU required to develop or evaluate.

**Negative.** Per-token cost, reported as cost-per-case with the price basis and run date. Network
egress and an availability dependency — handled by failing closed to `HUMAN_REVIEW`. Evaluation
results are specific to one model and are labelled as such. A provider change invalidates
prior results, which is why the model id is on every report and every audit row.

**Neutral.** Per-criterion adjudication multiplies call count by tree size. Measured in Phase 4;
calls are independent and parallelise.

## Rejected alternatives

| Alternative | Rejected because |
|---|---|
| **B — local Ollama only** | 4 GB VRAM forces a small model with CPU offload. Weak structured output undermines the schema containment this architecture depends on, and evaluation numbers would characterise the constraint rather than the design. Retained as an *optional* offline path, never the default. |
| **C — self-hosted vLLM now** | No hardware. Claiming it without serving it would be exactly the kind of unearned claim this project refuses. |
| **D — provider SDK directly** | Bypasses or complicates the firewall boundary. A non-OpenAI shape means either a translation seam or an unscreened model path; both are worse than using a compatible provider. |
| **A bespoke `LLMGateway` interface (as the brief proposed)** | The OpenAI contract already is that interface. See ADR-016. |
| **Multiple models in production** | Doubles evaluation cost and makes results ambiguous. One model, measured; alternatives compared later on the same frozen corpus if justified. |

---

## Amendment: Phase 0 capability probe

**OD-1 is resolved.** `scripts/probe_model_capabilities.py` measured the deployment
through the firewall; the artefact is [`eval/reports/20260823T091726Z__model-capabilities/report.md`](../../eval/reports/20260823T091726Z__model-capabilities/report.md).
Every figure below comes from it.

### Measured profile (n=5 per arm, temperature 0)

| role | `json_schema` | `tool_call` | `json_object` |
|---|---|---|---|
| **primary** (short context) | **supported, 5/5 schema-valid** | rejected | supported, **0/5** schema-valid |
| **long-context** | rejected | **supported, 5/5 schema-valid** | rejected |

The rejections share one cause, confirmed against the provider directly: the
long-context model is served with speculative decoding, and that path does not
support grammar-constrained decoding. It therefore refuses **every** constrained
mode - including a *forced* tool choice, since forcing a function also requires a
grammar. `tool_choice: "auto"` works because nothing is constrained.

`json_object` returning 0/5 is not a defect. It guarantees valid JSON, not *our*
JSON, and measuring it against the real nested verdict schema is what makes the
distinction visible rather than assumed.

### Decision: route by task

| Step | Role | Mode | Why |
|---|---|---|---|
| Intake, per-criterion adjudication | primary | `json_schema` | Grammar-constrained decoding makes conformance **structural** - the decoder enforces the closed schema, so containment does not depend on the model cooperating. |
| Ingest-time criteria extraction | long-context | `tool_call` | Takes a whole policy version in one pass; runs offline, so validate-and-repair is cheap. |

The short context window is sufficient for adjudication **because** ADR-001 split
that step per criterion - one criterion, its evidence chunks, the facts. A design
decision taken for traceability turns out to be what makes the strictly safer
model usable here.

### What this does not establish

Schema conformance only, on one criterion and one prompt. **No claim is made about
which model reasons better**; that is measured in Phase 6 against the frozen gold
corpus. The `retrieval` and `eval` extras remain unaffected.

### Consequence for reproducibility

The primary model is **not byte-deterministic at temperature 0** on the full
verdict schema. ADR-013's reproducibility claim already scoped itself to the
deterministic half of the pipeline; that scoping is now evidenced rather than
precautionary.
