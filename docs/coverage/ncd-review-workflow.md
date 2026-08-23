# NCD Review Workflow

Two queues, neither of which resolves anything: **coverage status** (OD-26) and
**code linkage** (OD-27).

Artefacts: `data/review/ncd_status_review.jsonl`,
`data/review/ncd_linkage_review.jsonl`, `data/review/ncd_review_summary.json`.
Built by `scripts/build_ncd_review_package.py`.

---

## Coverage status — 19 versions

```
PENDING ─┬─▶ IN_REVIEW ─┬─▶ VERIFIED                 the reviewer's status is recorded
         │              ├─▶ REJECTED                 the candidate was wrong
         │              └─▶ INTERPRETATION_REQUIRED  the text does not settle it
```

Every row carries: policy identity, title, temporal status and its raw source
string, effective/end dates, source URL, acquisition timestamp, content hash, the
four coverage text fields verbatim, the permitted statuses and states, the review
question, and empty decision fields.

**The candidate.** 8 of 19 rows carry a `candidate_status` from a narrow phrase scan
over the determination's own text. It is stamped `ENGINEERING_DERIVED`, which is
inadmissible as a coverage conclusion by construction, and its
`evidence_references` give the section and character offsets so a reviewer checks
the phrase rather than trusting the label.

11 rows carry no candidate — no unambiguous phrase, or conflicting ones. **Offering
a candidate for a determination whose prose says two things would be picking a side
the text does not pick.**

The review question is the same for every row and is deliberately concrete:

> What does this determination establish about national coverage for the item or
> service it names — COVERED, NOT_COVERED, CONDITIONAL, or does it address something
> other than coverage (NOT_APPLICABLE)? Quote the sentence that establishes it and
> name the section it is in.

**Undated determinations are in the queue.** They cannot be resolved by date and
they still need a status. Dropping them would quietly narrow the queue to the
tractable subset, and a test asserts they are present.

## Code linkage — 6 links

Each row carries the code and its description, the linkage type, provenance,
whether it is authoritative (**none is**), whether production admits it, confidence,
the curator's rationale, and the curator's role — *software engineer, not a
clinician, not a certified coder*.

| provenance | n | production |
|---|---|---|
| `HUMAN_CURATED` | 4 | resolves, **not authoritative** |
| `ENGINEERING_INFERRED` | 2 | **refused** |
| `SOURCE_STATED` | 0 | — and none is possible |

The two `ENGINEERING_INFERRED` links are deliberate. One connects a CBC panel code
to a tumour-antigen determination on "both are lab tests"; the other connects a
spectacle-frame code to a determination about visual testing on shared ophthalmic
subject matter. **They exist so the refusal path is exercised against real data**,
and the queue marks them inadmissible so a reviewer sees what production already
refuses.

## Nothing is pre-filled

`reviewer_status`, `reviewer_id`, `reviewer_rationale` and `reviewed_at` are `null`
in every row of both queues, asserted by test. `VERIFIED` is reachable only by a
person, and nothing in the pipeline sets it.

## What completing these would settle

**Coverage status:** the coverage layer would establish something. Today it is
structurally complete and substantively empty.

**Code linkage:** curated links would become verified curated links — still not
authoritative. Only a source that publishes linkage could make them that, and the
MCIM NCD record does not (OD-27).

**Neither settles** whether the determinations are correctly *applied* to a case.
That is adjudication, and it does not exist yet.
