# Phase 6 Readiness

**Classification: B — PARTIALLY READY. One named blocker stands between the corpus
and a first AI vertical slice.**

---

## The blocker, stated exactly

`REGULATION:42 CFR 410.32:2026-08-13` fails **one** of seven admissibility
conditions:

> `no_unresolved_dependency` — criterion **C03** ("furnished under the appropriate
> level of physician supervision") invokes the supervision levels set out in
> paragraph **(b)(3)**, which is not transcribed. Its evidence set cannot contain
> the standard it is measured against, so any verdict on it is unfounded (R-51).

Everything else about 410.32 passes: semantics `DECLARED`, 6 criteria span-verified,
temporally resolvable, coverage status not required (it is a regulation), no
`ENGINEERING_INFERRED` linkage, complete citation provenance.

**This is a review question, not an engineering one.** No code change resolves it.

Measured by `scripts/assess_slice_admissibility.py` into
`data/review/slice_admissibility.json` — re-running it after a reviewer closes the
blocker changes the answer without anyone editing this page.

## A finding that changed the numbers

The logic inventory's signal scanner had a **false negative**: it matched
`any of the following` but not `one of the following`, which is the commonest way a
regulation writes a disjunction.

42 CFR 410.61(b) — *"The plan is established before treatment is begun by **one of
the following**"* over five practitioner types — scanned clean because of it, and the
policy was classified `ASSUMED_CONJUNCTION` on that false negative. `(d)(1)` has the
same shape.

**Found by reading the regulation, not by the scan** — which is exactly why the
inventory calls these search terms rather than findings.

Consequence, reported rather than softened:

| | before the fix | after |
|---|---|---|
| policy versions adjudicable | 3 of 8 | **1 of 8** |
| gold cases adjudicable | 78 of 156 | **26 of 156** |
| synthetic cases adjudicable | 111 of 222 | **37 of 222** |

410.61 is now `REVIEW_REQUIRED`, correctly. The corpus did not get worse; the record
of it got more accurate.

## What Phase 6 closed

| | |
|---|---|
| **R-62** | policy type participates in identity; both eval runners and the linkage loader corrected; end-to-end collision test |
| **OD-26 (partially)** | a coverage-status model with provenance and evidence exists, and a 19-version review queue. **No status is recorded yet** |
| **OD-27 (partially)** | an NCD linkage layer with three authority levels; `ENGINEERING_INFERRED` refused by resolution. **No link is authoritative, and none can be** |

## What Phase 6 did not close

**OD-19.** 246 provisions still await review. This is upstream of everything else:
the one blocker on the designated slice is an OD-19 item.

**OD-26 substantively.** Every acquired NCD still establishes `UNKNOWN`. The layer is
structurally complete and substantively empty — by design, since inferring a status
is the thing being refused.

**OD-21.** LCDs remain licence-gated.

## Claims this phase does not support

- **Not** clinical accuracy or validation. No clinician has seen any case.
- **Not** that any NCD establishes coverage for anything.
- **Not** that any code link is authoritative — none is, and from these sources none
  can be.
- **Not** that a slice is ready. One is *nearly* ready, and the gap is named.
- **Not** that passing tests proves clinical correctness. They prove the code
  implements the declared behaviour.

## What would make this an A

One thing: a qualified reviewer rules on 42 CFR 410.32 `(b)(3)` — either
transcribing the supervision levels as criteria, or establishing that C03 is
adjudicable without them. That closes the last of the seven conditions, and the
admissibility script will say so on the next run.

The gold impact analysis records what that decision reaches: **23 of 156 gold
cases**.
