# gold_v2 Migration Plan

**A plan. Nothing here creates gold_v2, and nothing here may edit gold_v1.**

`app/review/migration.py` → `data/review/gold_v2_migration_plan.json`.

---

## The planner cannot write

`app/review/migration.py` imports **no filesystem module at all** — no `pathlib`,
`os`, `io`, `shutil` or `tempfile` — and contains no write call. Asserted over the
AST, so both the precursor (an import) and the act (a write) fail the suite.

`plan_migration()` returns a `MigrationPlan`. Turning one into a dataset is a
separate, deliberate act, taken only after FOCUS-001 is `ACCEPTED`.

## Why migration is additive, not corrective

23 of 156 cases reference C03. Fixing 23 rows in place looks smaller than rebuilding
a dataset. It is not smaller — **gold_v1 is the record of what was measured**, and
editing it makes every committed report describe a set that no longer exists. The
report does not become wrong loudly; it becomes wrong silently, while still reading
as evidence.

So `IMMUTABLE` names what a migration may never touch, and the list is checked rather
than promised:

```
data/gold/cases/gold_v1.jsonl · data/gold/manifests/gold_v1.manifest.json
data/synthetic/cases/cases.jsonl · eval/reports/**
eval/datasets/retrieval/questions.yaml · eval/datasets/retrieval_v2/questions.yaml
```

Current gold_v1 digest:
`ca990b804cf8fd38950bb1dc84e9e1f2a100d5cb579d124109b2d13387f2d0c9` — unchanged by
planning, asserted by test.

## All four outcomes are planned

Modelling only the likely answer is how the unlikely answer becomes the expensive
surprise.

| outcome | gold_v2 | cases migrating | why |
|---|---|---|---|
| `NARROW_C03_TO_BASELINE` | **required** | 23 of 156 | C03 is restated as the supervision floor; the criterion the labels were computed against no longer exists in that form |
| `SPLIT_C03` | **required** | 23 of 156 | C03 becomes two criteria; every affected case needs a state for a criterion that did not exist when it was generated |
| `LEAVE_C03_NOT_ADJUDICABLE` | not required | 0 | nothing changed, so nothing was invalidated |
| `OTHER` | **not planned** | — | the reading is not stated; a placeholder plan would mean inventing it, and would then be mistaken for preparation |

`OTHER` returning an empty plan rather than a guess is the point. Re-run the planner
once the reviewer's reading is recorded.

## The migration steps, when one is executed

1. Record the accepted FOCUS-001 decision and its reviewer attribution.
2. Update the 42 CFR 410.32 transcription and re-run the span gate — **zero failures
   before anything downstream runs**.
3. Regenerate from `data/synthetic/cases/cases.jsonl` through the **same** pipeline.
   Never hand-edit a case.
4. Reproduce the split rule byte-for-byte: stratify by (policy, revision, category);
   order within a stratum by `int(sha256(case_id)[:8], 16)`; `DEV_FRACTION=0.18`,
   `VALIDATION_FRACTION=0.10` as exact counts.
5. Write `gold_v2.manifest.json` with `supersedes_reason` naming the decision, and
   **reset the scoring budget** — budget is per version.
6. Leave gold_v1 in place. Reports keep pointing at the version they scored.

`SPLIT_C03` adds a seventh step: record that the escalation criterion is not
determinable from this corpus, so the admissibility gate keeps refusing 410.32.

## Splitting does not unblock the policy

The escalation half has **no evidence in this corpus** — the supervision indicator
lives in the physician fee schedule, not in 42 CFR at any depth. It inherits C03's
dependency. Splitting relocates the blocker rather than removing it, and the impact
table says so, because an analysis that reported the most-checking option as
admissible would be telling the reviewer something false about it.

## What is not decided here

Which outcome is right. That is FOCUS-001, and it is a domain question. This document
states what each answer would cost, so cost is visible when the answer is given —
and note that the **cheapest option is also the one that checks least**.
