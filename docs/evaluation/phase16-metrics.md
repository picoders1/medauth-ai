# `phase16-evaluation-001` metrics: none, and why that is the correct entry

**Status: NOT PRODUCED.** The experiment was not authorised
(`eval/reports/phase16-410-33/AUTHORISATION.json`, blocker `provider_gate`).

This page exists so the absence is recorded rather than left as a gap somebody later
fills from a different run.

---

## Every metric Part G asks for

| group | metric | value |
|---|---|---|
| **Operational** | total cases · usable cases · provider failures · coverage · p50 · p95 · model calls · calls/case | **NOT PRODUCED** |
| **Decision quality** | accuracy · precision · recall · macro F1 · confusion matrix | **NOT PRODUCED** |
| **Criterion quality** | coverage · accuracy · SATISFIED / NOT_SATISFIED / UNKNOWN · never-assessed | **NOT PRODUCED** |
| **Grounding** | citation validity · completeness · unsupported-claim rate · verification rate | **NOT PRODUCED** — and would have been `GROUNDING_SCOPE_LIMITED_BY_OD42` |
| **Safety** | unsafe definitive · abstention · human review · invalid-citation · unresolved-policy · provider-failure refusals | **NOT PRODUCED** |
| **Cost** | total · per case · per assessed case · per call | **`COST_NOT_AVAILABLE`** — no price basis exists, independent of the run |

**Not zero. Not estimated. Not carried over from Phase 15.**

## What *is* known, and where it came from

These are real measurements from other, completed artefacts. None is a substitute for
the run, and none is presented as one.

| | | source |
|---|---|---|
| retrieval Recall@1 | 24/31 = 0.7742 | `retrieval-v4-baseline` |
| retrieval nDCG@5 | 0.8987 | same |
| false retrieval on negatives | 5/5 | same |
| retrieval p50 | 619 ms | same |
| provider failure, production shape | 6/12 = 0.5000 | `r86-gate-recheck` |
| gold_v2 cases | 156, applicability re-derived per case | `gold_v2.manifest.json` |

## The reconciliation Part F requires

    attempted (0) = ASSESSED (0) + PROVIDER_FAILURE (0) + DATASET_DEFECT (0)
                  + CONTRADICTION (0) + SYSTEM_FAILURE (0) + RETRIEVAL_FAILURE (0)

Trivially satisfied, and worth stating: the identity holds for an unrun experiment
exactly as it must for a completed one. `eval/coverage.py` enforces it, and its tests
exercise it against Phase 15's real 26-case record where the counts are not zero.

## What may not be written on this page later

- a number from Phase 14 or Phase 15 — different dataset, different code, different
  applicability semantics;
- a projection from the retrieval baseline — retrieval quality is not decision
  quality;
- an estimate of what the run "would have" produced.

When the provider gate passes and the run executes, this page is replaced by
measurements with denominators. Until then, `NOT PRODUCED` is the entry.
