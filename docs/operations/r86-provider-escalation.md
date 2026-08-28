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

**Two further properties of the body, both load-bearing:**

- **~190 non-whitespace characters.** Less than any other `intake` cell in the factorial,
  and a sixth of what the passing short cell emits (1098) while terminating cleanly in 478
  tokens. The minimal document satisfying this schema is 110 characters compact. So it is
  not a long answer truncated by the ceiling — it is a nearly-empty one that never closed.
- **Byte-identical across trials.** Six trials in the factorial and six in the
  revalidation, taken hours apart at temperature 0, produced the same 1536 completion
  tokens, the same 2389 body characters and the same 0.9205 whitespace fraction every
  time. Whatever the decoder is doing, it does it identically on every attempt.

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

## 10b. The control boundary — evidenced, not asserted

Every earlier phase said MEDAUTH "cannot" reach the decoder. None of them showed it.
That distinction cost this project four phases once already: `FIREWALL_PROXY` was
treated as outside our control when the firewall was operated by the same team and its
append-only audit had been recording the answer the whole time. So the boundary is
established here by measurement.

### The chain, hop by hop

| hop | component | controllable from this environment? | evidence |
|---|---|---|---|
| 1 | MEDAUTH → gateway | **yes** | `MEDAUTH_LLM_BASE_URL` points at the locally-run gateway; this repository |
| 2 | gateway (LLM Firewall) | **yes, fully** | source tree, container and configuration all local and owned |
| 3 | gateway → provider | **configuration only** | `FIREWALL_UPSTREAM_BASE_URL` is an external `https://` endpoint; the value can be repointed, the service behind it cannot be changed |
| 4 | model / decoder / structured-output runtime | **no** | see below |

### Why hop 4 is closed, specifically

- **No administrative surface.** Through the sanctioned path, the model-info, runtime
  and admin paths all return `404`. `/v1/models` is not even proxied — the gateway
  answers `not_implemented`. There is no endpoint that reports a runtime
  version, a grammar backend, or a decoding configuration, let alone sets one.
- **No local alternative.** The reference machine has a single 4 GB GPU
  (RTX 3050 Laptop) and **zero** inference servers running — no vLLM, SGLang, TGI,
  llama.cpp or Ollama. OD-2 already records that this hardware cannot serve a useful
  model at the required context. Reproducing the decoder locally is not an option that
  was declined; it is one that does not exist.
- **Repointing the gateway is not a fix.** Sending the registered reproducer to a
  different model or runtime produces evidence about a different system.
  `docs/evaluation/r86-closure-gate.md` classifies that as `NEW_SYSTEM_CONFIGURATION`,
  and the acceptance note on the seal says closure requires the registered shape to
  succeed rather than a different shape to be substituted.

### The gateway is eliminated on the request path too

`r86-firewall-capture-001` eliminated the gateway for the **response**: 2389 characters
measured at the firewall and 2389 at MEDAUTH, `decision=allow`, four detectors, none
detecting. Two records on opposite sides of the proxy agreeing to the character.

The **request** path had not been shown the same way, and now is, by reading the
gateway's own source:

- `app/gateway/upstream.py::chat_completions(payload)` forwards with
  `self._client.post(..., json=payload)` — the payload dictionary, verbatim.
- The payload is **never mutated**: no assignment, `pop`, `update` or `del` against it
  anywhere in the chat route or the gateway.
- `response_format`, `json_schema`, `guided_*`, `strict`, `max_tokens` and
  `temperature` appear **nowhere** in the gateway or the chat route. The firewall has no
  structured-output handling to get wrong, because it has none at all.

So the registered request reaches the provider with its schema, strictness and decoding
parameters exactly as MEDAUTH constructed them, and the response returns unaltered. The
gateway is not a causal candidate on either path.

### What follows

**MEDAUTH cannot remediate this locally, and that is now a measured statement.** Every
remaining discriminator in §10 — decoder state, EOS eligibility, grammar state,
token-level trace, runtime version, speculative-decoding participation — lives behind
hop 4, and hop 4 exposes no surface that reports them and none that changes them.

This is not a request for access. MEDAUTH holds a revocable caller key scoped to one
gateway and holds no provider credential by design (ADR-016); it should not be given
one to satisfy this investigation.

*No host, address, model identifier or key appears anywhere in this document. It is an
outbound artefact, and `test_the_escalation_carries_no_secret_and_no_clinical_text`
reads the forbidden values from `Settings` and fails the build if one appears — which
is how the first draft of this section was caught carrying the gateway's address.*

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
