# Architecture — the decisions that shaped it

An index, not a summary. Each entry states the decision and what it costs; the ADR
carries the alternatives and the consequences.

**The governing invariant, from which most of the rest follows:**

> **Models produce per-criterion verdicts. Code produces the decision.**

`APPROVE_RECOMMENDED` and `DENY_RECOMMENDED` appear in no model output schema anywhere.
Enforced by a test that parses the AST, so a violation is caught in a module nobody
imports.

---

## Policy resolution and the routing boundary — [ADR-004](../adr/ADR-004-policy-resolution-and-temporal-versioning.md)

**Applicability is deterministic; only retrieval is semantic.** Which policy governs a
request comes from procedure code, diagnosis codes, jurisdiction and **date of service** —
never from similarity. Semantic search runs only *inside* the already-resolved versions.

A vector search over the whole corpus always returns something, and a confidently-cited
answer from an inapplicable policy is the worst failure available here: the citations are
genuine, so every grounding metric passes it.

Version selection is by date of service, never "latest", and retrieval applies the same
temporal predicate as resolution — so an out-of-scope chunk cannot enter an evidence set
even when it is the best semantic match.

## Decision and abstention — [ADR-023](../adr/), [decision-and-abstention.md](decision-and-abstention.md)

A pure function over per-criterion verdicts. Two orderings matter:

- **No applicable policy is never a denial.** Absence of a coverage determination means
  contractor discretion, not non-coverage. A test asserts `DENY_RECOMMENDED` is
  unreachable when resolution is empty.
- **Missing evidence is evaluated before evidenced failure.** That ordering is what stops
  the system denying for missing paperwork — the most common harm pattern in automated
  prior authorization.

**Uncalibrated, and it says so:** every recommendation carries
`confidence_state = UNCALIBRATED`. No threshold is quoted because none has been earned.

## Fail-closed policy semantics — [ADR-024](../adr/)

`decide()` will not adjudicate under a rule shape nobody has reviewed. Half the corpus is
therefore non-adjudicable and routes to a human — that is the finding, not a bug.

## Evidence provenance — [hitl-workflow.md](hitl-workflow.md)

**`historical evidence ≠ fresh retrieval.`** A reviewer sees what the original run used,
read from its audit trail. Re-running retrieval would show today's corpus for yesterday's
decision under a heading saying "supporting evidence" — and the failure would be
invisible, because the citations would still verify.

## Citation contract — [ADR-010](../adr/)

Every quote is span-verified against the chunk it claims, claimed metadata must match, and
the chunk must have been in that criterion's evidence set. `source_url`, `effective_date`
and `document_title` are joined from the database, never accepted from the model. Any
failure stops the case. When strict matching produces too many abstentions, the fix is
normalization or the prompt — never the contract.

## AI recommendation versus human disposition — [ADR-012](../adr/)

**`AI recommendation ≠ human decision.`** Separate fields; `human_disposition` is `None`
until a person acts; an override **preserves** the draft it disagreed with. The routing
explanation renders *above* the recommendation, because showing the proposed answer before
the question is how an interface manufactures agreement (R-04).

## Identity — [OD-43](../open-decisions.md), [reviewer-authentication.md](../security/reviewer-authentication.md)

Two identities that cannot substitute for each other: an API key establishes a **SERVICE**
caller, a validated OIDC token establishes a **HUMAN** reviewer. `Principal.require()`
checks the *type* before permissions, so a service that somehow acquired `REVIEW_CASE`
still cannot review.

## Qualification and competence — [qualification.py](../../app/identity/qualification.py)

Three separate things: **identity** (established), **qualification** (a sentence the person
typed — `SELF_ASSERTED`, grants nothing), **competence** (not modelled; no symbol for it
exists). `VERIFIED_BY_REGISTRY` is in the vocabulary and unreachable. The separation is an
absence, not a rule someone has to remember.

## Authorization — three permissions, cumulative sets

```
medauth-readonly        → {READ_CASE}
medauth-reviewer        → {READ_CASE, REVIEW_CASE, FINALIZE_CASE}
medauth-senior-reviewer → + {OVERRIDE_RECOMMENDATION}
unknown / no group      → {}
```

Enforced in the **service**, not the route. No RBAC beyond this, no reviewer assignment,
no default assignee — a case in `HUMAN_REVIEW` is reviewable by any authorised human, and
that is the honest description of the model rather than a schema nobody writes to.

## OIDC trust boundary — [ADR-030](../adr/ADR-030-identity-provider-selection.md), [identity-provider-contract.md](../security/identity-provider-contract.md)

Provider-neutral: a deployment configures an **issuer**, and `jwks_uri` comes from that
issuer's own discovery document. One canonical issuer per environment — accepting two
means a token from either is honoured and `identity_issuer` stops discriminating.
Keycloak 26 is selected for **non-production** only; no production provider exists.

## Append-only audit — [audit-trail.md](audit-trail.md), [ADR-005](../adr/)

Enforced by **trigger**, not by grant: PostgreSQL never restricts a table's owner, so the
`REVOKE` was inert until triggers replaced it. Retention deletes by `created_at` and by
nothing else — a purge that can be aimed at particular rows is a mechanism for erasing the
record of a specific recommendation.

## Reviewer UI — [ADR-020](../adr/)

Server-rendered Jinja. **No npm, no CDN, no `<script>` tag.** A CDN is a runtime
dependency and a third party in the request path; a reviewer console is not the place for
either.

## LLM gateway — [ADR-016](../adr/ADR-016-llm-firewall-integration.md)

MEDAUTH holds **no model-provider credential** — the firewall holds the upstream key and
MEDAUTH holds a revocable caller key. A `403` from it is never retried: retrying a blocked
request is an attempt to evade a security control. It routes to human review, as do `503`,
a timeout and unreachability. **Fail closed means fail toward the human, never toward a
denial.**

## Deployment — [ADR-019](../adr/ADR-019-deployment.md)

TLS terminates in front of the application, which holds no certificate. Migrations are an
explicit operator step, never run by the application. Discovery happens once at startup and
fails closed, which makes provider availability an ordering dependency the orchestrator
owns — see the [go-live contract](../deployment/go-live-contract.md).

## Evaluation integrity — [ADR-011+](../adr/), [r86-status.md](../evaluation/r86-status.md)

ADRs from 011 onward are **pre-registered protocols**: hypotheses, success criteria and
failure modes fixed before execution. Frozen corpora are versioned, never edited. Hold-outs
carry a scoring budget enforced at the library boundary. Ground truth is by construction —
a case's label comes from its criteria pattern through the same `decide()` the system uses,
because a model labelling cases it will later adjudicate measures self-consistency and
reports it as accuracy.

**The gate that authorises an evaluation has no override parameter and reads no
environment variable**, and a test asserts both over its own AST. It currently says
`BLOCKED`.
