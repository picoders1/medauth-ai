# ADR-010: Deterministic Decision Engine and LLM Containment

**Status:** Accepted · **Date:** 2026-08-23 · **Phase:** Planning
**The load-bearing ADR of this system.** ADR-001 sets the principle; this fixes the mechanism.

## Context

ADR-001 decided that models produce per-criterion verdicts and code produces the decision. This ADR
specifies the decision function, the enforcement of the boundary, and the containment layers that
depend on it.

## Problem

1. What exactly is the function from verdicts to a recommendation?
2. What stops that boundary from decaying into a convention as the codebase grows?
3. Given that the firewall's measured indirect-injection recall is **0.1423** (n=520; its
   `eval/results/20260817T130736Z__indirect-delivery-shape/report.md`), what actually
   contains an injection that reaches the adjudicator through retrieved policy text?

## Options

| # | Option | Assessment |
|---|---|---|
| A | Model emits the recommendation; code validates | The model decides; validation is a filter over a decision already made. |
| B | Model emits a recommendation *and* verdicts; code cross-checks | Two sources of truth. Disagreement has no principled resolution. |
| C | **Model emits verdicts only; code computes the recommendation** | Single source of truth. Decision surface is a pure function. |
| D | Weighted scoring over verdicts | Tunable, but the weights are unexplainable to a reviewer and denial becomes a threshold artefact. |

## Decision

**Option C**, with a rule-ordered table, structural enforcement, and five containment layers.

### The function

```
decide(verdicts, guardrail, resolution, criteria_tree, config) -> Recommendation
```

Pure — no I/O, no clock, no randomness, no model. Total. Tree logic (`ALL_OF`, `ANY_OF`, `N_OF`) is
evaluated bottom-up, then the table applies, evaluated in order, first match wins:

| # | Condition | Outcome |
|---|---|---|
| 1 | Zero applicable policy versions | `NEEDS_INFO` |
| 2 | Conflicting applicable versions | `HUMAN_REVIEW` |
| 3 | Any citation failed validation | `NO_DECISION` |
| 4 | Any model call blocked (403) or failed closed (503) | `HUMAN_REVIEW` |
| 5 | Verdicts contradict each other | `HUMAN_REVIEW` |
| 6 | Any **required** criterion `INSUFFICIENT_EVIDENCE` | `NEEDS_INFO` + missing-evidence list |
| 7 | An **exclusion** criterion `SATISFIED` with valid evidence | `DENY_RECOMMENDED` |
| 8 | A **required** criterion `NOT_SATISFIED` with valid evidence | `DENY_RECOMMENDED` |
| 9 | All required `SATISFIED`, no exclusion `SATISFIED` | `APPROVE_RECOMMENDED` |
| 10 | Otherwise | `HUMAN_REVIEW` (totality guard; reaching it is a defect signal and is counted) |

The abstention gate (ADR-011) then runs on rows 7–9 only, and may **downgrade** to `NEEDS_INFO`,
never upgrade.

### Enforcement — five AST-checked rules

Written in Phase 0, before there is anything to violate. The test parses source rather than
importing, so a violation is caught even if the module never runs.

1. `app/core` imports nothing from `app/`.
2. `app/decision` imports only `app/core`; no I/O, no model, no database.
3. `app/adjudication` and `app/intake` cannot import `app/decision`; `Recommendation` is not
   importable inside them.
4. Domain packages cannot import `app/graph` or `app/api`.
5. `langgraph` is importable only inside `app/graph`.

Plus a schema test: **no model output schema anywhere contains an approval or denial member.**

### Containment layers

| # | Layer | Effect on an injection that reaches the adjudicator |
|---|---|---|
| 1 | Fenced delivery, explicit data framing, never in the system prompt | Reduces compliance; does not prevent it |
| 2 | **Closed output schema** | The instruction "approve this" has no field to write into — the token does not exist |
| 3 | **Span-verified quotes** | A forged justification fails validation ⇒ `NO_DECISION` |
| 4 | **Code computes the decision** | A flipped verdict is one input among many, subject to rows 1–6 |
| 5 | **Per-criterion isolation** | Compromising one call cannot cascade; each call is independent and single-turn |

Layers 2–5 are structural. They hold whether or not the injection is *detected* — which matters,
because at 0.1423 recall it usually will not be.

## Rationale

**Row order is the safety design.** Rows 1–6 are all checked before any denial is reachable. In
particular row 6 (missing evidence) precedes rows 7 and 8 (evidenced failure), which is the
distinction between *"the note does not say"* and *"the note says otherwise"*. Collapsing them
would make the system deny for missing paperwork — the most common harm pattern in automated prior
authorization, and here it is structurally unreachable.

**Purity buys exhaustive testing of the branch that matters.** The truth-table suite covers every
reachable combination with no model and no network, in milliseconds. That is the only way to gain
real confidence in the path that produces a denial.

**Determinism buys replayable audit.** Same inputs, same recommendation, forever. `decision_rule_matched`
records which row fired, so a recommendation is *explainable* rather than merely reported.

**Rejecting weighted scoring is deliberate.** Weights are tunable, and a tunable denial threshold is
a dial that will eventually be turned. Rules are arguable in a review; weights are not.

## Consequences

**Positive.** The invariant is enforced, not described. Denial logic is inspectable line by line.
Injection cannot directly produce an outcome. Recommendations are reproducible and explainable.
Threshold changes are configuration, versioned and audited.

**Negative.** The table must be exhaustive; adding an outcome means revisiting every row. Novel
combinations land on row 10, which requires investigation rather than a widened row 9. Rule ordering
must be *correct* — a reordering is a clinical behaviour change and needs an ADR amendment.

**Neutral.** More `NEEDS_INFO` and `HUMAN_REVIEW` outcomes than a model-decides system. That is the
design, and coverage is reported explicitly so the trade is visible rather than implied.

## Rejected alternatives

| Alternative | Rejected because |
|---|---|
| **A — model decides, code validates** | Validation over an existing decision cannot restore an invariant already broken. |
| **B — both, cross-checked** | Two sources of truth with no principled tie-break. Disagreement would be resolved by a third rule, which is Option C with extra steps and extra tokens. |
| **D — weighted scoring** | Unexplainable to a reviewer and turns denial into a threshold artefact. "Why was this denied?" must be answerable with a criterion and a citation, not a weight vector. |
| **Rules in configuration rather than code** | Tempting for flexibility, but the decision table *is* the safety property. It belongs in version-controlled code with a test suite; only thresholds are configuration (ADR-017). |
