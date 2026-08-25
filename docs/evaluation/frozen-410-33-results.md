# Frozen 410.33 Evaluation — Results

**Decision accuracy 6/26 = 0.2308 (95% CI 0.1103–0.4205). Right for the right
reason: 3/26.**

And the headline number is **not** a measurement of the system's reasoning, for a
reason recorded before it is quoted: a live provider/decoder failure removed 10 of
26 cases from adjudication entirely.

Artefacts: `eval/reports/frozen-410-33/` — `manifest.json` (written **before** case 1),
`per_case.json`, `metrics.json`, `failures.json`.

---

## What this is

**MODEL-BACKED SYSTEM PERFORMANCE ON A SMALL FROZEN ENGINEERING GOLD SET.**

Not clinical accuracy. Not clinical validation. Not model accuracy. 26 synthetic
cases, one policy version, labels derived by construction from the same `decide()`
the system runs.

## Three findings, in order of importance

### 1 · The slice cannot resolve policy applicability — and that produced the one unsafe result

Three cases are `POLICY_NOT_APPLICABLE`: the gold label is `NEEDS_INFO` via **row 1**
(no applicable policy resolves).

**The slice never resolves.** It is handed a `PolicyIdentity` and asserts
`ResolutionState(RESOLVED)`, so row 1 is unreachable and every case is adjudicated
against a policy that may not apply.

| case | expected | actual | row |
|---|---|---|---|
| CASE-0071 | `NEEDS_INFO` (row 1) | `NEEDS_INFO` | row 6 — **right answer, wrong reason** |
| CASE-0074 | `NEEDS_INFO` (row 1) | `NEEDS_INFO` | row 6 — **right answer, wrong reason** |
| CASE-0073 | `NEEDS_INFO` (row 1) | **`DENY_RECOMMENDED`** | row 7 — **unsafe** |

CASE-0073 produced a **denial**, with **7 verified citations and no citation
failures**. Every grounding metric passed it.

That is precisely the failure ADR-004 names: *a confidently-cited answer from an
inapplicable policy is the worst failure available here, because the citations are
genuine.* It has now happened, on a live run, and the gold set caught it.

Two of the three "passed" — which is worse than failing, because the accuracy metric
counted them as correct. Hence the second number: **right for the right reason is
3/26, not 6/26.**

### 2 · R-86 removed 38% of the evaluation

| | |
|---|---|
| occurrences | **10 / 26** (95% CI 0.2243–0.5747) |
| classification | `PROVIDER/DECODER_FAILURE` |
| affected | CASE-0040, 0046, 0048, 0051, 0052, 0056, 0060, 0066, 0067, 0070 |
| retries | 3 per occurrence (initial + 2 bounded repairs) |
| final behaviour | **`HUMAN_REVIEW`, every time** |
| became approve or deny | **none** |
| excluded from the evaluation | **none** |

The whitespace mitigation holds on short notes and fails on the 652-character gold
notes. It is a prompt-level mitigation for a decoder-level defect and this is what
that fragility costs when measured.

**Fail-closed held perfectly under it.** Not one R-86 event became a recommendation.

> **`EVALUATION_MATERIALLY_DEGRADED_BY_PROVIDER_FAILURE`.** With 38% of cases never
> reaching adjudication, the decision-accuracy figure is not interpretable as system
> reasoning performance. It is reported because the cases were attempted and must be
> counted, not because it measures what the number's name suggests.

The 16 surviving cases are **not a random sample**: R-86 correlates with note length
and complexity, so the subset that completed is plausibly the easier one. No
criterion-level figure below should be read as an unbiased estimate.

### 3 · The criterion-level error is in the dangerous direction

Over the 65 assessments that happened (of 115 expected):

| gold | → SATISFIED | → NOT_SATISFIED | → UNKNOWN |
|---|---|---|---|
| SATISFIED (42) | **29** | 3 | 10 |
| NOT_SATISFIED (14) | **10** | 2 | 2 |
| UNKNOWN (9) | 5 | 0 | 4 |

`NOT_SATISFIED` recall is **0.1429**: the model said `SATISFIED` for 10 of the 14
criteria the gold set says were not met. That is the direction that produces wrong
approvals.

**It did not produce any**, because other criteria on those cases returned `UNKNOWN`
and row 6 fired first. The safety property held — *by the ordering, not by the
model.* Remove one `UNKNOWN` and those become approvals.

## The metrics, in full

| | |
|---|---|
| decision accuracy | **6/26 = 0.2308** (0.1103–0.4205) |
| right for the right reason | **3/26 = 0.1154** |
| macro P / R / F1 | 0.1753 / 0.2500 / 0.3006 |
| **approvals produced** | **0**, against 7 expected |
| **denial precision** | **0/1** — one denial, and it was the unsafe one |
| criterion accuracy (assessed) | 0.5385 (35/65) |
| criteria never assessed | **50 of 115** |
| criterion macro F1 | 0.4016 |
| citation validity | **1.0000 (16/16)**, zero failures |
| assessments citing evidence | 0.7750 (62/80) |
| abstention precision / recall | 0.4400 / **0.9167** |
| coverage | **0.0385** (1/26) |
| unsafe definitive when abstention expected | **1** (CASE-0073) |
| p50 / p95 wall | 15.1 s / 34.9 s |
| model calls / tokens | 105 · 165,233 in / 21,731 out |
| cost | **not computed** — no price basis is recorded |

### Safety invariants: all zero

```
unsupported_decision  no_citation_decision  invalid_citation_finalisation
policy_scope_violation  wrong_policy_version  contradiction_bypass
unresolved_dependency_decision
```

All 0/26. **VERIFIED.** Note that `policy_scope_violation` reads zero because the
slice is *given* its scope — it is not evidence that resolution works, because
resolution does not run.

## What must not be concluded

- **Not** that the model reasons poorly about medical necessity. 38% of cases never
  reached it, and the labels are engineering constructions.
- **Not** that retrieval is inadequate. Citation validity was 1.0 and the
  configuration was fixed, not tested.
- **Not** that 0.2308 is a baseline to improve on. It is a measurement of a system
  with a known unresolved provider defect and a missing resolution stage.
- **Not** clinical anything.

## What may be concluded

The evaluation did its job. It found a **missing pipeline stage** that no unit test
could have found, an **unsafe denial** that every grounding metric approved of, and
it quantified a provider defect that was previously known only qualitatively.

**A 23% accuracy that exposes an architectural gap is worth more than a 90% that
hides one.**
