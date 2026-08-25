# Policy applicability at runtime (Phase 15, R-93)

**Status:** implemented. **ADR:** [ADR-028](../adr/ADR-028-runtime-applicability-and-experiment-validity.md).
**Closes:** R-93. **Exposes:** R-97, R-98, OD-37, OD-38, OD-39.

---

## The defect, stated once

ADR-004 decided in Phase 1 that applicability would be deterministic — rules over
`policy_code_links`, no embeddings, no model. `app/policy/resolve.py` implemented it
in Phase 2 and has been correct ever since.

**The vertical slice never called it.** From Phase 11 to Phase 14 the runner took a
`PolicyIdentity` at construction and passed a literal to the decision table:

```python
ResolutionState(status=ResolutionStatus.RESOLVED, version_count=1)
```

Rows 1 and 2 of the decision table were unreachable from the live runtime for four
phases. Both had tests. Both passed. The tests called `decide()` directly.

The cost showed up in Phase 14's frozen run as CASE-0073:

| | |
|---|---|
| gold expectation | `NEEDS_INFO`, decision rule 1 |
| produced | **`DENY_RECOMMENDED`** |
| citations | 7 verified, **0 failures** |
| guardrail | `PASSED` |

Every grounding metric passed it, because the quotes were real, the chunks were in
the evidence set, and the metadata matched the database. That is the ADR-004 failure
verbatim: *a confidently-cited answer from an inapplicable policy*.

---

## The chain now

```
case
  ↓
applicability  [SQL: resolve() + 3 census counts → 6 states]   ← Phase 15
  ↓  only RESOLVED continues
intake         [model]
  ↓
retrieval      [pgvector, scoped]
  ↓
assessment     [model, one call per criterion]
  ↓
citations      [code]  →  contradiction [code]  →  decide() [pure]
```

**First, before intake.** Not only to save a token on a case whose policy does not
govern — every later stage's output is meaningless without it, and nothing downstream
can detect the problem. Retrieval will happily return five well-scoped chunks from
the wrong document, the model will reason correctly over them, and the citations will
verify.

## Six states

| state | reason examples | routes to | rule |
|---|---|---|---|
| `RESOLVED` | `DESIGNATED_POLICY_APPLIES` | retrieval | — |
| `NOT_APPLICABLE` | `NO_POLICY_LISTS_THE_PROCEDURE`, `NO_POLICY_IN_THIS_JURISDICTION`, `NO_POLICY_APPLIES_ON_THESE_FACTS` | `NEEDS_INFO` | 1 |
| `MULTIPLE_CANDIDATES` | `SEVERAL_POLICIES_COULD_GOVERN`, `CORPUS_VERSIONS_OVERLAP` | `HUMAN_REVIEW` | 2 |
| `TEMPORALLY_UNRESOLVED` | `NO_VERSION_IN_FORCE_ON_THAT_DATE` | `HUMAN_REVIEW` | 14 |
| `INSUFFICIENT_INFORMATION` | `NO_PROCEDURE_CODE`, `CODE_SYSTEM_NOT_STATED`, `NO_DATE_OF_SERVICE` | `NEEDS_INFO` | 15 |
| `RESOLUTION_ERROR` | `RESOLVER_FAILED`, `RESOLVED_VERSION_IS_NOT_THE_DESIGNATED_ONE`, `RESOLVED_POLICY_TYPE_DIFFERS` | `HUMAN_REVIEW` | 16 |

**Two levels, deliberately.** The state routes the case; the reason is what a
reviewer is owed. "No policy governs this request" and "policies list this code and
none reaches your jurisdiction" are the same state and completely different
sentences, and only one of them tells the reader what to do next.

**Routing is a dict, not a branch chain.** `_ROUTE_FOR_RESOLUTION` in
`app/decision/table.py` and `_ABSTENTION_FOR_RESOLUTION` in `app/graph/slice.py` must
each cover every non-`RESOLVED` member; a test asserts totality and a third asserts
the two agree. A seventh state fails a test rather than falling through to
adjudication.

