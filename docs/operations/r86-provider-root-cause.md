# R-86 — the provider-side root-cause question

**For:** the model provider. **Attribution:** [r86-provider-attribution.md](r86-provider-attribution.md).
**Evidence:** `data/escalations/r86-firewall-capture.json`, `r86-provider-attribution.json`.

The firewall has been eliminated by its owner's own append-only records. One question
remains, and this document does **not** answer it.

---

## 1. The question

**This is the primary question. It supersedes the two earlier framings kept below.**

> **Why does the constrained decoder enter a non-terminating generation path while the
> JSON document is still structurally incomplete, allowing generation to continue until
> the completion limit is exhausted instead of reaching a valid terminal state?**

We are not asking you to optimise MEDAUTH's prompt, schema or usage. We are asking you
to explain — and fix — the constrained-decoding behaviour.

### Secondary questions

1. Does the decoder reach a valid grammar state from which EOS is legal?
2. If EOS is legal, why is it not selected or emitted?
3. If EOS is not legal, which grammar state prevents termination?
4. Does the decoder have an explicit terminal condition for JSON-schema completion?
5. Does whitespace consumption occur inside an **incomplete** grammar state?
6. Is there a decoder/runtime loop or state transition that can repeatedly consume
   whitespace or other non-structural tokens?
7. Why does the same schema terminate successfully for the comparison
   `intake/filler/long` request?
8. Why does temperature perturbation change the surface form in one trial without
   restoring valid termination?
9. Is the behaviour tied to this decoder/runtime version?
10. Is constrained decoding implemented through a separate decoder path from
    unconstrained generation?

### The two framings this replaces

Kept, not deleted — a record that erases what was believed at the time cannot be
audited. Both are marked in `data/escalations/r86-provider-attribution.json` under
`hypothesis_register`.

| framing | state | why |
|---|---|---|
| *"a deterministic whitespace-dominated response that reaches the completion limit"* (Phase 16) | **NARROWED** | true as description, but it names the surface form rather than the failure |
| *"an unbounded whitespace run from an incomplete JSON state"* (§3b) | **NARROWED** | trial 5 of the temperature diagnostic broke the whitespace pattern and still did not terminate |

**The standing statement:** the observed whitespace-heavy behaviour is a *manifestation*
of the non-termination failure mode, **not yet established as the underlying cause.**

## 2. What the request is

Unchanged from the seal (`r86-reproducer-001`, `sha256:271127edace3d94d`), and it must
stay unchanged — a defect that disappears when the request is altered has not been
fixed, it has been avoided.

| | |
|---|---|
| cell | `intake/gold_note/long` |
| model digest | `sha256:31d69bc24c21367e` |
| schema digest | `sha256:a89278d7f1c9eba5` — five sibling arrays of objects, each legal when empty |
| `response_format` | `json_schema`, `strict: true` |
| temperature | `0.0` |
| `max_tokens` | `1536` |
| `stream` | `false` |
| prompt tokens | 512 |
| attempts | 1 per observation, no client retries |

## 3. What is observed

Six trials, six failures, byte-identical at temperature 0:

```
finish_reason        length
completion_tokens    1536          (the ceiling, exactly)
body_chars           2389
whitespace_fraction  0.9205        ~2199 whitespace, ~190 characters of JSON prefix
parsed_as_json       false         the document never closes
latency              6.3 s         against 2.1 s on the control cell
```

The control cell `intake/gold_note/short` — same model, same schema, same ceiling,
same temperature, shorter input — succeeds 6/6 with `finish_reason: stop`, 478
completion tokens and 9.3% whitespace. **The difference is the input, not the
configuration.**

`r86-factorial-001` established that the failure needs the **conjunction** of the
production schema, a longer input and real clinical content: 522 filler tokens succeed
6/6, 512 clinical tokens fail 6/6. A controlled gradient varying only length returned
0/56 up to 908 prompt tokens, so length alone reproduces nothing.

## 3b. What the committed data already establishes

**No new calls were made to derive any of this.** It is arithmetic over
`eval/reports/r86-gradient/factorial_results.json` and
`eval/reports/r86-revalidation/20260825T155710Z.json`, and it sharpens the question
below considerably.

### The character economy of all eight factorial cells

| cell | completion tokens | body chars | whitespace | **non-whitespace** | parsed |
|---|---|---|---|---|---|
| `flat/filler/short` | 22 | 44 | 20.4% | 35 | yes |
| `flat/filler/long` | 23 | 51 | 17.6% | 42 | yes |
| `flat/gold_note/short` | 22 | 41 | 21.9% | 32 | yes |
| `flat/gold_note/long` | 23 | 45 | 20.0% | 36 | yes |
| `intake/filler/short` | 37 | 126 | 8.7% | 115 | yes |
| `intake/gold_note/short` | 478 | 1211 | 9.3% | 1098 | yes |
| `intake/filler/long` | 1028 | 2764 | 27.9% | 1994 | yes |
| **`intake/gold_note/long`** | **1536** | **2389** | **92.0%** | **190** | **no** |

