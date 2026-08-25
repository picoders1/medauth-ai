# R-86 — Grammar-constrained decoding does not terminate

**For the owner of the LLM firewall and/or the model provider. Not fixable here.**

Reproducible, deterministic, and bounded on our side by mitigations that are fragile
by construction. This document exists because Phase 13 was asked not to claim a fix
where there is only a mitigation.

---

## The behaviour

A strict `json_schema` request returns a response that satisfies the grammar and
**never closes the document**. It emits a short prefix of real JSON, then pads with
newline-plus-indent until the token ceiling.

```
finish_reason      length
completion_tokens  1536 (ceiling) / 2000 (ceiling) / 4000 (ceiling)
whitespace         95.7% – 98.6% of the response body
tail               "    \n" repeated to the limit
```

With no `max_tokens` set, the call runs to the request timeout — **3 attempts × 60 s
= 180 s, no result**, per case.

## Reproduction

Same endpoint, same model, same schema, same temperature, same `max_tokens`. The
**only** difference is one sentence in the system turn asking for compact output.

| system turn contains the compact-output sentence | runs | `finish_reason` | tokens | whitespace |
|---|---|---|---|---|
| **yes** | 3/3 | `stop` | 37 | 9.0% |
| **no** | 3/3 | `length` | 1536 (ceiling) | 97.7% |

Deterministic in both directions. Not intermittent, not load-related.

## Why this is not a schema problem

The schema is valid, accepted, and produces correct output when the model
terminates. It was also reduced during diagnosis — nested to flat, five arrays to
one, and down to two fields — and **every variant reproduces the behaviour** once
the model enters the padded mode.

## Layer classification, as far as our evidence reaches

| candidate | verdict |
|---|---|
| `REQUEST_SHAPE` | **excluded.** Identical request bodies; only a prompt sentence differs |
| `TIMEOUT_HANDLING` | **excluded.** Our timeout fires correctly; it is what turns the hang into a 180 s loss |
| `MODEL_CONFIGURATION` | **excluded.** `temperature`, `max_tokens`, `stream` identical across both arms |
| `PROVIDER_DECODER` | **candidate** |
| `FIREWALL_PROXY` | **candidate** |

**We cannot distinguish the last two, and we do not guess.** MEDAUTH holds a
revocable caller key and reaches the provider only through the firewall — by design.
Separating them needs a request issued provider-side, which is the escalation.

The underlying mechanism is not in doubt, whichever component owns it:

> **JSON permits arbitrary whitespace between tokens. A constrained decoder can
> satisfy the grammar forever without closing the document. The grammar guarantees
> the output *shape*; it does not guarantee the output *ends*.**

## What we have done, and why it is not enough

| mitigation | effect | why it is not a fix |
|---|---|---|
| model-facing schema carrying only fields the model can produce | removed one trigger | the padded mode is still reachable |
| `max_output_tokens` ceiling | bounds the damage | converts a 180 s hang into a truncation → `SCHEMA_INVALID`. Still no result |
| compact-output instruction in the system turn | 0/3 → 3/3 terminating | **relies on the model honouring an instruction, which is precisely what a grammar constraint exists not to rely on.** One call in the Phase 12 live matrix still ran away at 20.8 s |

Every failure fails closed — to `HUMAN_REVIEW`, never to a recommendation — so this
is an availability and cost problem, not a safety one. It is filed as a risk rather
than an incident for that reason.

## What would actually fix it

A **decoder-side stop condition**: once the JSON document is structurally complete,
whitespace should not be a legal continuation. That is a change in the constrained
decoder, not in a prompt.

---

# Phase-15 controlled investigation (2026-08-25)

`scripts/investigate_r86.py`, report at `eval/reports/r86-investigation/results.json`.
Six arms of the reduced probe plus the exact Phase-14 intake shape, three runs each,
one attempt per observation. **Every arm goes through the firewall on the same caller
key.** MEDAUTH holds no provider credential and did not attempt to reach the provider
directly; no arm carries clinical, corpus or note text, and the report records model
digests rather than model names.

## The finding: it is input-length dependent, and it is a gradient

The reduced probe used for the Phase-13 diagnosis **no longer reproduces at all** -
3/3 terminate, 12% whitespace, at every ceiling from 256 to 1024 tokens. The exact
Phase-14 request shape does.

| band | prompt tokens | whitespace | padded |
|---|---|---|---|
| reduced probe (2 fields, 1 sentence) | 35 | 0.1220 | 0/3 |
| `intake.v2`, three **shortest** gold notes | 419 – 428 | 0.0933 – 0.0952 | 0/3 |
| `intake.v2`, three **longest** gold notes | 498 – 516 | **0.2037 – 0.9268** | **2/3** |

Two things follow, and the second is the useful one:

**Phase 13's diagnosis was measuring the wrong variable.** It reduced the schema
"nested to flat, five arrays to one, and down to two fields" - which also reduced the
prompt - and concluded every variant reproduced. Against today's deployment the
reduced form reproduces in none of six arms. The schema was never the axis.

**Padding is not a mode the decoder enters or does not.** At 500 prompt tokens the
same request produced 20%, 20% and 93% whitespace on three runs. The runaway is the
tail of a continuous degradation, not a switch. A component that padded responses as
a post-processing step would have no reason to scale with the input.

Neither observation identifies the owning layer - a decoder and a proxy could both
scale with input length - but it tells the owner **what to vary**.

## What the investigation could not do

| avenue | status |
|---|---|
| a provider-side request, outside the firewall | **not available to us, by design.** This is the escalation |
| streaming (incremental tokens = generated; a padded body delivered whole = not) | **closed.** The firewall refuses `stream: true` with 400, and `LlmClient` refuses to be constructed with it |
| a second model on the same firewall path | **inconclusive.** The alternate model returns 502 for `json_schema` at all - the inverted-capability finding from the 2026-08-25 probe - so it produces no comparable observation |
| `json_object` instead of `json_schema`, same model | ran, 3/3 terminating, **but on the reduced probe**, which no longer pads under `json_schema` either. It therefore separates nothing |

`PROVIDER_DECODER` and `FIREWALL_PROXY` remain **indistinguishable from here**, and
this document does not guess between them.

## Asked of the owner

1. Which component owns the constrained decoder for this deployment?
2. Can whitespace-after-completion be excluded from the grammar?
3. If not, is a server-side `finish_reason` for "complete document, padding" available?
4. **New:** does whitespace output scale with input length provider-side, on a
   request issued outside the firewall? A yes localises it to generation; a no
   localises it to the proxy. This is the one question that separates the two
   candidates, and only the owner can ask it.
5. **New:** is there a provider-side setting that bounds whitespace between tokens
   independently of `max_tokens`?

## Status

**Contained, not eliminated.** Any future statement that R-86 is fixed must cite a
change in the decoder, not a change in a prompt - and not a run in which it happened
not to fire. The Phase-15 evidence makes that stricter, not weaker: a short-prompt
arm that terminates is now known to prove nothing.
