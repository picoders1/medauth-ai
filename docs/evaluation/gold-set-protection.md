# Gold-Set Protection

`gold_v1` is frozen. This records what that means mechanically, what Phase 4 did to
test it, and what would have to happen for a `gold_v2` to exist.

---

## The rule

**A frozen split is never edited in place.** Not to fix a label, not to add a case,
not to reformat. Editing one destroys the record of what every earlier measurement
was measured against — the numbers stay in the report and quietly stop meaning what
they said.

Corrections ship as a **new version** with a recorded reason.

## What is pinned

| artefact | pinned by |
|---|---|
| `data/gold/cases/gold_v1.jsonl` | `sha256` in `gold_v1.manifest.json`, asserted by test |
| scoring budget | `scorings_spent: 0`, asserted by test |
| labelling claims | `clinically_validated: false`, `human_reviewed: false` |
| criteria the cases depend on | additive-only check (below) |

## Phase 4 changed a great deal and touched none of it

Phase 4 rewrote the decision engine, added two criteria, reclassified a provision
and changed behaviour on 3,472 input combinations. Every one of those is a way
gold_v1 could have been invalidated. It was not:

- **The gold file is byte-identical.** Its recorded sha256 still matches.
- **All 156 gold labels reproduce** through the rewritten `decide()`, along with all
  222 synthetic cases.
- **0 of 156 gold cases sit in a divergent class.** Case generation sets
  `has_valid_evidence` from the criterion state, so the unevidenced `NOT_SATISFIED`
  that drives both divergences never occurs in the corpus.
- **The declared 410.32 logic is not applied to any gold case.** gold_v1 was
  generated under assumed conjunction, and assumed conjunction is what continues to
  evaluate it.

## The additive-only rule for criteria

Phase 4 added two `EXCEPTION_CONDITION` criteria to 410.32, so the criteria
inventory's hash no longer equals the one recorded when the cases were generated.

Overwriting that recorded hash would erase the provenance of the corpus the cases
actually came from. Instead:

- `criteria_sha256` keeps the **generation-time** value.
- `criteria_sha256_current` records what the file is now.
- `criteria_extension_note` says what changed and why.
- A test asserts every criterion any case references **still exists with the same
  role and provenance**.

That is strictly weaker than hash equality for *additions* and exactly as strong for
*edits and deletions* — which are the changes that would silently invalidate a
label. Both failure modes were injected and confirmed to fail the test.

## What would force gold_v2

Three known candidates, none of them acted on:

1. **Declared logic for policies gold cases depend on.** Adopting declared logic for
   410.32 would change how its cases evaluate. Every 410.32 case would need
   regenerating. (OD-24)
2. **Routing `REVIEW_REQUIRED` policies to human review.** Four versions carry
   exception wording with no declared logic. Making the runtime act on that doubt
   would turn every 410.33, 410.38 and 411.15 case into `HUMAN_REVIEW`. (OD-24)
3. **A completed OD-19 review.** If review finds the criterion set incomplete — and
   seven confirmed gaps say it is — cases adjudicated against the old set are
   labelled against an incomplete rule set. This is the substantive one.

**No `gold_v2` was created in Phase 4.** None of the above is settled, and creating
a new frozen version on unsettled grounds would produce a second artefact with the
same problem as the first plus a broken lineage.

## If gold_v2 becomes necessary

1. Record the reason in `supersedes_reason` on its manifest. A test refuses a
   `gold_v[2-9]` file whose manifest does not say why it exists.
2. Regenerate from `cases.jsonl` through the same pipeline. Never hand-edit.
3. Reproduce the split rule byte-for-byte: stratify by (policy, revision, category),
   order within each stratum by `int(sha256(case_id)[:8], 16)`, take exact counts at
   `DEV_FRACTION = 0.18` and `VALIDATION_FRACTION = 0.10`. **The `[:8]` slice
   matters** — the full digest reorders every stratum.
4. Leave `gold_v1` in place. Both versions stay, and reports keep pointing at the
   version they scored.
5. Reset the scoring budget for the new version. Budget is per version and does not
   transfer.

## Scoring budget

`gold_v1` allows **1** scoring and has spent **0**. Phase 4 measured retrieval, not
decisions, and the gold set was audited without being scored. Additional scorings
must be declared in an ADR **in advance**; selection and threshold calibration use
dev only, enforced at the library boundary by `eval/schema.py:require_tunable`.

## What freezing does not mean

Frozen means immutable, not correct. All 156 cases audit as `REQUIRES_REVIEW`:
each label is derived correctly from its criterion states by the same `decide()` the
system uses, but whether those criteria are the *right* ones is exactly what OD-19
leaves open. Protecting the set protects the record, not the conclusion.
