# Retrieval Provenance Audit

**Every query must prove its own chain, or it may not be scored.**

```
query → intended policy → policy version → criterion → evidence chunk
```

`scripts/audit_evaluation_provenance.py` → `data/review/evaluation_provenance.json`.

---

## Six classifications

| | means | scorable |
|---|---|---|
| `VALID_AUTHORITATIVE` | the chain rests on a source-stated relationship | yes |
| `VALID_HUMAN_CURATED` | the chain rests on a curated judgement production admits | yes |
| `INVALID_INFERRED` | the chain rests on an `ENGINEERING_INFERRED` link, which production refuses | **no** |
| `INVALID_POLICY_SCOPE` | the code reaches a different policy entirely | **no** |
| `INVALID_VERSION` | the policy is right, the revision is not | **no** |
| `REQUIRES_REVIEW` | the chain is broken for some other reason | **no** |

`INVALID_POLICY_SCOPE` and `INVALID_VERSION` were split apart in Phase 8. They wear
the same shape — the query does not reach what it names — and they tell a maintainer
to fix different things.

## Results

| set | queries | scorable | unscorable | state |
|---|---|---|---|---|
| `retrieval_v1` | 23 | 16 | 7 | **CONTAMINATED** |
| `retrieval_v2` | 52 | 36 | 16 | **CONTAMINATED** |
| `retrieval_v3` | 36 | **36** | 0 | **CLEAN** |

**0 queries are `VALID_AUTHORITATIVE`** across all three sets, and none can be: no
link in this corpus is `SOURCE_STATED`, because neither 42 CFR nor the MCIM NCD
record publishes procedure-code linkage.

## Contaminated means *any*, not *most*

A set with one unscorable query is contaminated. Not "mostly clean" — a comparison
run over it reports a rate whose denominator includes measurements that mean
nothing, and the resulting figure is not wrong in a way anyone can bound.

Redefining contamination as a majority threshold makes `test_a_set_with_any_unscorable_query_is_contaminated`
fail. That mutation was run.

## Nothing is silently repaired

An unscorable query stays in the set it was authored into. The historical set and its
committed report record what was measured at the time, and that record stays true
only while the artefact behind it does.

**The inferred links are not restored to recover those queries.** They are refused
because applicability from resemblance is what ADR-004 exists to prevent, and
reinstating one to make an evaluation look better would be exactly backwards.