Three things follow, and none of them is what the escalation has been assuming.

### 1. It did not run out of room. It produced almost nothing.

The failing cell emitted **190 non-whitespace characters** — *less than any other
`intake` cell*, and a sixth of what the short gold-note cell produced (1098) while
terminating cleanly in 478 tokens.

"The answer was too long for the ceiling" is therefore excluded. It generated a small
amount of content, stopped generating content, and spent the remaining ~1400 tokens on
whitespace.

### 2. The document never closes — so the padding starts while it is still **open**

`parsed_as_json: false` on **all twelve observations**, across two runs taken hours
apart. Trailing whitespace after a complete document would still parse; this does not.
The closing structure is never emitted.

**This contradicts the reading the escalation has carried since Phase 16.** Hypothesis
2 below is worded "whitespace token handling **after a structurally complete state**",
and the state is *not* complete. The whitespace is admitted at a point where JSON is
still expecting more content — between tokens inside an open object or array, where
the grammar legitimately permits it.

So owner-side question 1 has a provisional answer *from our side*: **no**, not as
observed on the wire. That does not settle what the decoder believed internally, which
is exactly why it stays on the checklist.

For scale: the minimal document that satisfies this schema — `case_id` is the only
required field and all five arrays are legal when empty — is **110 characters
compact**. The failing response carries 190 non-whitespace characters. It is in the
neighbourhood of a nearly-empty extraction, and it still never closed.

### 3. It is a deterministic fixed point, not sampling variance

At temperature 0, six trials in the factorial and six in the revalidation produced
**byte-identical** results: 1536 completion tokens, 2389 body characters, whitespace
fraction 0.9205, every time, hours apart. Whatever the decoder is doing, it does it
the same way every time.

### The one cell that argues against a grammar dead-end

`intake/filler/long` is the near-miss: same schema, 1028 completion tokens, **770
whitespace characters (27.9%)** — and it *closed*. The same schema can enter a
whitespace-heavy stretch and still escape it.

That matters, because it argues against "the grammar has no terminal state": if there
were no exit, this cell could not have taken one. It points instead toward an exit that
exists but is not reached — which, under greedy decoding at temperature 0, is what a
fixed point on a whitespace token would look like.

**That is a hypothesis and it is not selected.** It is recorded because it is
consistent with every measurement above and because it is cheap for the owner to
confirm or kill, not because MEDAUTH has any view into the decoder.

> **Update — `r86-temperature-perturbation-001` partly killed it.** Six trials on the
> same cell with **only** temperature changed (0.0 → 0.2) failed 6/6. Five reproduced
> the greedy signature byte-identically; **trial 5 escaped the whitespace pattern
> entirely** — 3316 non-whitespace characters at 13% whitespace — **and still ran to
> the ceiling without closing.** The sampler left the whitespace path and termination
> did not follow, so a fixed point on a whitespace token is at best incomplete as the
> mechanism. Whitespace looks like one manifestation of a failure to terminate rather
> than the failure itself. A competing reading of trial 5 — an ordinary length
> truncation of a genuinely long answer — is not excluded. See
> [r86-temperature-perturbation.md](r86-temperature-perturbation.md).

## 4. Leading hypotheses — listed, not selected

**None of these is asserted, and no ranking is implied.** They are here so the owner's
investigation has a starting shape, not so this document can claim a conclusion it has
not earned. MEDAUTH cannot distinguish between them and does not try.

1. **Grammar-constrained decoder termination behaviour** — the decoder reaches a
   structurally complete state and does not treat it as terminal. *§3b: not supported
   as worded on the wire — the document never closes, so no complete state is
   observable. Kept, because "complete internally, closing tokens never emitted" is a
   version of this the owner can see and we cannot.*
2. **Whitespace token handling after a structurally complete state** — JSON permits
   arbitrary whitespace between tokens, so a grammar that admits it unconditionally
   admits it forever. *§3b: the "after complete" clause is contradicted. The mechanism
   survives with the clause dropped: whitespace is legal between tokens of an **open**
   document too.* **NARROWED / NOT ESTABLISHED after
   `r86-temperature-perturbation-001`:** trial 5 escaped the whitespace pattern
   entirely and still failed to terminate, so whitespace handling cannot be the whole
   mechanism. Not retired — a whitespace-consumption loop remains possible as one path
   into a non-terminating state (secondary questions 5 and 6).
