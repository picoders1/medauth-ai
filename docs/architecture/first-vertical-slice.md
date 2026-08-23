# The First Vertical Slice — Requirements to Admit One

**Not implemented, and not admissible yet.** This states what must be true before
one is built, so the slice is built to a contract rather than described by one
afterwards.

Companion: [vertical-slice-contract.md](vertical-slice-contract.md) defines the flow
and schemas. This defines the *entry condition*.
The consolidated Phase 9 contract is
[first-vertical-slice-contract.md](first-vertical-slice-contract.md).

---

## Entry condition

Exactly one policy version, passing all seven conditions in
[vertical-slice-admissibility.md](../data/vertical-slice-admissibility.md).

**Today: none.** `REGULATION:42 CFR 410.32:2026-08-13` passes six and fails
`no_unresolved_dependency`. The blocker is **FOCUS-001**, a reviewer decision.

## The contract, stage by stage

| stage | input | output | abstains when |
|---|---|---|---|
| **Intake** | synthetic note + requested service | structured facts, each with a source span | schema failure |
| **Resolution** | `PolicyIdentity`, code, date of service, jurisdiction | one policy version | none resolves → `NEEDS_INFO`; conflict → human |
| **Retrieval** | `RetrievalScope(document_type, version_ids, as_of)` | evidence set per criterion | empty scope → `RETRIEVAL_FAILURE` |
| **Assessment** | one call per criterion | verdict + citations + fact ids | schema failure; no evidence |
| **Guardrail** | citations | validated or refused | unverifiable quote → `NO_DECISION` |
| **Decision** | `PolicySemantics` (**required**) | `PolicyTruth` → `Recommendation` | unresolved semantics or dependency → human |

**No stage may be skipped, and none may be merged.** Merging assessment and decision
is how a model comes to emit an outcome; merging resolution and retrieval is how an
inapplicable policy becomes confidently cited.

## Model boundary

`ModelRole.STRUCTURED_ADJUDICATION` through `app/llm/gateway.py`. Phase 0 measured
that the grammar-constrained path (`response_format: json_schema`) is available and
returns 5/5 schema-valid, while the long-context model rejects every
grammar-constrained mode.

> **That establishes STRUCTURED OUTPUT SAFETY. It is not a claim about reasoning
> quality**, and no comparison of clinical reasoning has been run.

The interface stays abstract: roles, not model names. **No model call is made in
this phase.**

## Abstention

Eight structural states, each carrying a remedy, none yielding an approval or a
denial. `ScoredGate` is `UNCALIBRATED` and records it explicitly — "there is no
gate" and "the gate passed" are different claims, and an audit row that cannot tell
them apart lets an uncalibrated system read as a confident one.

**No confidence threshold is introduced.** Thresholds are selected on the dev split
under ADR-011/OD-8, and none exists.

## What the first slice may and may not claim

**May:** that a recommendation was produced deterministically from span-verified
criteria against a policy whose logic was declared, with every citation validated
and every abstention explained.

**May not:** clinical accuracy, clinical validation, that the criterion set is
complete, that the labels it is measured against are correct, or that any NCD
establishes coverage.

## Exact entry checklist

1. FOCUS-001 answered by a qualified reviewer.
2. `scripts/assess_slice_admissibility.py` reports a `designated_slice`.
3. If the answer changed C03, a `gold_v2` created deliberately with a recorded
   reason — `gold_impact.json` says it reaches 23 cases.
4. OD-28 decided **before** any re-measurement.

Steps 1 and 4 are not engineering.
