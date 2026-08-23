# LLM Gateway Contract

```
MEDAUTH  →  LLMGateway  →  LLM Firewall :8005/v1  →  model provider
```

`app/llm/gateway.py`. Interface only — **no call is made, in this phase or any
earlier one.**

---

## Request

```python
ModelRequest(
    role,
    prompt_id,
    instructions,
    evidence_block,
    schema_name,
    schema,
    max_repair_attempts,
    provenance_hint,
)
```

Two absences are the contract:

**No `stream` field.** The firewall refuses streaming with `400`, and every response
here is a validated object rather than prose to be parsed.

**No free-text field.** Adding one would reopen the containment argument the whole
architecture rests on.

`instructions` and `evidence_block` are separate fields because retrieved policy
text is **DATA**. It is fenced and framed as non-instruction, never concatenated
into a system prompt — and keeping them apart in the type means a caller cannot
merge them by accident.

A request with an empty schema, or no `prompt_id`, is refused at construction: a
call with no schema is a free-text call by another name.

## Response

```python
ModelResponse(
    value,
    outcome,
    model_id,
    prompt_id,
    attempts,
    latency_ms,
    prompt_tokens,
    completion_tokens,
    notes,
)
```

`value` is already validated against the closed schema. There is no raw-text field.

## Failure semantics

| outcome | routes to | retryable |
|---|---|---|
| `BLOCKED` (403) | `HUMAN_REVIEW` | **never** |
| `DETECTOR_UNAVAILABLE` (503) | `HUMAN_REVIEW` | no |
| `TIMEOUT` | `HUMAN_REVIEW` | yes |
| `UNREACHABLE` | `HUMAN_REVIEW` | yes |
| `SCHEMA_INVALID` | `HUMAN_REVIEW` after bounded repair | — |
| `UNSUPPORTED` (400) | configuration error at startup | no |

**A 403 is never retried as an ordinary model error.** Retrying a blocked request is
an attempt to evade a security control, and a retry loop that treats it as transient
would keep attempting until one got through.

**Every failure routes toward a person and none toward a denial.** Fail closed means
fail toward a human, never toward a refusal of care — asserted by test over the whole
enum.

## No provider shortcut

`GatewayFailure` carries the outcome so a caller cannot lose it. Domain packages
reach a model only through this seam; a direct `httpx` call in `app/adjudication`
would be a boundary violation rather than an expedient, which is why the interface
exists before the agents do.

## Credentials

MEDAUTH holds a revocable **caller** key. The provider credential lives in the
firewall's environment, so MEDAUTH holds no model-provider credential at all — and
this interface has no field through which one could be passed.

## Model selection is a safety claim, not a quality one

`ModelRole` names what a call needs, never which model serves it. Phase 0 measured
that the grammar-constrained path returns 5/5 schema-valid while the long-context
model rejects every grammar-constrained mode.

> That establishes **structured output safety**. It is **not** evidence that the
> model is clinically superior, and no comparison of clinical reasoning has been run.

The model name appears in configuration, never in business logic — so swapping one is
not a change across the codebase, and no capability claim is encoded where nobody
re-measures it.
