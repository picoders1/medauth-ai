# Decision Engine and Abstention

**Status:** Implemented, **uncalibrated**. The decision function and the abstention gate exist
and are tested. **No calibrated threshold exists and none may be quoted** — every recommendation
reports `confidence_state = UNCALIBRATED`, and that remains true.
**Authoritative for:** the decision function, the abstention gate, and the calibration protocol.

---

## 1. The decision function

```
decide(verdicts, guardrail, resolution, criteria_tree, config) -> Recommendation
```

Pure: no I/O, no clock, no randomness, no model. Total: every input maps to an outcome. This is
what makes the decision surface exhaustively testable as a truth table with nothing loaded, and
what makes an audit row replayable.

`app/decision/` may import only `app/core`. Asserted by AST test.

### The table

Evaluated in order; first match wins. The ordering is a safety property in itself.

| # | Condition | Outcome | Rationale |
|---|---|---|---|
| 1 | Resolution returned zero applicable policy versions | `NEEDS_INFO` | Absence of policy is not non-coverage (§3) |
| 2 | Resolution returned conflicting versions | `HUMAN_REVIEW` | Genuine policy conflict is a human judgement |
| 3 | Any citation failed validation | `NO_DECISION` | No evidence → no decision |
| 4 | Any model call blocked (403) or failed closed (503) | `HUMAN_REVIEW` | The reasoning is incomplete by construction |
| 5 | Verdicts contradict each other | `HUMAN_REVIEW` | The system does not adjudicate its own inconsistency |
| 6 | Any **required** criterion is `INSUFFICIENT_EVIDENCE` | `NEEDS_INFO` | Missing evidence is a request, not a denial |
| 7 | An **exclusion** criterion is `SATISFIED` with valid evidence | `DENY_RECOMMENDED` | Positively evidenced exclusion |
| 8 | A **required** criterion is `NOT_SATISFIED` with valid evidence | `DENY_RECOMMENDED` | Positively evidenced non-satisfaction |
| 9 | All required `SATISFIED`, no exclusion `SATISFIED` | `APPROVE_RECOMMENDED` | |
| 10 | Otherwise | `HUMAN_REVIEW` | Totality guard; reaching it is a defect signal and is counted |

Tree logic (`ALL_OF`, `ANY_OF`, `N_OF`) is evaluated bottom-up before the table is applied. A
parent's verdict is derived from its children by its own operator; `INSUFFICIENT_EVIDENCE`
propagates upward unless the operator can be decided without the undecided child (an `ANY_OF` with
one child already `SATISFIED` is `SATISFIED`).

### Row 6 versus row 8 — the distinction that matters most

These two rows separate *"the note does not say"* from *"the note says otherwise"*.

- Row 6: no evidence bearing on the criterion was found → **ask** (`NEEDS_INFO`).
- Row 8: evidence was found and it establishes non-satisfaction → **deny** (with citations).

Collapsing them would make the system deny for missing paperwork. That is the single most common
harm pattern in automated prior authorization, and the ordering here makes it structurally
unreachable: row 6 is evaluated before rows 7 and 8, so any required criterion lacking evidence
routes the whole case to `NEEDS_INFO` regardless of what other criteria say.

---

## 2. Denial is asymmetric

A wrong approval costs money. A wrong denial withholds care. The system treats these differently:

1. **Evidence bar.** Denial requires ≥1 valid, span-verified citation *and* ≥1 referenced intake
   fact on the criterion that fails. Absence of evidence never reaches rows 7 or 8.
2. **Always human-mandatory.** There is no configuration in which `DENY_RECOMMENDED` is actionable
   without human review. The reviewer console renders it as a *draft rationale for a human
   decision*, never as a decision.
3. **Separate reporting.** Denial precision is reported with its own denominator and interval, not
   folded into macro-F1. A system that is excellent overall and poor at denial is not acceptable,
   and an aggregate metric hides exactly that.
4. **Separate gate.** The abstention gate applies a stricter threshold to denial than to approval
   (§4). The thresholds are two values in configuration, not one.

---

## 3. Absence of policy is not denial

Zero applicable NCD/LCD generally means contractor discretion or case-by-case adjudication under
Medicare, not non-coverage. Mapping "I found no policy" to a denial would be wrong as a matter of
domain fact and wrong in the direction that harms patients.

Row 1 makes it unreachable. A test asserts that no combination of verdicts and guardrail results
can produce `DENY_RECOMMENDED` when `resolution.applicable_versions` is empty.

---

## 4. The abstention gate

The gate runs **after** the table, and only on rows 7, 8 and 9. It can downgrade a recommendation
to `NEEDS_INFO`. It can never upgrade one.

### 4.1 Why not a model-reported confidence

An LLM emitting `confidence: 0.87` is producing a token sequence, not a probability. It is not
calibrated, it is correlated with fluency rather than correctness, and it is manipulable by
anything in the context — including injected policy text. Building the safety gate on it would put
the model back in control of the decision through a side channel, undoing §1.

The gate therefore runs on **deterministic, checkable features**:

| Feature | Definition | Direction |
|---|---|---|
| `criteria_coverage` | required criteria with ≥1 valid citation ÷ required criteria | higher is better |
| `citation_validity_rate` | valid citations ÷ citations offered | higher is better |
| `evidence_density` | mean valid citations per decided criterion | higher is better |
| `rerank_margin` | top rerank score − score at cutoff, per criterion (min across criteria) | higher is better |
| `resolution_uniqueness` | 1 if exactly one policy version resolved, else 0 | binary |
| `criteria_tree_reviewed` | 1 if the tree is `HUMAN_REVIEWED` | binary |
| `contradiction_count` | from the guardrail | lower is better |
| `self_consistency` | agreement across *k* independent adjudications of the same criterion | higher is better |
| `model_self_report` | the model's own stated confidence | **at most one weak feature; never used alone** |

