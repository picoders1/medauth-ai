# `phase16-evaluation-001`: frozen, and not authorised to run

**Manifest:** `eval/reports/phase16-410-33/manifest.json`
**Pre-registration:** [ADR-029](../adr/ADR-029-phase16-experiment-preregistration.md)
**Gate:** `scripts/phase16_prerun_gate.py`
**Status:** `MANIFEST_FROZEN_RUN_NOT_AUTHORISED`

---

## The gate

| condition | |
|---|---|
| `provider_reliability` | **STOP** — 6/12 = 0.5000 in the production request shape, ceiling 0.10 |
| `gold_v1_immutable` | PASS |
| `gold_v2_exists` | PASS — 156 cases, digest matches |
| `r97_fixed` | PASS — applicability re-derived for every case |
| `gold_v2_budget` | PASS — scoring 1 of 1 |
| `retrieval_clean` | PASS — 36 queries, 10 categories, 0 invalid |
| `applicability_runtime` | PASS — R-93 closed |
| `regressions_pass` | PASS — 75 tests |
| `production_gate_ready` | PASS |
| `nothing_tuned` | PASS |

**Nine of ten. The one that fails is not ours.**

## Why the run has not happened

Spending gold_v2's only scoring on a run already known to be uninterpretable would
destroy the budget in order to learn something `r86-factorial-001` established
directly: the production intake shape fails 6/6 on longer clinical notes. The
validity rule would return `DEGRADED_BY_PROVIDER_FAILURE` before the first case, and
the pre-registration says so **in advance** — so it would be a confirmed prediction,
not a discovery, and the hold-out would be gone.

> The dataset, the benchmark, the manifest and the validity rule are ready.
> The provider path is not.

Running anyway is the failure mode ADR-029 exists to prevent. Phase 14 and Phase 15
each spent a scoring to learn afterwards what a gate could have said beforehand; this
is the gate.

## Why the manifest is frozen anyway

Freezing a manifest for a run that may not start is not a contradiction. The
configuration is a commitment, and committing it while the gate says STOP makes
*"we did not run it, and here is exactly what we would have run"* checkable rather
than asserted. The manifest carries the gate's verdict inside it.

## What is frozen

Dataset digest and all 156 case ids · applicability implementation and source digest ·
retrieval configuration and its baseline · prompt ids · model digest, mode,
temperature and ceilings · gateway configuration digest · validity rule and its
thresholds · the two-denominator reporting contract · source digests for gold_v2, its
manifest, the migration report, retrieval_v4 and its provenance audit.

**Not comparable with Phase 14 or Phase 15.** Different dataset, different code,
different applicability semantics. The manifest says so in a field.

## The two denominators, fixed in advance

    OPERATIONAL COVERAGE   assessed / attempted, provider failures INCLUDED
    DECISION QUALITY       over ASSESSED cases, labelled NOT overall accuracy

Neither may be reported without the other. Cases excluded from the second are counted
in the first and named by disposition; **no case is ever dropped.**

Demonstrated on Phase 15's committed record (`eval/reports/phase15-410-33/coverage.json`,
a read-only re-analysis that spends no budget):

| | |
|---|---|
| operational coverage | **12/26 = 0.4615** |
| decision quality | **4/12** on assessed cases |
| whole-run accuracy | 8/26, provider failures counted as incorrect |
| `PROVIDER_FAILURE` | 10 · `DATASET_DEFECT` 3 · `CONTRADICTION` 1 |
| cost | `COST_NOT_AVAILABLE` |

Three figures, three denominators, none of them "the accuracy".

## What unblocks it

1. R-86 owned and bounded by whoever holds the provider or the firewall — evidence
   and exact asks in [the escalation](../escalations/R-86-unbounded-whitespace.md).
2. `r86-factorial-001` re-run showing the production shape at or below the ceiling.
3. The gate passing on all ten.

None is an engineering task in this repository, and no prompt work substitutes for
any of them.

```bash
uv run python scripts/phase16_prerun_gate.py                    # 10 conditions
uv run python scripts/phase16_prerun_gate.py --freeze-manifest
```
