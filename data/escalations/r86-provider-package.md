# A constrained-decoding request that never terminates

**To:** whoever owns the model serving stack for this deployment.
**From:** MEDAUTH engineering. **Our reference:** R-86.

This is self-contained. It contains no credential, no endpoint, no model name
and no patient data - your identifiers appear as digests you can match against
your own records.

We are **not** asking you to help us tune a prompt or a schema. We believe
there is a defect in constrained decoding and we are asking you to explain and
fix it. If we are wrong about that, the evidence below is what we are wrong
about, and we would like to know.

---

## 1. The question

> Why does the constrained decoder enter a non-terminating generation path
> **while the JSON document is still structurally incomplete**, allowing
> generation to continue until the completion limit is exhausted instead of
> reaching a valid terminal state?

## 2. The request, exactly

Frozen since 2026-08-25 and unchanged since. A defect that disappears when the
request is altered has been avoided, not fixed, so we have not altered it.

| | |
|---|---|
| endpoint | `POST /v1/chat/completions` |
| model | digest `sha256:31d69bc24c21367e` |
| caller key | digest `sha256:bec21976619c4fca` (salted; confirms "the key I issued") |
| `response_format` | `json_schema`, `strict: true` |
| schema | digest `sha256:a89278d7f1c9eba5` - Five sibling arrays of objects. Every array is legal when empty, so the grammar admits a complete document at any point - which is what makes 'the schema is satisfied' compatible with 'the document never closes'. |
| temperature | `0.0` |
| `max_tokens` | `1536` |
| `stream` | `false` |
| prompt tokens | 512 |
| attempts | 1 per observation, no client retries |

## 3. What we observe

Six trials, byte-identical at temperature 0, reproduced on two separate days:

```
finish_reason        length
completion_tokens    1536   (the ceiling, exactly)
body_chars           2389
whitespace_fraction  0.9205
non_whitespace       190 characters
parsed_as_json       false   <- the document never closes
```

**Three things follow, and they are why the question is worded as it is.**

**It is not running out of room.** It emits 190 non-whitespace characters -
*fewer than any other cell that succeeds*. It produces a little content, stops
producing content, and spends the remaining tokens on whitespace.

**The document never closes.** Trailing whitespace after a complete document
would still parse; this does not. So whitespace is being emitted while the
document is still **open**. For scale, the minimal document satisfying this
schema is 110 characters
(only `case_id` is required and every array is legal empty).

**It is deterministic.** Byte-identical across 12 observations in two runs on different days.

### The same schema succeeds elsewhere

| cell | completion tokens | body chars | whitespace | non-whitespace | parsed | finish |
|---|---|---|---|---|---|---|
| `flat/filler/long` | 23 | 51 | 17.6% | **42** | yes | `stop` |
| `flat/filler/short` | 22 | 44 | 20.4% | **35** | yes | `stop` |
| `flat/gold_note/long` | 23 | 45 | 20.0% | **36** | yes | `stop` |
| `flat/gold_note/short` | 22 | 41 | 21.9% | **32** | yes | `stop` |
| `intake/filler/long` | 1028 | 2764 | 27.9% | **1994** | yes | `stop` |
| `intake/filler/short` | 37 | 126 | 8.7% | **115** | yes | `stop` |
| `intake/gold_note/long` | 1536 | 2389 | 92.0% | **190** | **no** | `length` |
| `intake/gold_note/short` | 478 | 1211 | 9.3% | **1098** | yes | `stop` |

`flat/*` is a small schema; `intake/*` is the production one. The only cell
that fails is the production schema with real clinical content at the longer
end. **`intake/filler/long` is the one we would most like you to compare
against**: same schema, comparable length, a long whitespace stretch of its
own - and it closes.

## 4. What we have already eliminated, so you do not have to

### The proxy between us is not doing it

Our gateway's own append-only audit recorded, for the six failing calls:

| | at the proxy | as we received it |
|---|---|---|
| response characters | 2389 | 2389 |
| request characters | 1058 | 1058 |
| control response | 1211 | 1211 |

