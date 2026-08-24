# FOCUS-001 — How to Submit Your Decision

**Operational instructions only. Nothing here suggests an outcome.**

Read [FOCUS-001.md](FOCUS-001.md) first — the question, its sources, and what each of
the four answers costs. This document is only about *how to record* the answer you
reach.

---

## The seven steps

### 1. Read the packet

| | |
|---|---|
| [FOCUS-001.md](FOCUS-001.md) | the question, the regulation text, C03/C07/C08, the three supervision definitions, what is missing and why |
| [FOCUS-001-impact.md](FOCUS-001-impact.md) | what each of the four answers changes, including what each gives up |

### 2. Select exactly one outcome

```
NARROW_C03_TO_BASELINE     SPLIT_C03
LEAVE_C03_NOT_ADJUDICABLE  OTHER
```

Spelled exactly as above. Anything else is refused rather than interpreted.

If none of the first three fits your reading, use `OTHER` and state the reading in
the rationale. Its impact is deliberately not precomputed — modelling an unstated
reading would mean inventing one.

### 3. Write your rationale

Free text, **at least 8 words**. That floor is not a quality bar; it exists to catch
"ok", "agreed", "looks fine" — the shapes a rubber stamp takes.

State why the reading follows from the source. A later reader must be able to weigh
the reasoning, not just observe that someone answered.

### 4. Name yourself and your standing

`reviewer_identity` and `reviewer_qualification` are both required and both
non-empty. The qualification is free text and is deliberately not drawn from a
closed list: this project cannot enumerate what standing to read coverage regulation
looks like, and pretending otherwise would be the wrong kind of precision (OD-29).

### 5. Submit

Write a JSON payload — anywhere on disk; it is not committed:

```json
{
  "focus_id": "FOCUS-001",
  "reviewer_identity": "your name or identifier",
  "reviewer_qualification": "your standing to answer this",
  "decision": "ONE_OF_THE_FOUR",
  "rationale": "why this reading follows from 42 CFR 410.32(b)(3)",
  "source_reference": "docs/review/FOCUS-001.md",
  "submitted_at": "YYYY-MM-DD"
}
```

`source_reference` must contain one of the packet's own references, so that the
answer is demonstrably to *this* question:

```
docs/review/FOCUS-001.md
42 CFR 410.32(b)(3) — data/cms/CFR-410_32-2026-08-13.md
https://www.ecfr.gov/current/title-42/section-410.32
docs/data/410-32-b3-review.md
```

Check the envelope without writing anything:

```bash
uv run python scripts/ingest_focus_decision.py --validate path/to/decision.json
```

Every problem is reported at once, each with a remedy, so a correction is one
round-trip rather than several. Then submit for real:

```bash
uv run python scripts/ingest_focus_decision.py --submit path/to/decision.json --write
```

**Without `--write` this is a dry run.** With it, the record becomes `SUBMITTED`.

> `SUBMITTED` unblocks nothing. Production stays blocked and the admissibility gate
> keeps reporting `BLOCKED`.

The validator checks the **envelope** — identity, standing, a rationale, the packet
cited, a real date. It says nothing about whether your answer is right. That is the
question it cannot settle.

### 6. Obtain separate acceptance

A **second person, named differently from the submitter**, records acceptance:

```json
{ "accepted_by": "a different identifier", "accepted_at": "YYYY-MM-DD" }
```

Both fields are required. `accepted_at` is **persisted** to the record, not merely
checked — an acceptance whose date nobody kept cannot later be placed relative to
the submission it accepted.

```bash
uv run python scripts/ingest_focus_decision.py --accept path/to/acceptance.json --write
```

Refused if:

- the same identity submitted and accepts — that collapses two acts into one and
  removes the only structural check on the first
- the gate is not `SUBMITTED`
- `accepted_at` predates `submitted_at` — an acceptance cannot predate what it accepts

If one person genuinely must do both, that is a process decision to record under
OD-29, not something to route around here.

### 7. Re-run the admissibility gate

```bash
uv run python scripts/assess_slice_admissibility.py --write
```

It recomputes on its own evidence. Nothing is asserted by hand.

---

## Two protections you should know about

**`scripts/build_focus_decision.py --write` now refuses to rebuild over an answered
decision.** `SUBMITTED`, `ACCEPTED`, `REJECTED` and `SUPERSEDED` are all protected,
and there is no `--force`. A `PENDING` record may be rebuilt only when the result is
byte-identical, or with `--archive-to PATH`, which preserves the existing record
first — history accumulates rather than being traded for convenience.

A superseding answer is recorded as a new `decision_version` beside the old one,
never over it.

**Do not hand-edit `data/review/focus_001_decision.json`.** The ingestion path exists
so that attribution, ordering and separation of the two acts are checked. An edited
record is an unattributable state change.

---

## What happens after acceptance

```
        SUBMITTED
            │  (a second, separately-named act)
            ▼
        ACCEPTED
            │
            ▼
  assess_slice_admissibility.py          ← recomputes all eleven conditions
            │
    ┌───────┴────────┐
    ▼                ▼
 admissible      still blocked
    │                │
    ▼                ▼
 production      the gate names
 gate re-        the remaining
 evaluates       condition, and
    │            work stops there
    ▼
 first AI vertical slice
 (one policy, one version)
```

Two answers leave 42 CFR 410.32 inadmissible even after acceptance
(`SPLIT_C03`, `LEAVE_C03_NOT_ADJUDICABLE`). That is a legitimate result, not a
failure of the process — and it is stated here so it is not a surprise later.

### If your answer changes what C03 means

gold_v1 is frozen and **is never modified**. A decision that invalidates labels
produces a *new* dataset version:

```
gold_v1  ──(regenerated through the same pipeline)──▶  gold_v2
   │
   └── stays exactly as it is, so every committed report keeps describing
       the dataset it actually scored
```

The migration is planned in advance for all four outcomes
([gold-v2-migration-plan.md](../evaluation/gold-v2-migration-plan.md)) and is
**executed as a separate, deliberate act** under the project's data-governance
workflow — never automatically as a side effect of acceptance.

Of the four outcomes, `NARROW_C03_TO_BASELINE` and `SPLIT_C03` each migrate 23 of
156 gold cases; the other two migrate none.
