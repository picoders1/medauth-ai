# Evaluation Provenance

**Every evaluation query must be able to prove its own chain:**

```
query → intended policy → policy version → criterion → evidence chunk
```

A query that cannot prove it is not a hard query, it is an unusable one: whatever it
measures, it is not what its label says.

`scripts/audit_evaluation_provenance.py` → `data/review/evaluation_provenance.json`.

---

## Four classifications

| | means |
|---|---|
| `VALID_AUTHORITATIVE` | the chain rests on a source-stated relationship |
| `VALID_HUMAN_CURATED` | the chain rests on a curated judgement, admissible for resolution |
| `INVALID_INFERRED` | the chain rests on an `ENGINEERING_INFERRED` link, which production refuses — so the query **cannot resolve in production and measures nothing there** |
| `REQUIRES_REVIEW` | the chain is broken otherwise: an unknown criterion, an unresolvable version, a code in no linkage file |

## Results

| set | queries | `VALID_HUMAN_CURATED` | `INVALID_INFERRED` | `REQUIRES_REVIEW` |
|---|---|---|---|---|
| `retrieval_v1` | 23 | 16 | 5 | 2 |
| `retrieval_v2` | 52 | 36 | 12 | 4 |

**0 queries are `VALID_AUTHORITATIVE`** in either set, and none can be: no link in
this corpus is `SOURCE_STATED`, because neither 42 CFR nor the MCIM NCD record
publishes procedure-code linkage.

The `INVALID_INFERRED` queries all target **42 CFR 410.61**, reachable only through
two inferred links. The `REQUIRES_REVIEW` queries are the 411.15 ones already
recorded as unreachable by resolution (OD-15) — a documented corpus gap, not a new
defect, and the audit says so rather than reporting it as one.

## A classifier bug worth recording

The first version judged **negative queries** against the positive chain and
reported six perfectly good queries as broken. A negative query has no expected
policy *by design* — its chain is `query → code → resolved scope → nothing
relevant`, which is shorter than the positive chain and is not a damaged version of
it. Fixed, and the fix is why v3 retains all five of its negative queries.

## Nothing is silently repaired

An `INVALID_INFERRED` query stays exactly where it is, in the set it was authored
into. The historical set and its committed report record what was measured at the
time, and that record stays true only while the artefact behind it does.

**The inferred links are not restored to recover those queries.** They are refused
because applicability from resemblance is what ADR-004 exists to prevent, and
reinstating a refused link to make an evaluation look better would be exactly
backwards.

## Guarded

`test_inferred_linkage_queries_are_flagged_not_repaired` asserts that **every**
query targeting 410.61 is classified `INVALID_INFERRED` — not merely that some
invalid query exists. An earlier version asserted only non-emptiness, and a mutation
that reclassified 11 of 12 left one survivor and passed. The strengthened version
fails on that mutation, with a positive control so the classifier cannot pass by
rejecting everything.
