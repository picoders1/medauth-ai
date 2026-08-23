# Ground-Truth Readiness Gate

**Classification: B — GROUND TRUTH PARTIALLY READY. Specific blockers remain.**

Assessed 2026-08-23. Every answer is `PASS`, `PARTIAL`, `FAIL` or `NOT_VERIFIED`.
An unknown is never recorded as a pass.

---

## The twelve questions

| # | Question | Verdict | Evidence |
|---|---|---|---|
| 1 | Are the selected policies authoritative? | **PASS** | 42 CFR via the official eCFR API (Office of the Federal Register), public domain, 8 documents |
| 2 | Are policy versions correct? | **PASS** | 7 versions across 3 revision dates; date-addressable and reproducible; temporal resolution tested |
| 3 | Are all decision-relevant criteria identified? | **FAIL** | 247 of 312 substantive provisions await qualified review. 7 confirmed gaps found by inspection |
| 4 | Are criteria source-verified? | **PASS** | 33/33 span-verified, 0 failures; gate refuses drifted text, wrong section, wrong revision, duplicate keys |
| 5 | Are exclusions explicitly documented? | **PASS** | Every excluded provision carries a recorded reason; 411.15 marked `EXCLUSION_OVERLAY`; 410.38 rev 2019 exclusion documented |
| 6 | Are code mappings appropriately classified? | **PARTIAL** | 16 links classified: 14 `HUMAN_CURATED`, 2 `INFERRED`, **0 `AUTHORITATIVE`**. Correct classification, weak foundation |
| 7 | Are case-policy relationships valid? | **PASS** | 0 cases reference unknown criteria, unlinked codes, or missing policies |
| 8 | Is gold-set labeling defensible? | **PARTIAL** | Internally sound and reproducible from criterion states; sufficiency rests on unverified completeness. All 156 audit `REQUIRES_REVIEW` |
| 9 | Has qualified human review occurred? | **FAIL** | **None.** 0 of 6 protocol requirements met |
| 10 | Is the coverage-policy source appropriate? | **PARTIAL** | 42 CFR is authoritative but one layer above coverage determinations. NCDs found openly accessible; adoption decided, not implemented |
| 11 | Are retrieval queries sufficiently representative? | **FAIL** | 21 of 33 criteria covered; **0 negative queries, 0 ambiguous queries**; 3 historical |
| 12 | Is clinical-text realism sufficient for the next phase? | **PARTIAL** | Notes carry headed sections, distractors, reordering and restatement — but are constructed. MIMIC `NOT_REQUESTED` |

**3 PASS-equivalent failures. 5 PASS. 4 PARTIAL. 3 FAIL.**

---

## Blockers, and the evidence each requires

### BLOCKER 1 — Criterion completeness is unverified (Q3, Q9)

**The controlling blocker.** Everything downstream inherits it, and it is why all
156 gold cases audit as `REQUIRES_REVIEW`.

*Evidence required:* a qualified reviewer resolves the 247 `REQUIRES_HUMAN_REVIEW`
provisions and rules on the 7 confirmed gaps. See
[ground-truth-review-protocol.md](../evaluation/ground-truth-review-protocol.md).

*Cannot be resolved by:* more engineering. The span-verification gate is already
exhaustive on the question it answers.

### BLOCKER 2 — Retrieval evaluation is not difficult enough (Q11)

Resolution accuracy of 1.0000 reflects queries built from the linkage table, not a
solved retrieval problem. No negative or ambiguous query exists.

*Evidence required:* an expanded set with negative cases, ambiguous cases, and
coverage of all 33 criteria — built **before** the next measurement and without
reference to which arm it favours.

*Resolvable by:* dataset work, no reviewer needed.

### BLOCKER 3 — Decision logic is universal where policy is not (Q8)

The decision table applies one rule set to every policy. 42 CFR 410.32(a) carries a
**mammography exception** — an alternative route to satisfying the ordering
requirement — so its required criteria are not purely conjunctive, and the table
treats them as if they were.

*Evidence required:* a reviewer confirms, per policy, whether required criteria
combine conjunctively; policy-specific logic is made explicit where they do not.

### NOT A BLOCKER — code linkage weakness (Q6)

`INFERRED` links are correctly classified and excluded from gold decision logic. It
constrains what can be claimed, not whether work can proceed.

---

## What IS ready

- **The policy layer is authoritative.** Real regulation, real amendment history.
- **Faithfulness is proven and mechanically enforced**, with the gate shown to fail
  on four corruption paths.
- **The walk is exhaustive** — 356 provisions enumerated; no provision is unexamined.
- **Nothing is silently excluded** — every exclusion carries a reason.
- **The gold set is stable and reproducible**, usable for regression testing.
- **Data isolation holds** — test and working databases separated after a real
  destructive incident.

---

## Classification

**B — GROUND TRUTH PARTIALLY READY.**

Not A, because criterion completeness is unverified and no qualified review has
occurred — a system built now would be measured against a rule set that is known to
be incomplete, with seven concrete gaps already identified.

Not C, because the foundation is sound: the corpus is authoritative, faithfulness is
proven, the walk is exhaustive, and the blockers are named with the evidence each
requires.

**Usable now:** regression testing, retrieval development, pipeline construction.
**Not usable now:** any claim about decision quality or clinical accuracy.
