# R-86 — temperature perturbation diagnostic

**Experiment:** `r86-temperature-perturbation-001` · **Parent:** `r86-reproducer-001`
(`sha256:271127edace3d94d`) · **Artefacts:**
`eval/experiments/r86-temperature-perturbation-001/{manifest.json,results.json}`

A diagnostic. It is not a fix, not an official evaluation, not a model-quality
benchmark and not a production configuration change. **R-86 is unchanged:**
`VERIFIED_FAILURE / PROVIDER_SIDE / UNRESOLVED`, official evaluation `BLOCKED`.

---

## 1. Hypothesis and registration

Registered before any call, and the manifest refuses to be re-frozen.

> Does a small amount of decoding stochasticity change the observed
> constrained-decoding runaway behaviour?

The prior it was built to test: §3b of
[r86-provider-root-cause.md](r86-provider-root-cause.md) noted that
`intake/filler/long` escaped a 770-character whitespace stretch under the same schema,
so an exit exists and is reachable — which, under greedy decoding at temperature 0,
would look like a fixed point on a whitespace token. That reading was recorded as
"consistent with every measurement and cheap to kill." This is the cheap test.

## 2. The one changed variable

| | |
|---|---|
| **changed** | `temperature`, **0.0 → 0.2** |
| unchanged | model, prompt, schema, request shape, gateway, firewall, caller identity, completion ceiling (1536), request mode (`json_schema`, `strict`), attempts (1) |
| trials | **6**, fixed in the manifest before the run |
| cell | `intake/gold_note/long` |

Enforced, not asserted. The runner calls `verify_against_seal()` — the revalidation's
own function, reused unmodified — and aborts before the first call if any sealed digest
differs. All eight agree. It separately aborts if `r86_gradient.TEMPERATURE` is no
longer `0.0`, because then there would be no baseline to perturb against, and if the
trial count disagrees with the frozen manifest.

The request is built by `_factorial_request()` — **the function the sealed reproducer
calls**, not a copy. A second implementation would agree with the first until it did
not, and the entire value of this experiment is that exactly one field differs.

The reproducer itself is untouched: `TEMPERATURE` is still `0.0` and a test asserts
that `_observe_cell`'s default is exactly that constant. The deviation is not "the
reproducer now runs at 0.2"; it is "the reproducer, still registered at 0.0, was
invoked once at 0.2 under its own experiment id."

## 3. Results

Six trials, all six failing under `r86-closure.v1`.

| trial | ctok | body | ws | **non-ws** | chars/tok | parsed | finish | signature |
|---|---|---|---|---|---|---|---|---|
| 1 | 1536 | 2389 | 0.9205 | 190 | 1.56 | no | length | R-86 |
| 2 | 1536 | 2389 | 0.9205 | 190 | 1.56 | no | length | R-86 |
| 3 | 1536 | 2389 | 0.9205 | 190 | 1.56 | no | length | R-86 |
| 4 | 1536 | 2389 | 0.9205 | 190 | 1.56 | no | length | R-86 |
| **5** | **1536** | **3818** | **0.1315** | **3316** | **2.49** | **no** | **length** | **not R-86** |
| 6 | 1536 | 2389 | 0.9205 | 190 | 1.56 | no | length | R-86 |

## 4. Comparison with temperature 0.0

| | temp 0.0 | temp 0.2 |
|---|---|---|
| failure rate | 6/6 | **6/6** |
| valid JSON rate | 0/6 | **0/6** |
| termination reason | `length` ×6 | **`length` ×6** |
| whitespace fraction | 0.9205 ×6 | 0.9205 ×5, **0.1315** ×1 |
| non-whitespace chars | 190 ×6 | 190 ×5, **3316** ×1 |
| deterministic | yes, byte-identical | **no** — 2 distinct signatures |
| output length | 2389 ×6 | 2389 ×5, **3818** ×1 |

## 5. Interpretation

The pre-registered band is `RUNAWAY_PERSISTS` (6 failures of 6), and its registered
interpretation, verbatim:

> The failure persists under this temperature perturbation. This does **not** establish
> that temperature is unrelated to the root cause — one perturbation at one value is
> insufficient to show that.

### Trial 5 is the finding, and it cuts against the prior

Five trials reproduced the greedy signature **byte-identically** — 2389 characters,
0.9205 whitespace, 190 non-whitespace. One did not: trial 5 produced **3316
non-whitespace characters at 13% whitespace**, escaping the whitespace attractor
entirely.

**And it still ran to the ceiling without closing.**

So the sampler did leave the whitespace path, and termination did not follow. That is
evidence *against* "a fixed point on a whitespace token" being the whole mechanism —
the hypothesis §3b flagged as cheap to kill is, at minimum, incomplete. Whitespace
looks like one manifestation of a failure to terminate rather than the failure itself.

**This is not proof, and there is a competing reading.** Trial 5 may simply be an
ordinary length truncation: with more randomness the model wrote more, and 1536 tokens
genuinely ran out. Nothing here distinguishes the two. What can be said is that 3316
characters of extraction from a 1058-character clinical note is a great deal of output
for the task, and that the taxonomy classified it `MALFORMED_RESPONSE` rather than the
R-86 signature — a *different* failure, correctly, on the same request.

### A second observation, offered as data

At temperature 0.2, five of six trials were byte-identical to the greedy output. For a
non-zero temperature that is a striking amount of agreement, and it is consistent with
the whitespace continuation holding a large share of the probability mass rather than
merely winning the argmax. **No causal model is fitted to six trials**, and this is
recorded as an observation the owner can check against their own logits, not as a
conclusion.

### Claims refused

Registered in the manifest before the run and repeated here: temperature is the root
cause · the provider bug is confirmed as greedy decoding · temperature is unrelated to
the root cause · anything about clinical correctness or model quality · anything about
whether R-86 is fixed.

## 6. Limitations

**One value, one cell, six trials.** 0.2 was chosen as a small perturbation, not as a
sweep. A different value could behave differently and this says nothing about any.

**No mechanism is observable from here.** MEDAUTH sees an HTTP response. Whether the
decoder considered itself complete, what the grammar admitted, and where the
probability mass sat are all provider-internal.

**Trial 5 is ambiguous**, as above, and one observation is not a rate.

**This cannot authorise anything.** The official system is registered at temperature
0.0; a result obtained at 0.2 describes a different decoding path.
`eval/official_gate.py` reads only sealed revalidations and does not know this
experiment exists.

## 7. Conclusion

The runaway persists at temperature 0.2. The one trial that escaped the whitespace
pattern **still failed to terminate**, which points away from a whitespace-specific
mechanism and toward termination itself — and gives the provider a sharper thing to
look for than "it emits whitespace."

R-86 remains `VERIFIED_FAILURE / PROVIDER_SIDE / UNRESOLVED`. The official evaluation
remains `BLOCKED`. Production stays at temperature 0.0; nothing here recommends
changing it, and changing it on this evidence would be a
`NEW_SYSTEM_CONFIGURATION` rather than a fix
([r86-provider-remediation.md](r86-provider-remediation.md)).
