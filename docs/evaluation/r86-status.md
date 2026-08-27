# R-86 — why the evaluation gate is blocked

**One sentence:** the model provider, given the production extraction schema and a long
clinical note, never finishes the JSON document — and because the failure is inside a
decoder MEDAUTH does not operate, the evaluation gate stays shut rather than being
adjusted to fit.

> **A blocked evaluation is not the same as a broken application.** Every application
> guarantee in this repository is verified and passing. What is blocked is the
> *measurement*, because the measurement depends on a provider behaving correctly and it
> does not.

---

## What R-86 is

The gate that authorises an official evaluation run. It reads exactly two artefacts —
the sealed reproducer manifest and the most recent revalidation — and authorises only if
the registered reproducer passed under the pre-registered threshold. There is no
`force`, no `override`, no environment variable, and a test asserts their absence over
the module's own AST.

## Current result

| | |
|---|---|
| Trials | **12** (6 per cell, two cells) |
| Failures | **6** |
| Failure rate | **0.5000** |
| Pre-registered ceiling | **0.10** |
| Gate | **`BLOCKED`** |

`6/12` is a **failure rate**, not a score. It is five times the ceiling, not halfway to it.

## The failure

`intake/gold_note/long` fails **6 of 6**, deterministically at temperature 0 —
byte-identical across trials taken hours apart:

| | failing cell | control cell |
|---|---|---|
| completion tokens | **1536** (the ceiling) | 478 |
| finish reason | `length` | `stop` |
| whitespace | **92.0%** | 9.3% |
| non-whitespace characters | **190** | 1098 |
| parsed as JSON | **no** | yes |

It emits about 190 characters — the minimal document satisfying this schema is 110 —
then stops producing content and spends the remaining ~1350 tokens on whitespace until
the ceiling stops it. `parsed_as_json: false` on all twelve observations, so the padding
begins while the document is still **open**.

## What was ruled out, each by measurement

| explanation | why it is refuted |
|---|---|
| MEDAUTH application defect | the same schema succeeds in three of four factorial cells |
| gateway mutates the request | the gateway forwards the payload dict verbatim and contains **no** reference to `response_format`, `json_schema`, `strict`, `max_tokens` or `temperature` |
| gateway mutates the response | 2389 characters measured at the firewall and 2389 at MEDAUTH — two records on opposite sides agreeing to the character |
| prompt length | `intake/filler/long` at **522** prompt tokens succeeds; the failing cell is **512** |
| context exhaustion | same |
| completion budget too small | the succeeding long cell finishes at 1028 tokens — 67% of the ceiling — while emitting **ten times more content** |
| the schema alone | succeeds with filler content at both lengths |
| the content alone | the same clinical note succeeds under the flat schema and at short length |
| a defective reproducer | it reproduces the production request shape exactly, and the control cell in the same run passes 6/6 |

It requires the **conjunction** of the production schema, real clinical content and the
longer input. One cell of eight fails, so every marginal is confounded and no single
factor is isolable.

## Why it cannot be fixed here

| hop | controllable? |
|---|---|
| MEDAUTH → gateway | yes |
| the gateway itself | yes, fully — source, container and configuration are local |
| gateway → provider | configuration only: the endpoint can be repointed, the service cannot be changed |
| **the decoder / structured-output runtime** | **no** |

The last hop exposes no administrative surface — model-info, runtime and admin paths all
return `404`, and model listing is not even proxied. There is no local alternative: a
single 4 GB GPU and no inference server, which OD-2 already records as unable to serve
this model at the required context.

Repointing at a different model would produce evidence about a different system, which
the closure contract classifies as `NEW_SYSTEM_CONFIGURATION` rather than a fix.

Every remaining discriminator — decoder state, EOS eligibility at the point output
begins looping, grammar state at failure, token-level trace, runtime version,
speculative-decoding participation — is provider-internal. Two of them would settle it
in one line: *which state, and was EOS legal there.*

## What was not done, and why that is the point

The threshold was not lowered. The schema was not simplified. The note was not
shortened. The failing cell was not dropped. Retries were not added. `gold_v2` was not
spent — it stands at **0/1**, and the 26-case evaluation has never run.

Any of those would have produced a green gate and a meaningless number. The gate is
built so that saying yes for the wrong reason requires editing the gate, and the edit
would be visible in the diff.

## Integrity

| | |
|---|---|
| seal | intact (digest recomputes) |
| registered schema, gold note, request shape | unchanged |
| `max_tokens` 1536 · `temperature` 0.0 · `json_schema` · strict · non-streaming | unchanged |
| threshold | **0.10**, unchanged |
| evaluator | unchanged |
| `gold_v1` | **2/2**, frozen |
| `gold_v2` | **0/1**, unspent |
| official revalidation | not re-run |
| 26-case evaluation | **not run** — the report directory holds `AUTHORISATION.json` recording `authorised: false`, and no results |

## Status

**Attribution:** `PROVIDER_SIDE`, high confidence. **Root cause:** not established — six
hypotheses remain and none is selected. **Local diagnostics:** exhausted.

Full escalation package, including the eight-item provider evidence request and the
evidenced control boundary: [../operations/r86-provider-escalation.md](../operations/r86-provider-escalation.md).
