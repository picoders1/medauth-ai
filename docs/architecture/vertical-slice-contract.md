# First AI Vertical Slice — Contract

**Nothing in this document is implemented.** It is the contract the first AI slice
must satisfy, written before the agents so that the agents are built to it rather
than described by it afterwards.
Superseded in scope by
[first-vertical-slice-contract.md](first-vertical-slice-contract.md), which consolidates
the stage boundaries, closed schemas and fixtures; this document keeps the detail.

---

## Admissibility comes first

A slice runs against **one** policy version, and only one that passes all seven
conditions in `scripts/assess_slice_admissibility.py`:

| # | condition | artefact |
|---|---|---|
| 1 | semantics `DECLARED` | `data/policy_logic/inventory.json` |
| 2 | criteria span-verified | `data/criteria/verification.json` |
| 3 | no unresolved criterion dependency | `data/review/policy_dependencies.json` |
| 4 | temporally resolvable | corpus / NCD registry |
| 5 | coverage status established, or not required | `data/coverage/registry.yaml` |
| 6 | no `ENGINEERING_INFERRED` linkage | the linkage files |
| 7 | citation provenance complete | criteria inventory |

**As of Phase 6 no policy passes all seven.** The nearest is
`REGULATION:42 CFR 410.32:2026-08-13`, failing exactly one: criterion **C03**
depends on paragraph `(b)(3)`, which is not transcribed (R-51). That is the single
blocker, and it is a review question, not an engineering one.

## The flow

```
Clinical case + requested service
        │
        ▼  INTAKE                                   [model, schema-constrained]
   structured clinical facts, each with a source span into the note
   ✗ may not reference coverage, policy, or any outcome
        │
        ▼  RESOLUTION                               [deterministic SQL]
   PolicyIdentity(type, id, version) — one policy type per scope
   ✗ ENGINEERING_INFERRED links cannot establish applicability
        │
        ▼  RETRIEVAL                                [local encoders]
   RetrievalScope(document_type, version_ids, as_of) — no value means "everything"
        │
        ▼  CRITERION EVIDENCE MAPPING               [deterministic]
   evidence set per criterion, from that criterion's scope only
        │
        ▼  ADJUDICATION                             [model, one call per criterion]
   verdict ∈ {SATISFIED, NOT_SATISFIED, INSUFFICIENT_EVIDENCE, NOT_APPLICABLE}
   + ≥1 citation with an exact quote  + ≥1 referenced intake fact id
   ✗ no case-level outcome member exists in the schema
        │
        ▼  GUARDRAIL                                [deterministic]
   span-verify every quote · check metadata · check the chunk was in scope
        │
        ▼  POLICY EVALUATION                        [pure function]
   PolicySemantics required — no default, no assumed conjunction
        │
        ▼  Recommendation
```

## Inputs

| field | |
|---|---|
| `case_id` | opaque; no patient identifier |
| `clinical_note` | synthetic only. **No real PHI, ever** |
| `procedure_code`, `code_system` | drives resolution |
| `diagnosis_codes` | reported, never used to decide applicability |
| `date_of_service` | **required**. Version selection is by date, never "latest" |
| `jurisdiction` | optional; absent means jurisdictional policies do not apply |

## Output

A `Recommendation`, already defined and frozen: `outcome`, `rule`,
`missing_evidence`, `policy_semantics`, `semantics_origin`,
`decision_config_version`. Plus, for the slice, the evidence set and every citation
with its derived fields joined from the database — `source_url`, `effective_date`,
`document_title` are **never** accepted from the model.

## Evidence and citation requirements

1. `normalize(quote)` is a substring of `normalize(chunk.text)`.
2. Claimed metadata matches the chunk's.
3. The chunk was in **that criterion's** evidence set.
4. Every derived field is joined, not supplied.

**Any failure ⇒ `NO_DECISION`.** When strict matching produces too many, the fix is
normalization or the prompt — never the contract (R-10).

## Error and abstention states

Structural only. `app/decision/abstention.py`:

`INSUFFICIENT_EVIDENCE` · `UNSUPPORTED_CITATION` · `UNRESOLVED_POLICY_SEMANTICS` ·
`UNRESOLVED_POLICY_DEPENDENCY` · `UNRESOLVED_COVERAGE` · `MODEL_SCHEMA_FAILURE` ·
`RETRIEVAL_FAILURE` · `CONTRADICTORY_EVIDENCE`

Every one carries a **remedy** — an abstention that does not say what would resolve
it is an apology. None yields an approval or a denial. Only
`UNSUPPORTED_CITATION` yields `NO_DECISION`; the rest route to a person.

**`ScoredGate` is `UNCALIBRATED` and says so.** No threshold has been selected;
they are chosen on the dev split under ADR-011/OD-8. "There is no gate" and "the
gate passed" are different claims, and an audit row that cannot tell them apart
would let an uncalibrated system read as a confident one.

## Audit events

Every stage emits one, and none carries clinical text — redaction is enforced at the
structlog sink, not per call site. Payloads carry fact ids, chunk ids and spans;
text is joined for display.

`case.received` · `intake.completed` · `resolution.completed` ·
`retrieval.completed` · `adjudication.criterion` (one per criterion) ·
`guardrail.completed` · `decision.emitted` · `abstention.recorded`

The audit trail is append-only. The application role has `INSERT`/`SELECT` and not
`UPDATE`/`DELETE`.

## What the slice must not do

No LangGraph. No free-text model call. No threshold. No claim of clinical accuracy
or validation. No policy version that fails admissibility — and **today that is all
of them**.
