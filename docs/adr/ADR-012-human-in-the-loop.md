# ADR-012: Human-in-the-Loop Review Workflow

**Status:** Accepted · **Date:** 2026-08-23 · **Phase:** Planning

## Context

MEDAUTH is decision support. A qualified human makes every decision. The architecture must make
that real rather than nominal — including against the failure mode where reviewers approve
everything the system suggests.

## Problem

1. What must a reviewer be able to see and do?
2. What stops "human in the loop" from degrading into a rubber stamp?
3. How is reviewer identity established safely?

## Options

| # | Option | Assessment |
|---|---|---|
| A | Review only low-confidence cases | Efficient. Creates a tier of effectively autonomous decisions. |
| B | **Review every case; abstention determines urgency, not whether review happens** | Slower. Every decision has a human owner. |
| C | Post-hoc sampling audit | Cheapest. Decisions take effect before any human sees them. |

## Decision

**Option B.** Every recommendation is reviewed. Nothing the system produces takes effect on its own.

### What a reviewer sees, in this order

1. The **case** — note, requested procedure, jurisdiction, date of service.
2. The **extracted facts**, each highlighted at its source span in the note.
3. The **resolved policy versions**, and *why* they resolved (matched code, link type, effective
   date range, jurisdiction).
4. The **criteria tree**, with each criterion's verdict.
5. For each verdict, its **citations** — the exact quote highlighted inside the stored chunk, with
   section, page and a link to the public source URL.
6. **Guardrail results**, including any invalid citation and its failure kind.
7. **Then** the recommendation, with the decision-table row that fired and the gate features.

The ordering is deliberate: evidence first, conclusion last.

### What a reviewer can do

Approve · deny · request information · override the recommendation. **Override requires a reason**,
enforced by a database `CHECK` constraint, not only by the UI.

### Identity

Derived from a trusted identity proxy, never read from an untrusted client. Identity headers are
read only when the socket peer falls inside `MEDAUTH_TRUSTED_PROXIES`; `X-Forwarded-For` is never
consulted. Unknown API paths default to reviewer-only, so a new route is protected before anyone
classifies it. Production refuses to start with no trusted range or with `0.0.0.0/0`.

### Audit

Every human action is recorded: reviewer subject, decision, agreement flag, override reason,
timestamps, review duration. The `CHECK` constraint makes an unexplained override impossible to
store.

## Rationale

**Reviewing only uncertain cases creates autonomy by omission.** Under Option A the confident cases
— the majority — are decided by the system in practice, whatever the documentation says. Abstention
should determine *urgency and framing*, not whether a human is involved.

**Evidence-before-conclusion is a design response to automation bias (R-04, T-26).** A reviewer
shown a recommendation first evaluates the recommendation; a reviewer shown evidence first evaluates
the case. The system's own interface is capable of causing the harm it exists to prevent, which is
why this is a threat entry and not a UX preference.

**Mandatory override reasons at the database, not the UI**, because a constraint that lives only in
the frontend is a suggestion. It also produces the dataset that reveals where the system is
systematically wrong.

**Denial is always human-mandatory** and rendered as a *draft rationale*, never as a decision
(ADR-010, R-05).

**Derived identity** follows the sibling project's ADR-023: a system that reads identity from a
client header trusts the client about who they are.

## Consequences

**Positive.** Every decision has a human owner. Reviewers can verify any claim against public source
text. Override data is a direct signal of systematic error. Automation bias is designed against
explicitly.

**Negative.** Review effort scales linearly with volume — this system reduces the *effort per
review*, not the number of reviews, and that limit is stated rather than glossed. Rich evidence
display is substantial UI work (ADR-020). Mandatory reasons add friction, which is the point and is
also a source of low-quality reasons under time pressure.

**Neutral.** Override rate, agreement and review time are **instrumented but not claimed** — they
require a pilot with real reviewers that has not happened and is not scheduled (OD-7). The
instrumentation exists; the numbers do not.

## Rejected alternatives

| Alternative | Rejected because |
|---|---|
| **A — review only low-confidence cases** | Creates a tier of effectively autonomous decisions, contradicting the decision-support boundary in the only way that matters. |
| **C — post-hoc sampling** | Decisions take effect before review. Appropriate for quality monitoring, not for a decision-support system whose outputs concern patient care. |
| **Recommendation shown first** | Optimises reviewer speed by encouraging the bias the system must avoid. |
| **Override reason optional** | Removes the only structured signal about where the system is wrong, and makes silent rubber-stamping indistinguishable from agreement. |
| **Identity from a client header** | Trusts the client about who they are. |
