# R-86: what two controlled experiments established, and what they withdrew

**Artefacts:** `eval/reports/r86-gradient/` — `preregistration.json`, `results.json`,
`factorial_preregistration.json`, `factorial_results.json`
**Harness:** `scripts/r86_gradient.py` · **Escalation:**
[R-86-unbounded-whitespace.md](../escalations/R-86-unbounded-whitespace.md)
**Status:** `OUTSIDE_ENGINEERING_CONTROL`. Not fixed, not fixable here.

---

## Phase 15's conclusion is withdrawn

Phase 15 reported R-86 as **input-length dependent**, from three observations at two
lengths. Phase 16 tested that properly and it does not hold.

### `r86-gradient-001` — length alone, seven bands, 56 observations

Everything held constant except payload length: same model, prompt, schema,
temperature, ceiling, caller key, gateway, firewall path. Synthetic seeded filler, so
a band is byte-reproducible and no note text leaves the machine.

| payload words | prompt tokens | provider failures | median whitespace |
|---|---|---|---|
| 25 | 66 | 0/8 | 0.2045 |
| 60 | 109 | 0/8 | 0.2045 |
| 120 | 185 | 0/8 | 0.2143 |
| 200 | 287 | 0/8 | 0.1765 |
| 320 | 423 | 0/8 | 0.1765 |
| 480 | 656 | 0/8 | 0.1875 |
| 700 | **908** | 0/8 | 0.1765 |

**0/56.** Nothing failed at any length, including 908 prompt tokens — nearly double
the ~510 at which Phase 15's real intake calls padded. Whitespace is flat across the
whole range.

**The pre-registered hypothesis is not supported.** Phase 15's arms varied length
*and* schema *and* content simultaneously, so "length dependent" was the reading
available from an under-controlled comparison. It is withdrawn rather than defended.

### `r86-factorial-001` — the three factors, crossed

Declared **after** the null result and **before** any factorial observation, and the
artefact says so. 2 × 2 × 2 cells, 6 trials each.

| cell | prompt tokens | R-86 | median whitespace |
|---|---|---|---|
| flat / filler / short | 91 | 0/6 | 0.2045 |
| flat / filler / long | 204 | 0/6 | 0.1765 |
| flat / gold_note / short | 107 | 0/6 | 0.2195 |
| flat / gold_note / long | 191 | 0/6 | 0.2000 |
| intake / filler / short | 409 | 0/6 | 0.0873 |
| **intake / filler / long** | **522** | **0/6** | 0.2786 |
| intake / gold_note / short | 428 | 0/6 | 0.0933 |
| **intake / gold_note / long** | **512** | **6/6** | **0.9205** |

## The decisive comparison

    intake / filler   / long   522 prompt tokens   0/6
    intake / gold_note/ long   512 prompt tokens   6/6

**Same schema. Same length band. Ten fewer tokens. Zero failures versus six.**

R-86 needs the **conjunction** of the production `IntakeExtraction` schema, a longer
input, *and* real clinical-note content. No single factor reproduces it: 0/24 on the
flat schema, 0/24 on filler content, 0/24 on short inputs. Every marginal rate in the
report is 6/24 and every one of those six is the same cell — the signature of a
three-way conjunction, not of a main effect. The report refuses an interaction claim
at 6 trials per cell and reports marginals with their denominators.

**Deterministic.** 6/6 at temperature 0, identical completion tokens (1536, the
ceiling), identical whitespace fraction, identical body length. The provider can
reproduce this exactly.

## The instrument was wrong first

The first execution reported those six as `MALFORMED_RESPONSE` with
`is_r86_signature: False`. `classify_provider_failure` tested *"did the body parse?"*
before *"is this a runaway?"* — and a runaway never closes its document, so it never
parses. The taxonomy hid the thing it was built to find.

Ordering corrected, matrix re-executed unchanged, both recorded in
`factorial_results.json`. A measuring device was repaired; no hypothesis, threshold
or cell moved after seeing a result.

## What is still not known

`PROVIDER_DECODER` and `FIREWALL_PROXY` remain **indistinguishable from here**, and
no factor result licenses naming either. What changed is the question the owner has
to answer:

> Under grammar-constrained decoding of a multi-array schema, does the decoder emit
> unbounded whitespace on some inputs and not others? The failing request is
> deterministic and its exact shape is reproducible from the harness.

Streaming would separate generation from post-processing cleanly and the firewall
refuses it with 400. Recorded as closed, not untried.

## What MEDAUTH can and cannot do about it (Part A4)

| candidate mitigation | verdict |
|---|---|
| request-size preflight | **refused — the evidence does not support it.** 522 prompt tokens of filler succeed 6/6 and 512 of clinical text fail 6/6. A length threshold would reject working requests and admit failing ones |
| content-based preflight | **refused.** A heuristic deciding whether clinical evidence may reach the model is worse than the defect |
| silent truncation of a note | **forbidden.** Discarding clinical evidence to satisfy a decoder |
| raising `max_output_tokens` | **refused.** Converts a bounded truncation back into a 180-second hang; a decoder that pads to 1536 pads to 4000 |
| **name the failure at case level** | **adopted.** `PROVIDER_LIMITATION` — routing unchanged, attribution now correct |
| **bound the damage** | **already in place.** Ceiling + timeout + bounded repair; the case fails to a human and never to a recommendation |
| **gate the evaluation on it** | **adopted.** `scripts/phase16_prerun_gate.py` refuses to authorise a run while the production-shape failure rate exceeds the validity ceiling |

**No local mitigation is evidence-based**, and saying so is the finding. The one
thing MEDAUTH added is honest accounting: the failure is named, attributed, counted
in the operational denominator, and excluded from decision quality.

## Reproducing

```bash
uv run python scripts/r86_gradient.py --plan                       # the matrix, no calls
MEDAUTH_LIVE_MODEL=1 uv run python scripts/r86_gradient.py --write
MEDAUTH_LIVE_MODEL=1 uv run python scripts/r86_gradient.py --factorial --write
```

No payload text, no clinical text, no model id and no base URL enters either report —
digests, counts and categories only, asserted by
`tests/evaluation/test_phase16_recovery.py`.
