# ADR-009: Evidence and Citation Contract

**Status:** Accepted · **Date:** 2026-08-23 · **Phase:** Planning

## Context

The governing invariant is *no evidence → no decision*. That is enforceable only if "evidence" has a
definition a machine can check. A citation that cannot be verified is decoration, and decoration is
worse than nothing here because it produces unwarranted confidence in a reviewer.

## Problem

What must a citation contain, how is it verified, and what happens when verification fails?

## Options

| # | Option | Assessment |
|---|---|---|
| A | Free-text citation ("per LCD L34567") | Human-readable, unverifiable. |
| B | Chunk id only | Verifiable existence; does not prove the chunk says what the verdict claims. |
| C | **Chunk id + exact quote + claimed metadata, all deterministically verified** | Fully checkable. Rejects fluent near-misses. |
| D | Option C plus an LLM faithfulness judge as the gate | Catches semantic drift; the gate becomes unverifiable again. |

## Decision

**Option C**, with an LLM faithfulness check permitted only as an **advisory** signal.

### The contract

| Field | Source | Verification |
|---|---|---|
| `chunk_id` | model | exists **and** was in this criterion's evidence set |
| `quote` | model | exact normalized substring of `chunk.text` |
| `policy_id` | model | matches the chunk's stored value |
| `policy_version` | model | matches the chunk's stored value |
| `section_path` | model | matches the chunk's stored value |
| `page` | model | within `[chunk.page_from, chunk.page_to]` |
| `document_title` | **derived** | joined from `policy_versions` |
| `effective_date` | **derived** | joined from `policy_versions` |
| `source_url` | **derived** | joined from `policy_documents` |

**Derived fields are never accepted from the model.** They are joined at validation time. A model
cannot fabricate a source URL because it is never asked for one — the field is not in its schema.

### Failure semantics

> **Any citation failing any check ⇒ `NO_DECISION` for the case.**

Not a warning. Not a lowered confidence score. Not a dropped citation with the verdict retained.
The case stops and goes to a human, and the specific failure is recorded.

### Normalization

Span matching normalizes whitespace runs and Unicode confusables, reusing `app/core/normalize`
(the approach of the firewall's ADR-010). This matters in both directions: a quote cosmetically
altered to smuggle in different meaning must fail, and a quote differing only in whitespace from a
PDF extraction must pass.

## Rationale

**Exact quotes make hallucination mechanically detectable.** A model that invents supporting text
produces a string that is not in the chunk, and that is a substring test, not a judgement.

**Metadata agreement catches the failure a quote check misses.** A real quote attributed to the
wrong policy, version, section or page is *more* dangerous than a fabricated one, because a human
spot-check reads the quote, finds it plausible, and passes it. Tracked as its own metric —
citation misattribution rate — precisely because it is the failure most likely to survive review.

**Evidence-set membership closes a subtle hole.** Without it, a model could cite a real chunk from a
different criterion's evidence — a citation that passes existence, span and metadata checks while
being unrelated to the criterion it supports.

**Deriving fields rather than requesting them removes a fabrication surface entirely**, which is
strictly better than verifying a field the model was invited to invent.

**Hard failure is the only setting consistent with the invariant.** A system that downgrades
confidence on an invalid citation still issues a decision on unverified evidence. `NO_DECISION` is a
first-class outcome with its own rendering and its own audit row, so failing this way costs a
reviewer's attention, not a silent error.

**Why the faithfulness judge is advisory only.** Semantic drift — a verdict not entailed by a
correctly-quoted passage — is real and deterministic checks miss it. But a model deciding whether to
release a decision is a model controlling the decision, which is ADR-001 Option A through a side
door. So the check may **withhold**, never **release**. A guardrail that can upgrade a decision is
not a guardrail.

## Consequences

**Positive.** Hallucinated and misattributed citations are caught deterministically, with no model
and no network. Every claim is traceable to source text a reviewer can open. Citation validity is a
measurable rate and a hard feature of the abstention gate. The contract is testable adversarially
with forged fixtures.

**Negative.** Strict matching will produce `NO_DECISION` on near-misses — a model quoting accurately
in substance but not verbatim. This is expected, is measured as citation validity rate in Phase 5,
and is addressed by fixing normalization or prompting, **never by loosening the contract** (R-10).
Exact quotes cost output tokens. Multi-chunk reasoning is harder to express, since each claim must
tie to a specific span.

**Neutral.** Coverage will be lower than a system that accepts unverified citations. That is the
trade being made deliberately, and evaluation reports it.

## Rejected alternatives

| Alternative | Rejected because |
|---|---|
| **A — free-text citations** | Unverifiable. Produces the appearance of grounding without the substance, which is worse than no citation at all. |
| **B — chunk id only** | Proves a chunk was retrieved, not that it supports the verdict. The most common real failure — confident claims about a genuinely retrieved passage — passes unnoticed. |
| **D — LLM judge as the gate** | Replaces a deterministic check with an unverifiable one at the exact point where verifiability matters most. Retained as advisory. |
| **Fuzzy / semantic quote matching** | Defeats the purpose. The value of an exact match is that it cannot be argued with. A similarity threshold is a knob that will be loosened under pressure. |
| **Invalid citation ⇒ drop the citation, keep the verdict** | Issues a decision on evidence known to be unverified. Directly contradicts the invariant. |
