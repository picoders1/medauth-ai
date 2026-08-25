# The official-evaluation gate

**Module:** `eval/official_gate.py` — the **only** thing that may authorise an
official run. **Current state: `BLOCKED`.**

---

## What it protects

Scoring a frozen hold-out is irreversible. gold_v2 has one scoring; spend it on a run
whose result is predetermined by an outage and it is gone, and the next attempt needs
a new dataset or a new ADR.

Phase 14 and Phase 15 each froze a correct manifest, passed every *internal*
condition, spent a scoring, and learned afterwards that a third of the cases never
reached a model. This gate is the thing that was missing.

## What it reads

1. **The sealed reproducer** (`data/escalations/r86-reproducer.manifest.json`) — does
   the live configuration still match the one the evidence describes?
2. **The latest revalidation** (`eval/reports/r86-revalidation/`) — did the registered
   production shape pass, under the pre-registered threshold?

Both must hold. Either missing is `INDETERMINATE`.

```python
from eval.official_gate import OfficialEvaluationGate

OfficialEvaluationGate.evaluate().require()  # raises EvaluationBlocked
```

## Three states, one of them permitting

| state | |
|---|---|
| `AUTHORISED` | the only state that permits an official run |
| `BLOCKED` | a revalidation FAILED |
| `INDETERMINATE` | no seal, no revalidation, a stale one, a broken seal, or a moved threshold |

`INDETERMINATE` **blocks exactly as `BLOCKED` does.** Uncertainty is not permission,
and giving it its own name stops it drifting into whichever neighbour is convenient.

`permits_official_evaluation` is an identity test against `AUTHORISED`, so a fourth
state added later is refused by default rather than admitted by omission.

## Bypass-proof by construction, not only by behaviour

There is **no** `force`, `skip`, `override`, `assume`, `disable` or `debug` parameter
anywhere in the module, and **no environment read**. That is asserted over the
module's own AST, because a behavioural suite can be entirely green against a gate
carrying a `force=True` that no test happens to pass.

A parameter is somewhere to pass `True` from. An absence is not. The same technique
keeps `RunMode.REPLAY` out of `PRODUCTION_MODES` and `GOLD_V1_REPLAY` out of
`PRODUCTION_ORIGINS` — the third time this repository has needed it.

A separate test parses **every script** and fails on any argparse flag starting with a
bypass token: a gate nobody can bypass, with a `--force` on the runner beside it, is a
gate with a door next to it.

## `require()` raises

A boolean is something a caller can ignore, and the callers that matter are scripts
written at the end of a long day. The failure mode of forgetting to check is a
traceback, not a scored hold-out.

## Replay is a different question

`RunMode.REPLAY` reproduces a historical label under a designated policy. It has its
own mode, its own finding reason (`DESIGNATED_WITHOUT_RESOLUTION`) and its own audit
stamp. **It neither consults this gate nor can satisfy it** — a gate satisfiable by a
replay would be satisfiable by a fixture. The gate does not name `REPLAY` anywhere in
code, and a test asserts that too.

## Ways a `PASS` could be manufactured, and why none works

| attempt | outcome |
|---|---|
| run under a different configuration | `INDETERMINATE` — the revalidation carries the seal digest it ran against |
| move the threshold and re-run | `INDETERMINATE` — the live ceiling is compared to the sealed one |
| hand-edit the sealed manifest | `INDETERMINATE` — it no longer matches its own digest |
| keep the earlier `PASS` and ignore the later `FAIL` | the **latest** run decides, not the best |
| drop the failing cell | fewer trials than registered → `INDETERMINATE` |
| add `--force` to a runner | fails `test_no_script_offers_a_forced_evaluation_path` |

Each is injected in `tests/evaluation/test_official_gate.py` and confirmed, and
`AUTHORISED` is proven reachable so none of them passes vacuously.

## Current state

```
state                    BLOCKED
reason                   R-86 revalidation FAILED: 6/12 = 0.5000 exceeds 0.10
seal                     r86-reproducer-001, intact
latest revalidation      20260825T155710Z.json — FAIL
```
