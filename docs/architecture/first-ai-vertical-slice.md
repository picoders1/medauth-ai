# The First AI Vertical Slice

**Implemented, and running.** One policy version, nine controlled scenarios,
**zero model calls**.

Code: [app/graph/slice.py](../../app/graph/slice.py) ·
Report: `eval/reports/first-vertical-slice/report.json` ·
Runner: `scripts/run_first_slice.py`

---

## What unblocked it

```
FOCUS-001  ACCEPTED (2026-08-24)  →  resolved the question, did NOT unblock 410.32
42 CFR 410.33 logic DECLARED      →  the gate recomputed to READY
```

The designated slice is **`REGULATION:42 CFR 410.33:2026-08-13`** — chosen by the
admissibility gate, not by preference. It was the only version whose failed checks
were a subset of the two that declaring logic resolves, and a test asserts that.

`scripts/run_first_slice.py` **refuses to run unless the gate says READY**. A slice
that could run around the gate would make every admissibility argument in this
repository conditional on a caller remembering to check.

## The chain

```
  SliceInput (synthetic note, R0075, date of service)
        ▼ intake            [model]   IntakeResult, every fact span-anchored
        ▼ resolution        [given]   PolicyIdentity, supplied not re-derived
        ▼ retrieval         [port]    one evidence set per criterion, pre-scoped
        ▼ evidence mapping  [code]    fact ↔ criterion ↔ span
        ▼ assessment        [model]   ONE CALL PER CRITERION, 3 states
        ▼ citations         [code]    4 checks, any failure stops the case
        ▼ policy logic      [pure]    declared semantics required, no default
        ▼ abstention        [code]    9 states, UNCALIBRATED gate recorded
        ▼ Recommendation + AuditEvent
```

## Where the containment actually lives

**The model has no token to aim at.** `AssessmentState` has three members and none
is an outcome. A test asserts the approval and denial tokens appear in neither the
instructions, the evidence block, nor the JSON schema handed to the model.

**Per-criterion isolation.** Each call sees only its own criterion's evidence, so a
tampered chunk influences one criterion — and that criterion's verdict still has to
survive span verification.

**Retrieved text is fenced data.** It enters only through
[evidence_block.py](../../app/adjudication/evidence_block.py): framed as data,
told what to do with an instruction found inside, and with the fence delimiter
neutralised so content cannot close its own block. `instructions` and
`evidence_block` are separate gateway fields, and a test asserts the caller did not
merge them anyway.

**This holds at detection recall zero.** The firewall's indirect-injection recall is
**0.1423**; none of the above depends on it noticing.

**The verdict packages cannot name an outcome.** `app/intake` and `app/adjudication`
are AST-checked against the tokens — which means they cannot even import
`GatewayOutcome`, because the enum's name contains one. So they let `GatewayFailure`
propagate and the orchestrator classifies it. That is the right place: what a blocked
call means for a case is a decision about the case.

## Results — 9 of 9 agree with the decision table

| scenario | expected | actual |
|---|---|---|
| complete | `APPROVE_RECOMMENDED` | ✓ |
| missing criterion | `NEEDS_INFO` | ✓ |
| evidenced refusal | `DENY_RECOMMENDED` | ✓ |
| exclusion established | `DENY_RECOMMENDED` | ✓ |
| invalid citation (tampered chunk) | `NO_DECISION` | ✓ |
| wrong policy version | `NO_DECISION` | ✓ |
| retrieval failure | `HUMAN_REVIEW` | ✓ |
| firewall blocked | `HUMAN_REVIEW` | ✓ |
| fabricated evidence id | `NEEDS_INFO` | ✓ |

Expectations come from the decision table's own rows, not from observing a run — a
scenario whose expectation came from the system would confirm whatever the system
did.

## Two things found by building it

**An unevidenced refusal cannot be expressed at all.** Writing the test revealed the
contract refuses `NOT_SATISFIED` with no evidence *at construction*, so it cannot
arrive from a model response. Stronger than the property being tested for. The one
route that could still produce it — an invented evidence id — is downgraded to
`UNKNOWN`, because a verdict whose only support was fabricated is not a weaker
verdict, it is an absence of one.

**A wrong `criterion_id` is still a string.** The closed schema cannot catch a model
answering about a different criterion, so the id is overwritten with the one asked
about. Left alone, one answer would be filed under a criterion nobody assessed and
another would silently have none.

## What this does NOT establish

`MODEL_REASONING_QUALITY_NOT_YET_EVALUATED`

Every model response came from a fixture. **The latencies are the cost of the
pipeline, not of inference.** Nothing here measures clinical accuracy, clinical
validation or model reasoning quality, and the committed report says so in its own
`note` field.

The retrieval benchmark remains `NOT_READY`, so the retrieval configuration this
slice uses is **unevaluated, not selected**.
