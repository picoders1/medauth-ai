# Retrieval Evaluation v2 — Results and Reading

Committed report: [`eval/reports/20260823T151741Z__retrieval-v2/`](../../eval/reports/20260823T151741Z__retrieval-v2/report.md).
Method: [retrieval-evaluation-methodology.md](retrieval-evaluation-methodology.md).
Addresses **OD-22**.

**The benchmark now discriminates at rank 1 and still saturates by rank 3.** That
is the headline, and both halves matter.

---

## Results

52 queries, 42 scored for ranking, 6 negative, 4 unreachable by resolution.

| encoder | reranker | R@1 | R@3 | R@5 | MRR | nDCG@5 | p50 ms |
|---|---|---|---|---|---|---|---|
| `bge-base-en-v1.5` | none | 0.7619 | 0.9762 | 1.0000 | 0.8591 | 0.8326 | 39.9 |
| `bge-base-en-v1.5` | `bge-reranker-base` | 0.6667 | 0.9762 | 1.0000 | 0.8115 | 0.8721 | 3222.3 |
| `bge-base-en-v1.5` | `ms-marco-MiniLM` | **0.8095** | 0.9762 | 1.0000 | **0.8909** | **0.9146** | 457.1 |
| `bge-small-en-v1.5` | none | 0.6429 | 0.9762 | 1.0000 | 0.8075 | 0.8109 | 20.3 |
| `bge-small-en-v1.5` | `bge-reranker-base` | 0.6667 | 0.9762 | 1.0000 | 0.8115 | 0.8721 | 3158.3 |
| `bge-small-en-v1.5` | `ms-marco-MiniLM` | **0.8095** | 0.9762 | 1.0000 | **0.8909** | **0.9146** | 462.4 |

Resolution accuracy: **1.0000 (42/42, 95% CI 0.9162–1.0000)**, identical across
arms because resolution is deterministic SQL and no encoder can change it.

## Did the harder set help?

**At rank 1, yes.** Recall@1 spans 0.6429 to 0.8095 — a spread of **0.1667**, and
the per-category table shows where it comes from:

| category | best arm | worst arm |
|---|---|---|
| `PARAPHRASED` | 3/5 | 1/5 |
| `HISTORICAL_VERSION` | 7/8 | 4/8 |
| `CROSS_POLICY` | 4/4 | 2/4 |
| `CROSS_VERSION` | 4/4 | 2/4 |
| `PARTIAL_INFORMATION` | 1/3 | 1/3 |

v1 could not have surfaced any of this. Every arm scored identically there.

**At rank 3, no.** Recall@3 is 0.9762 in all six arms and Recall@5 is 1.0000 in all
six. With 3–25 chunks per policy version, the answer is nearly always in the top
three whatever the ranking. **The corpus is too small for rank-3 discrimination**,
and no benchmark design fixes that — only more corpus does (R-55, ADR-022's NCD
layer).

## The reranked arms measure only the reranker

Both `bge-reranker-base` arms are byte-identical, and both `ms-marco` arms are
byte-identical, across two different encoders. That is not a coincidence:

> `top_k` = 40, and the largest policy version holds **25 chunks**.

First-stage retrieval never filters. Every reranker receives the complete resolved
scope regardless of which encoder ordered it, so the encoder's contribution is
discarded entirely.

**The encoder comparison is interpretable only in the two no-reranker arms**, where
`bge-base` leads `bge-small` 0.7619 to 0.6429 at Recall@1.

`top_k` was **not** lowered after seeing this. Changing a parameter once results are
in is how a comparison becomes a search for a flattering configuration. A corrected
comparison needs a larger corpus, or a pre-registered experiment at a smaller
`top_k` — not a quiet edit to this one.

## Reranking, again

Phase 3 corrected an earlier blanket claim that reranking hurts. v2 reproduces the
split, on a harder set and with a clearer margin:

- `bge-reranker-base` **reduces** Recall@1 (0.7619 → 0.6667 on `bge-base`)
- `ms-marco-MiniLM` **improves** it (0.7619 → 0.8095) and leads on MRR and nDCG

At n = 42 the intervals still overlap, so this is **not** grounds to change the
shipped default. It is grounds to stop describing "reranking" as one thing: the two
rerankers move the metric in opposite directions, and averaging them would report
that reranking does nothing.

The cost is also worth stating: `bge-reranker-base` adds ~3.2 seconds per query at
p50, for a result worse than no reranker at all.

## Negative queries

Every arm: false retrieval rate **1.0000 (6/6)**. Expected, not a defect — dense
retrieval has no abstention mechanism and always returns its nearest neighbour.

The useful number is beside it: mean top similarity **0.5468** (`bge-base`) and
**0.6058** (`bge-small`) on questions the corpus genuinely does not answer. For
comparison, a system with an abstention threshold would need to separate those from
genuine answers — and **no such threshold exists in this system today**. These are
the numbers one would have to be calibrated against, on the dev split, under OD-8.

That `bge-small` is *more* confident on non-answers than `bge-base` while being
worse at finding real ones is the kind of thing only a negative-query set can show.

## What this does not establish

- **No configuration is best.** Intervals overlap; no default was changed.
- **Not decision quality.** Right section ≠ right recommendation. That is Phase 6.
- **Not index recall.** Exact cosine was used deliberately.
- **Not generalisation to coverage determinations.** Five regulations, no NCDs or
  LCDs (R-55).
- **Not that resolution generalises.** 1.0000 measures the linkage table's
  self-consistency, because no code outside that table resolves to anything. See
  the leakage audit's `KNOWN_LIMITATION`.

## Open

- **OD-22** stays open. The set discriminates at rank 1 and saturates by rank 3;
  the remaining constraint is corpus size, not benchmark design.
- **R-58**: with `top_k` above the largest scope, no configuration in this pipeline
  is separable from its reranker.
