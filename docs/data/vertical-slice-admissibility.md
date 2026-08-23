# Vertical-Slice Admissibility

**No policy version is admissible. One fails a single condition.**

`scripts/assess_slice_admissibility.py` → `data/review/slice_admissibility.json`.
Re-runnable: when a reviewer closes the blocker, the answer changes without anyone
editing this page.

---

## The seven conditions

A slice must pass **all** of them. The conjunction is the point: a slice failing one
is a slice where the first AI experiment measures something other than what it
claims.

| # | condition | 410.32 |
|---|---|---|
| 1 | semantics `DECLARED` | pass |
| 2 | criteria span-verified | pass |
| 3 | **no unresolved criterion dependency** | **FAIL** |
| 4 | temporally resolvable | pass |
| 5 | coverage status established or not required | pass (a regulation needs none) |
| 6 | no `ENGINEERING_INFERRED` linkage | pass |
| 7 | citation provenance complete | pass |

## Every candidate

| policy version | failed conditions |
|---|---|
| `REGULATION:42 CFR 410.32:2026-08-13` | **`no_unresolved_dependency`** |
| `REGULATION:42 CFR 410.33:2026-08-13` | `semantics_declared` |
| `REGULATION:42 CFR 410.38:2022-01-01` | `no_unresolved_dependency`, `semantics_declared` |
| `REGULATION:42 CFR 410.38:2026-08-13` | `no_unresolved_dependency`, `semantics_declared` |
| `REGULATION:42 CFR 410.43:2026-08-13` | `citation_provenance_complete`, `criteria_span_verified`, `semantics_declared` |
| `REGULATION:42 CFR 410.61:2019-01-01` | `no_engineering_inferred_linkage`, `semantics_declared` |
| `REGULATION:42 CFR 410.61:2026-08-13` | `no_engineering_inferred_linkage`, `semantics_declared` |
| `REGULATION:42 CFR 411.15:2026-08-13` | `semantics_declared` |

**Six of seven pass for 410.32.** The seventh is criterion C03's dependency on
`(b)(3)` — see [410-32-b3-review.md](410-32-b3-review.md).

## The gate was not loosened

Transcribing (b)(3) is exactly the kind of progress that tempts a relaxed check.
`test_the_gate_still_blocks_410_32_on_the_dependency` asserts 410.32 still fails, and
on the same condition; an injection that sets `no_unresolved_dependency: True`
unconditionally makes it fail. Proven, not asserted.

## Adjudicability now accounts for dependencies

Phase 6's `production_coverage.json` reported adjudicability from **semantics
alone**. That let 42 CFR 410.32 read as adjudicable while 23 gold cases referencing
C03 would have produced a verdict on a criterion whose evidence set cannot contain
the standard it is measured against.

Two artefacts disagreeing on the same question is worse than either being wrong, so
adjudicability is now **semantics AND dependencies**:

| | |
|---|---|
| versions with executable semantics | **1** of 8 |
| of those, dependency-blocked | **1** |
| **versions adjudicable** | **0** of 8 |
| gold cases adjudicable | **0** of 156 |

Zero is the honest number. The positive control moved to the axis that still has a
non-zero answer — at least one version's *semantics* execute — so fail-closed
remains distinguishable from a system that simply does not work.

## What would make one admissible

One decision: FOCUS-001. Nothing else about 410.32 is outstanding.
