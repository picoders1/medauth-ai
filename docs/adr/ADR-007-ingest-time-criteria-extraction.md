# ADR-007: Criteria Extraction at Ingest Time

**Status:** Accepted · **Date:** 2026-08-23 · **Phase:** Planning
**Not in the original brief.** Added because moving this step changes latency, cost, consistency,
auditability and — decisively — makes non-circular ground truth possible.

## Context

ADR-001 requires per-criterion verdicts, so the system needs a structured list of criteria for each
policy version. Coverage policies state criteria as prose, often nested ("all of the following",
"at least two of", "except when"), and often split between the LCD and its Billing & Coding Article.

## Problem

When is prose turned into structure: once per policy version at ingest, or per request?

## Options

| # | Option | Assessment |
|---|---|---|
| A | Per request, from retrieved chunks | No ingest step. Criteria differ run to run; cost per case; no human oversight possible. |
| B | **Once per policy version at ingest, persisted** | One canonical, reviewable, diffable artefact. Requires an ingest step and a review workflow. |
| C | Manual authoring by a domain expert | Highest quality. Does not scale, and no expert is available here. |
| D | Hybrid: model extraction, human review, persisted | B plus an explicit review gate. |

## Decision

**Option D** — model-assisted extraction at ingest, persisted, versioned, and gated on human review.

- One extraction per policy version, over the section tree.
- Every criterion must carry ≥1 source chunk id. One that cannot be grounded is **rejected, not
  stored**.
- The tree records `kind` (REQUIRED / EXCLUSION / INFORMATIONAL), `logic` (ALL_OF / ANY_OF / N_OF /
  LEAF), parent/child structure, mutual exclusivity, and the extracting model and prompt version.
- Persisted as `DRAFT`; a human marks it `HUMAN_REVIEWED`.
- Re-extraction creates a **new tree revision**. Existing cases keep pointing at the revision that
  adjudicated them.
- `criteria_tree_reviewed` is a feature of the abstention gate (ADR-011). Whether `DRAFT` trees may
  produce recommendations outside evaluation is OD-4.

## Rationale

| | Per request (A) | At ingest (B/D) |
|---|---|---|
| Consistency | Two runs of the same case can adjudicate different criteria | One canonical tree |
| Cost / latency | Paid per case | Paid once per policy version |
| Auditability | Criteria are a transient model output | Criteria are an inspectable, diffable artefact |
| Human oversight | Impossible in the loop | Correct once, for every future case |
| Evaluation | Ground truth cannot be pinned to criteria | Cases constructible *from* the tree |

**The last row is the decisive one.** Because the criteria tree exists as data before any case is
written, a synthetic case can be constructed to satisfy or violate specific criteria, and the label
follows **by construction** from the same decision table the system uses (ADR-015). Without a
persisted tree, labels would have to be assigned by a model or by hand — and a model labelling
cases it will later adjudicate measures self-consistency, not correctness. Ingest-time extraction is
what makes the evaluation mean anything.

**Human review becomes possible at all.** A reviewer correcting a criterion once fixes every future
case against that policy version. Correcting a per-request extraction fixes one case.

**Reproducibility.** A case pins its tree revision, so a later corpus refresh cannot silently change
how a historical recommendation was reached.

## Consequences

**Positive.** Consistent criteria; cost amortised; a human-correctable artefact; ground truth by
construction; reproducible history.

**Negative.** An ingest step and a review workflow to build. **Adjudication has a hard dependency on
the tree** — no tree, no verdicts. A systematic extraction error becomes a systematic adjudication
error across every case touching that policy (R-06), which is why human review gates evaluation
use. Human review does not scale to a large corpus, which is exactly the tension in OD-4.

**Neutral.** Extraction accuracy is **not claimed**. What is recorded is the human correction rate
per criterion — a measure of how much review was needed, not a quality claim about the extractor.

## Rejected alternatives

| Alternative | Rejected because |
|---|---|
| **A — per request** | Non-deterministic criteria make recommendations irreproducible and audit meaningless; there is no point at which a human can intervene; and evaluation becomes circular because labels cannot be tied to a stable criteria set. |
| **C — fully manual** | Best quality, no scale, and no domain expert is available to this project. Rejected on feasibility, not on merit. |
| **Skip the tree; adjudicate against retrieved prose** | Returns to a single holistic judgement, which is ADR-001 Option A under a different name. Per-criterion traceability is lost. |
