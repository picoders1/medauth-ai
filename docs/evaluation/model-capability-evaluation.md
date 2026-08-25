# Model Capability, Measured on the Live Path

**Resolves nothing about reasoning. Establishes what the decoder does.**

Report: `eval/reports/20260825T070854Z__model-capabilities/`. Model identity is a
digest; concrete ids and hosts live in `.env` and appear nowhere in this repository.

---

## Results, 2026-08-25, n=5 per arm

| role | mode | supported | schema-valid | deterministic | median ms |
|---|---|---|---|---|---|
| structured | `json_schema` | yes | **5/5** | **no** | 713.9 |
| structured | `tool_call` | **no** (502) | — | — | — |
| structured | `json_object` | yes | **0/5** | yes | 803.4 |
| general | `json_schema` | **no** (502) | — | — | — |
| general | `tool_call` | yes | 5/5 | yes | 1025.7 |
| general | `json_object` | **no** (502) | — | — | — |

## The three things this says

**The routing was wrong and is now measured.** The runtime pointed every role at the
general model, which rejects `json_schema` outright. Adjudication would have failed
on its first case. Roles are now routed separately on this evidence.

**`json_object` is not a fallback.** Same model, same prompt, five well-formed JSON
responses, **zero** satisfying the schema. If `json_schema` were ever unavailable,
dropping to `json_object` would not be a degraded mode — it would be no constraint at
all, with a validator catching what it happened to catch.

**Determinism is not what temperature=0 buys.** The chosen arm is marked `no`:
identical requests produced non-identical bytes. At the slice level the *verdicts*
were stable across three runs, but that is a separate measurement and neither implies
the other.

## What this evidence does NOT cover

**It is scoped to the schema it tested.** The probe uses one small nested schema.
Live activation then found that the same model, same mode, **fails to terminate** on
`IntakeResult` — 96% whitespace, never closing the document (R-86). A capability
result is a claim about a decoder *and a schema*, and the probe measures one pair.

Any future "supports strict json_schema" claim must name the schema it was measured
against, or it is broader than its evidence.

**It says nothing about clinical reasoning.** The Phase 0 language holds unchanged:

> This establishes **structured output safety**. It is not evidence that the model is
> clinically superior, and no comparison of clinical reasoning has been run.
