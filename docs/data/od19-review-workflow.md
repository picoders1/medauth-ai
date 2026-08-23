# OD-19 Review Workflow

246 provisions await qualified review. This is the record they move through — and
the reason nothing in it can move them without a person.

Artefacts: `data/review/od19_review_package.jsonl`, `data/review/od19_summary.json`.
Built by `scripts/build_review_package.py`. Ranking rationale is unchanged from
Phase 4 — see [od19-review-package.md](od19-review-package.md).

---

## States

```
PENDING ─┬─▶ IN_REVIEW ─┬─▶ APPROVED                 represent as a criterion
         │              ├─▶ REJECTED                 not decision-relevant
         │              ├─▶ MERGE_REQUIRED           covered by an existing criterion
         │              ├─▶ INTERPRETATION_REQUIRED  meaning genuinely unsettled
         │              └─▶ CLINICAL_REVIEW_REQUIRED needs clinical judgement
```

**Every row starts `PENDING`, and there is no automatic transition to `APPROVED`.**
A workflow that can approve its own rows will eventually approve all of them, and
the entire premise of OD-19 is that engineering cannot settle these questions.
Asserted by test: `automatically_approved == 0`, and every row's decision fields are
`null`.

The last two states exist so a reviewer can record *"I cannot settle this"* without
either guessing or leaving the row blank. **A form that only permits confident
answers manufactures confident answers.**

## Decision → state

A reviewer records one decision; the state follows deterministically, so the two
cannot be left disagreeing:

| decision | state |
|---|---|
| `REPRESENT_AS_CRITERION` | `APPROVED` |
| `NON_DECISION_RELEVANT` | `REJECTED` |
| `MERGE_WITH_EXISTING_CRITERION` | `MERGE_REQUIRED` |
| `REQUIRES_POLICY_INTERPRETATION` | `INTERPRETATION_REQUIRED` |
| `REQUIRES_CLINICAL_REVIEW` | `CLINICAL_REVIEW_REQUIRED` |

`PENDING` is not in the range: a decision always moves a row off it.

## What each row carries

| | |
|---|---|
| `review_id` | `OD19-<provision_id>`, unique, asserted |
| `policy_id`, `policy_version`, `section_path`, `paragraph_path`, `hierarchy_level` | where it sits |
| `authoritative_text` | **the provision itself** — no lookup required |
| `source_page`, `obligation_markers` | citation and signal |
| `cited_by_criteria`, `same_section_criteria` | dependency and context, kept apart |
| `blocked_by_unresolved_dependency` | a transcribed criterion may be unevaluable without this |
| `suggested_requirement_type` + `suggestion_basis` | a word-scan suggestion, carrying `SUGGESTION ONLY` |
| `review_question` | the specific question this provision poses |
| `permitted_decisions`, `permitted_statuses` | the closed vocabularies |
| `review_status` | `PENDING` |
| `reviewer_decision`, `reviewer_rationale`, `reviewer_id`, `reviewed_at` | **all `null`** |

## Nothing is pre-filled

A pre-filled decision would let a lexical suggestion become a recorded human
judgement the moment someone accepted the defaults — which is precisely how an
unreviewed criterion set comes to look reviewed. The suggested requirement type is
offered because an empty form is harder to work than one with a starting point, and
it says so in its own field.

## Ranking does not reduce the denominator

All 246 require review. Priority decides only what is seen first. A provision ranked
11 is **not** established as unimportant — it is one no lexical signal flagged, by a
scan that cannot read meaning.

| priority | reason | n |
|---|---|---|
| 1 | cited by an existing criterion | **5** |
| 2–9 | applicability, exception, exclusion, timing, eligibility, documentation, necessity, codes | 91 |
| 10 | elaborates a transcribed section | 48 |
| 11 | remaining | 102 |

Priority 1 is the urgent tier and is populated only from `KNOWN_DEPENDENCIES` —
dependencies established by individual inspection, never by pattern match. See
[policy-dependency-model.md](policy-dependency-model.md).

## What completing this would settle

**Would settle:** whether the criterion set is complete for these five policies at
these revisions. That closes OD-19, unblocks `completeness_verified`, and is the
precondition for any `REVIEW_REQUIRED` policy becoming adjudicable in production.

**Would not settle:** whether the criteria are *clinically* correct
(`clinically_validated: false` stays until a clinician says otherwise); the coverage
status of any NCD; or anything about LCDs, which are not in the corpus (OD-21).
