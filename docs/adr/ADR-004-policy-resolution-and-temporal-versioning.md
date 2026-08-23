# ADR-004: Deterministic Policy Resolution and Temporal Versioning

**Status:** Accepted · **Date:** 2026-08-23 · **Phase:** Planning
**Not in the original brief.** Added because it addresses the largest grounding risk in this domain.

## Context

The brief specifies a single "Policy Retrieval" stage doing retrieval, reranking and citation
metadata. That conflates two operations with different natures:

1. **Which policy applies?** — a question of procedure code, diagnosis codes, jurisdiction and date
   of service.
2. **What does it say about this criterion?** — a question of semantic relevance within a document.

## Problem

A pure semantic search over the whole corpus always returns *something*. For a knee-MRI case the
top result will be a plausible, well-written, confidently-citable imaging policy — which may be the
wrong Medicare Administrative Contractor's jurisdiction, or a version retired before the date of
service.

The system then reasons impeccably over the wrong document and produces a fully-cited wrong answer.

**Citations do not protect against this.** The citations are genuine. The quotes verify. The
metadata is consistent. The policy simply does not apply. A human spot-checking citations will pass
it, which makes this the most dangerous failure mode available to a RAG system in this domain — and
it is invisible to every grounding metric.

Compounding it: policy is temporal. A version selected as "latest" rather than "in force on the
date of service" is silently wrong in the same undetectable way.

## Options

| # | Option | Assessment |
|---|---|---|
| A | Semantic search over the whole corpus | Simple. Applicability determined by cosine similarity, which does not encode jurisdiction or dates. |
| B | Semantic search with metadata post-filtering | Better, but the candidate pool is still selected by similarity — the applicable policy may not be in the top *k* at all. |
| C | **Deterministic resolution first; semantic search scoped inside the result** | Applicability by rules, relevance by similarity. Each mechanism does what it is good at. |
| D | Model-based policy selection | An LLM choosing the applicable policy from candidates. Adds a model call at the point where determinism is most valuable. |

## Decision

**Option C**, with temporal correctness first-class.

```
(procedure code, diagnosis codes, jurisdiction, date of service)
        │  SQL over policy_code_links — no embeddings, no model
        ▼
   applicable policy VERSIONS
        │  0 → NEEDS_INFO       conflicting → HUMAN_REVIEW
        ▼  semantic retrieval scoped INSIDE the resolved set only
   evidence
```

- `policy_code_links(policy_version_id, code, code_system, link_type)` is the resolution index — a
  plain table with a plain index.
- Every `policy_version` carries `effective_date`, `end_date`, `revision_id`, `superseded_by`.
  Selection is by **date of service**, never "latest".
- Retrieval applies the **same** temporal predicate, so an out-of-scope chunk cannot enter an
  evidence set even if it is the best semantic match.
- Zero resolved versions ⇒ `NEEDS_INFO`, **never a denial** (ADR-010, row 1).
- An NCD and an LCD both applying is normal: the NCD governs, the LCD may add detail, both are
  recorded. Two LCDs with incompatible criteria is a genuine conflict ⇒ `HUMAN_REVIEW`.

Four temporal tests are mandatory in Phase 1: date of service before `effective_date` does not
resolve; after `end_date` resolves to the version in force *then*; a corpus refresh does not change
a historical case's resolution; retrieval never returns a chunk outside the resolved set.

## Rationale

**Applicability is a rule, so it should be evaluated by rules.** Jurisdiction and effective dates
are facts in the data, not similarities in an embedding space. Encoding them as a query makes
resolution reproducible, explainable to a reviewer ("this policy applies because code 27447 is
listed as a covered procedure in L34567 revision 4, effective from 2023-03-15, jurisdiction J6"),
and diffable when the corpus is refreshed.

**It makes the dangerous failure impossible rather than unlikely.** Retrieval cannot select an
inapplicable policy because retrieval never sees one.

**It is also the strongest defence against retrieval manipulation** (T-07): crafted note text
cannot steer applicability, because applicability does not read the note text — it reads codes,
jurisdiction and a date.

**Semantic search then does what it is genuinely good at**: finding the relevant passage inside a
document set whose applicability is already established.

## Consequences

**Positive.** Applicability is reproducible and explainable. Temporal correctness is enforced, not
hoped for. The wrong-policy failure mode is structurally excluded. Resolution accuracy is measurable
separately from retrieval quality, so the two failure kinds are diagnosed and fixed separately.
Payer-agnosticism becomes real: applicability rules are rows, not code.

**Negative.** The resolution index must be built and maintained per policy version, which is
ingestion work. If a code linkage is missing, the case resolves to nothing and routes to
`NEEDS_INFO` — a false negative that looks like missing policy. This is the correct direction to
fail, and index completeness becomes a Phase 1 quality measure. Cases whose procedure is not in the
corpus can never be adjudicated, which is honest but limits coverage.

**Neutral.** `NEEDS_INFO` will be more frequent than a similarity-only system's confident answers.
That is the system working, not underperforming, and the evaluation reports coverage explicitly so
the trade is visible.

## Rejected alternatives

| Alternative | Rejected because |
|---|---|
| **A — global semantic search** | Cannot encode jurisdiction or effective dates. Produces confident, well-cited answers from inapplicable policies — the worst failure mode here. |
| **B — post-filtering** | The candidate pool is still similarity-selected, so the applicable policy may not appear in the top *k*. Filtering an already-wrong pool does not fix it. |
| **D — model-based selection** | Introduces a model at the one point where reproducibility is most valuable, and makes "why did this policy apply?" an unauditable answer. It would also be steerable by note content, reopening T-07. |
| **Resolve by procedure code only** | Ignores jurisdiction and date of service, which are exactly the two dimensions that make coverage policy non-trivial. |
