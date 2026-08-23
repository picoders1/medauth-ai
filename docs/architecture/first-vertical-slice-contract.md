# The First Vertical Slice — Contract

**Nothing here is implemented, and nothing may be, until FOCUS-001 is `ACCEPTED`.**

The contract is written first so the slice is built to it rather than described by it
afterwards. Companions:
[first-vertical-slice.md](first-vertical-slice.md) (entry condition),
[vertical-slice-admissibility.md](vertical-slice-admissibility.md) (the machine gate),
[phase9-transition.md](phase9-transition.md) (where the repository stands).

Schemas: `app/contracts/slice.py`. Fixtures: `tests/fixtures/slice/`.

---

## The gate, first

`app/production_gate.py` is the **single** authority. Five checks, all read from
committed artefacts, all failing closed:

```
domain_decisions_accepted     ← data/review/focus_001_decision.json
admissibility_gate_readable   ← the file parses at all
policy_slice_admissible       ← at least one policy passes all eleven conditions
admissibility_status_ready    ← the gate itself says READY
semantics_executable          ← the declared-logic loader produces logic
```

`_load()` returns `None` on **any** read error — missing, unparseable, wrong shape —
and `None` is `BLOCKED`. An unreadable artefact is not permission; it is the absence
of permission, and the two look identical only if you squint. `require()` raises
`PermissionError`; there is no boolean a caller can ignore.

**Today: `BLOCKED`,** on `domain_decisions_accepted` and `policy_slice_admissible`.

## Eight stages, and what each may not do

| stage | produces | may not |
|---|---|---|
| **Intake** [model] | `IntakeResult` — facts with required spans | name any outcome; the tokens are AST-forbidden in `app/intake` |
| **Resolution** [SQL] | one `PolicyIdentity` | pick "latest"; date of service governs |
| **Retrieval** [local] | `RetrievalScope` → evidence per criterion | cross document types; an empty scope is unconstructible |
| **Evidence mapping** [code] | `EvidenceMapping` | assert `SUPPORTED`/`CONTRADICTED` without both a fact id and a citation |
| **Assessment** [model, one call per criterion] | `CriterionAssessment` | return anything but `SATISFIED`/`NOT_SATISFIED`/`UNKNOWN`; decide without citing |
| **Citation validation** [code] | verified spans | accept `source_url`, `effective_date` or `document_title` from the model |
| **Policy logic** [pure] | `PolicyTruth` | run at all without `PolicySemantics` — there is no default |
| **Abstention + decision** [pure] | `Recommendation` + `AuditEvent` | reach an approval or a denial from any of the nine abstention states |

## Per-criterion isolation

One model call per criterion, each seeing only its own evidence set. A criterion's
evidence cannot influence another's verdict, so a successful injection in one chunk
is contained to the one criterion that retrieved it — and that criterion's verdict
still has to survive span verification before it reaches `decide()`.

This is why containment does not depend on detection. The firewall's
indirect-injection recall is **0.1423**; the structural properties hold at recall
zero.

## The eight fixtures

Every fixture is a hand-written contract shape. **None involved a model call.**

| | exercises |
|---|---|
| `01-complete` | the happy path — all criteria assessed, all citations verifiable |
| `02-missing-criterion` | `MISSING` → `UNKNOWN` → `INSUFFICIENT_EVIDENCE` → `NEEDS_INFO` |
| `03-contradictory` | verdicts disagreeing → `HUMAN_REVIEW`, never adjudicated by the system |
| `04-invalid-citation` | a quote absent from its chunk → `NO_DECISION` |
| `05-retrieval-failure` | no evidence set → `HUMAN_REVIEW` |
| `06-unresolved-policy` | `REVIEW_REQUIRED` semantics → `HUMAN_REVIEW` |
| `07-schema-failure` | `PROBABLY_SATISFIED` → refused, not coerced |
| `08-no-applicable-policy` | nothing resolves → `NEEDS_INFO`, **never a denial** |

They use only C01, C02 and C04 of 42 CFR 410.32 — **C03 is deliberately absent**,
because it is the criterion FOCUS-001 is about and a fixture asserting a shape for it
would be a quiet answer to the question.

## Nine abstention states, none of which is a denial

`NO_APPLICABLE_POLICY` · `INSUFFICIENT_EVIDENCE` · `UNSUPPORTED_CITATION` ·
`UNRESOLVED_POLICY_SEMANTICS` · `UNRESOLVED_POLICY_DEPENDENCY` ·
`UNRESOLVED_COVERAGE` · `MODEL_SCHEMA_FAILURE` · `RETRIEVAL_FAILURE` ·
`CONTRADICTORY_EVIDENCE`

Each carries a required `remedy` and an `audit_event`. The scored gate is
`UNCALIBRATED` and recorded as such — "there is no gate" and "the gate passed" are
different claims, and an audit row that cannot tell them apart lets an uncalibrated
system read as a confident one.

## What the slice will and will not establish

It will establish that the pipeline runs end to end on synthetic cases against one
admissible policy version, and that every refusal is explainable by pointing at a
rule.

It will **not** establish clinical correctness. Nothing in this repository does, and
no field anywhere in the codebase represents clinical validation — deliberately,
because a field for it is an invitation to set it.
