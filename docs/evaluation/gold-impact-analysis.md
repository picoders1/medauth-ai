# Gold Impact Analysis

**"If a reviewed provision changes, which gold cases are affected?"**

gold_v1 is immutable. That protects the record and it also means a reviewer working
the OD-19 queue has no way to see, before deciding, how far a decision reaches. This
answers that and changes nothing.

`app/review/impact.py`, `scripts/analyse_review_impact.py`,
`data/review/gold_impact.json`.

---

## The chain

```
provision ──cited_by──▶ criterion ──referenced_by──▶ case
                │
                └──belongs_to──▶ policy version ──▶ cases
```

A provision reaches a criterion two ways, and they are **not equally strong**:

**A recorded dependency.** The criterion invokes a rule this provision contains
(R-51). Changing the provision changes what the criterion means, so every case
referencing that criterion is affected.

**Shared policy version.** The provision sits in a policy a criterion was drawn
from. Ruling `REPRESENT_AS_CRITERION` on it *adds* a criterion, which changes what a
complete adjudication of any case on that version requires — even though no existing
criterion changed.

The second is weaker and is reported as a note rather than as affected cases.
Merging them would make every decision look like it invalidated half the corpus.

## Measured today

| | |
|---|---|
| subjects analysed | 15 (5 priority-1 provisions + 10 dependency-blocked criteria) |
| subjects that would reach gold | **10** |
| gold cases reachable | **69 of 156** |

| subject | gold cases |
|---|---|
| 42 CFR 410.32 `(b)(3)` | 23 |
| 42 CFR 410.38 `(d)(1)(ii)(A)` and `(B)` (both revisions) | 46 |
| criterion 410.32 C03 | 23 |
| criteria 410.38 C02, C03 (both revisions) | 23 each |

The 410.32 `(b)(3)` row is the one that matters most: it is the single blocker
standing between the designated candidate slice and admissibility, and it reaches 23
gold cases.

## A stale reference is not "no impact"

They look identical in a summary and mean opposite things. A subject the corpora do
not know comes back with a note saying so, never as an empty impact.

## What it does not do

**It does not modify gold_v1**, and a test asserts the case count is unchanged. It
does not create a `gold_v2`. It does not decide whether a decision *should* be made
— only what acting on it would touch.

`touches_frozen_data` flags when acting would force a new frozen dataset version.
That is a decision of its own, made deliberately with a recorded reason, **not a
consequence discovered afterwards**.

## Review versioning

Decisions accumulate as versions; history is never mutated. `review_v1` is what the
first reviewer concluded, `review_v2` is what the second concluded *beside* it. A
version:

- may supersede only an **earlier** version, and only **with a recorded reason** —
  two versions disagreeing with nothing saying why is worse than one being wrong
- must carry at least one decision, each **signed and reasoned** — a state change
  with no reasoning is a change, not a review
- takes its number from the highest existing version, never the count, so a gap
  cannot cause a number to be reused

`app/review/versioning.py`. Nothing there *applies* a decision: acting on one —
retranscribing a criterion, declaring logic, regenerating a gold set — is separate,
deliberate work, and the impact analysis exists so its size is visible before anyone
starts.
