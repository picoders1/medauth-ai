# `phase16-evaluation-001`: authorised? No.

**Verdict:** `eval/reports/phase16-410-33/AUTHORISATION.json` ·
**Status: `NOT_AUTHORISED`** · **Blocker: `provider_gate` (Part C)**
**gold_v2 scoring budget: 0 of 1 — unspent.**

---

## The decision

Fifteen preconditions, all evaluated — the check does not short-circuit, because
"the provider path is the only thing wrong" is a materially different statement from
"the provider path is wrong and so are three other things", and only an exhaustive
pass can tell them apart.

| part | check | |
|---|---|---|
| **C** | **provider gate** | **STOP** — FAIL, 6/12 = 0.5000 against a 0.10 ceiling |
| A | recheck conditions unchanged | PASS |
| C | validity rule matches the manifest | PASS |
| C | threshold unchanged | PASS |
| I | gold_v1 immutable | PASS — `ca990b80…` |
| I | gold_v2 matches its manifest | PASS — `000cba13…`, 156 cases |
| I | gold_v2 unmoved since the freeze | PASS |
| I | gold_v2 budget unspent | PASS — 0 of 1 |
| I | structured applicability provenance | PASS — 156 re-derived from input + linkage |
| I | no narrative-only ground truth | PASS |
| E | prompt versions | PASS — `intake.v2`, `adjudication.v1` |
| E | model digest | PASS — `sha256:31d69bc24c21` |
| E | applicability version | PASS — `sha256:34296cff9b95` |
| E | gateway configuration digest | PASS — `sha256:47b96c93a407` |
| J | retrieval configuration | PASS — `ENGINEERING_DEFAULT_UNRESOLVED`, top_k 40 |
| J | retrieval baseline matches the frozen configuration | PASS — R@1 24/31, same settings |

**Fourteen of fifteen pass. The one that fails is not ours.**

## What did not happen, and what that cost

The official evaluation **did not run**. No per-case record, no metrics, no failure
analysis, no coverage report — and `test_no_official_result_exists_for_an_unauthorised_experiment`
asserts their absence, because a gate that stops the run and lets the artefacts
appear anyway has stopped nothing.

Every metric Part G asks for is therefore **NOT PRODUCED**, not estimated. There is no
partial run to quote, no subset to extrapolate from, and no degraded figure to caveat.

**The cost is zero and reversible.** gold_v2's single scoring is unspent. When the
provider gate passes, the experiment executes exactly as frozen against a hold-out
that has never seen its own answers.

## Why running anyway would have been worse than not running

The validity rule would have returned `DEGRADED_BY_PROVIDER_FAILURE` — ADR-029 says
so **in advance**, so it would have been a confirmed prediction rather than a finding.
The hold-out would be gone and the next attempt would need a new dataset or a new ADR.

Phase 14 and Phase 15 each froze a correct manifest, passed every internal condition,
spent a scoring, and learned afterwards that a third of the cases never reached a
model. That is the failure mode this gate exists to stop, and stopping it is the
deliverable.

## The frozen manifest was not edited

An authorisation is *about* a manifest, not part of one. Rewriting a frozen manifest
to record that it was refused would make the freeze conditional on the outcome, so the
verdict is a sibling file and records the manifest's digest.

## Not permitted in response

Written into the artefact so the next reader does not have to re-derive them:

- lowering the acceptance threshold;
- changing the reproducer's request shape;
- excluding the failing cell;
- running anyway and labelling the result degraded.

## What unblocks it

1. R-86 owned and bounded by whoever holds the provider or the firewall — evidence and
   exact asks in [the escalation](../escalations/R-86-unbounded-whitespace.md); the
   reproducer is deterministic.
2. `scripts/r86_gate_recheck.py` returning `PASS` under unchanged conditions.
3. `scripts/phase16_authorisation.py` returning `AUTHORISED`.

None is an engineering task in this repository.

```bash
uv run python scripts/phase16_authorisation.py --write
```
