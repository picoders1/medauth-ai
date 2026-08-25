# R-86 — escalation to the provider / firewall owner

**To:** whoever owns the model provider or the LLM Firewall for this deployment.
**From:** MEDAUTH engineering. **Risk:** R-86.
**Canonical evidence:** `data/escalations/r86-reproducer.manifest.json`
(`r86-reproducer-001`, seal `sha256:271127edace3d94d`).

---

## 1. Problem statement

A schema-constrained chat completion returns **HTTP 200** with a body that satisfies
the grammar and **never closes the document**. It emits a short prefix of real JSON,
then pads with whitespace until the token ceiling.

JSON permits arbitrary whitespace between tokens, so a constrained decoder can
satisfy the schema indefinitely. **The grammar guarantees the output's shape; it does
not guarantee the output ends.**

This blocks MEDAUTH's official evaluation. It is not blocking anything of yours, and
we are not asking for a priority — we are asking one question we cannot answer from
where we sit.

## 2. Exact failing request shape

| | |
|---|---|
| reproducer cell | **`intake/gold_note/long`** — the identifier used by the sealed manifest, the revalidation script and the gate, so a result can be cross-referenced against this document |
| endpoint | `POST /v1/chat/completions` through the firewall, one caller key |
| model | digest `sha256:31d69bc24c21367e` (the configured structured-output model) |
| caller key id | `sha256:bec21976619c4fca` — a digest salted with the firewall base URL, so you can confirm "the key I issued" without the key crossing anything |
| `response_format` | `json_schema`, `strict: true`, schema digest `sha256:a89278d7f1c9eba5` |
| schema shape | `IntakeExtraction` — **five sibling arrays of objects**, each legal when empty |
| messages | `system` (instructions), `user` (fenced clinical note). Two turns, strict alternation |
| temperature | `0.0` |
| `max_tokens` | `1536` |
| `stream` | `false` |
| prompt tokens | **512** |
| attempts | 1 per observation (no client retries in the reproducer) |

The schema shape matters: every array is legal when empty, so the grammar admits a
complete document at *any* point. "The schema is satisfied" and "the document never
closes" are compatible states, and that is the heart of it.

## 3. Exact observed response behaviour

```
finish_reason      length
completion_tokens  1536   (= the ceiling)
whitespace         0.9205 of the body
body               2389 characters
parses as JSON     no  — the document is never closed
classification     SCHEMA_GRAMMAR_FAILURE
latency            ~6.5 s median
```

## 4. Reproduction frequency

**6 of 6.** Two independent runs on different days (Phase 16 and Phase 17), same
result both times, under conditions verified field by field as unchanged.

## 5. Determinism evidence

At `temperature: 0.0`, all six trials returned the **identical** completion-token
count, whitespace fraction and body length. This is a deterministic reproducer, not
an intermittent — you should be able to trigger it on demand.

## 6. What has already been ruled out

Each from a controlled experiment, not from inspection:

| candidate | evidence |
|---|---|
| **request shape** | identical bodies differing only in *content* succeed — see §7 |
| **model configuration** | `temperature`, `max_tokens`, `stream` identical across passing and failing arms |
| **timeout handling** | our timeout is never reached; the token ceiling is |
| **input length alone** | a seven-band sweep, **0 failures in 56 observations**, up to **908** prompt tokens on a two-field schema |
| **schema shape alone** | the same production schema with synthetic filler: **0 failures in 24** |
| **intermittency** | 6/6 identical responses at temperature 0 |

## 7. The contrast that localises it

Two cells from the same registered matrix, same model, same transport, same day:

```
intake schema + synthetic filler   522 prompt tokens   0/6 failures
intake schema + clinical note      512 prompt tokens   6/6 failures
```

**Ten *more* prompt tokens of filler succeed where clinical text fails.** The
production schema, a longer input and real clinical content are all required
together; no single factor reproduces it.

## 8. What remains ambiguous — and it is the only thing we need

**Which layer produces the non-terminating response.** MEDAUTH observes exactly one
hop: we hold a revocable caller key, no provider credential, and no direct path. A
decoder that pads and a proxy that pads are indistinguishable from here.

We have **not** attributed this to either component and will not without evidence.

## 9. The question

> **Under the registered production request shape, which layer is producing the
> non-terminating / whitespace-dominated structured response: the provider decoder or
> the firewall / proxy path?**

## 10. What would answer it (owner-side only)

We are not asking you to run anything on our behalf, and we have not attempted any of
these — each requires access we correctly do not have.

1. **Direct provider observation** — the same model, schema and ceiling, issued
   outside the firewall. If it pads there, the proxy is exonerated.
2. **Firewall-side upstream capture** — the request as forwarded and the response as
   received, before any proxy transformation. Within your own access controls.
3. **`finish_reason` before proxy transformation** — is `length` set upstream, or
   applied by the proxy?
4. **Response body size before and after the proxy** — a size that grows across the
   hop points one way; a size that matches points the other.
5. **Provider-side request/response identifiers** for a correlated trace — ours is
   half a trace without yours.
6. **Constrained-decoder logs**, if the serving stack exposes them: does the grammar
   admit whitespace after a structurally complete document?

**One and two are decisive on their own.** The rest narrow it.

> ### Update, 2026-08-25 — check 2 has been run, and it answers the question
>
> The firewall owner ran the upstream capture. The firewall received **2389 characters**
> of completion content from the provider, `decision=allow`, four detectors run and
> **none detecting** — so neither the outbound request nor the returned body was
> altered. MEDAUTH measured that same response at `body_chars` 2389 and 92.05%
> whitespace. **Two independent records, opposite sides of the proxy, agreeing to the
> character.**
>
> **The proxy is exonerated.** Attribution is `PROVIDER_SIDE`; `FIREWALL_PROXY` is
> eliminated. Checks 1, 3, 4 and 5 exist to separate the two layers and are no longer
> needed. Evidence: `data/escalations/r86-firewall-capture.json`, method in
> [r86-firewall-capture.md](r86-firewall-capture.md).
>
> **This document is therefore now addressed to the model provider**, and one question
> remains — check 6:
>
> > Does the constrained decoder's grammar admit whitespace after a structurally
> > complete document?
>
> Nothing about this lifts the block. The defect reproduces 6/6 and the gate still
> reads 6/12 = 0.5000 against the pre-registered ceiling of 0.10.

## 11. Acceptance criterion for closure

R-86 is closed when the **registered production shape** — unchanged schema, prompt,
content shape, temperature and ceiling — satisfies all of:

- returns a valid, closed, schema-conformant document;
- no runaway whitespace;
- no `finish_reason: length` truncation;
- reproduces across the registered trial count (6 per cell, both production cells);
- meets the pre-registered failure threshold of **0.10**.

Run by us with `scripts/r86_revalidate.py`, which verifies the configuration against
the seal before making a call.

**The threshold will not be adjusted to match observed behaviour, and the request
shape will not be changed to avoid the defect.** Either would close the risk on paper
and leave the system unable to run an evaluation.

## 12. What we would also accept

A statement that the behaviour is expected and bounded, with the bound — for example
a documented guarantee that whitespace after a structurally complete document is
excluded from the grammar, or a server-side `finish_reason` distinguishing "complete
document, padding" from ordinary truncation. We can work with a documented limit. We
cannot work with an unbounded one.

## 13. What we are not asking for

- Not a fix on any timeline.
- Not an admission of fault — the attribution is genuinely open.
- Not access we do not already have. **MEDAUTH will not bypass the firewall**, and no
  part of this investigation has.