`self_consistency` is the most expensive feature (it multiplies adjudication cost by *k*) and its
value is an open question — whether it adds signal over `criteria_coverage` and `rerank_margin` is
measured in Phase 6 before it is adopted (OD-8).

### 4.2 Gate form

Phase 6 begins with the simplest form that could work and adds complexity only if measurement
justifies it:

1. **Rule gate** — hard constraints first: `resolution_uniqueness = 1`, `citation_validity_rate = 1`,
   `contradiction_count = 0`, `criteria_coverage ≥ τ_cov`. These are non-negotiable and are not
   traded off against anything.
2. **Scored gate** — a monotone score over the remaining features, thresholded at `τ_approve` and
   `τ_deny` with `τ_deny > τ_approve`.

Logistic regression over the features, fit on dev, is the initial candidate for the scored stage —
chosen because it is inspectable, monotone-constrainable, and yields a coefficient table a
reviewer can read. A gradient-boosted model is not adopted unless it clears a materially better
coverage/safety frontier, because an uninterpretable abstention gate is difficult to defend in a
clinical review.

---

## 5. Calibration protocol

This is a **pre-registered protocol**. Criteria are fixed before results are seen and are not
retuned afterwards.

```
   [1] fit / fix the gate on the DEV split only
            │
   [2] coverage vs accuracy curve      (sweep thresholds, dev)
            │
   [3] unsafe-decision analysis        (dev) — what survives the gate and is wrong
            │
   [4] threshold selection             (dev) — against the pre-registered rule below
            │
   [5] single scored validation        (TEST split, frozen, budget-controlled)
```

Steps 1–4 touch **dev only**. This is enforced at the library boundary, not by discipline: the
calibration entry points call a `require_tunable(split)` guard that raises on a frozen split, in
the same way the firewall's `eval/schema.py` does.

### 5.1 Threshold selection rule (pre-registered)

> Choose the **lowest** threshold whose dev unsafe-decision rate upper Wilson bound is at or below
> the configured ceiling. Iterate **upward** from the lowest candidate and return the first
> qualifying value.

The "iterate upward" instruction is not stylistic. Computing "smallest *k* satisfying a bound" by
scanning downward returns the endpoint rather than the first qualifying value — a bug that has
occurred three times in the sibling project. It is stated here so it does not occur a fourth.

Ceilings for approval and denial are set as configuration in `config/decision-policy.yaml` before
step 2 is run, and are recorded in ADR-011 at that time.

### 5.2 What "unsafe" means

Not simply "wrong". Errors are weighted by harm direction:

| Error | Class |
|---|---|
| `DENY_RECOMMENDED` where gold is approve | **Unsafe.** Withholding indicated care. |
| `APPROVE_RECOMMENDED` where gold is deny | Costly, not unsafe. |
| `APPROVE`/`DENY` issued on an invalid citation | **Unsafe.** Should have been `NO_DECISION`. |
| `NEEDS_INFO` where gold is a decision | Coverage loss, not unsafe. |
| Decision on the wrong policy version | **Unsafe.** Correct-looking, ungrounded. |

The abstention gate is judged on whether it removes **unsafe** decisions, not on whether it
removes errors in general. A gate that only reduces coverage has failed, and the report says so.

### 5.3 The claim that must be earned

> *"Abstention improves safety rather than merely reducing coverage."*

Permitted only when a committed report shows a reduction in the unsafe-decision rate that is not
explained by the coverage reduction alone — i.e. the unsafe rate falls faster than coverage, with
intervals stated. The comparison is paired on the same cases, using exact McNemar. Until that
artefact exists the claim is **not made** — not softened, not hedged, not made. Tracked in
[evidence-and-claims.md](../evidence-and-claims.md).

### 5.4 Scoring budget

The test split has a scoring budget. Step 5 spends **one** scoring. Any additional scoring must be
declared in an ADR *in advance*, with its reason. Re-scoring a frozen split until a number improves
is how an evaluation becomes fiction.

---

## 6. Threshold governance

Thresholds are **configuration, not code**: `config/decision-policy.yaml`, versioned, loaded at
startup, and recorded on every recommendation as `decision_config_version`.

- Invalid policy prevents startup and is never silently repaired.
- Keys matching `*_key`, `*secret*`, `*token*`, `*password*` are structurally rejected, so a
  credential cannot be committed through this file.
- Every recommendation stores `gate_features`, so a proposed threshold change can be replayed over
  historical cases **without re-running any model** — recalibration costs a query, not a corpus.

Changing a threshold changes clinical behaviour. It is an ADR-worthy event, and the config version
on the audit row is what lets a reviewer establish which rules were in force for a given case.

---

## 7. Reported metrics

Defined in [evaluation-strategy.md](../evaluation/evaluation-strategy.md); listed here so the gate
and its measurement stay in one mental frame.

| Metric | Definition |
|---|---|
| Coverage | cases receiving `APPROVE_RECOMMENDED` or `DENY_RECOMMENDED` ÷ all cases |
| Selective accuracy | accuracy on covered cases only |
| Unsafe-decision rate | unsafe outcomes (§5.2) ÷ all cases |
| Abstention precision | abstentions that would have been wrong ÷ abstentions |
| Abstention recall | abstentions that would have been wrong ÷ all cases that would have been wrong |
| Denial precision | correct denials ÷ denials — **reported separately, always** |

All are **pending evidence**. No value for any of them exists or may be quoted.
