# 410.61 Evaluation Repair — `retrieval_eval_v3`

**v2 is not modified. v3 is derived from it by provenance.**

---

## What broke, and why it is not a regression

Phase 6 made `ENGINEERING_INFERRED` code links inadmissible for production
resolution: applicability may not rest on resemblance (ADR-004). 42 CFR 410.61 was
reachable only through two such links (`G0295`), so every v2 query targeting it now
fails resolution in production.

That is the intended behaviour of a correct rule, not damage. What it damages is the
*measurement*: a query that cannot resolve measures nothing, and leaving 12 of them
in a denominator of 52 understates every rate for a reason unrelated to retrieval.

## The repair

`scripts/build_retrieval_v3.py` derives `eval/datasets/retrieval_v3/questions.yaml`
from v2, keeping only queries the provenance audit classifies `VALID_*`.

| | |
|---|---|
| v2 queries | 52 |
| kept in v3 | **36** |
| excluded — `INVALID_INFERRED` | 12 |
| excluded — `REQUIRES_REVIEW` | 4 |

**Selection is on provenance, computed before any arm ran.** No query was dropped
for scoring badly, and every exclusion is listed in the file with its reason, so the
difference between v2 and v3 is inspectable rather than asserted.

## What survives, and what thins out

All ten query categories survive — asserted by test, because an exclusion that
removed a whole category would silently narrow what the benchmark can detect, and
the negative queries most of all.

But two categories thin materially:

| category | v2 | v3 |
|---|---|---|
| `CROSS_VERSION` | 4 | **2** |
| `DIRECT` | 8 | 6 |
| `PARAPHRASED` | 5 | 3 |
| `AMBIGUOUS` | 3 | 2 |

The `CROSS_VERSION` loss is the one to note: the 410.61 temporal pair is gone, so
cross-version evidence now rests on **one policy** (410.38). Temporal scoping is
still exercised, on a narrower base than v2 exercised it.

Criterion coverage drops from 35 of 35 to **21 of 35**.

## v3 has never been scored

No report exists for it, and **no number from v2's report may be attributed to it** —
the denominators differ. A test asserts both: `scored: false` in the file, and no
`*retrieval-v3*` directory under `eval/reports/`.

Whether and how to re-measure is **OD-28**, and that decision belongs *before* the
run. Choosing after seeing which set produces better figures is exactly what OD-22
already warns about.

## What is not done

- **v2 is untouched** — 52 queries, `version: "2"`, asserted by test.
- **v1 is untouched.**
- **The inferred links are not restored.**
- **gold_v1 is untouched.**
