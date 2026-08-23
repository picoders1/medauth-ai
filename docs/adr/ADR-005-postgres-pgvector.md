# ADR-005: PostgreSQL + pgvector as the Only Datastore

**Status:** Accepted · **Date:** 2026-08-23 · **Phase:** Planning

## Context

The system stores relational data (policies, versions, code links, criteria trees, cases, verdicts,
citations, audit events) and vectors (policy chunk embeddings). The brief asks explicitly whether
PostgreSQL + pgvector is sufficient before introducing a separate vector database.

## Problem

One datastore or two?

## Options

| # | Option | Assessment |
|---|---|---|
| A | **PostgreSQL 16 + pgvector** | One system, one transaction domain, joins across relational and vector data. HNSW performance below purpose-built engines at large scale. |
| B | PostgreSQL + a dedicated vector DB (Qdrant, Weaviate, Milvus) | Better ANN at scale, richer vector features. Two systems, two consistency domains, a synchronisation problem. |
| C | PostgreSQL + an embedded index (FAISS, Chroma) | No extra service. Index lifecycle becomes application code; persistence, concurrency and migration are hand-rolled. |
| D | Managed vector service | No operations. Third-party egress for a healthcare system, and cost. |

## Decision

**Option A. PostgreSQL 16 + pgvector, HNSW index, host port 5435.** No separate vector database.

## Rationale

**Scale does not justify a second system.** CMS NCDs, LCDs and attached Articles for a bounded set
of procedures produce chunks in the thousands to low tens of thousands. Purpose-built vector engines
earn their operational cost in the millions-to-billions range. At this size, an HNSW index in
pgvector is comfortably adequate, and the difference is not the bottleneck — a per-criterion model
call is.

**The decisive argument is the query shape.** Every search in this system is scoped by a relational
predicate:

```sql
... WHERE policy_version_id = ANY(:resolved_versions)
ORDER BY embedding <=> :query_vector LIMIT :k
```

Retrieval is *always* filtered to the versions that resolution selected (ADR-004). That is a join,
and it belongs where the joined data lives. In an external vector store there are two options, both
worse: over-fetch and post-filter, which silently degrades recall exactly when the resolved set is
small; or duplicate policy metadata into the index and keep it synchronised, which creates a second
source of truth for applicability — the one thing in this system that must not have two.

**Transactional consistency across ingest.** Writing a policy version, its chunks, its embeddings
and its code links is one transaction. A partially-ingested policy version is not a state the system
can be in. Across two systems, it is.

**Operational weight is a real cost.** One database to back up, migrate, monitor and secure. The
audit trail — which has integrity requirements (ADR-013) — lives in the same place, under the same
grants.

**PostgreSQL 16 is already present** on the reference machine, and the sibling project uses the same
stack, so both repositories are operated identically.

## Consequences

**Positive.** One datastore, one backup, one migration path, one set of grants. Vector search joins
relational filters natively. Ingest is transactional. Alembic versions the whole schema including
the index. Local development is one container.

**Negative.** ANN performance is below purpose-built engines and will not scale to millions of
chunks without revisiting. HNSW build time grows with corpus size. pgvector offers fewer vector
features (no native multi-vector or sparse-dense hybrid). Embedding dimension is fixed in the column
type, so changing embedding model requires a migration — acceptable, since it also requires
re-embedding the corpus.

**Neutral.** Reranking is a cross-encoder in the application, not a database feature, so the
database is not asked to do what it is bad at.

## Conditions that would justify revisiting

Recorded now so the decision can be re-opened on evidence rather than on preference:

1. Corpus exceeds roughly one million chunks (multi-payer, multi-year).
2. Measured p95 vector search latency exceeds 20% of end-to-end case latency.
3. A requirement for hybrid sparse-dense retrieval that pgvector cannot express.
4. Read throughput requiring independent scaling of search from transactional workload.

None applies. Each would be measured, not assumed.

## Rejected alternatives

| Alternative | Rejected because |
|---|---|
| **B — dedicated vector DB** | Solves a scale problem this system does not have, while creating a synchronisation problem it would otherwise not have. Duplicating policy metadata into an index means two sources of truth for applicability. |
| **C — embedded index** | Moves index persistence, concurrency and migration into application code. Restart and multi-process behaviour become the application's problem, and the audit database is still needed anyway. |
| **D — managed service** | Third-party egress of policy embeddings for a healthcare system, plus cost and an external dependency, to solve a problem that does not exist at this scale. |
