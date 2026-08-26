# Human-review metrics — defined, and none reported

**No values appear in this document, and none may until real review activity exists.**

Definitions are written now, before any data, for the same reason experiment manifests
are frozen before a run: a metric defined after seeing the numbers is a metric chosen to
suit them.

---

## The metrics

| metric | definition | denominator |
|---|---|---|
| **review turnaround** | `disposition_at − recommended_at`, per case | cases reaching a disposition |
| **override rate** | `OVERRIDE` ÷ all review actions | review actions, not cases |
| **AI–human agreement** | dispositions matching `recommended_outcome_at_review` | reviewed cases with a recommendation |
| **request-information rate** | `REQUEST_INFO` ÷ all review actions | review actions |
| **reviewer workload** | distinct cases per `principal_id` per day | authenticated humans only |
| **cases reviewed per day** | dispositions per calendar day | — |

Every one is computable from `human_review_events` alone, which is append-only. No
metric here requires mutating a record to produce.

## Reporting rules

**Agreement is not accuracy.** A reviewer agreeing with the engine says the reviewer
agreed. It says nothing about whether either was right, and reporting agreement as an
accuracy proxy would be the circular-ground-truth error the evaluation regime already
refuses.

**Override rate is not a quality signal on its own.** A low rate may mean the engine is
good or that reviewers are rubber-stamping — R-04, the automation-bias risk, is exactly
the second reading. It must be reported beside review duration, never alone.

**Denominators are review actions, not cases.** A case can be reviewed more than once
(`REQUEST_INFO` returns it), and dividing by cases would quietly inflate rates.

**Legacy rows are excluded from any per-reviewer metric.** A
`LEGACY_CALLER_SUPPLIED` row records a name somebody typed, and attributing workload to
an unauthenticated string would be a number about nothing.

## Why nothing is reported

There has been no clinical review activity. The system has been exercised by fixtures
and integration tests, and counting test traffic as reviewer workload would be
fabrication.

When real activity exists, these figures come from the audit trail with denominators and
Wilson intervals, like every other rate in this project.
