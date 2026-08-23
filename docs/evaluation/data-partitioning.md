# Data Partitioning

Three partitions, different permissions, one rule for assignment.

---

## 1. Partitions

| Partition | n | Share | May be used for |
|---|---|---|---|
| `development` | 48 | 22% | Prompt wording, retrieval parameters, threshold calibration, model and reranker selection |
| `validation` | 18 | 8% | Intermediate checks within a phase, sanity runs, regression triage |
| `gold` | 156 | 70% | **Nothing except a budgeted final scoring** |

Counts are from `data/gold/manifests/gold_v1.manifest.json` and asserted by test.
They shift slightly as the corpus grows; the manifest is authoritative, not this table.

---

## 2. Assignment rule

Within each **(policy version × category)** stratum, cases are ordered by
`sha256(case_id)[:8]` and split by exact count.

Two properties, and both are needed:

* **Deterministic.** The hash ordering depends on nothing but the case id - not on
  file order, not on a clock, not on a seed that might drift. The split is identical
  on any machine.
* **Exactly stratified.** Counts are computed per stratum rather than by percentile.
  An earlier version assigned by rank percentile and rounded badly on small strata:
  in a stratum of seven, ranks 0 and 1 both fell below the 15th percentile, so
  development took 29% while validation was starved to 5%. Exact counts hold the
  proportions whatever the stratum size.

The `[:8]` slice is load-bearing. Using the full digest, or a different width, moves
cases between partitions silently - and a case that moves from gold to development
is a case that was held out and now is not.

A stratum small enough that tuning partitions would consume it entirely gives
everything but one case to gold. Coverage of a category matters more than hitting a
fraction exactly.

---

## 3. What leakage prevention actually requires

Disjointness is necessary and nowhere near sufficient.

| Control | Mechanism |
|---|---|
| Partitions are disjoint and complete | Asserted by test over all three files |
| No gold label reaches the input | Every outcome and criterion-state token is grepped out of `input`; asserted by test |
| Input and expected are separate objects | Schema-level separation, not a convention |
| Gold is not tuned against | Scoring budget in the manifest; further scorings need a prior ADR |
| Thresholds are calibrated on dev only | Enforced at the library boundary by `require_tunable` (Phase 6) |
| Retrieval queries are not copies of their targets | Content-word overlap must stay below 0.6; asserted by test |

The last one is the least obvious and the easiest to get wrong. A retrieval query
lifted from the criterion it targets makes retrieval look excellent and measures
nothing but string matching.

---

## 4. What tuning on gold would cost

Nothing visibly. That is the problem: a threshold tuned on the gold set produces a
number that is right about the gold set and unfalsifiable about anything else, and
the report looks identical either way.

The budget exists because the failure is undetectable after the fact. Once a split
has been looked at repeatedly it is no longer held out, however carefully each look
was justified.

---

## 5. Reproducing a partition

The assignment is a pure function of the case ids, so `scripts/build_gold_set.py`
reproduces it exactly from the same corpus. The manifest records the rule, the
fractions, and the SHA-256 of each partition file. An evaluation report cites the
gold set version and hash; if either differs, the report describes a dataset that no
longer exists.
