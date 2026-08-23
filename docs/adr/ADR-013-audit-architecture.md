# ADR-013: Audit Architecture

**Status:** Accepted · **Date:** 2026-08-23 · **Phase:** Planning

## Context

Every recommendation must be reconstructable later. The question a reviewer will eventually face is
not "what did the system say" but "why did it say that, against what text, under which rules, and
who accepted it".

## Problem

1. What is captured, at what granularity?
2. How is the trail protected from alteration?
3. Is the audit write on or off the request path?

## Options

### Write path

| # | Option | Assessment |
|---|---|---|
| A | **Synchronous, on the request path; failure blocks the recommendation** | Nothing is lost. Adds latency; an audit outage becomes a service outage. |
| B | Queued, drops under load (the sibling project's ADR-029) | ~9 ms saved at p50. Records can be lost precisely when the system is busiest. |
| C | Append to a log file, ship asynchronously | Decoupled. A second consistency domain, and log shipping can fail silently. |

## Decision

**Option A: synchronous, on the request path. `MEDAUTH_AUDIT_REQUIRED=true` by default.**
**A recommendation that cannot be audited is not issued.**

### Captured

Case id · request id · input version and note hash · corpus snapshot id · extracted fact ids and
spans · resolved policy ids and versions · matched code and link type · retrieval and rerank scores
· model and model version · prompt version ids · agent versions · per-criterion verdicts · citations
with validation status · guardrail results · the decision-table row that fired · gate features ·
abstention flag and reason · decision-config version · reviewer subject · human decision · override
reason · timestamps · latency and token counts per step · every retry attempt.

### Not captured

| Excluded | Why |
|---|---|
| Clinical free text in payloads | Payloads carry fact **ids** and spans; text is joined from `cases` for display. An audit trail duplicating the note multiplies exposure for no gain. |
| Prompts and completions | Never persisted; prompt *version ids* and token *counts* are. No audit column may hold one, asserted against the schema. |
| Credentials | MEDAUTH holds no provider key; the caller key is environment-only. |
| Raw identity headers | Only the derived subject. |

### Integrity

- **Append-only.** The application role has `INSERT` and `SELECT` on `audit_events` and **not**
  `UPDATE` or `DELETE`. No code path in `app/` updates or deletes an audit row. A test asserts the
  grant, not merely the absence of code.
- **Retention deletes by age and by nothing else.** The only predicate is `created_at` — no filter
  by outcome, reviewer, policy or case, because a purge that can be aimed at particular rows is a
  mechanism for erasing the record of a specific recommendation. Asserted against the compiled SQL.
- Retention runs under a **separate role**, is **off by default** (deletion is irreversible), and is
  batched, because the database command timeout would otherwise make one unbounded `DELETE` time
  out, roll back, and delete nothing while appearing enabled.
- The metric that matters is `oldest_audit_row_age_seconds`, not the delete counter — a counter can
  tick while the backlog grows.

### Reproducibility

`corpus_snapshot_id` + `policy_version_id` + chunk `text_sha256` + `prompt_version` + `model` +
`agent_version` + `decision_config_version` make a recommendation reproducible: the deterministic
half exactly, the model half to whatever extent the provider is deterministic (measured, not
assumed — ADR-008).

## Rationale

**The synchronous write is a deliberate divergence from the sibling project**, and the reason is
what the two trails are *for*. The firewall's audit records a security decision **already
enforced** — dropping a row under load loses a record, not a control. MEDAUTH's audit records the
**provenance of a clinical recommendation**, which is the artefact a reviewer will be asked to
justify. An unauditable recommendation has no value here, so MEDAUTH pays the latency instead. The
firewall's ADR-029 remains right for the firewall.

**Ids rather than text** keeps the trail complete and the exposure minimal: everything needed to
reconstruct the reasoning, nothing that duplicates the clinical record.

**Append-only enforced at the grant** rather than by convention, because the threat is a future code
path, not today's code.

**Unaimable retention** is the property that makes the trail evidence rather than a log. Retention
that could target a decision, a reviewer or a policy would allow the record of a specific
recommendation to be removed while the mechanism looked routine.

## Consequences

**Positive.** Every recommendation is explainable and reproducible. The trail cannot be selectively
altered or purged. No clinical text is duplicated. Threshold recalibration replays from
`gate_features` without re-running any model.

**Negative.** Audit latency is on every request; measured and accepted (R-28). An audit-store outage
stops new recommendations — deliberate, and mitigated by keeping the reviewer console available so
humans can continue working existing cases. Rendering an audit trail requires joins. Storage grows
with case volume and retention is off by default.

**Neutral.** Retention periods are configuration; deletion remains opt-in.

## Rejected alternatives

| Alternative | Rejected because |
|---|---|
| **B — queued, drops under load** | Correct for the firewall, wrong here. Losing the provenance of a clinical recommendation exactly when the system is busiest is the worst time to lose it. |
| **C — log files shipped asynchronously** | A second consistency domain, and shipping can fail silently. The audit trail must be queryable with the case it belongs to. |
| **Storing clinical text in audit payloads** | Multiplies exposure without adding recoverable information — the text is one join away. |
| **Retention filtered by outcome or age of decision** | Any aimable purge is a mechanism for erasing evidence of a specific recommendation. |
| **Cryptographic hash-chaining of audit rows** | Considered. Deferred: it defends against a database administrator, who is out of scope in the threat model, and append-only grants plus separate retention roles address the in-scope threats. Revisit if the threat model widens. |
