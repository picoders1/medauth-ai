# ADR-011: Abstention Strategy and Calibration Protocol

**Status:** **Pre-registered** — criteria fixed before execution · **Date:** 2026-08-23
**Phase:** Planning; executed in Phase 6 · **Amendment required** before Phase 6 step 2 (OD-8)

## Context

The system must abstain when its evidence is inadequate. The brief explicitly rejects
`confidence < 0.5 → abstain` and asks for a calibration strategy.

## Problem

1. What does the gate read?
2. How are thresholds chosen without contaminating the evaluation?
3. What would demonstrate abstention improves **safety** rather than merely reducing coverage?

## Options

### What the gate reads

| # | Option | Assessment |
|---|---|---|
| A | Model-reported confidence | Free. Not a probability, correlated with fluency rather than correctness, and manipulable by anything in the context — including injected text. |
| B | **Deterministic features from the pipeline** | Checkable, unmanipulable, explainable. Requires design and calibration. |
| C | Self-consistency across *k* samples | Genuine signal. Multiplies adjudication cost by *k*. |
| D | A trained calibrator over features | Best frontier if data supports it. ~30 dev cases is thin for fitting. |

## Decision

**Option B as the foundation**, with C as a candidate feature (OD-5) and D as a constrained second
stage adopted only if it beats the rule stage on measurement.

### Gate features

| Feature | Definition |
|---|---|
| `criteria_coverage` | required criteria with ≥1 valid citation ÷ required criteria |
| `citation_validity_rate` | valid citations ÷ citations offered |
| `evidence_density` | mean valid citations per decided criterion |
| `rerank_margin` | min across criteria of (top score − score at cutoff) |
| `resolution_uniqueness` | 1 if exactly one policy version resolved |
| `criteria_tree_reviewed` | 1 if the tree is `HUMAN_REVIEWED` |
| `contradiction_count` | from the guardrail |
| `self_consistency` | agreement across *k* independent adjudications (OD-5) |
| `model_self_report` | **at most one weak feature; never used alone** |

### Gate form

1. **Rule stage** — hard constraints, not traded off against anything:
   `resolution_uniqueness = 1`, `citation_validity_rate = 1`, `contradiction_count = 0`,
   `criteria_coverage ≥ τ_cov`.
2. **Scored stage** — monotone-constrained logistic regression over the remaining features,
   thresholded at `τ_approve` and `τ_deny`, with **`τ_deny > τ_approve`**.

The gate may downgrade rows 7–9 to `NEEDS_INFO`. It can never upgrade.

### Calibration protocol (pre-registered)

```
[1] fix the gate on DEV only
[2] coverage-vs-accuracy sweep      (dev)
[3] unsafe-decision analysis        (dev)
[4] threshold selection             (dev)
[5] ONE scored validation           (TEST, frozen, budget-decremented)
```

Steps 1–4 touch dev only, enforced at the library boundary: `eval/schema.py:require_tunable(split)`
raises on a frozen split, and every calibration entry point calls it.

**Selection rule, fixed now:** choose the **lowest** threshold whose dev unsafe-decision-rate upper
Wilson bound is at or below the configured ceiling. **Iterate upward and return the first
qualifying value.** (Scanning downward returns the endpoint instead of the first hit — a bug that
has occurred three times in the sibling project. A unit test asserts the direction.)

**The ceilings are not yet set.** They must be written into this ADR **before** step 2 runs (OD-8).
Choosing them after seeing the sweep would be retuning criteria against results.

### Unsafe is not the same as wrong

| Error | Class |
|---|---|
| Denial where gold is approve | **Unsafe** |
| Decision issued on an invalid citation | **Unsafe** |
| Decision on the wrong policy version | **Unsafe** |
| Approval where gold is deny | Costly, not unsafe |
| `NEEDS_INFO` where gold is a decision | Coverage loss, not unsafe |

### Success criterion — the claim to be earned

> *"Abstention improves safety rather than merely reducing coverage."*

Permitted only when a committed report shows the unsafe-decision rate falling **faster than
coverage**, paired on the same cases by exact McNemar, with intervals stated. Until that artefact
exists the claim is not made — not softened, not hedged.

### Pre-registered failure modes

Declared now, so none can later be presented as a discovery:

1. The gate reduces coverage without reducing unsafe decisions → **negative result, reported, claim
   not made.**
2. `~30` dev cases are too few to fit a scored stage → fall back to the rule stage alone and say so.
3. `self_consistency` adds no signal over `criteria_coverage` and `rerank_margin` → dropped, and its
   cost is not paid (OD-5).
4. The rule stage alone already gates everything the scored stage would → the scored stage is not
   adopted.

## Rationale

**Model self-report is not a probability**, and building the safety gate on it would return the
model to control of the decision through a side channel, undoing ADR-010. An injected instruction
can raise a stated confidence; it cannot forge a span-verified citation.

**The chosen features are all quantities the system already computes and the guardrail already
verifies**, so the gate costs nothing extra and is explainable to a reviewer in plain terms: "two of
five required criteria had no supporting citation."

**Asymmetric thresholds follow from asymmetric harm.** `τ_deny > τ_approve` because a wrong denial
withholds care while a wrong approval costs money. One threshold would average two different risks.

**Interpretability is a requirement, not a preference.** A monotone logistic model yields a
coefficient table a clinical reviewer can read. An uninterpretable gate deciding when the system
declines to answer is difficult to defend in a clinical review — which is the setting this system
must survive.

## Consequences

**Positive.** The gate cannot be manipulated by context. Every abstention is explainable. Thresholds
are versioned configuration recorded on each recommendation. `gate_features` are persisted, so
recalibration replays over historical cases **without re-running any model**.

**Negative.** Feature design is manual work. Small dev denominators limit what can be fitted (R-20).
Hard rules may abstain on cases a human would decide. Adding a feature later means recalibrating.

**Neutral.** Coverage will be lower than an ungated system. That is the intent; the reports state
coverage explicitly rather than leaving it implied.

## Rejected alternatives

| Alternative | Rejected because |
|---|---|
| **A — model confidence threshold** | Not calibrated, correlated with fluency, and manipulable by injected content. The brief rejects it and the rejection is correct. |
| **D alone — trained calibrator on all features** | Roughly 30 dev cases cannot support fitting a flexible model. Adopted only as a constrained second stage behind hard rules. |
| **Gradient-boosted calibrator** | Better frontier is plausible, but an uninterpretable abstention gate cannot be defended in a clinical review. |
| **No abstention; always decide** | Contradicts the governing invariant and guarantees decisions on inadequate evidence. |
| **Abstain on any imperfection** | Coverage near zero. The gate must be measured, not maximised. |
