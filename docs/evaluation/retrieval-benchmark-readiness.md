# Retrieval Benchmark Readiness

## `RETRIEVAL_BENCHMARK_NOT_READY`

**No configuration comparison may be run. No result is manufactured.**

`scripts/assess_retrieval_readiness.py` →
`data/review/retrieval_benchmark_readiness.json`.

---

## Two things must both hold

**Provenance.** Every query proves its chain. A contaminated set produces a rate
whose denominator includes measurements that mean nothing.

**Discrimination.** The set can actually separate configurations. A clean set on
which every arm ties has measured the set, not the systems — which is what Phase 3
found of v1, and what OD-22 records.

A set can be clean and useless, or discriminating and contaminated. **Only a set that
is both is ready.**

## Where each set stands

| set | queries | scorable | R@1 spread | ready | fails |
|---|---|---|---|---|---|
| `retrieval_v1` | 23 | 16 | — | no | provenance, discrimination, category coverage |
| `retrieval_v2` | 52 | 36 | 0.1667 | no | **provenance** |
| `retrieval_v3` | 36 | **36** | — | no | **never scored** |

The shape of the problem: **v2 can discriminate but is contaminated; v3 is clean but
has never been scored.** Neither is usable, and neither is close in the same
direction.

## Unknown is not a pass

A never-scored set has no evidence that it discriminates. Treating absence of
evidence as a pass is how an untested benchmark becomes the one everything is
compared on — so `discriminates_between_arms` is `False` for an unscored set, not
`None` and not `True`.

Rewriting that check to admit unscored sets makes
`test_an_unscored_set_does_not_pass_the_discrimination_check` fail. That mutation was
run.

## What this forbids

While the status is `NOT_READY`, nothing may be tuned against a retrieval benchmark:
**not embeddings, not the reranker, not chunking, not top-k, not thresholds.** A
configuration chosen on a contaminated or undiscriminating set is a configuration
chosen on noise, and the resulting number would then be cited as evidence.

## What would change it

Scoring v3 — a deliberate act governed by **OD-28**, decided *before* the run. If v3
then shows a non-zero spread it becomes ready; if it ties, that is a finding about
v3 and it stays not ready.

Deciding after seeing which set flatters a configuration is exactly what OD-22 warns
about, and it is why the decision belongs before the run rather than after.

## Relationship to the first vertical slice

The two gates are independent and neither substitutes for the other.
`RETRIEVAL_BENCHMARK_NOT_READY` does **not** block the slice: the slice runs one
configuration and claims nothing comparative about it. What it blocks is any
*comparison* — and therefore any claim that the configuration the slice happens to
use was chosen on evidence.

So a slice may run while this says `NOT_READY`, and its report must say the retrieval
configuration is unevaluated rather than selected.
