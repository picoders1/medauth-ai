# Ground-Truth Review Protocol

**Review status: NOT COMPLETED.** No qualified reviewer has examined any artefact.
This document defines what such a review would require; it does not record one.

---

## 1. Why this exists

Span verification proves each criterion is faithful to its source. It cannot prove
the criterion *set* is complete, that the interpretation matches practice, or that a
case's expected decision is the one a reviewer would reach.

Those are judgements. A non-clinician made them, and a program applied them
consistently — consistency is not correctness.

---

## 2. Expertise required

| Review layer | Minimum qualification | Why |
|---|---|---|
| Criterion completeness | Coverage-policy analyst, certified coder, or clinician with utilization-review experience | Deciding which provisions bear on a decision requires knowing how the policy is applied |
| Policy applicability | Same, plus coding familiarity | Whether a procedure code falls within a policy's scope |
| Decision logic | Utilization-review clinician | Whether criterion states combine the way the policy intends |
| Case labels | Clinician | Whether a note's facts support the assigned criterion state |

A software engineer can review provenance, structure and internal consistency —
**that review has been done.** None of the above has.

---

## 3. What must be reviewed

### 3.1 Criterion-level

For each of the 33 criteria: is the transcription faithful *and* material? Is the
normalized interpretation how the requirement is actually applied? Is the
comparator/threshold right?

**And the harder half:** of the **247 provisions marked `REQUIRES_HUMAN_REVIEW`**,
which are decision-relevant? That is the completeness question, and it cannot be
delegated to a rule.

Reviewer receives: the criterion, its authoritative text, the source URL, the full
provision list with classifications and reasons.

### 3.2 Policy applicability

For each of the 16 curated code links: does the code fall within the policy's
subject matter? Both `INFERRED` links (G0295) need a verdict — they currently rest
on resemblance and are excluded from gold decision logic.

### 3.3 Decision logic

Does the universal decision table match each policy's own semantics? Specifically:
42 CFR 410.32(a) carries a **mammography exception**, so its required criteria are
not purely conjunctive — the table currently assumes they are (§F of the audit).

### 3.4 Case labels

A stratified sample of the 156 gold cases: given the note, is the expected criterion
state right, and does the expected decision follow?

---

## 4. Recording disagreement

Every disagreement is recorded, never silently resolved:

```yaml
review_id: R-0001
artefact: criterion | provision | linkage | decision_logic | case
artefact_id: 42_CFR_410_38_2026_08_13_C04
reviewer: <name, qualification>
verdict: AGREE | DISAGREE | UNCLEAR
finding: what is wrong, or what is missing
recommendation: what should change
severity: BLOCKING | MATERIAL | MINOR
```

`UNCLEAR` is a first-class verdict. A reviewer who cannot decide has told you
something real, and forcing a binary would discard it.

Where two reviewers disagree, both verdicts stand and the disagreement is reported.
Agreement is measured at criterion level and decision level separately — decision
agreement can be high while the reasons differ entirely.

---

## 5. How corrections are versioned

**The gold set is frozen and is never edited.** A review finding produces:

1. A recorded finding (above).
2. If criteria change: a new transcription version, re-verified through the gate.
3. If cases change: **`gold_v2.jsonl`** — a new version, with the reason and the
   findings that drove it.
4. Every evaluation citing `gold_v1` is marked superseded and re-run.

Labels are never adjusted because a model scores badly against them. If a label is
wrong it is wrong independently of what any model said.

---

## 6. Minimum bar for "reasonable ground-truth confidence"

Not full clinical validation — a defensible engineering evaluation set:

| Requirement | Status |
|---|---|
| Every `REQUIRES_HUMAN_REVIEW` provision resolved | **NOT DONE** (247 open) |
| Confirmed gaps (§4 of completeness) transcribed or dismissed with reason | **NOT DONE** (7 open) |
| Both `INFERRED` code links resolved | **NOT DONE** |
| Policy-specific decision logic confirmed or corrected | **NOT DONE** |
| Stratified sample of gold cases reviewed | **NOT DONE** |
| Reviewer qualification recorded | **NOT DONE** |

**0 of 6 met.**

Reaching this bar would permit: *"ground truth reviewed by a qualified coverage
analyst"*. It would still **not** permit *"clinically validated"*, which requires
clinical validation of outcomes, not review of a dataset.

---

## 7. If no reviewer is available

Then this stays **REVIEW NOT COMPLETED**, and the honest position is the one
currently recorded: criteria are faithful, completeness is unverified, and the gold
set is an engineering artefact whose sufficiency is unestablished.

That is a usable position for building and regression-testing a system. It is not a
basis for any claim about clinical accuracy, and no such claim is made.
