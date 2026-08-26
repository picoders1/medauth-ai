# The application lifecycle

**Machine:** `app/case/lifecycle.py` · **Orchestration:** `app/case/service.py` ·
**Review:** `app/case/review.py` · **Tests:** `tests/integration/test_application_lifecycle.py` (14)

The claim this establishes, exactly:

> **`APPLICATION_LIFECYCLE_VERIFIED_INDEPENDENT_OF_LIVE_PROVIDER`**

Not that the model is correct. Not that R-86 is fixed. A fixture gateway proves the
application moves a case correctly — which is a property of this code, and the only
property a fixture can carry.

---

## 1. The states

```
RECEIVED ──► PROCESSING ──► RECOMMENDATION_READY ──► HUMAN_REVIEW ──► FINALIZED
    │             │                                       │
    │             └──────────► NEEDS_INFO ◄───────────────┘
    └──────────────────────────► HUMAN_REVIEW
  (any live state) ──────────────────────────────────────────────► FAILED
```

`FINALIZED` and `FAILED` are terminal — empty successor sets, so a finalised case
cannot be reopened by any code path.

**There is no `RECOMMENDATION_READY → FINALIZED` edge.** That is this project's central
claim as a graph property: the system produces recommendations *for a human*, and no
edge lets one become an outcome on its own. Two tests and a mutation defend it.

## 2. Where a completed run goes

| engine outcome | state | why |
|---|---|---|
| `NEEDS_INFO` | `NEEDS_INFO` | row 6 — "the note does not say". A question for the **submitter**, not a reviewer task |
| `APPROVE_RECOMMENDED` | `RECOMMENDATION_READY` → `HUMAN_REVIEW` | a definitive draft |
| `DENY_RECOMMENDED` | `RECOMMENDATION_READY` → `HUMAN_REVIEW` | the case where it matters most |
| `HUMAN_REVIEW`, `NO_DECISION` | `HUMAN_REVIEW` | already a person's problem |

### A defect the end-to-end test found

The first version routed definitive outcomes to `RECOMMENDATION_READY` and stopped.
The graph allowed `RECOMMENDATION_READY → HUMAN_REVIEW` and **no code path ever took
it** — so an approval or a denial was stranded: unreviewable, and therefore
unfinalisable.

Nothing but the end-to-end test would have found that. Every unit test passed; the
state existed, the edge existed, and the case sat in a state with no way out.

It is now **two transitions with two events**, because they are two facts: the engine
concluded, and then the case was put in front of a person. A reader of the trail sees
both.

## 3. Human review

Only a case in `HUMAN_REVIEW` may be reviewed — otherwise a reviewer could finalise a
case the engine never assessed.

| action | outcome | case goes to |
|---|---|---|
| `APPROVE` | `APPROVED` | `FINALIZED` |
| `DENY` | `DENIED` | `FINALIZED` — **rationale required** |
| `OVERRIDE` | reviewer's own | `FINALIZED` — **rationale required**, and must say what it overrode *to* |
| `REQUEST_INFO` | `INFORMATION_REQUESTED` | `NEEDS_INFO` |

**An override never edits the recommendation.** It inserts beside it, with
`recommended_outcome_at_review` denormalised, so "did the human agree, and with what"
is answerable from that row forever. Proven: the recommendation row's `id` and
`outcome` are identical before and after an override.

## 4. Duplicate actions (Part L)

Classified against the service's actual contract, not an invented guarantee:

| action | classification | why |
|---|---|---|
| duplicate submission (same `case_id`) | **REJECTED** | case ids are the caller's; silently returning the existing case would hide a collision between two different requests |
| second run of the same case | **ACCEPTED**, additive | legitimate after a corpus refresh or a provider outage; `run_seq` orders them and no earlier recommendation is overwritten |
| review of a finalised case | **REJECTED** | two reviewers must not both finalise. Fails loudly — "already done" and "you did it" are different answers |
| review of a case not in `HUMAN_REVIEW` | **REJECTED** | see §3 |

No idempotency keys, no retry semantics. Neither exists in the service, so neither is
claimed.

## 5. The audit trail is the record

Every transition writes an event, in the same transaction as the state change. The
trail for one full lifecycle:

```
CASE_RECEIVED · CASE_VALIDATED
RUNTIME_STAGE × n        ← lifted from the runtime, not re-derived
RECOMMENDATION_CREATED
HUMAN_REVIEW_REQUESTED
HUMAN_DECISION_RECORDED · CASE_FINALIZED
```

`RUNTIME_STAGE` events are **lifted** from `SliceOutcome.audit` — the events the
runtime produced while doing the work. Re-deriving them from the outcome would give
this project two descriptions of one run, and the persisted one would be the one nobody
checked. That is R-99's shape, avoided by construction.

Verified in the same test: every event carries the case id, the request id and the
correlation id; evidence chunk ids reach the trail; and the trail is checked against the
submitted note for any five-word window — there is none.

## 6. Applicability still comes first

An inapplicable case reaches a refusal **with `FakeGateway.calls == []`** — the model is
never called. That is R-93's regression asserted through the whole application rather
than at the runtime alone, and it is enforced by `SliceRunner`, not by this service: a
`PRODUCTION` runner cannot be constructed without an `ApplicabilityPort`.

## 7. The fixture cannot escape into production

`FakeGateway` returns whatever a caller tells it to. A production module that imported
it could produce a fully-formed recommendation with no model, no retrieval and no
firewall — and every downstream check would pass, because the shape would be perfect.

`test_app_does_not_import_the_evaluation_harness_or_the_test_doubles` forbids `app/`
importing `tests`, `eval` or `scripts`. Proven non-vacuously: the import was injected
into `app/case/service.py`, the test failed, the import was removed, the test passed —
and that is now a standing mutation.

The first attempt at that mutation weakened the rule's own constant and **survived**,
because nothing in `app/` imports `tests` anyway. A rule is defended by the violation
failing, not by the rule being present.

## 8. What this does not establish

- **Nothing about model quality.** A fixture returns what it is told.
- **Nothing about R-86.** The provider-failure path is a *simulation* of the downstream
  shape (`SCHEMA_INVALID`); it asserts the application's half — a broken response path
  never becomes an approval or a denial. R-86 remains `VERIFIED_FAILURE`,
  `PROVIDER_SIDE`, root cause not established.
- **Nothing clinical.** No validation, no readiness claim.
- **Reviewer identity is not authenticated.** The API key identifies the *integrator*;
  the reviewer names themselves in the request body and this boundary cannot verify it.
  A real reviewer identity is a later authentication phase.