3. **Interaction between grammar-constrained decoding and the decoder/runtime** — the
   constraint and the sampler disagreeing about when generation may stop.
4. **Interaction between the production structured-output schema and decoding** — five
   sibling arrays each legal when empty is an unusual shape; the schema may reach
   satisfaction in a state the grammar cannot exit.
5. **Provider-side speculative/decoder/runtime defect** — including speculative
   decoding interacting with the constrained path.
6. **Other provider-internal cause** — the list is not claimed to be exhaustive.

Hypothesis 2 is the one the escalation has always named as most legible from outside,
and it is **still not selected**. It is legible precisely because it is the one
visible without provider telemetry, which is a reason to distrust its prominence
rather than to believe it.

## 4b. Provider-internal evidence we are asking for

Local diagnostics are exhausted. Three artefacts — `r86-factorial-001`,
`r86-firewall-capture-001` and `r86-temperature-perturbation-001` — have narrowed the
question without entering the provider, and everything further needs visibility
MEDAUTH correctly does not have.

**Any one of these can narrow the root cause substantially. We are not asking for all
eight.**

| # | evidence | what it would settle |
|---|---|---|
| 1 | decoder grammar/state trace for the failing request | which state the decoder is in when it stops making progress |
| 2 | EOS eligibility at the point the output begins looping | secondary questions 1–3, directly |
| 3 | grammar state at termination failure | whether a terminal state was reachable at all |
| 4 | decoder token-level trace for the failing cell | what is being emitted, and against what mass |
| 5 | comparison against the successful `intake/filler/long` cell | why the same schema terminates there and not here |
| 6 | constrained-decoding implementation / runtime version | whether this is version-specific (secondary question 9) |
| 7 | whether speculative decoding or another specialised path participates | secondary question 10 |
| 8 | whether the behaviour reproduces outside the firewall | corroborates our capture from your side |

**1 and 2 are the pair we would choose** if only one trace is available: "which state,
and was EOS legal there" is the failure stated in one line.

Item 8 is the weakest ask and the cheapest — our own capture already eliminates the
proxy (`r86-firewall-capture-001`), so this only corroborates.

## 5. Owner-side disambiguation checklist

These require provider-internal telemetry. **MEDAUTH has not run any of them and must
not** — it holds no provider credential, and running unauthorised provider tests is
outside both its access and its remit.

| # | question |
|---|---|
| 1 | Did the decoder reach a structurally complete JSON state? |
| 2 | If yes, why did generation continue? |
| 3 | Does the grammar allow trailing whitespace indefinitely? |
| 4 | Does the constrained decoder have an explicit terminal state? |
| 5 | Is EOS allowed after the complete schema? |
| 6 | Is the JSON grammar terminating on the same model/runtime version? |
| 7 | Does the issue reproduce outside the firewall? |
| 8 | Does the issue reproduce with the exact production schema? |
| 9 | Does the issue reproduce with the exact production prompt/input shape? |
| 10 | Does a simpler closed schema terminate correctly? |
| 11 | Does changing only schema structure alter the behaviour? |
| 12 | Is speculative decoding involved in the constrained path? |
| 13 | Is the problem model-runtime specific? |

**Four of these now have partial answers from our side** (§3b), and they are supplied
so the owner does not spend telemetry re-deriving them:

| # | what we can say, and its limit |
|---|---|
| 1 | **Not on the wire.** `parsed_as_json: false` on all twelve observations — the document never closes. Whether the decoder considered itself complete internally is exactly what we cannot see. |
| 4 | An exit **exists and is reachable**: `intake/filler/long` entered a 770-character whitespace stretch under the same schema and still closed. So this is unlikely to be a grammar with no terminal state. |
| 10 | **Yes.** The `flat` schema terminates on the same clinical content — 0/24 R-86 across all four `flat` cells, `finish_reason: stop`. |
| 11 | **Yes.** Schema structure is the only factor that never fails: `schema=flat` is 0/24, `schema=intake` is 6/24. |

Questions 1 and 2 remain the pair that matters most, restated for what is actually
observed: **it stopped producing content at ~190 non-whitespace characters, never
closed, and padded to the ceiling — deterministically.** Question 12 gains weight from
§3b's determinism finding, since a speculative-decoding interaction would also
reproduce byte-identically at temperature 0.

Question 7 is now largely answered from our side — the firewall is eliminated — but is
kept because a provider-side reproduction outside the proxy is stronger evidence than
our elimination of the proxy, and costs the owner very little.

## 6. What an answer changes here

Nothing automatically. An explanation is not a fix, and a fix is not a closure: closure
is defined in [../evaluation/r86-closure-gate.md](../evaluation/r86-closure-gate.md)
and is decided by re-running the registered reproducer, not by agreeing that the cause
makes sense.
