# Phase 12 — Real Model Activation

**A model has now been called.** Live, through the firewall, schema-validated into
the internal contract. That sentence could not be written before 2026-08-25.

Everything below was found by making the call. None of it was visible from the
fixture suite, which was green throughout.

---

## The three findings that mattered

### 1 · The runtime was pointed at a model that cannot do structured output

The live capability probe found the two configured models support **inverted**
structured-output modes:

| role | strict `json_schema` | `tool_call` | `json_object` |
|---|---|---|---|
| structured-output model | **5/5 schema-valid** | 502 | 5/5 returned, **0/5 schema-valid** |
| general `llm_model` | 502 | 5/5 schema-valid | 502 |

The application was configured to use the second for everything. Adjudication would
have failed on its first clinical case.

Fixed by routing structured roles separately (`llm_structured_model`,
`app/llm/wiring.py`). The routing is a **measurement**, not a preference.

That middle column is the one worth keeping: same model, same prompt, `json_object`
instead of `json_schema` — five well-formed JSON responses, **zero** satisfying the
schema. Conformance here is structural, enforced by the decoder, not cooperative
compliance the validator happens to catch afterwards.

### 2 · The upstream refuses two consecutive `user` turns

The first smoke call failed with `502 upstream_error / "The upstream model is
unavailable"` — deterministically, 3/3, while `tool_call` on the same path returned
200. Not availability: **a request-shape rejection wearing an availability message.**

Bisected to strict role alternation. `FirewallGateway` had been sending instructions
and evidence as two consecutive `user` turns to keep them apart.

The fix moved the trusted half into `system` and left retrieved text in `user`.
**Different roles, not merely different turns** — a stronger separation than the one
it replaced. The two rejected alternatives are worth recording: merging them into one
turn would have dissolved the distinction, and inserting a synthetic `assistant` turn
would have put words in the model's mouth to satisfy a transport.

### 3 · Grammar-constrained decoding does not guarantee termination

The clinical finding of this phase.

Intake calls burned **3 × 60 s and returned nothing**. The cause, measured directly:

```
completion_tokens 2000, finish_reason "length"
whitespace        98.6% of output
tail              "    \n" repeated to the ceiling
```

**JSON permits arbitrary whitespace between tokens, so a constrained decoder can
satisfy the schema forever without closing the document.** The grammar guarantees the
output *shape*. It does not guarantee the output *ends*.

Two contributing causes, both real:

**The model-facing schema contained fields the model cannot know.** `IntakeResult`
requires `prompt_id`, `model_id` and per-fact `extraction_prompt_id` — all ours, all
joined afterwards anyway. The model could not supply them and could not stop either.
`IntakeExtraction` now contains only what a model can produce; `extract_facts` joins
the rest. **A model-facing schema must contain only fields the model can actually
produce.**

**Pretty-printing is absorbing.** Once the model begins indenting, it does not stop.
A compact-output instruction keeps it out of that mode: 3/3 terminated at ~436
tokens with it, 0/3 without.

That instruction is a **prompt-level mitigation for a decoder-level defect (R-86)**,
and it is fragile by construction: it relies on the model honouring an instruction,
which is the one thing a grammar constraint exists not to rely on. It reduced the
failure rate; **it did not eliminate it** — one intake call in the final matrix still
ran away, at 48.6 s. A `max_output_tokens` ceiling only converts the hang into a
truncation. A decoder-side stop condition would be the real fix and is not ours.

---

## What the live path proves

```
MEDAUTH -> SliceRunner (gate enforced) -> FirewallGateway -> llm-firewall -> provider
```

- a real model's output reaches `CriterionAssessment` and passes validation
- the deterministic engine still owns the recommendation — **no live run produced an
  approval or denial from the model**
- every gateway failure became an abstention, none became a decision
- the production gate stands in front of the runner, not just the script

## What it does not prove

`MODEL_REASONING_QUALITY_NOT_YET_EVALUATED`. Seven hand-built scenarios are a
contract check. No scenario carries an expected model answer, nothing was compared to
ground truth, and no clinical claim is available from this evidence.
