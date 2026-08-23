# Retrieval Evaluation Dataset

**Version 3 · 23 queries · built against the authoritative 42 CFR corpus.**

`eval/datasets/retrieval/questions.yaml`

---

## 1. What it measures, and why separately

Retrieval is evaluated apart from decision quality because the two fail differently
and are fixed differently. A resolution error is a rule or data defect; a ranking
error is a model defect *within* a correctly-scoped set. Folding them into one
number lets a corpus gap masquerade as an encoder problem.

Each query records:

| Field | Purpose |
|---|---|
| `text` | The query, in a reviewer's phrasing |
| `procedure_code`, `code_system` | Drives deterministic resolution |
| `as_of` | Date of service - selects the governing revision |
| `expect.policy_id`, `expect.revision_id` | Which version should resolve |
| `expect.section_path` | Which section answers it |
| `expect.criterion_id` | **Which policy requirement it targets** |

The criterion link is what lets a retrieval failure be attributed to a specific
requirement rather than to "the corpus". It is verified against
`data/criteria/inventory.jsonl` by test, so renaming a criterion breaks the build
instead of silently invalidating the set.

---

## 2. Two design decisions that carry the set

### Queries are not copies of their targets

Query text is hand-authored in the phrasing a reviewer would actually use:

> criterion: *"face-to-face encounter with the beneficiary within the 6 months preceding"*
> query: *"How recently must the doctor have seen the patient in person?"*

A query lifted from the criterion it targets makes retrieval look excellent and
measures string matching. A test asserts that content-word overlap between query and
authoritative text stays below 0.6, and it has already caught one query that was
effectively a copy.

### Chunk ids are deliberately not pinned

Truth is recorded as a `(policy, revision, section, criterion)` tuple. Chunk ids
change whenever chunking changes; pinning them would make the evaluation measure the
chunker against itself, and any chunking improvement would look like a regression.

---

## 3. Coverage

| Dimension | Represented |
|---|---|
| Policies | 5 - 410.32, 410.33, 410.38, 410.61, 411.15 |
| Revisions | 3 - 2019-01-01, 2022-01-01, 2026-08-13 |
| Criteria targeted | 21 of 33 |

Multiple revisions matter: a set covering only the current revision cannot detect a
temporal failure, which is the failure this architecture exists to prevent. Two
queries are deliberately identical in text but differ in `as_of`, so the *correct
answer changes* with the date of service.

---

## 4. Metrics

Recall@1, Recall@3, Recall@5, MRR, nDCG@5, and ranking latency (p50, p95). Rates
carry a Wilson interval and a denominator; a bare percentage is not permitted.

**Resolution accuracy is reported separately** and is identical across every
configuration, because resolution uses no embeddings and no model. An encoder cannot
change which policy version applies, and that invariance is the point.

Ranking is scored with **exact cosine**, not through the HNSW index: ANN
approximation would confound an encoder comparison with index recall. Index
behaviour is covered by the integration tests.

---

## 5. The reranking finding

Measured on the authoritative corpus, the effect **splits by reranker**:

| encoder | no reranker | `bge-reranker-base` | `ms-marco-MiniLM` |
|---|---|---|---|
| `bge-base-en-v1.5` | 0.7619 | **0.5714** | **0.8095** |
| `bge-small-en-v1.5` | 0.7143 | **0.5714** | **0.8095** |

The earlier phase recorded a blanket finding - "reranking reduces Recall@1" - and
that generalisation is now **corrected**. One reranker degrades retrieval and
another improves it. The earlier measurement was sound; the conclusion drawn from
it was too broad.

**No configuration change is made.** At n=21 the intervals overlap heavily, and
switching a default on that evidence would be tuning on noise. What the result
establishes is narrower: a reranker can actively *degrade* retrieval here, so any
reranker must be measured before it ships.

---

## 6. Limitations

1. **Small.** 23 queries. A Wilson interval on a rate near 0.9 spans roughly 20
   percentage points at this denominator; most configurations will be
   indistinguishable and the report says so.
2. **One author.** The same person transcribed the criteria and wrote the queries.
   Overlap is checked mechanically, but shared mental model is not.
3. **Section-level truth.** A query is correct if the right *section* is retrieved.
   Sub-section precision is unmeasured.
4. **Regulation, not determinations.** 42 CFR prose is denser and more cross-
   referential than an LCD. Results do not automatically transfer.
