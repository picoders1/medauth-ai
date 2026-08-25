# R-86 gate recheck: identical conditions, identical result

**Artefact:** `eval/reports/r86-gate-recheck/results.json` ·
**Script:** `scripts/r86_gate_recheck.py` · **Reproducer:** `r86-factorial-001`, unmodified
**Gate: FAIL** · **Status: OUTSIDE ENGINEERING CONTROL**

---

## Part A — the registered conditions still hold

Compared field by field against `factorial_preregistration.json` **before any call**.
A recheck that quietly adapted to a changed environment would measure a different
experiment and report it under the old id, so drift is a refusal rather than a note.

| field | registered | observed |
|---|---|---|
| model digest | `sha256:31d69bc24c21` | **same** |
| temperature | 0.0 | **same** |
| `max_output_tokens` | 1536 | **same** |
| attempts per observation | 1 | **same** |
| structured mode | `json_schema` | **same** |
| firewall path | MEDAUTH → firewall → provider, one caller key | **same** |
| design | 8 cells × 6 trials | **same** |
| acceptance threshold | 0.10 | **same** |

**No drift.** The stack had been restarted since Phase 16 — a real change in external
state, and the reason this check is not ceremonial.

The threshold is read from `eval.validity.ValidityRule`, never restated in the gate.
A second copy of a number that must not move is a second place it can move.

## Part B — the re-run

Same schema, same prompt, same clinical-content shape, same caller key, same model
interface, same temperature, same firewall and gateway path.

| cell | prompt tokens | R-86 | Phase 16 |
|---|---|---|---|
| flat / filler / short | 91 | 0/6 | 0/6 |
| flat / filler / long | 204 | 0/6 | 0/6 |
| flat / gold_note / short | 107 | 0/6 | 0/6 |
| flat / gold_note / long | 191 | 0/6 | 0/6 |
| intake / filler / short | 409 | 0/6 | 0/6 |
| intake / filler / long | 522 | 0/6 | 0/6 |
| intake / gold_note / short | 428 | 0/6 | 0/6 |
| **intake / gold_note / long** | **512** | **6/6** | **6/6** |

**Cell for cell identical.** Under conditions verified unchanged, that is evidence the
defect persists — not evidence that nothing was tried.

### The failing cell

```
finish_reason      length            (all 6)
completion_tokens  1536  = ceiling   (all 6)
whitespace         0.9205            (all 6)
body_chars         2389              (all 6)
parsed as JSON     no                (all 6)
failure kind       SCHEMA_GRAMMAR_FAILURE
attribution        INDETERMINATE
median latency     6476 ms
deterministic      yes
```

Six identical responses at temperature 0. **That determinism is the useful part**: the
owner can reproduce this exactly rather than hunting an intermittent.

## Part C — the gate

```
production-shape failure   6/12 = 0.5000
pre-registered ceiling     0.10
result                     FAIL
```

Read from `intake/gold_note/*` and **only** those cells. The gradient scored 0/56 on a
two-field probe, so a gate reading the flat cells would certify a green light through
the exact outage it exists to catch — asserted by
`test_the_gate_reads_the_production_shape_and_ignores_the_easy_cells`.

The rule was applied, not reinterpreted. No threshold moved, no cell was excluded, no
request shape changed.

## Part D — OD-40, and why no live signal was added

Both endpoints were probed rather than dismissed on paper. Neither can see this
failure:

> R-86 returns **HTTP 200**. It is a decoder failing to terminate on a specific
> request shape. No health endpoint reports it and no capability listing mentions it.
> **A gate reading `/health` would report GREEN through the outage that made two
> evaluations uninterpretable.**

So the pre-registered diagnostic remains the experiment precondition and **OD-40 stays
open**. Closing it by adding a probe that cannot see the failure would be worse than
leaving it open: it would look like monitoring.

What would change it: a provider- or firewall-exposed signal describing
constrained-decoding behaviour — a stop-condition guarantee, or a metric counting
`finish_reason=length` on schema-constrained requests.

## Part 2 — attribution

`INDETERMINATE`, unchanged. MEDAUTH reaches the provider only through the firewall and
holds no provider credential; a decoder that pads and a proxy that pads are
indistinguishable from one hop. **No factor result licenses naming either**, and the
escalation asks the owner rather than answering for them.

## What this does not license

- **not** lowering the acceptance threshold;
- **not** changing the reproducer's request shape;
- **not** excluding the failing cell;
- **not** running the evaluation anyway and labelling the result degraded — that
  spends a hold-out to confirm a prediction already in writing.

```bash
uv run python scripts/r86_gate_recheck.py --verify-only          # Part A, no calls
MEDAUTH_LIVE_MODEL=1 uv run python scripts/r86_gate_recheck.py --write
```
