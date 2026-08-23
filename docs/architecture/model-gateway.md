# Model Gateway

**The seam a model call crosses. No call is made yet.**

```
MEDAUTH  ──▶  ModelGateway  ──▶  LLM Firewall :8005/v1  ──▶  provider
```

`app/llm/gateway.py`. Interface only — declared now, before any agent, because a
direct model call added later "just to try it" becomes load-bearing before anyone
removes it. Declaring the seam first makes the shortcut a **visible violation**
rather than an expedient.

---

## What crosses it

Only **schema-constrained chat completions**. Every call names a closed output
schema and the response is validated before it becomes a value.

There is **no free-text path**, and `ModelRequest` has no field for one. Adding it
would reopen the containment argument the architecture rests on: a successful prompt
injection cannot emit an approval when no approval token exists in the schema being
filled.

**Embeddings do not cross it.** The firewall exposes no `/v1/embeddings`, and
embedding a policy corpus through a security gateway would inspect nothing useful.
They run in-process (ADR-016).

**Streaming does not cross it.** The firewall refuses it with `400`, and every
response here is a validated object rather than prose to be parsed. `ModelRequest`
has no `stream` field — the absence is the contract.

## Evidence is a separate field from instructions

```python
ModelRequest(instructions=..., evidence_block=..., ...)
```

Retrieved policy text is **DATA**. It is fenced and framed as non-instruction and is
never concatenated into a system prompt. Keeping the two apart in the type means a
caller cannot merge them by accident.

`provenance_hint` is passed so the firewall can distinguish user-authored text from
retrieved content. It is **available and not relied upon**: the firewall's
indirect-injection recall is **0.1423** and its provenance overlay ships
uncalibrated (OD-3). Containment here is structural.

## Failure semantics, and their asymmetry

| outcome | routes to | retryable |
|---|---|---|
| `BLOCKED` (403) | `HUMAN_REVIEW` | **never** |
| `DETECTOR_UNAVAILABLE` (503) | `HUMAN_REVIEW` | no |
| `TIMEOUT` | `HUMAN_REVIEW` | yes |
| `UNREACHABLE` | `HUMAN_REVIEW` | yes |
| `SCHEMA_INVALID` | `HUMAN_REVIEW` | after bounded repair |
| `UNSUPPORTED` (400) | configuration error at startup | no |

**A `403` is never retried.** Retrying a blocked request is an attempt to evade a
security control. Every failure routes toward a person and **none toward a denial**:
fail closed means fail toward a human, never toward a refusal of care. Asserted by
test over the whole enum.

## Credentials

MEDAUTH holds a revocable **caller** key. The provider credential lives in the
firewall's environment. MEDAUTH therefore holds no model-provider credential at all,
and this interface has no field in which one could be passed.

## Roles, not models

```python
class ModelRole(StrEnum):
    STRUCTURED_ADJUDICATION
    STRUCTURED_INTAKE
```

A call site naming a model would make swapping one a change across the codebase, and
would encode a capability claim where nobody re-measures it.

Phase 0 measured that the primary model supports `response_format: json_schema` at
5/5 schema-valid, while the long-context model is served with speculative decoding
and rejects every grammar-constrained mode. So structured adjudication prefers the
grammar-constrained path.

> **That is a claim about output safety, not about reasoning quality.** No
> comparison of clinical reasoning has been run, and none may be claimed.

## What is deliberately not built

No implementation, no HTTP client wiring, no retry policy tuning, no prompt. The
existing `app/llm/client.py` and `app/llm/schema_call.py` remain the transport;
the gateway is the domain-facing seam they will be adapted to.
