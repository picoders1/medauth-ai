# Retrieval Evaluation Methodology

How a retrieval benchmark for this corpus is built and scored, and what it can and
cannot support. Applies to `retrieval_eval_v2`; v1 is superseded as a *method* but
its numbers remain attached to it.

---

## Why v1 needed replacing

v1 was not wrong. It could not fail.

| | v1 | v2 |
|---|---|---|
| queries | 23 (21 scored) | 52 (42 scored) |
| criteria covered | 21 of 33 | **35 of 35** |
| negative queries | **0** | 6 |
| ambiguous queries | **0** | 3 |
| relevance | binary | graded, three levels |
| Recall@3 spread across arms | **0.0000** | 0.0000 |
| Recall@1 spread across arms | 0.2381 | **0.1667** |

Six configurations tying on Recall@3 is not a measurement of any of them. A
benchmark on which every system scores the same has measured the benchmark.

## Query construction

**From the criterion's intent, never from its text.** A query lifted from the
passage it targets measures string matching. One v1 query — *"Are hearing aids paid
for?"* — had 100% content-word overlap with its criterion. The bound is asserted by
test: content-word overlap below 0.8, with a narrow exemption for one- and two-word
queries in the deliberately-underspecified categories, where there is no room to
differ and demanding it would force padding into the query.

**Every query states why it exists.** A question with no reason to exist is padding,
and padding inflates a denominator, which makes every rate in the report look better
founded than it is. Enforced by loader and by test.

**Chunk ids are never pinned.** They change whenever chunking changes, and pinning
them would measure the chunker against itself. Targets are sections.

## The ten categories

| category | what it tests | n |
|---|---|---|
| `DIRECT` | the base case, in ordinary words | 8 |
| `PARAPHRASED` | clinician phrasing, none of the regulation's words | 5 |
| `PARTIAL_INFORMATION` | underspecified, as real queries are | 3 |
| `AMBIGUOUS` | more than one section legitimately answers | 3 |
| `NEGATIVE` | the corpus does not answer it | 6 |
| `HISTORICAL_VERSION` | the answer is in a superseded revision | 8 |
| `EXCEPTION` | alternative pathways and exclusions | 7 |
| `DISTRACTOR` | strongest lexical match is the wrong section | 4 |
| `CROSS_POLICY` | subject spans policies; scope decides | 4 |
| `CROSS_VERSION` | same text, different date, different revision | 4 |

`CROSS_VERSION` queries come in pairs with **identical text and code**, differing
only in date of service. Nothing else varies, so the pair isolates temporal scoping
from every other factor. Asserted by test.

## Graded relevance

`RELEVANT` = 2, `PARTIALLY_RELEVANT` = 1, `NOT_RELEVANT` = 0 (the default, never
enumerated).

Binary relevance would have to call two of three sections wrong for a query like
*"What does the plan have to say?"*, where 410.61 splits plan requirements across
establishment, content and changes. Grading says what is true: one section answers
it and two bear on it.

Labels were set from each section's subject matter **before any arm was run**, and
none was changed after seeing a result.

## Metrics

| metric | definition here |
|---|---|
| Recall@k | a **fully** relevant section reaches rank ≤ k |
| MRR | reciprocal rank of the first fully relevant section |
| nDCG@5 | graded gains; ideal = this query's own labels sorted descending, truncated at k |
| P@3 | fraction of the top 3 with non-zero gain |
| latency | p50 / p95, per query, first-stage plus rerank |
| false retrieval rate | on negatives only, with its own denominator |

### nDCG cannot exceed 1

v1's ideal DCG assumed exactly one relevant chunk. A target section spans several,
so the ideal was too small and nDCG came out **above 1.0** — impossible, and the
only reason the defect was noticed.

Here the ideal is the *same multiset* as the gains, sorted descending. No ranking
can beat the ideal ordering of its own labels, so the bound holds by construction
rather than by remembering to clamp it. A 50-seed fuzz test over random graded
rankings, including all-zero and single-element ones, asserts `0 ≤ nDCG ≤ 1`.

### Precision@3 is reported and is not meaningful here

P@3 sits near 0.51 in every arm. Most queries have one or two relevant sections, so
a query with a single relevant section caps P@3 at 0.3333 however perfect the
ranking. It measures label density, not retrieval quality. MRR and nDCG@5 carry the
ranking signal on this set.

### Negatives are scored separately, never folded into recall

For a negative query every chunk in scope is `NOT_RELEVANT` by construction, so a
top-1 result is always a false retrieval and the rate is 1.0000 in every arm. That
is the expected result, not a defect: **dense retrieval has no abstention
mechanism** and always returns its nearest neighbour. The figure exists to make
that explicit, and the mean top similarity beside it (0.5468 for `bge-base`, 0.6058
for `bge-small`) is what an abstention threshold would have to be calibrated
against. Calibrating one on this set is not permitted — OD-8 governs threshold
selection and it is dev-only.

## Statistical conventions

Wilson intervals for every rate, reported with successes and denominator. A bare
`0.8095` hides that it is 34 of 42. Exact McNemar for paired same-corpus
comparisons. At n = 42 an interval on a rate near 0.8 spans roughly 25 points, so
most arms overlap most arms — stated up front so no reader has to derive it.

## Rules that were followed

1. **No tuning on the benchmark.** `top_k`, `rerank_top_n`, chunking and the
   resolution policy are identical across arms and identical to the shipped
   defaults. No default was changed on these results.
2. **The set was frozen before any arm ran.** No query was rewritten, reweighted or
   dropped after seeing a result.
3. **v1 was not modified.** It keeps its own version marker, its own file and its
   own committed report.
4. **v2 reuses no v1 query.** Asserted by test, so a comparison between the two
   cannot double-count a shared subset.
5. **The report is regenerated from the committed `results.json`**, never re-run for
   a wording change — a report whose prose and figures came from different runs is
   worse than no report.

## What this methodology cannot support

- **Any claim that a configuration is best.** Denominators are small and intervals
  overlap.
- **Generalisation to real coverage determinations.** The corpus is five
  regulations, not NCDs or LCDs (R-55).
- **That resolution generalises.** Every resolvable query must use a code the
  linkage table contains, because no other code resolves to anything. Resolution
  accuracy of 1.0000 measures the table's self-consistency. Recorded as a
  `KNOWN_LIMITATION` in the leakage audit, not as a pass.
- **An encoder comparison when a reranker is present.** `top_k` is 40 and the
  largest policy version holds 25 chunks, so first-stage retrieval never filters:
  every reranker receives the complete resolved scope and the encoder's ordering is
  discarded. The reranked arms are byte-identical across encoders, and that is why.
  See [retrieval-evaluation-v2.md](retrieval-evaluation-v2.md).
