# R-86 — the closure gate

**Rule:** `r86-closure.v1` (`eval/r86_closure.py`) · **Threshold:**
`provider-failure-validity.v1`, 0.10, unchanged · **Runner:**
`scripts/r86_revalidate.py`

R-86 is closed when the **registered** reproducer succeeds. Not when the provider
explains it, not when a different shape works, not when a client-side workaround makes
the symptom go away.

---

## 1. The conditions

R-86 is `CLOSED` only if the exact registered production-shaped reproducer:

1. executes successfully;
2. produces **valid, closed** JSON;
3. does **not** terminate via completion-length exhaustion;
4. does **not** produce runaway whitespace;
5. satisfies the same registered schema contract;
6. passes the required trial count (6 per cell, 12 total);
7. stays at or below the existing **0.10** failure threshold.

The request shape must not be changed to make the defect disappear. The threshold must
not be changed. The provider configuration used by the official experiment stays
identified and sealed.

## 1a. Two things this gate is repeatedly misread as

Both misreadings arrived together in a revalidation request on 2026-08-27, and both
would have unblocked the gate on evidence that says nothing about it. Recorded here
because the wording invites them.

### "6/12" is a failure RATE, not a count of satisfied requirements

`eval/reports/r86-revalidation/20260825T155710Z.json` records:

```json
"production_failures": 6, "production_trials": 12,
"production_failure_rate": 0.5, "acceptance_threshold": 0.1, "result": "FAIL"
```

Six of twelve **trials failed** — a 50% failure rate against a 10% ceiling. It is not
"six of twelve conditions met", and there is no list of twelve requirements anywhere.
The number twelve is condition 6 above: six trials in each of two cells.

Read as a scorecard, `6/12` looks like meaningful progress toward a threshold. Read
correctly, it is five times the maximum permitted failure rate.

### R-86's "production shape" is a REQUEST shape, not a deployment environment

This is the more dangerous one, because the phrase now names two unrelated things in
this repository:

| | |
|---|---|
| **R-86 "production-shaped reproducer"** | the production `IntakeExtraction` schema and a long gold clinical note, sent to the model provider. The cells are `intake/gold_note/long` and `intake/gold_note/short` |
| **deployment "production-shaped environment"** | HTTPS, a canonical issuer, TLS verification, a persistent Keycloak, a clean image (`docs/deployment/production-shape-contract.md`) |

They share an adjective and nothing else. R-86 is a decoder that does not terminate;
the deployment work is about how MEDAUTH is served and who may review a case.

**No amount of deployment evidence can close this gate**, and the gate is built so it
cannot be offered any: `eval/official_gate.py` reads exactly two artefacts — the sealed
reproducer manifest and the most recent revalidation. It has no input for TLS, an
issuer, an image digest or a smoke result, so the question "does the production-shaped
deployment satisfy R-86?" has no mechanism by which it could.

The only thing that closes R-86 is the registered reproducer succeeding.

## 2. A defect this definition uncovered (R-106)

Conditions 3 and 4 were **not enforced**. Writing them down is what exposed it.

`scripts/r86_revalidate.py` decided whether a trial succeeded by asking the failure
taxonomy, and the taxonomy decides by asking whether the call **raised**:

```python
if error is None:
    return ProviderFailure(kind=ProviderFailureKind.NONE, ...)
```

That is right for the taxonomy — it classifies errors, a successful call is not an
error, and it deliberately refuses any parameter about whether the answer was good.
It was wrong as a *closure* definition, and the difference is exploitable by a partial
fix.

**The response that would have passed.** Suppose the provider closes the document but
keeps padding to the ceiling:

```
{"conditions": [...], ...}<2000 characters of whitespace>
```

Then, in order:

| | |
|---|---|
| `json.loads(body)` | **succeeds** — trailing whitespace is legal JSON |
| `satisfied_schema` | `True` |
| the call raises | no — so `failure_kind` is `NONE` |
| `counts_toward_provider_reliability` | `False` |
| the trial counts as | **SUCCESS** |

Six of those and the gate returns **PASS at 0/12**, the official evaluation is
authorised, and the provider path is still burning 1536 completion tokens and 6.3
seconds per call on whitespace that means nothing.

R-86 is *non-termination*. **A document that closes and then pads has not terminated;
it has become parseable.** Those are different properties and the gate was checking
the wrong one.

The taxonomy already computed `looks_like_whitespace_runaway` and recorded
`is_r86_signature` on every observation. Nothing consulted either when deciding the
gate. The signal was measured and then discarded at the one place it decided
something — the same shape as R-99, where the instrument hid the defect it was built
to find.

## 3. Why this is a strengthening, not a retune

Changing what counts as a failure after seeing results is exactly what this regime
forbids. So, stated rather than assumed:

**It cannot alter any recorded result.** Of the 164 observations committed under
`eval/reports/`, **zero** satisfied the schema while exhibiting the runaway shape. The
Phase-17 gate recheck and the Phase-18 revalidation both still read 6/12 = 0.5000. A
test asserts this and will fail if it ever stops being true.

**It can only make PASS harder.** Every condition can add a failure; none can remove
one. A rule that can only tighten cannot be a rule tuned toward a favourable answer —
the direction is wrong for that.

**It is registered before the run it governs**, which is the order the
pre-registration regime requires. Nothing has been scored under it.

## 4. What is *not* changed

| | |
|---|---|
| threshold | **0.10**, in `eval/validity.py`, compared against the seal on every run |
| request shape | exactly as sealed; `verify_against_seal()` blocks on any drift |
| schema, model, prompt, temperature, ceiling | untouched |
| the taxonomy | keeps its contract and its accuracy-blindness |

`r86-closure.v1` adds an independent condition on top of schema validity. It removes
nothing.

## 5. The verdicts, demonstrated

| trial | verdict |
|---|---|
| R-86 as observed — unterminated, 92% whitespace | **FAILURE** |
| control cell as observed — `stop`, 9% whitespace | SUCCESS |
| **partial fix — closes, then pads to the ceiling** | **FAILURE** |
| genuine fix — closes and stops | SUCCESS |
| unobservable trial (no shape recorded) | **FAILURE** |

The last one matters on its own. A trial whose termination cannot be checked is not a
successful trial — the same reason `INCONCLUSIVE` blocks exactly as `FAIL` does at the
gate above this one.

## 6. What closure does not accept

**A different configuration is not a fix.** If the provider's answer is "use a
different model / a different schema / a different API mode / a different runtime",
that does not close R-86. It is a `NEW_SYSTEM_CONFIGURATION` and needs a new
configuration digest, a new experiment identity, a new pre-registration and a new
baseline. The existing experiment is not overwritten. See
[../operations/r86-provider-remediation.md](../operations/r86-provider-remediation.md).

**A client-side repair is not a fix.** Whitespace stripping, forced JSON repair,
retry-until-success, a raised completion limit, a simplified schema, a shortened
prompt or a truncated clinical note would each make the symptom go away without the
provider path terminating. Any of them may be investigated later as a separate,
pre-registered **containment** experiment. None of them closes R-86, and the closure
rule is written so that they cannot: conditions 3 and 4 are about the provider's
generation, not about what we can salvage from it.

## 7. The only transition

```
provider-side fix evidence
        ↓
MEDAUTH_LIVE_MODEL=1 uv run python scripts/r86_revalidate.py --write
        ↓
PASS  →  the official evaluation gate opens
FAIL / INCONCLUSIVE  →  blocked, identically
```

`eval/official_gate.py` reads the **latest** revalidation, not the best one. A
historical PASS never overrides a later FAIL, and `INCONCLUSIVE` is not permission.
