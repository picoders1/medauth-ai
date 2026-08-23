# ADR-006: Section-Aware Chunking, Embedding and Reranking

**Status:** Accepted · **Amended in Phase 1 on evidence** - see [Amendment](#amendment-phase-1-retrieval-baseline)
**Date:** 2026-08-23 · **Phase:** Planning

## Context

Once policy resolution has established *which* policy versions apply (ADR-004), retrieval must find
the passages bearing on each criterion, inside a small and lexically homogeneous document set.

## Problem

Three sub-decisions: how to chunk, what to embed with, and whether reranking is worth its cost.

## Options

### Chunking

| # | Option | Assessment |
|---|---|---|
| A | Fixed-size with overlap | Simple, uniform. Ignores document structure. |
| B | **Section-aware, never crossing a section boundary** | Respects meaning. Variable sizes; oversized sections need splitting. |
| C | Semantic chunking by embedding similarity | Adaptive. Non-deterministic and hard to explain in a citation. |
| D | One chunk per criterion | Perfect alignment, but requires criteria before chunks, and criteria come from chunks. |

### Embedding / reranking

Candidates: general-purpose encoders (`bge-base-en-v1.5`, `e5-base-v2`, `all-MiniLM-L6-v2`),
biomedical encoders (PubMedBERT-derived), rerankers (`bge-reranker-base`,
`ms-marco-MiniLM-L-6-v2`), or a hosted embedding API.

## Decision

**Chunking: Option B, section-aware, never crossing a section boundary.** Oversized sections are
split with overlap *within* the section, and every part inherits the same `section_path`.

**Embedding: `BAAI/bge-base-en-v1.5` as the provisional default.** Local, in-process
`sentence-transformers`, CPU by default. It does **not** traverse the firewall.

**Reranking: `BAAI/bge-reranker-base` as the provisional default**, cross-encoder over ANN
candidates.

**Both model choices are defaults, not decisions.** Phase 1 builds a frozen retrieval evaluation set
and compares at least two candidates in each role. This ADR is amended with the measured basis, and
until then the word "best" is not used (OD-10).

## Rationale

### Why section-aware chunking is a safety property, not a quality tweak

Coverage policy is written so that the section *is* the unit of meaning: "Indications",
"Limitations", "Coverage Criteria", "Documentation Requirements". A chunk spanning the boundary
between Indications and Limitations can yield a citation that is **textually exact and semantically
inverted** — a quote that verifies perfectly while supporting the opposite of what the policy says.

That is the worst failure available to this system: the guardrail passes it, because span
verification is doing its job on a chunk that should never have existed. Chunking is therefore
upstream of the citation contract, and the boundary rule is asserted by test rather than left to
the chunker's judgement.

### Why reranking earns its cost here specifically

More than in general RAG. The candidate pool is small and homogeneous — within one LCD, many
sections share vocabulary almost entirely, and a bi-encoder separates them poorly. A cross-encoder
sees the criterion and the passage together, which is the distinction that matters.

The rerank score margin is also reused as a deterministic feature in the abstention gate
(ADR-011), so the reranker contributes to safety and not only to relevance.

### Why local rather than a hosted embedding API

Three reasons, in order: the firewall exposes no `/v1/embeddings`, so an API path would bypass the
security boundary the rest of the system routes through; embedding a policy corpus through a
security gateway would inspect nothing meaningful anyway; and a hosted API adds egress and cost for
a workload that runs comfortably on CPU. The 4 GB GPU on the reference machine can host a base-size
encoder with no contention, since no generative model runs locally.

### Why the model choices stay provisional

Coverage policy is a narrow, templated, jargon-dense domain. General-purpose retrieval benchmarks
do not obviously transfer, and biomedical encoders are trained on clinical literature rather than
regulatory prose — neither is clearly right in advance. Asserting a choice without measuring it
would be exactly the kind of claim this project refuses to make.

## Consequences

**Positive.** Citations name a real section, which is what makes them checkable. Reranking improves
separation within a homogeneous set and feeds the abstention gate. Local inference means no egress
and no per-query cost. The embedding dimension (768) is fixed in the schema, which is honest about
the migration cost of changing model.

**Negative.** Variable chunk sizes complicate token budgeting for the adjudication context. Section
detection must handle CMS layout variation and fail loudly when it cannot. Cross-encoder reranking
adds latency per criterion. Changing the embedding model requires a migration and full re-embedding.

**Neutral.** Chunk count per policy version is higher than fixed-size chunking would produce, which
matters not at all at this corpus size.

## Rejected alternatives

| Alternative | Rejected because |
|---|---|
| **A — fixed-size chunking** | Produces boundary-crossing chunks, enabling a citation that verifies while inverting the policy's meaning. |
| **C — semantic chunking** | Non-deterministic boundaries mean a citation's `section_path` is a model artefact rather than a document fact, weakening the citation contract. |
| **D — one chunk per criterion** | Circular: criteria are extracted from chunks (ADR-007). |
| **Hosted embedding API** | Bypasses the firewall boundary, adds egress and cost, and solves nothing that local inference does not. |
| **Skipping reranking** | The candidate pool is homogeneous, which is the case where bi-encoder ranking is weakest — and it would remove a deterministic abstention feature. |
| **Hybrid BM25 + dense** | Plausible and reconsidered if Phase 1 shows lexical matching helps on code-heavy passages. Not adopted before measurement. |

---

## Amendment: Phase 1 retrieval baseline

Measured against the frozen retrieval set; the artefact is the `retrieval-baseline`
report under `eval/reports/`. Two of this ADR's positions survive and one does not.

### Chunking: confirmed, and it found two defects

Section-aware chunking held, and building it surfaced two failures this ADR had not
anticipated:

* **Wrapped prose reads as a heading.** The first structure detector matched headings
  lexically and filled the section tree with body text, because a thirteen-word wrapped
  sentence satisfies every lexical test for a heading. Local headings now require
  *structural* evidence - a preceding blank line and following content (R-34).
* **Some sections cannot be split at a sentence boundary.** Enumerations and code tables
  carry no terminal punctuation, and produced a chunk wider than the encoder's context,
  silently truncated at embedding time. A word-boundary split is now the last resort,
  never mid-word (R-35).

### Encoder: the default stands, but not because it is best

Two encoders were compared. `bge-base-en-v1.5` led on recall@1, but at n=11 every arm's
interval overlaps every other and paired exact McNemar does not distinguish them. The
default therefore stands as **adequate and unrefuted**. The word "best" is still not
used, and OD-10 is closed on that basis rather than on a demonstrated ordering.

`bge-small-en-v1.5` emits 384 dimensions. Adopting it is a migration plus a full
re-embed, not a configuration change.

### Reranking: the argument in this ADR is **not supported** by the measurement

This ADR argued that reranking "earns its cost here specifically", because sections
within one determination share almost all their vocabulary and a bi-encoder separates
them poorly.

**Reranking reduced recall@1 for both encoders.** Recall@5 was unaffected, so the
reranker is not losing the correct section - it is demoting it. On this corpus the
bi-encoder already separates the sections, and the cross-encoder appears to reward
passages that restate the question's wording over the one that answers it.

Consequences, recorded rather than tuned away:

1. **The claim that reranking earns its cost is withdrawn** until it is measured on a
   corpus where this ADR's premise - long, repetitive, lexically similar sections -
   actually holds. The constructed corpus does not have that property, so the result
   does not refute the argument either; it leaves it unevidenced.
2. **The shipped default is unchanged.** Switching it on 11 questions whose intervals
   all overlap would be tuning on noise, and the constructed corpus is the wrong
   evidence for a decision about real policy prose.
3. `rerank_margin` remains available as an abstention feature (ADR-011), but its value
   is now explicitly unmeasured.

### What the amendment does not establish

Nothing about real CMS prose. The corpus is CMS-*shaped* (R-33), and the claim that
these figures transfer is refused.

---

## Amendment 2: Phase 2B, measured on the authoritative corpus

Re-measured against real 42 CFR with a corrected nDCG (the earlier implementation
assumed one relevant chunk per query and returned values above 1.0, which is
impossible - a target *section* spans several chunks).

| encoder | no reranker | `bge-reranker-base` | `ms-marco-MiniLM-L-6-v2` |
|---|---|---|---|
| `bge-base-en-v1.5` | 0.7619 | **0.5714** | **0.8095** |
| `bge-small-en-v1.5` | 0.7143 | **0.5714** | **0.8095** |

Recall@1, n=21, resolution accuracy 1.0000 [0.8454, 1.0000].

### The earlier finding was too broad and is corrected

Amendment 1 recorded that "reranking reduced recall@1 for both encoders" and
withdrew this ADR's claim that reranking earns its cost. On the authoritative
corpus that statement is **wrong as a general claim about reranking**:

* `bge-reranker-base` **hurts** - 0.5714 against a 0.7619 baseline, consistent
  across both encoders and consistent with the earlier corpus.
* `ms-marco-MiniLM-L-6-v2` **helps** - 0.8095, above baseline on both encoders.

So the effect is a property of the *specific reranker*, not of reranking. The
earlier measurement was not wrong; the generalisation drawn from it was.

### What is still not claimed

At n=21 the intervals overlap heavily: `none` [0.5491, 0.8937] against `ms-marco`
[0.6000, 0.9233]. **No configuration change is made on this evidence.** Switching
the shipped default on twenty-one questions whose intervals overlap would be tuning
on noise, which is the failure this project's evaluation discipline exists to
prevent.

What the measurement does establish is narrower and worth having: **a reranker can
actively degrade retrieval on this corpus**, and `bge-reranker-base` does. That is
a reason to measure any reranker before shipping it, not a reason to ship a
different one now.

Recall@3 is identical (0.9524) across every arm, and recall@5 differs only for
`bge-reranker-base`. The rerankers are reordering the top of a list that already
contains the answer.
