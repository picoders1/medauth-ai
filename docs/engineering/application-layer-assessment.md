# Application layer — what to reuse, what to build

**Assessed at:** 2026-08-26 · **Baseline:** `2aaa19b`, working tree clean.

The previous track built the audit *schema* and proved it append-only. Nothing writes
to it. This assessment is the map from that schema to a working application.

---

## 1. Reusable — call it, do not rebuild it

| component | interface | note |
|---|---|---|
| `SliceRunner.run(SliceInput) -> SliceOutcome` | `app/graph/slice.py` | **Never raises on a case.** Every failure is an outcome. This is the decision pipeline; there must not be a second one |
| `AuditEvent` | `app/contracts/slice.py` | already produced per stage, already carries no text |
| `ApplicabilityPort` | `app/policy/applicability.py` | applicability runs *inside* `run()`, first, before retrieval |
| Provider failure taxonomy | `app/llm/failure_taxonomy.py` | 11 kinds × 5 attributions |
| `Outcome`, `DecisionRule` | `app/decision/` | the vocabulary the API must expose |
| Audit schema | `app/audit/models.py`, migration 0005 | four tables, append-only enforced by trigger |
| Error base | `app/core/errors.py` | `MedauthError` with a handler already registered |

**Critical ordering fact:** applicability is enforced *inside* `SliceRunner`, and a
`PRODUCTION` runner cannot be constructed without an `ApplicabilityPort`. The case
service therefore gets applicability-before-model **for free**, and must not re-implement
or reorder it. Part N is satisfied by delegation, not by new code.

## 2. Missing

| gap | consequence |
|---|---|
| audit **writer** | the schema is unreachable from the runtime |
| case **domain + state machine** | `CaseState` exists as an enum with no transition rules; any string can follow any other |
| case **service** | nothing orchestrates submit → run → persist → route |
| human review **service** | the schema accepts events; nothing produces them |
| **API v1** | `/health`, `/ready`, `/metrics` only |
| **authentication and authorization** | **none at all.** No caller identity anywhere in the API |

## 3. Authorization: the honest starting point

There is no authentication in this application today. Part L says not to add one
unnecessarily — but "not unnecessarily" is not "not at all" when the answer to *who may
read this case* is currently *anyone who can reach the port*.

The minimum that is honest: a caller identity derived from an API key, cases owned by
the caller that submitted them, and enforcement in the **service**, not the route. It is
deliberately small, and its limits are documented rather than dressed up — this is a
caller boundary, not a clinical user model, and it does not know what a reviewer is
allowed to review beyond ownership.

## 4. Dependency order

1. **state machine** — pure, no I/O, testable alone
2. **audit writer** — one abstraction, no raw SQL anywhere else
3. **case service** — orchestrates, delegates to `SliceRunner`
4. **human review service** — writes review events, never edits recommendations
5. **API v1** — routes call services and contain no logic

## 5. Audit insertion points

Fixed by the lifecycle, not by convenience:

```
POST /cases          CASE_RECEIVED, CASE_VALIDATED
service.run()        APPLICABILITY_RESOLVED | APPLICABILITY_REJECTED
                     (stage events lifted from SliceOutcome.audit)
                     PROVIDER_FAILURE where the taxonomy reports one
                     RECOMMENDATION_CREATED | ABSTENTION
                     HUMAN_REVIEW_REQUESTED where routed
POST /review         HUMAN_DECISION_RECORDED, CASE_FINALIZED
any raise            CASE_FAILED
```

`SliceOutcome` already carries per-stage `AuditEvent`s. The writer **lifts** them rather
than re-deriving them, so the persisted trail and the in-memory one cannot disagree.

## 6. Transaction boundary

One transaction per lifecycle step: the case-state update and its audit event commit
together or not at all. A case that reads `RECOMMENDATION_READY` with no event
explaining how it got there is precisely the inconsistency Part H names.

The model call happens **outside** any open transaction — it takes seconds, and holding a
database transaction across a network call to a provider that is currently known to hang
for 6.3 s (R-86) would be a connection-pool outage waiting to happen.

## 7. Out of scope here

UI, Langfuse, Kubernetes, additional providers, confidence calibration, official
evaluation, retrieval tuning, gold changes.
