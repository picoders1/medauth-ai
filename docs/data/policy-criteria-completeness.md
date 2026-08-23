# Policy Criteria Completeness (OD-19)

**Answer: completeness is NOT verified.** The walk is exhaustive; the classification
is not reviewed.

---

## 1. The distinction this document exists to make

| Question | Answered by | Status |
|---|---|---|
| Is each criterion **faithful** to the source? | span verification | **VERIFIED** — 33/33, 0 failures |
| Were **all** decision-relevant criteria identified? | this analysis | **NOT VERIFIED** |

These are different questions, and passing the first says nothing about the second.
Checking the criteria you wrote down tells you nothing about the ones you did not.

---

## 2. Method

Every provision in every policy version was enumerated mechanically
(`app/policy/provisions.py`), at every hierarchy level, with its full paragraph path
resolved through the hierarchy tracker. That produces the **denominator** a
completeness claim requires.

Each provision was then classified into exactly one of:

- `REPRESENTED_CRITERION` — a verified criterion's authoritative text lies within it
- `NON_DECISION_RELEVANT` — with a recorded reason
- `REQUIRES_HUMAN_REVIEW` — a rule could not place it confidently

Classification is rule-assisted with manual overrides
(`scripts/classify_provisions.py`). **Anything a rule could not place confidently
became `REQUIRES_HUMAN_REVIEW`, not `NON_DECISION_RELEVANT`** — the default is
"someone must look", because the cost of a wrong dismissal is an invisible gap.

---

## 3. Result

| | Count |
|---|---|
| Provisions enumerated | **356** |
| Substantive (≥60 chars) | 312 |
| `REPRESENTED_CRITERION` | **29** provisions carrying all 33 criteria |
| `NON_DECISION_RELEVANT` | 80 |
| **`REQUIRES_HUMAN_REVIEW`** | **247** |
| Unclassified | 0 |

**Walk exhaustive: true. Completeness verified: false**, blocked by 247 provisions
awaiting qualified review.

Note that 29 provisions carry 33 criteria: some provisions state more than one
requirement. 42 CFR 410.61's plan-content sentence carries two — the parameters to
prescribe, and the diagnosis and goals to state. An earlier matcher returned only
the first and made four criteria look unrepresented.

### Per policy version

| Policy | Rev | Provisions | Substantive | Represented | Awaiting review |
|---|---|---|---|---|---|
| 410.32 | 2026-08-13 | 58 | 52 | 4 | high |
| 410.33 | 2026-08-13 | 59 | 58 | 5 | high |
| 410.38 | 2022-01-01 | 30 | 23 | 5 | moderate |
| 410.38 | 2026-08-13 | 40 | 31 | 5 | moderate |
| 410.43 | 2026-08-13 | 27 | 21 | 0 | not transcribed |
| 410.61 | 2019-01-01 | 17 | 12 | 5 | low |
| 410.61 | 2026-08-13 | 17 | 12 | 5 | low |
| 411.15 | 2026-08-13 | 108 | 103 | 4 | high (overlay) |

---

## 4. Confirmed gaps — provisions that should probably be criteria

These were inspected individually. Each is a requirement checkable against a
submission that **no transcribed criterion represents**. They are the concrete
evidence that completeness is not verified.

| Provision | Requirement | Why it matters |
|---|---|---|
| `410.38 (d)(1)(ii)(A)` | The written order must reach the supplier **prior to delivery** for face-to-face list items | A distinct timing requirement. A case could satisfy every transcribed criterion and still fail this |
| `410.38 (d)(1)(ii)(B)` | For other DMEPOS, the order must reach the supplier **prior to claim submission** | Second timing requirement, unrepresented |
| `410.38 (d)(3)(ii)` | The face-to-face encounter must be **documented** in the medical record with beneficiary-specific findings | Criterion C04 covers the encounter's *timing*, not its *documentation* |
| `410.38 (d)(2)(i)` | The encounter must be **for the purpose of** diagnosing or managing the condition the item is for | A purpose requirement distinct from timing |
| `410.38 (d)(3)` | The supplier must **retain** the order and supporting documentation | Whether this bears at authorisation or only at audit is a judgement for a reviewer |
| `410.32 (a)(3)` | **Nonphysician practitioners** may order tests under stated conditions | C01 addresses only physicians, so the criterion is narrower than the rule |
| `410.32 (b)(3)` | Defines the supervision **levels** (general, direct, personal) | C03 requires "the appropriate level" without capturing which level applies — **the criterion is not checkable on its own** |

The last one is the most serious: a transcribed criterion that cannot be evaluated
without a provision that was not transcribed.

---

## 5. Temporal completeness

Analysed per version, not assumed to carry across.

| Policy | Revisions | Finding |
|---|---|---|
| 410.38 | 2022, 2026 | Same criteria verify against both; the cited spans are unchanged |
| 410.38 | **2019** | **Criteria do NOT verify.** The section was restructured |
| 410.61 | 2019, 2026 | Same criteria verify against both |

### 410.38 revision 2019 — resolved as a documented limitation

The three options in the brief were: acceptable and documented, recoverable through
structural mapping, or a genuine evaluation limitation.

**It is a genuine evaluation limitation, and it is documented rather than
recovered.** The 2019 text is not a reordering of the 2026 text - the paragraph
structure differs, so no structural mapping exists that would not amount to
inventing one. The honest options were to transcribe the 2019 revision
independently, which reproduces the same unverified-completeness problem at greater
cost, or to exclude it. It is excluded: no transcription, no cases, and the refusal
recorded here and in the transcription notes.

**Consequence:** the corpus carries no pre-2022 DMEPOS cases. Temporal evaluation
for 410.38 spans 2022→2026 only.

---

## 6. What this means for the gold set

Every policy version carries provisions awaiting review, so **all 156 gold cases
audit as `REQUIRES_REVIEW`** — see [gold-set-audit.md](../evaluation/gold-set-audit.md).

That does not mean the cases are wrong. It means their *sufficiency* rests on a
criterion set whose completeness is unestablished. A case can be internally perfect
and still be adjudicated against an incomplete rule set.

---

## 7. Open questions

1. **Are the 247 provisions awaiting review genuinely decision-relevant?** A
   qualified reviewer resolves this. A non-clinician cannot.
2. **Should the seven confirmed gaps be transcribed now?** Doing so by the same
   non-clinician would grow the criterion set without changing what is *verified*.
   Recorded rather than acted on.
3. **Is 42 CFR the right corpus at all?** Coverage determinations state criteria
   directly and carry code linkage. See
   [ncd-lcd-source-assessment.md](ncd-lcd-source-assessment.md).
