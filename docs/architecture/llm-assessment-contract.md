# Structured LLM Assessment Contract

**Per criterion. Three states. No case-level outcome exists in the schema.**

`app/contracts/slice.py`. Not implemented.

---

## The output

```python
CriterionAssessment(criterion_id, assessment, evidence_ids, rationale_summary, uncertainty)
```

## The entire vocabulary

```
SATISFIED · NOT_SATISFIED · UNKNOWN
```

Three members, and what is absent from them is the point:

**No `APPROVE`, no `DENY`.** A successful prompt injection cannot emit an approval
because no approval token exists in the schema being filled. The containment is
structural and holds whether or not an injection is detected — which matters,
because the firewall's indirect-injection recall is **0.1423** and this is a RAG
application whose corpus is the untrusted surface.

**No `LIKELY_SATISFIED`, no `PARTIALLY_SATISFIED`.** Each is a hedge a downstream
step would have to interpret, and interpreting a hedge is how a maybe becomes a yes.

**No `NOT_APPLICABLE`.** Whether a criterion applies is a policy-logic question,
answered by `When` in the declared logic — not a judgement for the model making the
assessment.

A value outside the three is **refused**, not coerced to the nearest legal one.
`07-schema-failure.json` exercises exactly this with `PROBABLY_SATISFIED`.

## A decided assessment must cite evidence

`SATISFIED` and `NOT_SATISFIED` require at least one `evidence_id`. **Only `UNKNOWN`
may be reached without citing something** — which is correct, because "I could not
tell" is the one answer that rests on an absence.

## The rationale is for a human and is never parsed

`rationale_summary` exists for a reviewer to read. Nothing acts on it. Everything the
system acts on comes from `assessment` and `evidence_ids`, both closed and checkable.

A system that acted on the rationale would be reasoning about prose a model wrote
about prose a model read — two layers of interpretation, neither checkable.

`uncertainty` is the model's own words about what it was unsure of. It is **not** a
probability and **not** a threshold input.

## What the model never returns

A final authorization decision. The recommendation is computed by `decide()` from
per-criterion verdicts, and `app/adjudication` cannot even import the module where
`Outcome` lives — enforced by an AST test that parses rather than imports, so the
rule binds a module nobody has run.
