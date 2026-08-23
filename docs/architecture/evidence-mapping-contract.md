# Evidence Mapping Contract

```
ClinicalFact  ↔  PolicyCriterion  ↔  EvidenceReference
```

`app/contracts/slice.py`. Not implemented.

---

## The mapping

```python
EvidenceMapping(criterion_id, clinical_fact_ids, evidence, support_state, citation, provenance)
```

## Four support states, and why `MISSING` and `UNCERTAIN` stay apart

| | means |
|---|---|
| `SUPPORTED` | the fact establishes the criterion |
| `CONTRADICTED` | the fact establishes that it is not met |
| `MISSING` | the note does not address it |
| `UNCERTAIN` | the note addresses it and the reading is unclear |

The last two are a single state in most systems, and merging them sends the wrong
next step: `MISSING` means *ask for records*, `UNCERTAIN` means *a person must
read it*. A request for documentation that the submitter already provided is a
delay with no remedy attached.

## An assertion must cite both sides

A `SUPPORTED` or `CONTRADICTED` mapping is **refused at construction** without both:

- at least one `clinical_fact_id` — what in the note it rests on
- at least one `EvidenceReference` — what in the policy it rests on

So an unsupported free-text claim has nowhere to live. `MISSING` and `UNCERTAIN`
carry neither, which is exactly what they mean.

## Derived fields are joined, never supplied

`EvidenceReference` carries `evidence_id`, `chunk_id`, `policy_identity`,
`section_path` and `quote` — and deliberately **not** `source_url`,
`effective_date` or `document_title`. Those come from the database at render time.
Accepting them from a model would let it assert provenance it cannot have (ADR-009),
and the model is the one component whose provenance claims cannot be checked.

`extra="forbid"` means supplying one is a refusal rather than a silently-dropped
field.

## The quote must verify

`normalize(quote)` must be a substring of `normalize(chunk.text)`; the claimed
metadata must match the chunk's; and the chunk must have been in **that criterion's**
evidence set. Any failure ⇒ `NO_DECISION`.

When strict matching produces too many refusals, the fix is normalization or the
prompt — **never the contract** (R-10).
