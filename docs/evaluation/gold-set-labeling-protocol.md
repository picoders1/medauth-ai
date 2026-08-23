# Gold-Set Labelling Protocol

**Gold set version:** 1 · **Frozen** · **Scorings spent: 0 of 1**
**Policy basis: authoritative** (42 CFR via eCFR) · **Criteria: human-transcribed, span-verified** · **Notes: constructed**

How a case gets its label, what that label is worth, and what it is not.

---

## 1. Who labelled this, and what that means

**A program did.** Labels are computed by `app.decision.table.decide` from criterion
states chosen at construction time. There was no human annotator, no clinician, and
no adjudication of disputed cases.

Stated plainly, because the temptation to blur it is the largest credibility risk in
the project:

> This is an **engineering evaluation set**. It is **not clinically validated**.
> No clinician has reviewed any case, any criterion, or any label. The phrase
> "clinically validated" must not be applied to it, and the manifest records
> `clinically_validated: false` so that a future reader cannot mistake the matter.

The labels are *internally consistent*, which is a real and useful property: they
test whether the system reproduces a stated policy's own logic. They are not
evidence that the logic matches clinical practice, nor that a reviewer would agree.

---

## 1a. What is authoritative here, and what is not

The chain has become uneven, and the unevenness is the important part:

| Layer | Standing |
|---|---|
| Policy text | **Authoritative.** Real 42 CFR from the official eCFR API |
| Criteria | **Human-transcribed from that text and span-verified against it.** Faithful, but not proven complete |
| Code linkage | **Curated engineering artefact.** Authoritative for nothing |
| Clinical notes | **Constructed.** No real clinical text |
| Criterion states | Chosen at construction |
| Decision labels | Computed by `decide()` from those states |

So a case-level label is exactly as good as the criteria it rests on, and those rest
on real regulation. What remains constructed is the *clinical* half: the note, and
therefore whether a real submission would present the facts as cleanly.

## 2. The labelling order, and why it is that way

```
policy -> criteria -> criterion states -> clinical note -> expected decision
```

Criterion states are chosen **first**. The note is then written to realise them, and
the decision is computed from the states.

The alternative - write a note, then decide what it should mean - makes the label an
opinion about text, which is exactly what a model would be doing at inference. An
evaluation built that way measures agreement between two opinions.

---

## 3. Criterion-level labels are primary

Every applicable criterion carries one of:

| State | Meaning | Evidence in the note |
|---|---|---|
| `SATISFIED` | The record establishes the criterion is met | present |
| `NOT_SATISFIED` | The record establishes it is **not** met | present |
| `UNKNOWN` | The record does not address it | **absent** |

`UNKNOWN` is an **omission, never a statement**. A note reading "face-to-face
encounter date unknown" would hand the system a hint no real submission contains;
the note simply does not mention it, and a test asserts the word does not appear.

Notes are also deliberately made less tidy than a checklist: facts are distributed
across headed sections out of criterion order, clinically plausible distractors that
bear on no criterion are interleaved, and one fact may be restated in different
words. What is **not** introduced is ambiguity that would make a label arguable -
realism that made ground truth unknowable would destroy the dataset rather than
harden it.

The case-level decision is *derived*, never assigned:

```
c1 SATISFIED, c2 SATISFIED, c3 UNKNOWN   ->   NEEDS_INFO   (rule 6)
```

So a decision label can never hide which criteria produced it. Both levels are
stored, and a test recomputes every case-level label from its criterion states -
disagreement fails the build.

---

## 4. What counts as sufficient evidence

A criterion is `SATISFIED` or `NOT_SATISFIED` only if the note contains a sentence
asserting the underlying fact. The mapping from state to sentence is declared in
`data/synthetic/case_templates.yaml`, in data rather than code, so a reviewer can
read exactly what a case will assert without reading a generator.

A criterion with no sentence is `UNKNOWN`, and `has_valid_evidence` is false for it.
That flag is what stops row 8 from firing: a verdict of `NOT_SATISFIED` backed by
nothing is missing evidence wearing a verdict's clothes, and it routes to
`NEEDS_INFO`.

---

## 5. Conflicting evidence

A conflicting case asserts a fact and then contradicts it in an addendum - which is
how contradictions actually reach a reviewer, as a late document that disagrees with
an earlier one.

Expected outcome is `HUMAN_REVIEW` (rule 5). The system does not adjudicate its own
inconsistency, and the gold label does not pretend one reading is correct.

---

## 6. Temporal applicability

The corpus now carries **real** amendment history rather than constructed version
pairs: 42 CFR 410.38 and 410.61 each have two revisions retrieved from the eCFR API
at different dates, with genuinely different text.

One consequence is worth recording. 410.38's criteria were transcribed against the
2026 revision and **re-verified** against 2022, where the cited spans are unchanged.
Against the 2019 revision they **fail** - that text was restructured - so 2019 has no
transcription and generates no cases. Carrying criteria across an amendment without
re-verifying would silently attribute requirements to a text that never contained
them.

A case's date of service is generated **inside the effective window of the revision
it was built against**, so the case exercises that revision and no other.

This is the property the `L34567` pair exists for: the same clinical facts yield
different expected outcomes depending on the date, because R3 requires six weeks of
conservative therapy and R4 requires twelve. A system that resolves "latest" gets
the 2023 cases wrong while looking entirely confident.

Expected policy and revision are recorded explicitly, together with an
`applicability_rationale` stating the code, jurisdiction and date window that make
the policy apply - independently checkable, not inferred from similarity.

---

## 7. Citations

The gold set records **section-level** targets, not chunk ids. Chunk ids change
whenever chunking changes; pinning them would make the evaluation measure the
chunker against itself and would silently move the ground truth under a refactor.

Criterion provenance - section, page, span offsets into the source text - is
recorded in `data/criteria/inventory.jsonl` and verified at ingest.

---

## 8. Ambiguity

Cases are constructed, so genuine ambiguity is absent by design except where a
category creates it deliberately (`BORDERLINE`, `CONFLICTING_EVIDENCE`).

**This is a limitation, not a feature.** Real submissions are ambiguous in ways this
set does not contain: facts stated twice with different values, relevant detail in
an unexpected section, hedged clinical language. Performance here is an upper bound.

---

## 9. Disagreement resolution

There is one labeller, so there are no disagreements to resolve, and **no
inter-annotator agreement was measured**. It is not reported as unavailable or
pending: there is nothing to measure it between, and a fabricated κ would be worse
than its absence.

Should a second labeller ever exist, agreement is measured at criterion level and
at decision level, and reported separately - criterion-level agreement is the more
informative of the two, because decision-level agreement can be high while the
reasons differ entirely.

---

## 10. Corrections

The gold set is **frozen**. Its SHA-256 is recorded in the manifest and asserted by
test, so an in-place edit fails the build.

A labelling error is corrected by:

1. Recording what was wrong and why, in the new manifest.
2. Publishing `gold_v2.jsonl` - a **new version**, never an edit.
3. Re-running every evaluation that cited v1, and marking those results superseded.

Labels are never adjusted because a model scores badly against them. If a label is
wrong it is wrong independently of what any model said, and the evidence for that
must not be a metric.

---

## 11. Scoring budget

The gold set may be scored **once**. Further scorings require an ADR declared in
advance, stating the reason.

Re-scoring a frozen split until a number improves is how an evaluation becomes
fiction - the split stops being held out and becomes a slow-motion training set.
Tuning happens on `development`; `validation` exists for intermediate checks. See
[data-partitioning.md](data-partitioning.md).
