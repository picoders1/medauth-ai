# OD-42: what "grounding" may and may not mean here

**Status: OPEN.** Not resolved by Phase 17, and not pretended to be.
**Scope marker for any report: `GROUNDING_SCOPE_LIMITED_BY_OD42`.**

---

## The question

Can this project report **grounding quality**, or only **citation validity**? They
are different claims and the difference is not rhetorical.

| claim | needs | have it? |
|---|---|---|
| *this quote appears in the chunk it says it came from* | the chunk, the quote, `normalize()` | **yes** — deterministic |
| *this chunk was in that criterion's evidence set* | the evidence set the model was given | **yes** — recorded per call |
| *the metadata matches the chunk's* | the database row | **yes** — joined, never accepted from the model |
| *this was the RIGHT chunk for this criterion* | a per-criterion chunk-level answer key | **no** |
| *every chunk that should have been cited was* | the same key | **no** |

The first three are verification. The last two are grounding *accuracy*, and they
need ground truth this project does not have.

## Why chunk-level ground truth is absent

**Chunk ids are assigned at ingest.** They are database UUIDs, generated when a
document is chunked and embedded. Re-ingest the corpus — a chunking change, a fresh
volume, a different machine — and every id changes while every regulation stays
identical.

A gold set recording them would be ground truth about **one database**, not about the
regulation. It would pass on the machine that built it and fail everywhere else, and
the failure would look like a retrieval regression.

Three options, and only one is honest:

| option | verdict |
|---|---|
| record chunk ids | **rejected** — ties the dataset to one ingest |
| invent plausible ids | **rejected** — fabricated ground truth |
| record what is stable and say what is missing | **adopted** |

So gold_v2 records `evidence_refs` as `policy:version:ordinal` — stable across
re-ingest, readable by a human, and **section-level**. Its
`evidence_ground_truth` field says so in the artefact:

> `SECTION_LEVEL.` Per-criterion source chunk references from the criteria inventory.
> Chunk-level ground truth is **NOT established**: chunk ids are assigned at ingest
> and would tie this dataset to one database. Recording invented ids would be
> fabricated ground truth.

## What a report may still say

**Citation validity — permitted, and it is not a weak claim.** Span verification is
deterministic: `normalize(quote)` must be a substring of `normalize(chunk.text)`, the
claimed metadata must match the row, and the chunk must have been in that criterion's
evidence set. Any failure is `NO_DECISION`. **No model judges it** — there is no
LLM-as-judge anywhere in this metric, which is unusual enough to state.

Also permitted: unsupported-claim rate (an asserting verdict with no citation — zero
by construction, and reported *as* by-construction so the zero is not read as an
observation), and evidence completeness (the share of verdicts resting on something).

## What a report may not say

- *"grounding accuracy"* or *"citation precision/recall against gold"* — there is no
  gold to compute them against;
- *"the model cited the right passage"* — verified only that it cited **a real
  passage from the admitted set**;
- *"retrieval found everything relevant"* — measured on `retrieval_v4` against
  **section** labels, and that is a retrieval claim, not a grounding one.

## Would the official run have been affected?

**No.** `phase16-evaluation-001` was blocked at Part C by the provider gate, not by
OD-42 — but the answer matters for whenever it runs, so it is recorded now:

> The run **can** report citation validity, unsupported-claim rate and evidence
> completeness, each marked `GROUNDING_SCOPE_LIMITED_BY_OD42`. It **cannot** report
> grounding accuracy, and the metric is `unavailable` rather than zero.

`unavailable` and `0.0` mean opposite things and would be aggregated identically.

## What would close it

A chunk identity stable across re-ingest — a content hash over normalised text plus
its section path, say — recorded in the gold set, plus a reviewer establishing which
passages answer which criterion. The first is engineering; the second is not, and it
is the same qualified-review dependency that OD-19 has.

**Until both exist, the narrower claim is the only one available**, and it is the one
made.
