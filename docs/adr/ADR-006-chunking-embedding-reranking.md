# ADR-006: Section-Aware Chunking, Embedding and Reranking

**Status:** Accepted (model selections **provisional**, pending Phase 1 measurement)
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