## Where the work happens

| concern | lives in | why there |
|---|---|---|
| discovery, temporal filter, jurisdiction filter | `app/policy/live_applicability.py`, in SQL | `in_force_on` and `applies_in_jurisdiction` stay the **only** implementations. A Python copy would pass every test written against today's corpus and disagree the moment a version is superseded |
| the six-state decision | `app/policy/applicability.py::classify`, pure | takes counts and identities, never a session, so the machine is a truth table with no database |
| what a state means for a case | `app/graph/slice.py` | orchestration owns routing, as it owns gateway-failure routing |

### The census, and why counts rather than lists

`resolve()` answers one question: which versions apply, on this date, in this
jurisdiction. When the answer is "none", that fact alone cannot distinguish three
situations with three different next actions:

```
total = 0                        → the corpus has never heard of this code
total > 0, in_force = 0          → it holds the policy; not for that date
total > 0, in_jurisdiction = 0   → it holds the policy; not for that region
```

Three SQL counts, each reusing the shared predicates. `classify()` reads integers and
performs no temporal reasoning of its own — which is what keeps the "exactly one
temporal predicate" property true.

## `PRODUCTION` and `REPLAY`

`RunMode` has **no default**, like `gate` and `semantics`. A default mode is a mode
nobody chose, and the one it would have to be is the one that skips the check.

- `PRODUCTION` requires an `ApplicabilityPort`. Constructing one without it raises —
  at construction, not per case, because a per-case refusal is 26 abstentions in a
  report and reads as a hard corpus rather than as a defect.
- `REPLAY` runs without a resolver and stamps every outcome and audit row. Its
  finding carries `DESIGNATED_WITHOUT_RESOLUTION`, so `resolved_applicability` is
  `False` even though the state reads `RESOLVED` — a replay can never be read as a
  resolution that happened to agree.
- `REPLAY` is excluded from `PRODUCTION_MODES` by **absence**, never by a branch that
  names it. A branch is somewhere to add an exception to.

A replay does not consult a supplied port either: a replay exists to reproduce a
historical label, and a resolution that ran would make the reproduction conditional
on today's corpus.

## What this does not fix

**R-97 — the gold set's not-applicable cases are unreachable from their own input.**
Made visible by this change and not caused by it. `gold_v1`'s three
`POLICY_NOT_APPLICABLE` cases write the non-applicability into the clinical narrative
("Requested service: unlisted procedure 99199") while emitting `R0075` — a genuinely
covered code — in `requested_procedure.code`. Deterministic resolution reads the
structured request, correctly resolves 42 CFR 410.33, and the gold label of row 1
becomes unreachable.

The tempting fix is to let the resolver read the note. It is refused: that is a
semantic resolver wearing a deterministic one's clothes, it would resolve differently
for the same structured request depending on prose, and it reintroduces the exact
class of failure ADR-004 exists to prevent. The three cases are reported as
`DATASET_DEFECT`, counted, never excluded. A gold_v2 is OD-37.

**R-98 — a right answer can be reached by a new wrong row.** With five refusing
states, a case can now be refused for the wrong *kind* of absence and still score
correct at the outcome level. Mitigated the same way R-96 was: the scorer reports
`accuracy_right_for_the_right_reason` separately and emits a failure record whenever
the rows differ.

**Nothing about model reasoning.** Applicability decides which document is in scope.
It says nothing about whether the reasoning over that document is any good.

## Evidence

| claim | how to check |
|---|---|
| an inapplicable policy cannot produce a denial | `pytest tests/integration/test_case_0073_regression.py` |
| all six states behave, including the boundaries | `pytest tests/unit/test_policy_applicability.py` |
| no model output can bypass applicability | `pytest tests/security/test_applicability_cannot_be_bypassed.py` |
| the regression is load-bearing | `python scripts/mutation_guard.py -k applicability` and `-k resolution`, `-k refusal`, `-k only-resolved` |
| the runtime actually resolves | `eval/reports/phase15-410-33/per_case.json`, field `applicability_resolved` |
