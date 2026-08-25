# Retrieval Configuration — The Decision, and Why It Is Not a Winner

## `RETRIEVAL_CONFIGURATION_UNRESOLVED`

**No configuration is empirically selected. One is adopted as an engineering
default, and the two are different claims.**

Benchmark: `eval/datasets/retrieval_v3/questions.yaml`, sha256 `c8a7d9e23838…`,
36 queries, **scored once** (budget 1/1 spent) under OD-28.
Report: `eval/reports/20260825T100405Z__retrieval-v3/`.

---

## The measurement

Six arms, every parameter identical to the shipped defaults and to the v2 run:
`top_k=40`, `rerank_top_n=5`, same chunking, same resolution policy. Nothing was
tuned before scoring and nothing has been tuned since.

Denominator: **31 of 36** queries. The 5 `NEGATIVE` queries have no relevant section
and therefore no Recall@1 denominator — they are excluded rather than counted as
misses, which would flatter every arm equally and mean nothing.

| encoder | reranker | R@1 | 95% CI (Wilson) | MRR | nDCG@5 | p50 ms |
|---|---|---|---|---|---|---|
| bge-base | **MiniLM-L-6-v2** | **0.7742** | 0.6019–0.8860 | **0.8683** | **0.8987** | 467 |
| bge-small | **MiniLM-L-6-v2** | **0.7742** | 0.6019–0.8860 | **0.8683** | **0.8987** | 459 |
| bge-base | none | 0.7419 | 0.5675–0.8630 | 0.8468 | 0.8000 | **31** |
| bge-small | none | 0.6452 | 0.4695–0.7888 | 0.8118 | 0.7971 | **10** |
| bge-base | bge-reranker-base | 0.6129 | 0.4382–0.7627 | 0.7769 | 0.8456 | 3209 |
| bge-small | bge-reranker-base | 0.6129 | 0.4382–0.7627 | 0.7769 | 0.8456 | 3207 |

Recall@1 spread **0.1613** — the set discriminates, which v1 could not.

## Why nothing is empirically selected

Exact McNemar over all 15 pairs. **Not one reaches p < 0.05.**

| A | B | A>B | B>A | p |
|---|---|---|---|---|
| MiniLM | bge-reranker-base | 5 | 0 | **0.0625** |
| MiniLM | bge-small + none | 5 | 1 | 0.2188 |
| bge-base + none | bge-small + none | 3 | 0 | 0.2500 |
| bge-base + none | bge-reranker-base | 7 | 3 | 0.3438 |
| MiniLM | bge-base + none | 3 | 2 | 1.0000 |

**The best result is 5 discordant queries, all favouring MiniLM, and exact McNemar
on 5–0 gives p = 0.0625.** That is the *minimum achievable p at this sample size*:
even a perfect sweep of every discordant query cannot cross 0.05 with 31 paired
observations.

So the honest statement is not "MiniLM is not significantly better". It is:

> **v3 is too small to establish significance between any two arms, by
> construction.** Scoring it was still worth doing — it is the first clean
> measurement this project has — but it cannot settle a selection.

## The encoder question is not merely unresolved — it is unmeasurable here

`bge-base` and `bge-small` produce **identical results on every query** under either
reranker. Not similar: identical.

The reason is structural and already documented from Phase 4. `top_k=40` exceeds the
largest retrieval scope (25 chunks), so first-stage retrieval returns the entire
scope and ranks nothing away. The reranker then re-orders that whole set, and the
encoder's contribution is discarded before it can affect the outcome.

**No encoder comparison is possible at `top_k=40` on this corpus.** Lowering `top_k`
would make one possible — and doing so *now*, having seen these results, is exactly
the tuning-after-the-fact this regime forbids. It belongs in a pre-registered
protocol.

## What is adopted, and on what authority

| choice | status | basis |
|---|---|---|
| reranker `cross-encoder/ms-marco-MiniLM-L-6-v2` | **ENGINEERING DEFAULT** | best point estimate on R@1, MRR and nDCG; **7× faster** than `bge-reranker-base` (467 ms vs 3209 ms). p = 0.0625 |
| encoder | **UNRESOLVED** | identical under reranking; unmeasurable at this `top_k` |
| `top_k = 40` | **UNRESOLVED, and flagged** | it is what makes the encoder comparison vacuous |
| `rerank_top_n = 5` | **ENGINEERING DEFAULT** | never varied; no evidence either way |

`bge-reranker-base` is **worse than no reranker at all** on this set (0.6129 vs
0.7419) and 100× slower than not reranking. That is the clearest signal here, and it
is a signal about one component, not a selection among all six.

## What may and may not be said

**May:** *the retrieval configuration is an engineering default, adopted on point
estimates and latency, on a clean benchmark that cannot separate the arms
statistically.*

**May not:** *the retrieval configuration is optimal, selected, validated, or better
than the alternatives.* None of those is supported.

## What would resolve it

1. A larger clean set. 31 paired observations cannot reach p < 0.05 on a 5-query
   margin; roughly 3–4× would be needed for a difference of this size.
2. A **pre-registered** `top_k` sweep, so the encoder comparison stops being vacuous.
3. Both fixed before the run, not after seeing this table.

Until then the label stands: **`RETRIEVAL_CONFIGURATION_UNRESOLVED`.**
