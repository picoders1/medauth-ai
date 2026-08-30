# MEDAUTH AI — one-page summary

An evidence-grounded decision-support system for prior authorization, built so that it is
**structurally unable to make the decision itself**.

---

## Problem

Prior authorization asks a reviewer to decide whether a requested procedure meets a
payer's coverage criteria for a specific patient: read a clinical narrative, find the
policy that actually applies — right jurisdiction, right version *as of the date of
service* — and check each criterion against the record.

Automating it has a documented failure mode: systems that issue denials at scale, faster
than anyone can appeal them. The design question is not "can a model do this" but "what
must a system be unable to do".

## Architecture

```
User ──HTTPS──► Identity Provider ──OIDC/RS256──► MEDAUTH
                                                    │ discovery → JWKS → validate
                                                    ▼
                                            validated Principal
                                                    │ permission set
                                                    ▼
                                        service-layer authorization
                                                    ▼
   Case ─► policy/routing ─► evidence ─► AI recommendation ─► HUMAN_REVIEW
              (deterministic)  (semantic,      (per-criterion         │
               by date of       inside the      verdicts; code    accept / request-info
               service)         resolved        computes the       / override
                                versions)       outcome)              ▼
                                                            human disposition
                                                                      ▼
                                                          append-only audit
```

Two separations the whole design exists to protect:

- **`AI recommendation ≠ human decision`** — distinct fields, and an override preserves
  the draft it disagreed with rather than overwriting it.
- **`historical evidence ≠ fresh retrieval`** — a reviewer sees what the original run
  used, read from its audit trail.

## The GenAI component, described accurately

The model does one thing: given a policy criterion and a fenced block of retrieved policy
text, return a **structured per-criterion verdict** with span-verified quotes. It does not
choose the policy, does not decide the outcome, and cannot express one — the tokens
`APPROVE_RECOMMENDED` and `DENY_RECOMMENDED` exist in no model schema, enforced by an
AST-parsing test.

Applicability is resolved by **code** from procedure code, diagnosis codes, jurisdiction
and date of service. Retrieval is semantic but runs only *inside* those resolved versions,
because a confidently-cited answer from an inapplicable policy passes every grounding
metric while being exactly wrong. Every quote is verified as a substring of the chunk it
claims, or the case stops.

## Security engineering

OIDC with RS256 verified against the provider's JWKS; issuer, audience, expiry, nbf,
subject and algorithm all enforced; key rotation verified against a real provider.
Authentication failures are **uniform** — 19 negative cases return one identical `401`, so
a caller cannot learn which check failed. Unknown signing keys and full provider outages
both **fail closed**, never to a `500` and never to a weaker verifier.

Authorization is enforced in the service rather than the route, over three cumulative
permission sets, with the principal's **type** checked before its permissions — a service
integration holding every permission still cannot review. Callers cannot inject an
identity or a permission, because neither field exists. Cases are `404` to anyone not
entitled to them, so existence itself does not leak.

The audit trail records the provider's `sub` **with its issuer**, and is append-only by
database **trigger** — the grants alone were inert, because PostgreSQL never restricts a
table's owner.

## HITL safety

The routing explanation renders **above** the recommendation, which is labelled
*"AI-generated recommendation — not a decision"*. Override requires a rationale;
request-info requires the information requested; accept requires neither, because agreeing
with a cited, rule-derived recommendation adds nothing a later reader lacks. There is no
reviewer assignment, no competence model, and a stated qualification grants nothing.

*R-04 mitigation is structural; its effectiveness on real reviewers is not measured and is
not claimed.*

## Validation

**1373** local tests (unit 648 · api 90 · security 665 · integration 79 · evaluation 516) ·
**47/47** mutations caught · **45/45** production-shaped E2E over HTTPS against a real
Keycloak · smoke suite **7/7** in a mode proven to write nothing · remote CI run
**33168337280** green with database-backed api/security tests genuinely executing.

## Limitations

**R-86 blocks the evaluation.** The provider, given the production schema and a long
clinical note, never closes the JSON document — 6 of 12 trials against a 10% ceiling,
deterministic. It is localised to a decoder MEDAUTH does not operate. The threshold was
not lowered, the schema not simplified, the note not shortened; `gold_v2` is unspent and
the 26-case run has never executed. **A blocked evaluation is not a broken application** —
and there is consequently **no accuracy figure anywhere in this repository**.

**No production deployment.** The topology is verified in production *shape*; platform,
domain, certificate authority, secrets mechanism and operator are all unresolved external
decisions.

**No clinical validation, and no enterprise SSO.** Neither is performed, and neither is
claimed.
