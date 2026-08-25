# ADR-027 — Pre-registration: larger retrieval benchmark (OD-35) and top_k sweep (OD-36)

**Status:** Pre-registered (2026-08-25). **Not executed.**
**Resolves when run:** OD-35, OD-36. **Depends on:** ADR-011 (pre-registration regime).

Everything below is fixed **before** any of it is measured. That is the whole
mechanism: hypotheses, sample size, metrics, significance method, stopping rule and
decision rule are all here, and none may be revised after seeing a number.

---

## Why this exists

`retrieval_v3` was scored once and answered a question nobody asked: **it cannot
separate any two arms.** 31 paired observations; the best comparison is 5 discordant
queries all favouring one arm, giving exact-McNemar p = 0.0625 — *the minimum
achievable at that sample size.* A perfect sweep could not have crossed 0.05.

And the encoder comparison was worse than inconclusive: both encoders were
**identical on every query**, because `top_k=40` exceeds the largest retrieval scope
(25 chunks), so first-stage retrieval returns the whole scope and ranks nothing away.

Two separate defects, two separate experiments.

## OD-35 — a benchmark large enough to answer the question

**Hypothesis (H1).** At least one reranker configuration differs from another in
Recall@1 by a margin detectable at α = 0.05.

**Null (H0).** No pair differs detectably.

| | |
|---|---|
| construction | Same six-way provenance audit as v3. Derived from the criteria inventory, one query per criterion per category, authored before any arm runs |
| sample size | **≥ 120 scorable queries.** At 31, a 5-query margin cannot reach p < 0.05; ~4× is the minimum for a difference of that size. The number is fixed here, not chosen when the data arrives |
| categories | The ten v3 categories, each ≥ 8 queries, so a category cannot be silently under-represented |
| relevance labels | `RELEVANT` / `PARTIALLY_RELEVANT` / `NOT_RELEVANT`, assigned before scoring, by section path |
| negatives | Queries with no relevant section. **Excluded from the Recall denominator**, scored separately as a false-positive rate. Counting them as misses flatters every arm equally and measures nothing |
| exclusions | **None.** No query may be dropped after seeing a result |

**Metrics:** Recall@1/3/5, MRR, nDCG@5, Precision@3, p50/p95 latency. Recall@1 is the
primary endpoint; the rest are reported and are not the decision.

**Significance:** exact McNemar on paired per-query hits, Wilson intervals on single
rates. Both already implemented in `eval/metrics/`.

**Stopping rule:** one scoring of the full set. No interim looks, no re-scoring.

**Decision rule, fixed now:**

- p < 0.05 on the primary endpoint → that arm is **EMPIRICALLY SELECTED**
- otherwise → `RETRIEVAL_CONFIGURATION_UNRESOLVED` **stands**, and the incumbent
  remains an engineering default

**Pre-registered failure mode.** The set may again fail to separate the arms. That is
a finding about the corpus — a small, templated regulation corpus may simply not
discriminate rerankers — and it must be reported as such, not as a reason to enlarge
the set again until something crosses 0.05.

## OD-36 — the `top_k` sweep

**Hypothesis (H2).** Encoder choice affects Recall@1 at some `top_k` below the scope
size.

**Null (H0).** It does not, at any tested `top_k`.

| | |
|---|---|
| values | `top_k ∈ {5, 10, 20, 40}`, fixed here. 40 is the incumbent and is included so the comparison contains the status quo |
| arms | 2 encoders × 4 `top_k` = 8, reranker held at the current default so `top_k` is the only variable |
| confound | Below the scope size, first-stage retrieval genuinely filters. Above it, it cannot. **The 40 arm is expected to show no encoder difference** — that is a prediction, recorded now, and confirming it is not a discovery |

**Decision rule:** encoder selection requires p < 0.05 at a `top_k` that is **also**
the configured value. A difference visible only at `top_k=5` does not justify
selecting an encoder while shipping 40.

**Order:** OD-36 runs **after** OD-35 and on the OD-35 set. Sweeping `top_k` on a set
too small to separate anything would produce eight arms nobody can compare.

## What neither experiment establishes

Not clinical relevance. Not that better retrieval produces better recommendations —
that link is unmeasured and is a different experiment again. A retrieval metric is a
statement about ranking, and the corpus it ranks is 13 chunks of one regulation.

## Prohibited

Editing `retrieval_v3`. Re-scoring it. Adding queries after seeing results. Changing
`α`, the sample size, the primary endpoint or the decision rule once either
experiment begins. Selecting a configuration on point estimates and describing it as
empirical.
