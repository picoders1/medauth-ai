# Retrieval Evaluation v3

Compares six configurations on `eval/datasets/retrieval_v3`. Addresses **OD-28**:
whether a retrieval benchmark for this corpus can discriminate between systems at
all.

**v1 and v2 are not superseded.** Its numbers remain attached to its own set and its own
report. This is a different, harder benchmark, and the two are not comparable.

## Provenance

| | |
|---|---|
| dataset | `eval/datasets/retrieval_v3/questions.yaml` |
| dataset_sha256 | `c8a7d9e238386272` |
| dataset_version | `3` |
| generated_at | `2026-08-25T10:04:05.443438+00:00` |
| git_commit | `9c2f424` |
| machine | `Linux x86_64` |
| python | `3.12.3` |
| queries | `36` |
| rerank_top_n | `5` |
| top_k | `40` |

## What the set contains

| category | queries |
|---|---|
| AMBIGUOUS | 2 |
| CROSS_POLICY | 4 |
| CROSS_VERSION | 2 |
| DIRECT | 6 |
| DISTRACTOR | 4 |
| EXCEPTION | 3 |
| HISTORICAL_VERSION | 4 |
| NEGATIVE | 5 |
| PARAPHRASED | 3 |
| PARTIAL_INFORMATION | 3 |
| **total** | **36** |

## Resolution accuracy

Reported separately from ranking and identical across arms: resolution is
deterministic SQL on code, jurisdiction and date, so an encoder cannot change
which policy version applies. Negative queries are excluded from this denominator -
they have no expected version.

**1.0000 (31/31, 95% CI 0.8897-1.0000)**

## Ranking quality

Graded relevance: RELEVANT = 2, PARTIALLY_RELEVANT = 1. Recall counts a fully
relevant section reaching rank k. Exact cosine, not the HNSW index.

| encoder | reranker | R@1 | R@3 | R@5 | MRR | nDCG@5 | P@3 | p50 ms |
|---|---|---|---|---|---|---|---|---|
| `BAAI/bge-base-en-v1.5` | `none` | 0.7419 | 0.9677 | 1.0000 | 0.8468 | 0.8000 | 0.5376 | 30.8 |
| `BAAI/bge-base-en-v1.5` | `BAAI/bge-reranker-base` | 0.6129 | 0.9677 | 1.0000 | 0.7769 | 0.8456 | 0.5376 | 3209.3 |
| `BAAI/bge-base-en-v1.5` | `cross-encoder/ms-marco-MiniLM-L-6-v2` | 0.7742 | 0.9677 | 1.0000 | 0.8683 | 0.8987 | 0.5376 | 466.6 |
| `BAAI/bge-small-en-v1.5` | `none` | 0.6452 | 1.0000 | 1.0000 | 0.8118 | 0.7971 | 0.5376 | 10.3 |
| `BAAI/bge-small-en-v1.5` | `BAAI/bge-reranker-base` | 0.6129 | 0.9677 | 1.0000 | 0.7769 | 0.8456 | 0.5376 | 3207.2 |
| `BAAI/bge-small-en-v1.5` | `cross-encoder/ms-marco-MiniLM-L-6-v2` | 0.7742 | 0.9677 | 1.0000 | 0.8683 | 0.8987 | 0.5376 | 458.5 |

Recall@1 spread across arms: **0.1613**. Recall@3 spread: **0.0323**.

On v1 the Recall@3 spread was **0.0000** - every arm scored 0.9524 and the
benchmark distinguished nothing. Whether this set does better is the number above,
and it is reported whatever it says.

## The reranked arms are encoder-independent, and that is a finding

Every pair of arms sharing a reranker produced **identical** metrics:

- `BAAI/bge-base-en-v1.5` and `BAAI/bge-small-en-v1.5` with `BAAI/bge-reranker-base` agree on R@1, MRR and nDCG to four decimals
- `BAAI/bge-base-en-v1.5` and `BAAI/bge-small-en-v1.5` with `cross-encoder/ms-marco-MiniLM-L-6-v2` agree on R@1, MRR and nDCG to four decimals

That is not a coincidence and not a bug. `top_k` is **40**,
so first-stage retrieval never filters anything. Every reranker receives the
complete resolved scope whatever ordering the encoder produced, and the
encoder's contribution is discarded entirely.

**Consequence: with a reranker present, this benchmark measures the reranker
alone.** The encoder comparison is interpretable only in the two arms with no
reranker, where `bge-base` leads `bge-small` at R@1 (0.7419 vs 0.6452).

The same effect explains the negative-query table below: mean top similarity is
measured before reranking, so it varies by encoder and not by reranker.

`top_k` was **not** lowered to fix this. Changing a parameter after seeing
results is how a comparison becomes a search for a flattering configuration,
and Part C of this phase fixes `top_k` across arms deliberately. A corrected
comparison needs either a corpus large enough that 40 candidates is a real
filter, or a pre-registered experiment at a smaller `top_k` - not a quiet edit
to this one.

## Negative queries

