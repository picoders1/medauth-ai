# Vertical-Slice Admissibility — The Machine-Checkable Gate

## `BLOCKED`

`scripts/assess_slice_admissibility.py` → `data/review/slice_admissibility.json`.

**READY or BLOCKED. There is no "close enough".** A slice failing one condition is a
slice where the first AI experiment measures something other than what it claims.

---

## The eleven conditions

Every one is read from a committed artefact. The gate computes them the same way for
every candidate — no policy is special-cased.

| # | condition | reads from |
|---|---|---|
| 1 | `semantics_declared` | the logic inventory |
| 2 | `criteria_span_verified` | the verification record |
| 3 | `no_unresolved_dependency` | the dependency report |
| 4 | `temporally_resolvable` | the corpus / NCD registry |
| 5 | `coverage_status_established_or_not_required` | the NCD registry |
| 6 | `no_engineering_inferred_linkage` | both linkage files |
| 7 | `citation_provenance_complete` | the criteria inventory |
| 8 | `retrieval_scope_constructible` | corpus registry + admissible links |
| 9 | `evaluation_provenance_sufficient` | the provenance audit, **clean sets only** |
| 10 | `production_semantics_executable` | the declared-logic loader |
| 11 | `domain_decisions_resolved` | the FOCUS-001 decision record |

Four were added in Phase 8. Three are worth explaining:

**`production_semantics_executable`** is distinct from `semantics_declared`. A
declaration can exist and fail to load; a policy declared on paper only would
otherwise read as ready. The check *loads* the file rather than globbing for it.

**`evaluation_provenance_sufficient`** requires a scorable query in a **clean** set.
A scorable query inside a contaminated set is still a query whose report cannot be
trusted as a whole.

**`domain_decisions_resolved`** reads `is_resolved` from the decision record. The
gate does not compute the answer and cannot: `is_resolved` is `True` only for an
`ACCEPTED` decision, and nothing in the pipeline can produce one.

## Result

| policy version | failed conditions |
|---|---|
| **`REGULATION:42 CFR 410.32:2026-08-13`** | **`domain_decisions_resolved`, `no_unresolved_dependency`** |
| `REGULATION:42 CFR 410.33:2026-08-13` | `production_semantics_executable`, `semantics_declared` |
| `REGULATION:42 CFR 410.38:2022-01-01` | + `no_unresolved_dependency` |
| `REGULATION:42 CFR 410.38:2026-08-13` | + `no_unresolved_dependency` |
| `REGULATION:42 CFR 410.43:2026-08-13` | six conditions |
| `REGULATION:42 CFR 410.61:2019-01-01` | four, including `no_engineering_inferred_linkage` |
| `REGULATION:42 CFR 410.61:2026-08-13` | four, including `no_engineering_inferred_linkage` |
| `REGULATION:42 CFR 411.15:2026-08-13` | three |

**42 CFR 410.32 fails two conditions, and both are the same decision seen from two
sides** — the dependency FOCUS-001 would close, and the gate that holds it. Nine of
eleven pass, and no engineering blocker hides among the two that do not.

## No other policy was considered as a bypass

410.61 would be the tempting alternative — it has no dependency-blocked criterion.
It fails four conditions of its own, including `no_engineering_inferred_linkage`,
which is the rule that made its evaluation queries unusable in the first place.

Selecting a policy because it produces more green cases is how a gate stops meaning
anything. Each candidate is assessed independently and none passes.

## The gate was not loosened

Setting `domain_decisions_resolved` to `True` unconditionally makes
`test_an_open_domain_decision_blocks_the_policy_it_names` fail. Dropping the
dependency check makes the Phase 7 test fail. Both mutations were run and restored.
