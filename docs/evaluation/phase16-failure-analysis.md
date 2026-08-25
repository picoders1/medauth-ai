# `phase16-evaluation-001` failure analysis: one failure, and it is not a case

**Status:** no case-level failure analysis exists. The experiment did not run.

The only failure Phase 17 has to analyse is the one that stopped it, and it belongs
to a component MEDAUTH cannot reach.

---

## The single failure

| | |
|---|---|
| category | **`PROVIDER_FAILURE`** (`SCHEMA_GRAMMAR_FAILURE`, R-86 signature) |
| stage | model boundary — intake, before any adjudication |
| attribution | **`INDETERMINATE`** — provider or firewall, indistinguishable from one hop |
| count | 6 of 6 in the production-shape long cell; 0 of 42 in every other cell |
| rate | 6/12 = **0.5000** on production-shape cells, against a 0.10 ceiling |
| determinism | **yes** — six identical responses at temperature 0 |
| root-cause status | **OUTSIDE ENGINEERING CONTROL**, escalated, unresolved |
| impact | the official evaluation was not authorised; gold_v2's scoring is unspent |

```
finish_reason      length         (6/6)
completion_tokens  1536 = ceiling (6/6)
whitespace         0.9205         (6/6)
parsed as JSON     no             (6/6)
```

## Why it is not a model error

The model produced no answer to be wrong about. A response that never closes its
document is a broken response path, and calling it a reasoning failure is precisely
the collapse Phase 16's taxonomy was built to prevent — Phase 14 reported ten of these
as sixteen reasoning errors.

`classify_provider_failure` cannot see correctness; a test asserts it over the
signature.

## The categories, and why five are empty

| category | count | why |
|---|---|---|
| `PROVIDER_FAILURE` | **1 (the gate)** | R-86, deterministic, unresolved |
| `MODEL_ASSESSMENT` | 0 | no case was assessed |
| `DATASET_DEFECT` | 0 | gold_v2 re-derives all 156 applicability states; R-97 is closed |
| `RETRIEVAL_FAILURE` | 0 | retrieval_v4 is provenance-clean; the baseline scored normally |
| `CONTRADICTION` | 0 | no case ran |
| `SYSTEM_FAILURE` | 0 | fourteen of fifteen preconditions passed |

**Zero here means "no case reached this stage", not "this stage is clean."** The
distinction matters: a report that read these zeros as evidence of quality would be
claiming a clean run from an absent one.

## What the empty categories do tell us

Something, though less than a run would. The preconditions that passed are real
measurements:

- **the dataset is not the blocker** — 156 cases, applicability re-derived from input
  plus committed linkage, gold_v1 byte-identical, no narrative-only ground truth;
- **retrieval is not the blocker** — clean provenance, a scored baseline under the
  frozen configuration, no `SYSTEM_CONFIGURATION_DRIFT`;
- **the configuration is not the blocker** — every frozen digest matches live.

The failure is isolated to one hop, and everything on this side of it is ready.

## Impact on validity

Had the run proceeded, `provider-failure-validity.v1` would have returned
`DEGRADED_BY_PROVIDER_FAILURE` on condition 1. ADR-029 predicted exactly that **before
the run existed**, so it would have been a confirmed prediction rather than a finding —
and the hold-out would have been spent to obtain it.

## Root cause

Unresolved and not ours. Grammar-constrained decoding guarantees the output *shape*
and not that the output *terminates*: JSON permits arbitrary whitespace between
tokens, so a decoder can satisfy the schema forever without closing the document.

The fix is a decoder-side stop condition. It is not a prompt change, and Phase 16
established that no request property MEDAUTH can measure predicts the failure — 522
filler tokens succeed where 512 clinical tokens fail.

See [r86-gate-recheck.md](r86-gate-recheck.md) and
[the escalation](../escalations/R-86-unbounded-whitespace.md).
