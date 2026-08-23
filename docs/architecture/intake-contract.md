# Intake Contract

**Extraction only. Intake cannot name an outcome, and there is nowhere to put one.**

`app/contracts/slice.py`. Not implemented.

---

## Input

```python
IntakeRequest(case_id, clinical_note, requested_service)
```

The note is **synthetic only. No real PHI, ever.**

## Output

```python
IntakeResult(
    case_id,
    diagnoses,
    procedures,
    clinical_facts,
    temporal_facts,
    documentation_facts,
    prompt_id,
    model_id,
)
```

Each entry is a `ClinicalFact`:

| field | |
|---|---|
| `fact_id` | unique within the result; duplicates are refused |
| `kind`, `value` | what was found |
| `span_start`, `span_end` | **required**, and must be non-empty |
| `model_reported_confidence` | only if the model reports one |
| `extraction_prompt_id` | which prompt version produced it |

## The span is not optional

A fact that cannot be located in the note is a claim *about* the note rather than a
reading *of* it — and it is uncheckable by exactly the reviewer who most needs to
check it. `ClinicalFact` refuses an empty span at construction.

## No outcome vocabulary, structurally

`IntakeResult` and `ClinicalFact` have no `outcome`, `recommendation`, `coverage`,
`decision` or `approved` field, and a test asserts their absence. The AST boundary
test additionally forbids the tokens `APPROVE_RECOMMENDED`, `DENY_RECOMMENDED`,
`Recommendation`, `Outcome` and `DecisionRule` from appearing anywhere in
`app/intake` — **including in comments**.

Intake extracts what the note says. What it means for coverage is decided later, by
code, from criteria.

## Confidence is recorded and never acted on

`model_reported_confidence` is carried if the model reports one. It is **not** a
threshold input: no threshold is calibrated (ADR-011, OD-8), and treating a model's
self-reported number as a probability is the specific error the abstention design
refuses.

## Reproducibility

`prompt_id` and `model_id` are required. An extraction that cannot name the prompt
that produced it cannot be reproduced, and prompts are versioned files — editing one
in place without incrementing the version is a defect.
