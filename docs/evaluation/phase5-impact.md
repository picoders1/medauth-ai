# Phase 5 Impact on Evaluation

**gold_v1 is byte-identical. Half of it is no longer usable to validate production.**

Both halves are true, and neither is a defect. This records `gold_v1_impact`: what
fail-closed semantics cost the evaluation corpora, and why production adjudication
and historical replay now deliberately diverge.

---

## gold_v1 integrity — VERIFIED

| | |
|---|---|
| `gold_v1.jsonl` sha256 | matches the manifest, byte-for-byte |
| cases | 156, unchanged |
| synthetic corpus | 222, regenerates byte-identically |
| labels changed | **0** |
| expected decisions changed | **0** |
| criterion states changed | **0** |
| scoring budget | 0 of 1 spent |
| gold_v2 | **not created** |

Regeneration was run into a temporary directory and diffed against the committed
file. Byte-identical.

## What changed

The logic inventory classifies four of eight policy versions `REVIEW_REQUIRED`.
Production now refuses to execute them.

| | adjudicable | blocked |
|---|---|---|
| policy versions | 3 of 8 | 5 |
| **gold_v1** | 78 | **78 (50%)** |
| synthetic | 111 | **111 (50%)** |

Blocked versions: `42 CFR 410.33`, `42 CFR 410.38` (both revisions), `42 CFR 411.15`
(all `REVIEW_REQUIRED`) and `42 CFR 410.43` (`NO_CRITERIA`).

Measured by `scripts/report_adjudicability.py` into
`data/policy_logic/production_coverage.json`, with a test asserting the counts
against the datasets so this page cannot drift from the data.

## Production and replay diverge, deliberately

gold_v1's labels were computed before the inventory existed, under an assumed
conjunction. Three options existed:

1. **Change the labels** — refused. A frozen split is a record of a completed
   construction; editing it destroys what every earlier measurement was measured
   against (ADR-015).
2. **Abandon label reproduction** — discards half the corpus's value as a regression
   set, and the project could no longer show that its decision function reproduces
   its own dataset.
3. **Reproduce the assumption explicitly, and refuse it in production.**

Phase 5 took (3). `eval/replay.py::gold_v1_semantics` reproduces the historical
assumption, stamped `GOLD_V1_REPLAY`, and `app/policy/semantics_guard.py` refuses it
in production on two independent grounds:

- **origin** — `GOLD_V1_REPLAY` is not in `PRODUCTION_ORIGINS`
- **digest** — its attestation names gold_v1's *manifest*, whose hash can never
  match the logic inventory loaded at startup

It lives outside `app/`, and two AST rules enforce that: no module under `app/`
imports `eval` or `scripts`, and no production module *references* the replay origin
in code.

**Honest limit:** a determined in-process caller can defeat an in-process check. The
claim is narrower and true — the *accidental* path fails closed, and the *deliberate*
path is visible in the recommendation, in the audit row, and in grep.

## What this means for evaluation

**Still valid.** All 222 labels reproduce through the replay path. The corpus remains
a regression set for `decide()`'s table rows, criterion-state derivation and dataset
consistency.

**No longer valid.** The 78 blocked gold cases cannot validate production behaviour.
A recommendation produced for one says what the system *would have said in the
data-foundation phase* — not what it should say now. **They cannot be used to
validate an agent.**

**The usable evaluation subset is 78 of 156 gold cases**, on `42 CFR 410.32`
(`DECLARED`) and `42 CFR 410.61` (both revisions, `ASSUMED_CONJUNCTION`).

## Retrieval evaluation

Unchanged in substance. The scope contract changed — `search_chunks` now takes a
`RetrievalScope` naming one policy type — but `eval/runners/retrieval*.py` filter
candidates by version id in Python rather than through `search_chunks`, so the v1
and v2 retrieval reports remain valid for the corpus they were run against.

**Known limitation:** those runners scope by version id without a document-type
partition. With the CFR-only corpus they were run against, no crossing is possible.
Before the next retrieval measurement over a corpus containing NCDs, they must adopt
`scope_for()`. Recorded as **R-62**.

## Claims this phase does NOT support

- **Not** that decision quality improved. Nothing about accuracy was measured.
- **Not** that the criterion set is more complete. 246 provisions still await review.
- **Not** clinical validation. No clinician has seen any case.
- **Not** CMS corpus completeness. 11 NCDs were selected deliberately; 10 acquired.
- **Not** NCD temporal completeness. 3 of 19 versions have no published effective
  date and are unresolvable — that is a property of the source.
- **Not** that passing tests proves clinical correctness. They prove the code
  implements the declared behaviour.
