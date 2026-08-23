# Retrieval Evaluation Assessment (Part G)

**Verdict: the evaluation set is not difficult enough. Resolution accuracy of
1.0000 is not evidence that retrieval is solved.**

---

## 1. What the current set covers

| Dimension | Coverage | Assessment |
|---|---|---|
| Queries | 23 (21 scored) | **Small.** Wilson interval near 0.9 spans ~20pp |
| Policies | 5 of 5 | Complete |
| Policy versions | 3 of 3 | Complete |
| Criteria targeted | **21 of 33** | **12 criteria have no query** |
| Distinct sections | 13 | Reasonable |
| Historical-revision queries | 3 | Thin |
| Temporal pairs (same text, different date) | 3 | Present, and the strongest part of the set |
| **Negative queries** (no correct answer exists) | **0** | **Gap** |
| **Ambiguous queries** (>1 plausible section) | **0** | **Gap** |

## 2. Why 1.0000 resolution accuracy is not reassuring

Resolution is deterministic: a SQL lookup on code, jurisdiction and date. Perfect
accuracy means **the queries exercise codes that are in the linkage table** — which
they do by construction, because the set was built from that table.

It does not test:

- a code linked to **no** policy (should yield `NONE_APPLICABLE`)
- a code linked to **two** policies (should yield `CONFLICTING`)
- a date **before** any effective date
- a code linked at `low` or `INFERRED` confidence

Every one of those is a decision-table row the corpus can reach and the retrieval
set never exercises.

## 3. Ranking results, and what they are worth

| encoder | none | `bge-reranker-base` | `ms-marco-MiniLM` |
|---|---|---|---|
| `bge-base-en-v1.5` | 0.7619 | **0.5714** | **0.8095** |
| `bge-small-en-v1.5` | 0.7143 | **0.5714** | **0.8095** |

Recall@1, n=21. Recall@3 is **0.9524 across every arm** and Recall@5 is 1.0000 for
four of six.

That flat Recall@3 is the finding. The rerankers are reordering the top of a list
that already contains the answer, and with 4–13 chunks per policy version the
retrieval problem is small enough that the answer is nearly always in the candidate
set. **A corpus this size cannot discriminate between encoders.**

## 4. What would make the evaluation valid

Ordered by how much each would change what the numbers mean:

1. **Negative queries** — codes resolving to no policy. Tests the row-1 path, which
   is the one that must never become a denial. Currently untested by retrieval.
2. **Ambiguous queries** — where two sections could plausibly answer. The current
   set has one obvious target per query.
3. **Cover the remaining 12 criteria** — a criterion with no query cannot have a
   retrieval failure attributed to it.
4. **More historical queries** — 3 of 21 is too few to detect a temporal regression.
5. **A larger corpus** — adopting NCDs (OD-20) would raise chunk counts materially
   and make ranking a real problem rather than a small one.

## 5. What was deliberately not done

**The system was not changed to improve these numbers.** The reranking result was
not tuned away, the defaults were not switched despite `ms-marco` scoring higher,
and no query was rewritten after seeing a result.

Two corrections *were* made, both because the measurement was wrong rather than
inconvenient:

- **nDCG exceeded 1.0**, which is impossible. A target section spans several chunks,
  so several are relevant, but ideal DCG assumed one. Fixed and re-run.
- **Two queries targeted 411.15**, an exclusion overlay no procedure code can
  resolve to. They are now excluded from the denominator with the reason recorded —
  not deleted.

## 6. Recommendation

Expand the set **before** the next retrieval measurement, and treat the current
figures as a floor on difficulty rather than a ceiling on capability. The
expansion is dataset work, not system work, and must happen without looking at
which arm it favours.
