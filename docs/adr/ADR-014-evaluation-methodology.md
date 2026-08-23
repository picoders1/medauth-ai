# ADR-014: Evaluation Methodology

**Status:** **Pre-registered** — criteria fixed before execution · **Date:** 2026-08-23
**Phase:** Planning; executed in Phase 6

## Context

The project must produce quantitative evidence about decision quality, grounding, abstention and
operations. The corpus is ~200 constructed cases, ~150 gold-labelled.

## Problem

1. How are the four measurable layers separated?
2. How is leakage prevented in all four of its forms?
3. What can honestly be claimed at these denominators?

## Options

| # | Option | Assessment |
|---|---|---|
| A | One end-to-end accuracy number | Simple, and hides which layer failed. |
| B | **Layer-separated measurement with independent denominators** | Diagnostic. More harness work. |
| C | LLM-as-judge over outputs | Scales. Circular — a model grading a model's output on cases a model helped construct. |

## Decision

**Option B**, with LLM-as-judge permitted only for faithfulness on a human-spot-checked sample.

### Four layers, four denominators

| Layer | Unit | Approx. denominator |
|---|---|---|
| Policy resolution | case | ~150 |
| Retrieval | criterion-query | ~1,000+ |
| Grounding | citation | thousands |
| Decision | case | ~150 |

Retrieval and grounding are measured at far larger denominators than decision quality — deliberately,
because that is where statistically meaningful statements are actually available.

### The statistical limitation, fixed before any result exists

At ~25–40 cases per class, a 95% Wilson interval on a rate near 0.85 spans roughly **±10–15
percentage points**. Therefore:

- Differences below roughly 15 pp between per-class rates are **not detectable and are not claimed**.
- Every per-class figure is reported with `n` and its interval. A bare percentage is not permitted.
- Configuration comparisons use **exact McNemar** on paired same-corpus runs.
- Stronger statements are sourced from the retrieval and grounding layers.

### Leakage controls

| Leakage | Control |
|---|---|
| Train/test | Hash split: `int(sha256(normalised_key(text))[:8], 16) % 100 < 20 → dev`. Both the `[:8]` slice and the boundary are load-bearing; changing either silently moves samples between splits |
| Gold-set contamination | Tuning on dev only, enforced by `require_tunable(split)` raising on a frozen split at the library boundary |
| Policy leakage | A case's constructed pattern is never injected into its own retrieval context |
| Prompt leakage | No gold label or expected outcome appears in any rendered prompt; asserted by scanning outgoing prompts |

### Scoring budget

The test split records its scoring count. Phase 6 spends **one**. Further scorings require a prior
ADR stating the reason. Re-scoring a frozen split until a number improves is how an evaluation
becomes fiction.

### Reporting

Every run writes `eval/reports/<ISO8601>__<slug>/` carrying dataset hash and version, split, `n` per
class, git commit, model id, prompt versions, corpus snapshot, decision-config version and machine
metadata. **A figure that cannot be traced to such a report appears nowhere in this repository** —
not in the README, not in an ADR, not on a CV, not in an interview.

### Pre-registered failure modes

1. Denominators too small for the differences of interest → intervals reported, claims withheld.
2. Metrics look strong because cases are constructed → the generalisation claim stays **refused**.
3. Abstention reduces coverage without reducing unsafe decisions → **negative result, reported**
   (ADR-011).
4. A retrieval or resolution defect dominates decision error → reported as a layer finding, not
   absorbed into decision accuracy.

## Rationale

**Layer separation is diagnostic, not cosmetic.** A single accuracy number cannot distinguish a
resolution defect (a data or rule problem), a retrieval defect (a ranking problem), a grounding
defect (a citation problem) and a reasoning defect (a model problem) — which are fixed by four
different actions.

**Denial precision is reported separately, always.** A system strong overall and weak at denial is
not acceptable, and macro-F1 hides exactly that. Asymmetric harm requires asymmetric reporting.

**Stating the statistical limitation before results** makes it impossible to quietly omit
afterwards. This is the difference between an evaluation and a demonstration.

**LLM-as-judge is confined to faithfulness on a spot-checked sample** because everywhere else it
would be a model grading a model on cases a model helped build — the circularity ADR-015 exists to
break.

**Enforcing the dev/test boundary in code, not in discipline**, because discipline fails under
deadline. `require_tunable` raises.

## Consequences

**Positive.** Failures are attributable to a layer. Claims are bounded by evidence. Reports are
reproducible from committed artefacts. Regression gating works against committed reports, so CI
needs no API key.

**Negative.** Substantial harness work before any number exists. Small denominators bound what can
be concluded, permanently. The scoring budget means a disappointing test result cannot be
re-litigated — which is the point, and will be uncomfortable.

**Neutral.** Human-review metrics are instrumented but unclaimable without a pilot (OD-7).

## Rejected alternatives

| Alternative | Rejected because |
|---|---|
| **A — single accuracy number** | Cannot attribute failure to a layer, and would let a retrieval defect masquerade as a reasoning defect. |
| **C — LLM-as-judge as the primary method** | Circular, and would let the evaluation inherit the exact biases it exists to detect. |
| **Larger gold set instead of accepting the limitation** | More cases would help, but constructed cases do not become real notes by being numerous. The binding limitation is construction, not count — so the count is stated honestly rather than inflated. |
| **Report only aggregate metrics** | Hides denial performance, which is the metric with asymmetric harm. |
