# R-86 — final evidence package

**Status:** `VERIFIED_FAILURE` · `PROVIDER_SIDE` · root cause `NOT_ESTABLISHED` ·
`EVALUATION_BLOCKING`
**Sendable form:** `data/escalations/r86-provider-package.md` — self-contained, generated,
digest-only. **This document is the internal index onto the evidence; that one is what
leaves the building.**

---

## 1. Executive summary

A schema-constrained chat completion returns **HTTP 200** with a body that satisfies the
grammar and never closes the document. It emits ~190 non-whitespace characters, then
pads to the 1536-token ceiling, deterministically, at temperature 0.

The proxy between MEDAUTH and the provider is eliminated by the proxy owner's own
append-only records. Which component *inside* the provider is responsible is not
established and is not guessed at.

MEDAUTH's own behaviour under it is safe and proven: every occurrence routes to a human
and never becomes a recommendation.

## 2. The evidence matrix

| observation | evidence | layer | reproducible | owner known |
|---|---|---|---|---|
| HTTP 200 with an unterminated JSON body | `r86-reproducer-001` (sealed) | PROVIDER | **yes**, 18/18 | no |
| 1536 completion tokens = the exact ceiling; `finish_reason: length` | revalidation `20260825T155710Z` | PROVIDER | yes | no |
| 92.05% whitespace; ~190 non-whitespace characters | factorial + revalidation | PROVIDER | yes | no |
| Byte-identical across 18 observations, 3 runs, 2 days, temperature 0 | factorial, revalidation, perturbation | DECODER | yes | no |
| **Response identical on both sides of the proxy** (2389 == 2389, 1058 == 1058) | `r86-firewall-capture-001` | FIREWALL | yes | **yes — eliminated** |
| Proxy `decision=allow`, 4 detectors run, **0 detected**, no body mutation | firewall audit trail | FIREWALL | yes | **yes — eliminated** |
| Needs the **conjunction** of production schema + longer input + real clinical content | `r86-factorial-001` (6/6 vs 0/42) | PROVIDER | yes | no |
| Length alone reproduces nothing (0/56 up to 908 prompt tokens) | `r86-gradient-001` | — | yes | n/a — hypothesis withdrawn |
| A simpler schema terminates on the same content (`flat/*` 0/24) | factorial | PROVIDER | yes | no |
| Persists at temperature 0.2 (6/6); the one trial that escaped the whitespace pattern **still hit the ceiling** | `r86-temperature-perturbation-001` | DECODER | yes | no |
| MEDAUTH bounds it: ceiling, timeout, bounded repair, then `HUMAN_REVIEW` | slice + taxonomy tests | MEDAUTH | yes | **yes — ours, and safe** |

**Symptom-first attribution is refused.** The failure appears at MEDAUTH's boundary; it
is not MEDAUTH's, and the matrix says why for each row rather than assigning blame to
whichever layer noticed.

## 3. What is proven, layer by layer (Part B)

1. **Inside MEDAUTH — VERIFIED.** Bounded execution, safe failure, no definitive
   decision under any provider failure mode, correct classification as a *broken
   response path* rather than a wrong answer.
2. **About the firewall — VERIFIED (this reproducer only).** It did not alter the
   request or the response. Two independent measurements agree to the character.
3. **About the provider — the defect is upstream of the proxy, and no further.**
   Which component, and why, is `NOT_ESTABLISHED`.
4. **Unobservable from here — by design.** MEDAUTH sees one HTTP hop and holds no
   provider credential. Grammar state, EOS eligibility, token-level logits and the
   serving stack's identity are all invisible, and correctly so.
5. **What would distinguish decoder from proxy:** the firewall-side capture — and it
   has been run. `FIREWALL_PROXY` is eliminated. What would now distinguish components
   *within* the provider is a grammar/state trace or EOS eligibility at the point
   output stops progressing.
6. **Can MEDAUTH obtain it without bypassing the firewall?** **No.** That is the
   definition of the boundary, not a gap in it.

