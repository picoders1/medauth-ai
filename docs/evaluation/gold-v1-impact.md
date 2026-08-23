# gold_v1 Impact — Phase 7

**gold_v1 is byte-identical. 156 cases, 0 labels changed, 0 scorings spent, no
gold_v2.**

Phase 7 added two criteria, changed how adjudicability is computed, and derived a
new evaluation set. None of that touched a frozen dataset.

---

## What changed around it

| | before Phase 7 | after |
|---|---|---|
| criteria in the inventory | 35 | **37** |
| versions with executable semantics | 1 | 1 |
| **versions adjudicable** | 1 (semantics only) | **0** (semantics AND dependencies) |
| **gold cases adjudicable** | 26 | **0** |

The drop from 26 to 0 is **not** new breakage. It is the correction of an artefact
that reported adjudicability from semantics alone, which let 42 CFR 410.32 read as
adjudicable while 23 of those 26 cases reference criterion C03 — whose evidence set
cannot contain the standard it is measured against (R-51).

**Two artefacts disagreeing about the same question is worse than either being
wrong**, so `production_coverage.json` now applies both axes and reports 0.

## If C03's dependency were RESOLVED

| | |
|---|---|
| gold cases referencing C03 | **23** |
| gold cases referencing any dependency-blocked criterion | 69 |
| gold cases that would become adjudicable | **26** |

The 26 are every gold case on 42 CFR 410.32 — the 23 that reference C03 plus 3 that
do not. Resolving C03 unblocks the policy, and the policy is what gates the cases.

**They would become mechanically replayable, and nothing more.** "Replayable" means
`decide()` can run over them without producing a verdict on an unfounded criterion.
It does **not** mean the labels are clinically correct, that the criteria are the
right ones, or that anything has been validated. All 156 cases still audit as
`REQUIRES_REVIEW` (Phase 3), and `clinically_validated: false` stands.

## The additions are additive

C07 and C08 were transcribed from 42 CFR 410.32(b)(3) and (b)(4). **No gold case
references either** — asserted by test. No existing case's meaning changed, no label
was recomputed, and no case was regenerated.

The synthetic case manifest keeps its generation-time criteria hash and records the
extension separately, as it did for the Phase 4 additions. Drift is detected by
asserting the extension is *additive*, which still fails on any edit or deletion —
both mutations were injected and confirmed to fail.

## Phase 8: the four-way impact is precomputed

A reviewer answering FOCUS-001 can now see what each option costs **before**
deciding, for every option rather than only the expected one:

| outcome | 410.32 admissible after | gold_v2 | gold cases |
|---|---|---|---|
| `NARROW_C03_TO_BASELINE` | **yes** | yes | 23 |
| `SPLIT_C03` | no | yes | 23 |
| `LEAVE_C03_NOT_ADJUDICABLE` | no | no | 0 |
| `OTHER` | not computed | — | — |

`SPLIT_C03` costs a gold_v2 **and** does not unblock the policy: the escalation half
is itself not determinable from this corpus, so splitting relocates the blocker
rather than removing it. Reporting it as admissible would tell the reviewer something
false about the option that preserves the most checking.

Detail: [../review/FOCUS-001-impact.md](../review/FOCUS-001-impact.md).

## What would force a gold_v2

Acting on FOCUS-001 in a way that changes what C03 means. `NARROW_C03_TO_BASELINE`
and `SPLIT_C03` both would: cases labelled against the old C03 were labelled against
a criterion that no longer exists in that form.

`data/review/gold_impact.json` records the reach in advance — **23 cases for the C03
decision** — so that is a decision made deliberately with a recorded reason, not a
consequence discovered afterwards.

`LEAVE_C03_NOT_ADJUDICABLE` forces nothing: it leaves the corpus exactly as it is and
410.32 inadmissible.