Six queries the corpus does not answer. Every chunk in scope is NOT_RELEVANT by
construction, so a top-1 result is always a false retrieval - the measurement is
the *confidence* attached to it. A system that returns its best non-answer at 0.30
is behaving differently from one that returns it at 0.80, and only the second would
mislead a reviewer.

| encoder | reranker | false retrieval rate | mean top similarity |
|---|---|---|---|
| `BAAI/bge-base-en-v1.5` | `none` | 1.0000 (5/5, 95% CI 0.5655-1.0000) | 0.5503 |
| `BAAI/bge-base-en-v1.5` | `BAAI/bge-reranker-base` | 1.0000 (5/5, 95% CI 0.5655-1.0000) | 0.5503 |
| `BAAI/bge-base-en-v1.5` | `cross-encoder/ms-marco-MiniLM-L-6-v2` | 1.0000 (5/5, 95% CI 0.5655-1.0000) | 0.5503 |
| `BAAI/bge-small-en-v1.5` | `none` | 1.0000 (5/5, 95% CI 0.5655-1.0000) | 0.6076 |
| `BAAI/bge-small-en-v1.5` | `BAAI/bge-reranker-base` | 1.0000 (5/5, 95% CI 0.5655-1.0000) | 0.6076 |
| `BAAI/bge-small-en-v1.5` | `cross-encoder/ms-marco-MiniLM-L-6-v2` | 1.0000 (5/5, 95% CI 0.5655-1.0000) | 0.6076 |

A false retrieval rate of 1.0000 is the expected result, not a defect: dense
retrieval has no abstention mechanism and always returns its nearest neighbour.
The figure exists to make that explicit and to give the similarity distribution a
denominator - **there is currently no threshold below which this system declines to
retrieve**, and these numbers are what such a threshold would have to be calibrated
against. Calibrating it on this set is not permitted (OD-8 governs threshold
selection, and it is dev-only).

## Per-category recall@1

| category | `bge-base-en-v1.5`+`none` | `bge-base-en-v1.5`+`bge-reranker-base` | `bge-base-en-v1.5`+`ms-marco-MiniLM-L-6-v2` | `bge-small-en-v1.5`+`none` | `bge-small-en-v1.5`+`bge-reranker-base` | `bge-small-en-v1.5`+`ms-marco-MiniLM-L-6-v2` |
|---|---|---|---|---|---|---|
| AMBIGUOUS | 2/2 | 1/2 | 1/2 | 2/2 | 1/2 | 1/2 |
| CROSS_POLICY | 3/4 | 4/4 | 4/4 | 2/4 | 4/4 | 4/4 |
| CROSS_VERSION | 2/2 | 0/2 | 2/2 | 2/2 | 0/2 | 2/2 |
| DIRECT | 6/6 | 5/6 | 5/6 | 5/6 | 5/6 | 5/6 |
| DISTRACTOR | 3/4 | 3/4 | 4/4 | 3/4 | 3/4 | 4/4 |
| EXCEPTION | 2/3 | 2/3 | 2/3 | 2/3 | 2/3 | 2/3 |
| HISTORICAL_VERSION | 3/4 | 3/4 | 4/4 | 2/4 | 3/4 | 4/4 |
| NEGATIVE | - | - | - | - | - | - |
| PARAPHRASED | 1/3 | 0/3 | 1/3 | 1/3 | 0/3 | 1/3 |
| PARTIAL_INFORMATION | 1/3 | 1/3 | 1/3 | 1/3 | 1/3 | 1/3 |

Cells are hits/scored. A dash means every query in that category was excluded from
ranking - which for NEGATIVE is by definition and for EXCEPTION reflects the 411.15
queries that no procedure code can resolve to (OD-15).

## Why precision@3 is low everywhere

P@3 sits near 0.51 in every arm, and that is a property of the labels rather
than of the retrievers. Most queries have one or two relevant sections, so a
query with a single relevant section caps P@3 at 0.3333 however perfect the
ranking is. It is reported because Part B asks for precision where meaningful,
and this is the honest reading: **it is not meaningful here.** MRR and nDCG@5
carry the ranking signal on this set.

## What the per-category table shows

This is where v2 earns its existence. PARAPHRASED ranges from 1/5 to 3/5 across
arms and HISTORICAL_VERSION from 4/8 to 7/8 - differences v1 could not have
surfaced, because on v1 every arm scored the same. PARTIAL_INFORMATION is 1/3 in
every arm, which is the expected result for two-word queries and is reported as
a property of the category rather than as a failure of any configuration.

## What this report does NOT establish

- **Not a claim that any configuration is best.** Denominators are still small and
  intervals still overlap. No default was changed on this evidence.
- **Not decision quality.** This measures whether the right section is retrieved,
  not whether a correct recommendation follows.
- **Not index recall.** Exact cosine was used deliberately, so an ANN approximation
  cannot be confounded with encoder quality.
- **Not generalisation to real coverage determinations.** The corpus is five
  regulations, not NCDs or LCDs (R-55).
- `BAAI/bge-small-en-v1.5` emits 384 dimensions. Adopting it would require a
  migration of `policy_chunks.embedding` and a full re-embed.
