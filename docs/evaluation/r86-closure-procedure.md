# R-86 — the closure procedure

The only legitimate path from the current state to an authorised evaluation. It is short,
and every step but the last belongs to someone other than MEDAUTH.

---

## Current state

`FAIL` — **6/12 = 0.5000** against a pre-registered ceiling of **0.10**. Official gate:
**`BLOCKED`**. `gold_v2` **unspent** at 0/1. The 26-case evaluation has never run.

## The sequence

```
CURRENT R-86 FAIL
        ↓
provider-side evidence          decoder state · EOS eligibility · grammar state ·
        ↓                       token/termination trace · runtime version ·
provider root cause established speculative-decoding participation
        ↓
provider-side correction
        ↓
independent verification        the registered shape, succeeding, before the gate is asked
        ↓
scripts/r86_revalidate.py       run by MEDAUTH, against the unchanged seal
        ↓
result PASS
        ↓
failure rate ≤ 0.10
        ↓
official gate → AUTHORISED
```

Nothing skips a step. In particular the revalidation is **not** the diagnostic: it is the
record made after the correction is believed to work, and a revalidation run hoping for a
pass is an experiment run twice until it agrees.

## What must not change, and why each would invalidate the result

| | |
|---|---|
| **the sealed reproducer** | The gate compares the revalidation's `seal_sha256` against the manifest. A pass under a different configuration is a pass for a different system, and the gate says so rather than accepting it |
| **the registered schema** | The production `IntakeExtraction` shape is one of the three factors whose *conjunction* produces the failure. Simplifying it removes the phenomenon rather than fixing it |
| **the gold note** | Same: real clinical content is a second factor. A shorter or synthetic note is a different cell |
| **`max_tokens` 1536 · `temperature` 0.0 · `json_schema` · strict · non-streaming** | Each is held constant in the sealed manifest. Changing one makes the comparison to the recorded failure meaningless |
| **the threshold `0.10`** | Pre-registered before the result was known. Moving it after the fact is the definition of retuning to the observed behaviour, and the seal records the value so the gate can refuse a mismatch |
| **six trials per cell, both cells** | Fewer trials, or dropping `intake/gold_note/long`, removes the failing evidence rather than the failure |
| **the evaluator** | `eval/official_gate.py` has no `force`, no `override` and reads no environment variable, asserted over its own AST. Making it say yes requires editing it, and the edit is visible in the diff |
| **`gold_v1` / `gold_v2`** | `gold_v1` is frozen at 2/2 and `gold_v2` is unspent. Neither is touched by any step above |

## Two things that are not fixes

**A modified request that succeeds is a different experiment.** If the corrected system
only passes with a shorter note, a flatter schema or a raised ceiling, then R-86 has not
been closed — a different, easier question has been answered. The closure contract
classifies this as `NEW_SYSTEM_CONFIGURATION`.

**Provider substitution is a different system configuration.** Repointing at another
model or runtime produces evidence about that model. It may well be the right *operational*
decision; it is not a closure of this finding, and must not be recorded as one.

## What MEDAUTH does, and what it does not

**Does:** hold the seal, run `scripts/r86_revalidate.py` when a correction is claimed,
record the outcome, and let `eval/official_gate.py` decide what that permits.

**Does not:** diagnose the decoder, apply a provider-side correction, or run the
revalidation speculatively. Local diagnostics are exhausted — three artefacts narrowed the
question without entering the provider, and everything further needs visibility MEDAUTH
correctly does not have.

## If it is never closed

That is an acceptable outcome and is already the recorded one. The evaluation stays
unrun, `gold_v2` stays unspent, and this repository continues to contain **no accuracy
figure of any kind**. A blocked evaluation is not a broken application — every application
guarantee is verified and passing, and the escalation package
(`docs/operations/r86-provider-escalation.md`) is complete enough for an external owner to
act without touching the registered experiment.
