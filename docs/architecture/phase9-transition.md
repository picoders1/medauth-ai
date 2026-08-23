# Phase 9 — The Transition

**Engineering preparation is complete. The repository is waiting on one decision it
cannot make.**

Phase 9 built nothing that runs. It built everything that will be *needed* the
moment FOCUS-001 is answered, so that answering it requires no architectural change
and offers no shortcut.

---

## The state, stated plainly

| | |
|---|---|
| FOCUS-001 | **`PENDING`** — unanswered, and unanswerable here |
| production inference | **`BLOCKED`** by one authoritative gate |
| admissible policy versions | **0 of 8** |
| gold_v1 | byte-identical, 156 cases, 0 scorings |
| gold_v2 | **not created**, planned for all four outcomes |
| retrieval benchmark | **`RETRIEVAL_BENCHMARK_NOT_READY`** |
| model calls made this phase | **0** |

## What was built

| | |
|---|---|
| `app/review/ingest.py` | strict validation of an externally supplied decision |
| `app/production_gate.py` | **the one** gate; fails closed on anything unverifiable |
| `app/review/migration.py` | gold_v2 planner with **no write path at all** |
| `app/contracts/slice.py` | closed schemas for every slice boundary |
| `tests/fixtures/slice/` | eight contract fixtures, no model inference |
| `scripts/ingest_focus_decision.py` | two commands, because there are two acts |

## The three properties that matter

**An answer cannot be forged.** `DecisionGate.pending()` is the only constructor.
Submission and acceptance are separate entry points; a submission by the same
identity that accepts it is refused, because that collapses two acts into one and
removes the only structural check on the first. Six mutations were injected — self
acceptance, acceptance without submission, an unresolved decision ignored by the
gate, an unreadable artefact read as permission, a citation-free verdict, an
unsupported mapping — and all six fail the suite.

**A migration cannot mutate what it migrates from.** The planner imports no
filesystem module and contains no write call, asserted over the AST. Both the
precursor (an import) and the act (a write) fail the test.

**Replay cannot enable production.** `eval/replay.py` reproduces gold_v1 under
semantics production refuses. The gate has no input through which replay could
reach it, and a boundary test asserts it neither imports nor names the replay
constructor.

## The canonical flow, with the block marked

```
   FOCUS-001  ── PENDING ──▶  production_gate  ──▶  BLOCKED
        │                            ▲
        │  (a qualified reviewer)    │
        ▼                            │
   SUBMITTED ──(second act)──▶ ACCEPTED
                                     │
                                     ▼
   ┌─────────────────────────────────────────────────────────┐
   │ synthetic case                                          │
   │      ▼ intake            [model]  facts + spans         │
   │      ▼ resolution        [SQL]    PolicyIdentity        │
   │      ▼ retrieval         [local]  RetrievalScope        │
   │      ▼ evidence mapping           SUPPORTED/…/UNCERTAIN │
   │      ▼ assessment        [model]  SATISFIED/…/UNKNOWN   │
   │      ▼ policy logic      [pure]   PolicySemantics req'd │
   │      ▼ citation validation        span-verified or stop │
   │      ▼ abstention gate            9 states, UNCALIBRATED│
   │      ▼ recommendation             + audit event         │
   └─────────────────────────────────────────────────────────┘
                    NOT IMPLEMENTED IN THIS PHASE
```

## Historical replay stays separate

gold_v1 replay may continue to reproduce the historical experiment — that is what
keeps every committed report interpretable. It says nothing about production, and
the gate is built so it cannot be made to say anything.

## Clinical validation remains unestablished

Nothing in this phase, or any earlier one, establishes that adjudicating cases this
way produces clinically correct outcomes. `SOURCE_VERIFIED` is an engineering fact
about where text sits. `QUALIFIED_REVIEWED` is a reader agreeing it is the right
criterion. Clinical validation is a third thing with **no representation anywhere in
this codebase**, deliberately — a member for it would invite someone to set it.
