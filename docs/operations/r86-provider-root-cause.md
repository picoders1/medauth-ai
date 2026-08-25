# R-86 — the provider-side root-cause question

**For:** the model provider. **Attribution:** [r86-provider-attribution.md](r86-provider-attribution.md).
**Evidence:** `data/escalations/r86-firewall-capture.json`, `r86-provider-attribution.json`.

The firewall has been eliminated by its owner's own append-only records. One question
remains, and this document does **not** answer it.

---

## 1. The question

> **Why does the constrained-decoding provider path, for this exact registered request
> shape, generate a deterministic whitespace-dominated response that reaches the
> completion limit without closing the JSON document?**

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

## 4. Leading hypotheses — listed, not selected

**None of these is asserted, and no ranking is implied.** They are here so the owner's
investigation has a starting shape, not so this document can claim a conclusion it has
not earned. MEDAUTH cannot distinguish between them and does not try.

1. **Grammar-constrained decoder termination behaviour** — the decoder reaches a
   structurally complete state and does not treat it as terminal.
2. **Whitespace token handling after a structurally complete state** — JSON permits
   arbitrary whitespace between tokens, so a grammar that admits it unconditionally
   admits it forever.
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

Questions 1 and 2 are the pair that matters most: everything else narrows, but
"complete, and yet it kept going" is the defect stated in one line.

Question 7 is now largely answered from our side — the firewall is eliminated — but is
kept because a provider-side reproduction outside the proxy is stronger evidence than
our elimination of the proxy, and costs the owner very little.

## 6. What an answer changes here

Nothing automatically. An explanation is not a fix, and a fix is not a closure: closure
is defined in [../evaluation/r86-closure-gate.md](../evaluation/r86-closure-gate.md)
and is decided by re-running the registered reproducer, not by agreeing that the cause
makes sense.
