# ADR-016: LLM Firewall Integration and RAG-Injection Containment

**Status:** Accepted · **Date:** 2026-08-23 · **Phase:** Planning
**Sibling project:** a separate local repository

## Context

An existing release-candidate OpenAI-compatible security gateway is available. The brief proposes it
become MEDAUTH's security layer, reached through a bespoke `LLM Gateway Interface` abstraction, and
integrated in a late phase.

## Problem

1. What abstraction sits between MEDAUTH and the firewall?
2. When is it integrated?
3. **What does the firewall actually protect, given that MEDAUTH is a RAG application?**

## Options

### Abstraction

| # | Option | Assessment |
|---|---|---|
| A | A bespoke `LLMGateway` interface with adapters | Provider-agnostic in principle. Adds a layer whose only job is converting a standard contract into a private one. |
| B | **OpenAI-compatible client with a configurable `base_url`** | The abstraction already exists in the protocol. |

### Timing

| # | Option | Assessment |
|---|---|---|
| C | Integrate in Phase 7, as the brief proposes | Simpler early phases. The `403`/`503` paths get retrofitted into a built decision graph. |
| D | **Integrate from Phase 1** | Configuration change plus designed-in failure paths. |

## Decision

**B and D.** The abstraction is `base_url`; integration is from Phase 1.

```
MEDAUTH ──(caller key)──▶ llm-firewall :8005/v1 ──(provider key)──▶ OpenAI-compatible provider
```

- The provider credential is held by the **firewall**. MEDAUTH holds only a revocable caller key.
  **MEDAUTH holds no model-provider credential at all.**
- `403` is **never retried** — retrying a blocked request is an attempt to evade a security control.
- `403`, `503`, timeouts and unreachability all route the case to `HUMAN_REVIEW` via row 4 of the
  decision table. Fail closed means **fail toward the human, never toward a denial.**
- Streaming is never requested; the firewall refuses it (`400`) and schema-validated output makes it
  meaningless here.
- Embeddings do **not** traverse the firewall — it exposes no `/v1/embeddings`, and inspecting a
  corpus embedding request would serve no security purpose.
- `X-Medauth-Request-Id` correlates the two independent audit trails without either storing the
  other's data.

## The central finding

**The firewall does not protect MEDAUTH's primary attack surface, and MEDAUTH does not pretend it
does.** From the firewall's own committed evidence:

| Measurement | Value | Source |
|---|---|---|
| Indirect-injection recall | **0.1423** (n=520) | `eval/results/20260817T130736Z__indirect-delivery-shape/report.md` |
| Recall on *planted* content | 0.0938 (n=480) | same |
| Recall on *user-requested* content | 0.7250 (n=40) | same |
| Baseline through-socket recall | 0.4706 | R-102 |
| "The firewall protects RAG applications" | **claim refused** | `docs/22-evidence-and-claims.md` |

The detector classifies **the user's turn**. MEDAUTH's threat is content the user never wrote — a
poisoned passage inside a retrieved policy chunk. That is exactly the 0.0938 case.

**Therefore containment is MEDAUTH's own responsibility and is structural** (ADR-010): fenced
delivery, closed output schemas with no decision token, span-verified quotes, a decision computed by
code, per-criterion isolation, and corpus content hashing. These hold whether or not the injection
is detected — which matters, because usually it will not be.

## Rationale

**The bespoke interface is rejected because the firewall *is* the OpenAI API** — that is its entire
adoption argument (its ADR-004). Wrapping a standard contract in a private one adds a translation
layer and a second thing to keep in sync on every provider feature, to obtain portability the
protocol already provides: vLLM, Ollama, Together, Groq and OpenRouter all speak it. Switching
endpoints, including to a bare provider for a controlled comparison, is a configuration change.

**Early integration because a `403` changes control flow.** A blocked model call is not an error to
be retried; it is a case that must reach a human. Discovering that in Phase 7, after the decision
graph is built and the truth table written, means retrofitting a terminal state into finished logic.
Building it in from Phase 1 costs nothing and makes row 4 real from the start.

**Credential placement is a genuine security gain**, not an accident of topology. The firewall's
ADR-024 establishes that a caller's credential never becomes the gateway's. Sitting on the correct
side means compromising MEDAUTH yields a revocable caller key scoped to one gateway, not provider
access.

**Naming what the firewall does not do is the point of this ADR.** The easy version of this
integration claims "all model calls pass through a security firewall" and stops. That sentence is
true and, for a RAG system, misleading. The honest version states which threat class it covers
(caller-turn injection, its strongest measured case) and which it does not.

## Consequences

**Positive.** Every model call is screened, rate-limited and independently audited. No provider
credential in MEDAUTH. Provider portability for free. Fail-closed semantics designed in rather than
retrofitted. Two independent audit trails, joinable by request id.

**Negative.** A runtime dependency on a separately-deployed service — mitigated by an advisory
readiness check, so a firewall outage stops new recommendations without taking the reviewer console
down. Firewall false positives on clinical text would block legitimate cases (R-19), measured from
Phase 0. Additional latency per call. Local development needs the firewall running.

**Neutral.** MEDAUTH is the firewall's first real RAG consumer. Interesting, and not evidence of
anything until measured.

## Provenance signalling

MEDAUTH marks retrieved content as untrusted using the firewall's ADR-017 capability. That capability
**ships off and uncalibrated** there (its OD-3), so MEDAUTH treats it as defence-in-depth and **not**
as a control it relies on or claims. Enabling it would require a calibrated threshold and an ADR in
the firewall repository first.

## Rejected alternatives

| Alternative | Rejected because |
|---|---|
| **A — bespoke `LLMGateway` interface** | Converts a standard contract into a private one to obtain portability the standard already provides. |
| **C — integrate in Phase 7** | Retrofits terminal states into a finished decision graph and truth table. |
| **Direct provider access, no firewall** | Forfeits screening, credential isolation and an independent audit for no gain. |
| **Relying on the firewall for RAG injection defence** | Contradicted by its own committed evidence. Would be an unearned safety claim of exactly the kind both projects refuse. |
