# Phase-15 evaluation: the same 26 cases, a different system

**Experiment:** `phase15-410-33`. **Artefacts:** `eval/reports/phase15-410-33/`.
**Status:** `DEGRADED_BY_PROVIDER_FAILURE` under `provider-failure-validity.v1`,
pre-registered in [ADR-028](../adr/ADR-028-runtime-applicability-and-experiment-validity.md)
before this run existed.

**This is not a continuation of Phase 14 and its numbers are not a comparison.**
Both runs are degraded; comparing two degraded figures compares two outage draws.

---

## What changed, and what deliberately did not

| | Phase 14 | Phase 15 |
|---|---|---|
| policy applicability | asserted as a literal | **resolved in SQL, before intake, over six states** |
| encoder, reranker, `top_k`, chunking | — | **identical** |
| prompt ids, model digest, temperature, ceilings | — | **identical** |
| dataset | gold_v1, 26 cases | **byte-identical** |

Nothing was tuned against the Phase-14 result. The pre-run gate checks that against
the Phase-13 freeze rather than taking anyone's word for it, and
`test_nothing_was_tuned_between_the_two_runs` asserts it field by field across the
two manifests.

## Headline numbers

| metric | value |
|---|---|
| decision accuracy | **8/26 = 0.3077** (95% CI 0.1650–0.4999) |
| right for the right reason | **4/26 = 0.1538** |
| macro P / R / F1 | 0.2788 / 0.3000 / 0.3569 |
| approvals produced | **0**, against 7 expected |
| denials produced | **0**, against 7 expected — denial precision has no denominator |
| criterion accuracy (over assessed) | 0.4923 (32/65); 50 never assessed |
| `NOT_SATISFIED` recall | **0.0769** (1 of 13) |
| citation validity | **1.0000** (16/16), 59 citations verified |
| safety invariants | **0/26 on all seven** |
| **unsafe definitive decisions** | **0** (Phase 14: 1) |
| provider failure (R-86) | **10/26 = 0.3846** |
| coverage | **0.0000** |

**None of these is interpretable as reasoning performance.** The pre-registered rule
demotes the run on condition 1 — provider failure 0.3846 against a ceiling of 0.10 —
and that status is computed by code from the per-case record, not decided by eye.

## The three things worth reading

### 1. Applicability ran, and never refused

All 26 cases resolved: `RESOLVED` / `DESIGNATED_POLICY_APPLIES`, `run_mode:
PRODUCTION`, zero `DESIGNATED_WITHOUT_RESOLUTION`.

That is a real fact about the run and a **weak** one about the fix. The run
demonstrates the stage executes, records its state and reason per case, and never
contradicts itself. It does **not** demonstrate that the refusing states work,
because none of them fired. That evidence lives in
`tests/unit/test_policy_applicability.py` (all six states, both boundary sides),
`tests/integration/test_case_0073_regression.py` (the Phase-14 conditions
reconstructed), and four mutations in `scripts/mutation_guard.py`.

### 2. CASE-0073's denial did not recur — and not because of the fix

This is the uncomfortable part, and it is the reason R-97 exists.

Phase 14's unsafe denial came from adjudicating an inapplicable policy. Phase 15
resolves CASE-0073 to **`RESOLVED`**, because the case's structured request names
`R0075` — a code the corpus genuinely links to 42 CFR 410.33. The non-applicability
is written only in the clinical narrative ("Requested service: unlisted procedure
99199"), where a deterministic resolver may not look and must not.

So the case took the same path as Phase 14: six model calls, five verified citations,
full adjudication. It came out `NEEDS_INFO` via **row 6** rather than
`DENY_RECOMMENDED` via row 8, because the model returned different verdicts this run.

> **The applicability fix did not prevent this denial. It did not recur.** Those are
> different facts, and the second one is not evidence for the first. Under the same
> model draw as Phase 14, this case would deny again — because for this case, with
> this input, the policy genuinely does apply.

The gold label of row 1 is unreachable from the input as recorded. That is R-97, a
**dataset** defect, and it is reported as three `DATASET_DEFECT` failure records
rather than repaired: gold_v1 is frozen, and teaching the resolver to read prose
would reintroduce the exact failure class ADR-004 prevents. A gold_v2 is OD-37.

### 3. Zero definitive decisions, in both directions

Not one approval, not one denial, across 26 cases. Coverage 0.0000.

Two causes, both measured:

- **10 cases never reached adjudication** (R-86). Every one routed to
  `HUMAN_REVIEW`; none became a recommendation; none was excluded.
- **The remaining 16 mostly held on open questions.** Row 6 fired repeatedly because
  the model returned `UNKNOWN` for 13 of 43 criteria the gold set says were
  satisfied.

Fail-closed held perfectly. A system that decides nothing is also a system that helps
nobody, and coverage of zero is the honest description of this run's usefulness.

## Failure analysis

22 records, none hidden, and every case that was outcome-correct by the wrong row
still produced one.

| stage | count | severity |
|---|---|---|
| `PROVIDER_FAILURE` | 10 | HIGH (availability) |
| `MODEL_ASSESSMENT` | 8 | MEDIUM |
| `DATASET_DEFECT` | 3 | MEDIUM (label unreachable from input) |
| `CONTRADICTION` | 1 | LOW (behaved as designed) |

`PROVIDER_FAILURE` is its own stage as of Phase 15. Folding it into
`MODEL_ASSESSMENT`, as Phase 14 did, made a provider outage read as 16 reasoning
errors.

## What this run cannot support

- Any claim about reasoning performance — the validity rule says so, in the artefact.
- Any comparison with Phase 14. Both are degraded.
- Any claim about retrieval. The configuration is `ENGINEERING_DEFAULT_UNRESOLVED`,
  fixed so it is not a variable.
- Any claim that the refusing applicability states work in production. They are
  verified by fixtures and mutations; this run did not exercise them.
- Anything clinical. 26 synthetic cases, one policy version, labels derived by
  construction from the same `decide()` the system runs, no qualified clinical review.

## Reproducing it

```bash
uv run python scripts/phase15_prerun_gate.py            # 9 conditions; STOP on any
MEDAUTH_LIVE_MODEL=1 uv run python scripts/run_phase15_evaluation.py --write
uv run python scripts/score_frozen_410_33.py --report-dir eval/reports/phase15-410-33 --write
```

The gold scoring budget is now **2 of 2, exhausted**. A third scoring requires its
own ADR, declared in advance.
