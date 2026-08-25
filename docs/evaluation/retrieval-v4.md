# retrieval_v4: a provenance-clean benchmark, and its baseline

**Dataset:** `eval/datasets/retrieval_v4/questions.yaml` (36 queries)
**Audit:** `data/review/retrieval_v4_provenance.json`
**Baseline:** `eval/reports/retrieval-v4-baseline/results.json`
**Status:** benchmark clean · configuration `ENGINEERING_DEFAULT_UNRESOLVED` · budget 1/1 **spent**

---

## The audit comes first, and it may reject anything

A query is scorable only if its whole authority chain resolves against committed
artefacts:

    query → policy type → policy id → policy version → criterion → evidence section

A query missing any link is `INVALID_FOR_SCORING` and is **not reinterpreted**.
Guessing the version a query "obviously" meant is how a benchmark comes to measure a
corpus nobody assembled — R-70 is what that looked like last time.

### What Phase 16 checks that Phase 13 could not

Phase 15 made policy type part of retrieval scope and applicability a runtime stage,
so two links were previously implicit:

- **policy type** — a `RetrievalScope` cannot exist without one, and a query that
  does not name it is scoped by whatever the runner passed.
- **applicability** — a `NEGATIVE` query must be negative because *no section answers
  it*, not because its procedure code fails to resolve. Those are different
  measurements and only the first belongs here. The audit checks every query's code
  against the linkage, including negatives.

### Result

**36 of 36 scorable. Zero invalid. All ten categories non-empty.**

| DIRECT | PARAPHRASED | PARTIAL | AMBIGUOUS | NEGATIVE | HISTORICAL | EXCEPTION | DISTRACTOR | CROSS_POLICY | CROSS_VERSION |
|---|---|---|---|---|---|---|---|---|---|
| 6 | 3 | 3 | 2 | 5 | 4 | 3 | 4 | 4 | 2 |

`retrieval_v3` was built carefully; this says so with a check rather than a claim.
**Non-vacuity is proven separately:** `test_the_audit_rejects_a_broken_chain` breaks
one link at a time — unknown policy, unknown criterion, unlinked code, missing
`as_of` — and each must be caught. 36/36 passing means nothing unless the audit can
fail.

## The baseline — one arm, on purpose

`scripts/evaluate_retrieval_v3.py` sweeps six configurations. This runs the **single
configuration the system ships** and reports what it does.

| | |
|---|---|
| encoder | `BAAI/bge-base-en-v1.5` |
| reranker | `cross-encoder/ms-marco-MiniLM-L-6-v2` |
| `top_k` / `rerank_top_n` | 40 / 5 |
| chunking | section-aware, never crossing a section boundary |
| status | **`ENGINEERING_DEFAULT_UNRESOLVED`** |

| metric | value |
|---|---|
| Recall@1 | **24/31 = 0.7742** |
| Recall@3 | 30/31 |
| Recall@5 | 31/31 |
| MRR | 0.8683 |
| nDCG@5 | 0.8987 |
| Precision@3 | 0.5376 |
| false retrieval on negatives | **5/5** |
| latency p50 / p95 | 619 ms / 737 ms |

**Denominator 31, not 36.** The five `NEGATIVE` queries have no relevant section to
recall and are excluded from Recall, scored separately as a false-retrieval rate.
Counting them as misses flatters every arm equally and measures nothing.

**5/5 false retrieval is expected and is the ADR-004 point.** A vector search always
returns something. The number says the system returns a top-1 chunk for questions no
section answers, which is precisely why applicability is deterministic and why a
confidently-cited answer from an inapplicable policy is the failure this
architecture is built around.

## Arithmetic

Checked before the report is written, and again by test:

- nDCG@5 and MRR within [0, 1] — the ideal is **this query's own labels** sorted
  descending, so nDCG cannot exceed 1 *by construction* rather than by a clamp;
- Recall monotone in k;
- every Recall denominator equal to the ranking denominator.

Metrics come from `eval/runners/retrieval_v2.py` **unchanged**. Re-implementing them
here would give this project two definitions that agree until they do not.

## What this may not be used for

- **No tuning.** Not chunking, `top_k`, the encoder, the reranker or query
  construction. Selection needs OD-35/36's pre-registered protocol (ADR-027).
- **No comparison with v2 or v3.** Different benchmarks; a difference is not
  attributable to the configuration.
- **No arm separation at n=36.** `retrieval_v3` established the ceiling
  arithmetically at n=31: a 5-query margin cannot reach p < 0.05.
- Nothing clinical.

The budget is now **1/1, spent**. A second scoring requires an ADR in advance.