→ The remaining root-cause question is **`OUTSIDE_ENGINEERING_CONTROL`**.

## 4. Reproduction (Part C)

**No new calls were made in this phase, and that is the correct minimum.**

Part C asks for "the minimum safe reproduction necessary to confirm the existing
finding". The finding is already confirmed by **18 observations across three
independent runs on two days**, every one byte-identical at temperature 0. A fourth run
would spend model calls to re-derive a deterministic result.

It would also contradict the repository's own recorded constraint:
`r86-handoff-status.json` sets
`next_allowable_repository_action: REVALIDATE_AFTER_EXTERNAL_OWNER_RESPONSE`, and no
owner response has arrived. Running one now would be the repository ignoring a rule it
wrote for itself.

If behaviour ever differs, `scripts/r86_revalidate.py` writes a **new timestamped
report** and never overwrites an existing one.

## 5. Contrasting requests — the same system succeeding

| cell | completion tokens | non-whitespace | parsed | finish |
|---|---|---|---|---|
| `intake/gold_note/short` | 478 | 1098 | yes | `stop` |
| `intake/filler/long` | 1028 | 1994 | yes | `stop` |
| `flat/gold_note/long` | 23 | 36 | yes | `stop` |
| **`intake/gold_note/long`** | **1536** | **190** | **no** | **`length`** |

The failing cell produces **less** real content than any cell that succeeds. It did not
run out of room.

## 6. Safety disposition (Part D) — VERIFIED

```
R-86 → bounded execution → schema-invalid / provider failure
     → HUMAN_REVIEW → NO definitive recommendation
```

Proven across no-response, truncated, schema-invalid, timeout and retry-exhaustion. A
`403` is never retried — retrying a blocked request is an attempt to evade a security
control. `MODEL_WRONG` exists nowhere in the codebase: a broken response path is never
recorded as a bad answer.

**No failure mode produces `APPROVE_RECOMMENDED` or `DENY_RECOMMENDED`.** If one ever
does, that is a P0 and the run stops.

## 7. Evaluation-blocking rationale (Part E) — VERIFIED

```
rule       provider-failure-validity.v1     ceiling 0.10   (pre-registered, unchanged)
observed   6/12 = 0.5000                    worst cell intake/gold_note/long at 1.0
gate       BLOCKED
```

The threshold has not been edited, no exception exists, and there is no second
threshold. If a future observation falls at or below 0.10 the gate re-evaluates
**mechanically** — no judgement call, no new document.

## 8. What is required from the provider

One question:

> Why does the constrained decoder enter a non-terminating generation path **while the
> JSON document is still structurally incomplete**, allowing generation to continue
> until the completion limit is exhausted instead of reaching a valid terminal state?

Any **one** of these narrows it: a grammar/state trace for the failing request; EOS
eligibility at the point output stops progressing; the grammar state at termination
failure; a token-level decoder trace; the same for the `intake/filler/long` cell that
succeeds; the constrained-decoding implementation and runtime version; whether
speculative decoding participates.

**Not asked for:** anything about MEDAUTH's prompt or schema. This is not a request for
tuning advice.

## 9. Next revalidation procedure (Part G)

```bash
MEDAUTH_LIVE_MODEL=1 uv run python scripts/r86_revalidate.py --write
```

Verifies the live configuration against the seal field by field **before the first
call**; applies `provider-failure-validity.v1`; emits `PASS`, `FAIL` or `INCONCLUSIVE`;
writes a timestamped report that accumulates. It cannot change the threshold, cannot
touch a gold dataset, and cannot rewrite a historical report.

**Running the script does not make an evaluation runnable.**
`eval/official_gate.py` reads the *latest* revalidation, and only a `PASS` opens
anything. `FAIL` and `INCONCLUSIVE` block identically.

## 10. Excluded from this document

No credentials, no API key, no base URL, no model or host name, no clinical text, no raw
prompts or responses. Deployment identifiers appear only as salted digests, and a test
checks that against the **live** configuration rather than a hardcoded list.