HTTP 200, decision `allow`, 4 content detectors executed and **0 detected** on every trial, so the only
body-mutating path in the proxy was never entered. Two independent
measurements on opposite sides of the hop agree **to the character**: the
response was already whitespace-dominated and unterminated when it arrived.

### Temperature is not the whole story either

We ran the identical request at temperature 0.2 - one changed field, everything else fixed:

- **6/6 still failed.**
- Five reproduced the greedy output byte-identically.
- **One escaped the whitespace pattern entirely** and *still* ran to the
  ceiling without closing.

That last trial is why we do not think this is fundamentally about whitespace.
The sampler left the whitespace path and termination did not follow.

### Hypotheses we have narrowed or retired

| hypothesis | state | why |
|---|---|---|
| grammar/whitespace handling after a structurally complete state | **NARROWED / NOT ESTABLISHED** | The failing responses remain structurally INCOMPLETE. |
| a greedy fixed point on a whitespace token at temperature 0 | **NARROWED / NOT ESTABLISHED** | r86-temperature-perturbation-001 trial 5 escaped the whitespace pattern entirely - 3316 non-whitespace characters at 13% whitespace - and STILL reached the ceiling without closing. |
| the answer was genuinely too long for the 1536-token ceiling | **RETIRED** | The failing cell produces 190 non-whitespace characters - LESS than any other intake cell, and a sixth of the 1098 produced by intake/gold_note/short which terminated cleanly in 478 tokens. |

**Standing statement:** The observed whitespace-heavy behavior is a manifestation of the non-termination/failure mode, not yet established as the underlying cause.

**What we do NOT claim.** We have no visibility into your stack and have not
guessed at it:

- the provider decoder is specifically identified
- a grammar bug is proven
- an EOS bug is proven
- a whitespace bug is proven
- a greedy-decoding bug is proven

## 5. Questions we cannot answer from outside

1. Does the decoder reach a valid grammar state from which EOS is legal?
2. If EOS is legal, why is it not selected or emitted?
3. If EOS is not legal, which grammar state prevents termination?
4. Does the decoder have an explicit terminal condition for JSON-schema completion?
5. Does whitespace consumption occur inside an **incomplete** grammar state?
6. Is there a decoder/runtime loop that can repeatedly consume non-structural tokens?
7. Why does the same schema terminate for the comparison request in §3?
8. Why does temperature perturbation change the surface form without restoring termination?
9. Is the behaviour tied to this decoder/runtime version?
10. Is constrained decoding a separate decoder path from unconstrained generation?

**Questions 1 and 2 are the pair we would pick** if you can only answer one
thing: *which grammar state, and was EOS legal there.*

## 6. Evidence that would settle it

**Any one of these narrows it substantially. We are not asking for all of them.**

| | evidence |
|---|---|
| 1 | decoder grammar/state trace for the failing request |
| 2 | EOS eligibility at the point output stops making progress |
| 3 | grammar state at termination failure |
| 4 | token-level decoder trace for the failing request |
| 5 | the same, for the comparison request that succeeds |
| 6 | constrained-decoding implementation and runtime version |
| 7 | whether speculative decoding or another specialised path participates |
| 8 | whether it reproduces outside our proxy (corroborates §4; lowest priority) |

## 7. What would let us close this

The **same** request, unchanged, succeeding: valid closed JSON, not stopped by
the completion ceiling, no whitespace runaway, across the registered trial
count, at or under our pre-registered failure ceiling of 0.1.

We will not move that ceiling and we will not reshape the request to make the
defect disappear.

**If your answer is "use a different model, version, runtime, schema, API mode
or temperature"** - that may well be the right engineering advice, and we will
consider it. But we will record it as a *different system*, with its own
baseline, not as a fix to this one. We would rather adopt your recommendation
honestly than close a defect that is still there.

**If you swap the stack behind the same model name**, please tell us. Our
configuration check hashes the model identifier we send, not what serves it, so
that change is invisible from here - and a pass we cannot attribute is a pass
we cannot use.

## 8. Impact, stated plainly

This blocks an evaluation on our side. It is not blocking anything of yours and
we are not asking for a priority. Every occurrence already fails safely for us -
it routes to a human reviewer and never becomes an automated recommendation - so
this is a correctness question, not an incident.
