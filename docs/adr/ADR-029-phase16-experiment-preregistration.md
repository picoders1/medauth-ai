# ADR-029 — Pre-registration: `phase16-evaluation-001` on gold_v2

**Status:** Pre-registered (2026-08-25). **NOT executed.**
**Dataset:** gold_v2 (156 cases), scoring budget **1**, unspent.
**Depends on:** ADR-011 (pre-registration regime), ADR-015 (ground truth by
construction), ADR-027 (retrieval pre-registration), ADR-028 (runtime applicability,
provider-failure validity).

Everything below is fixed **before** any of it is measured. None of it may be revised
after seeing a number.

---

## Why a third experiment identity

gold_v1's scoring budget is spent, 2 of 2 (ADR-028 Part 1b). Its dataset also carries
R-97: eighteen cases whose applicability label is unreachable from their own
structured input. Running again under the same identity would spend a budget that no
longer exists against a dataset that cannot answer part of the question.

`phase16-evaluation-001` is therefore a new experiment on a new dataset, and its
figures are **not comparable** with Phase 14's or Phase 15's — different corpus,
different code, different applicability semantics.

## What is frozen

| | |
|---|---|
| dataset | `gold_v2`, sha256 recorded in `data/gold/manifests/gold_v2.manifest.json` |
| cases | all 156. **No subset, no stratified sample, no exclusions** |
| policy versions | the six 42 CFR 410 versions gold_v2 inherits |
| applicability | `applicability.v1`, source digest recorded |
| retrieval | `ENGINEERING_DEFAULT_UNRESOLVED` — bge-base, MiniLM-L-6-v2, `top_k=40`, `rerank_top_n=5`, section-aware chunking |
| prompts | `intake.v2`, `adjudication.v1` |
| model | digest only; `json_schema`, temperature 0.0, ceilings 1536 / 512 |
| gateway | configuration digest, `fail_closed=true`, no streaming |
| validity rule | `provider-failure-validity.v1` (ADR-028) |
| coverage reporting | `eval/coverage.py` — two denominators, six dispositions |

## The two denominators, fixed in advance

**Operational coverage** — assessed cases over every case attempted, provider
failures **included**. This is what the system delivered.

**Decision quality** — over `ASSESSED` cases only, and labelled in the artefact as
*not overall system accuracy*.

Neither may be reported without the other. Cases excluded from the second denominator
are counted in the first and named by disposition; **no case is ever dropped**.

## Pre-registered failure interpretation

The validity rule may classify the run and may **not** see accuracy. It decides
whether decision-level figures are readable as reasoning performance, nothing else.
Safety metrics stay interpretable under either status.

**The expected outcome is `DEGRADED_BY_PROVIDER_FAILURE`.** R-86 reproduces 6/6 in
the production intake shape (`r86-factorial-001`), so a run today would exceed the
0.10 ceiling on the first condition. Recording that expectation here is the point of
a pre-registration: if it happens it is a confirmed prediction, not a discovery, and
it is not a reason to raise the ceiling or re-run.

## The stopping rule — and why this experiment has not run

**It does not start until the pre-run gate passes**
(`scripts/phase16_prerun_gate.py`). One of its conditions is provider reliability:

> the most recent provider diagnostic must show a failure rate at or below the
> validity rule's ceiling, in the **production request shape**

That condition currently fails, and the gate stops. This is deliberate and is the
substance of Phase 16's finding:

> Spending gold_v2's only scoring on a run already known to be uninterpretable would
> destroy the budget in order to learn something the diagnostic already established.
> The dataset, the benchmark, the manifest and the rule are ready. The provider path
> is not.

**Running anyway would be the failure mode this ADR exists to prevent.**

## What unblocks it

1. R-86 owned and bounded by whoever holds the provider or the firewall — the
   evidence and the exact asks are in
   `docs/escalations/R-86-unbounded-whitespace.md`.
2. A re-run of `r86-factorial-001` showing the production shape below the ceiling.
3. The gate passing on all conditions.

None of the three is an engineering task inside this repository, and no amount of
prompt work substitutes for any of them.

## Prohibitions

- No case may be excluded after seeing a result.
- No prompt, model, retrieval or decision parameter may change after the freeze.
- No threshold may be calibrated on gold_v2.
- The provider-failure rule may not consult accuracy.
- A second scoring of gold_v2 requires its own ADR, declared in advance.
- Neither denominator may be presented as "the accuracy".
