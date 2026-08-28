# MEDAUTH AI — final project brief

**State:** engineering complete · **Evaluation:** blocked by an external provider ·
**Production:** not deployed · **Clinical validation:** not performed

---

## Problem

Prior authorization asks a reviewer to decide whether a requested procedure meets a
payer's coverage criteria for a specific patient: read a clinical narrative, find the
policy that actually applies — right jurisdiction, right version **as of the date of
service** — and check each criterion against the record.

Automating it has a well-documented failure mode: systems that issue denials at scale,
faster than anyone can appeal them. So the design question was never "can a model do
this". It was **what must the system be structurally unable to do**.

## Architecture

```
User
 ↓ HTTPS
OIDC Identity Provider
 ↓ RS256 token
JWT / JWKS validation
 ↓
Principal            (type checked BEFORE permissions)
 ↓
Permission set       (three permissions, cumulative)
 ↓
Service authorization (in the service, not the route)
 ↓
HITL
 ↓
Append-only audit    (enforced by trigger, not by grant)
```

```
Case
 ↓
Policy / routing     deterministic — code, jurisdiction, DATE OF SERVICE
 ↓
Evidence             semantic, but only INSIDE the resolved versions
 ↓
AI recommendation    per-criterion verdicts; CODE computes the outcome
 ↓
Human review
 ↓
Human disposition
 ↓
Audit
```

**The invariant everything else follows from:** models produce per-criterion verdicts,
code produces the decision. `APPROVE_RECOMMENDED` and `DENY_RECOMMENDED` appear in no
model output schema anywhere, enforced by a test that parses the AST so a violation is
caught in a module nobody imports.

## Engineering highlights

- **OIDC / JWKS with asymmetric signing.** Issuer, audience, expiry, nbf, subject and
  algorithm all enforced; keys read from the issuer's own discovery document; rotation
  verified against a real provider.
- **Fail-closed authentication.** Unknown `kid` and full provider outage both refuse,
  never a `500`, never a weaker verifier. 19 negative cases return **one identical
  `401`**, so no oracle is offered.
- **Service-layer authorization** over three cumulative permission sets, with the
  principal's *type* checked before its permissions.
- **HITL that cannot be short-circuited.** Draft and disposition are separate fields; an
  override preserves the draft it disagreed with; the routing explanation renders *above*
  the recommendation.
- **Evidence provenance.** A reviewer sees what the original run used, read from its
  audit trail — never re-retrieved.
- **Append-only audit by database trigger.** Grants alone were inert: PostgreSQL never
  restricts a table's owner.
- **Runtime reproducibility.** Clean `--no-cache` image, 37 packages, no optional extra
  masking a runtime dependency.
- **Real Keycloak 26 integration**, production-shaped: HTTPS, persistent storage,
  non-development mode, verified key rotation.

## Evidence

| | |
|---|---|
| Local suite | **1369 passed** (unit 644 · api 90 · security 665 · integration 79 · evaluation 516) |
| Mutation testing | **47/47 caught** |
| Production-shaped E2E | **45/45** through the published port |
| Safe smoke | **7/7**, zero review-event rows written |
| Remote CI | run **33168337280** — success, no non-success steps |
| Static | ruff · format · mypy · alembic · `uv lock` all clean |

## The limitation, stated plainly

**R-86 blocks the evaluation.** On the registered reproducer the provider emits ~190
non-whitespace characters, never closes the JSON document, and pads whitespace to the
completion ceiling — **6 of 12 trials against a 10% threshold**, deterministic at
temperature 0 and byte-identical across runs. The failure is localised with high
confidence to a decoder MEDAUTH does not operate and cannot inspect.

The threshold was not lowered, the schema not simplified, the note not shortened, the
failing cell not dropped. `gold_v2` remains **unspent** and the 26-case evaluation has
never run. **There is consequently no accuracy figure anywhere in this repository** — and
a blocked evaluation is not a broken application.

## The only legitimate path out

```
PROVIDER EVIDENCE
      ↓
ROOT CAUSE IDENTIFIED
      ↓
PROVIDER-SIDE CORRECTION
      ↓
INDEPENDENT VERIFICATION
      ↓
scripts/r86_revalidate.py
      ↓
PASS ≤ 0.10
      ↓
official gate → AUTHORISED
```

**The revalidation must run against the unchanged registered seal and reproducer.** A
modified request that succeeds is a different experiment, not a repair of this one — the
closure contract classifies it as `NEW_SYSTEM_CONFIGURATION`.

## What is finished, and what is somebody else's decision

| Item | Classification | Current state | Required action |
|---|---|---|---|
| MEDAUTH application | **COMPLETE** | verified | none |
| Remote CI | **COMPLETE** | passing | none |
| Production-shaped E2E | **COMPLETE** | 45/45 | none |
| Security | **COMPLETE** | verified | none |
| HITL | **COMPLETE** | verified | none |
| Audit / provenance | **COMPLETE** | verified | none |
| R-86 | **EXTERNAL BLOCKER** | 6/12 | provider correction, then revalidation |
| Production platform | **EXTERNAL DECISION** | not selected | choose when deploying |
| Production IdP ownership | **EXTERNAL DECISION** | not supplied | assign an owner |
| Production secrets platform | **EXTERNAL DECISION** | not selected | select for real deployment |
| DNS / CA | **EXTERNAL DECISION** | not supplied | establish for production |
| HA / DR / backups | **EXTERNAL OPERATIONS** | not performed | design and execute before production |
| Reviewer governance | **EXTERNAL DECISION** | no owner | decide who may hold senior-reviewer |
| Clinical validation | **OUT OF CURRENT SCOPE** | not performed | separate validation programme |
| `data/cms/registry.yaml` | **NON-BLOCKING DEBT** | known | optional future cleanup |

**None of the rows below "R-86" is an application defect.** They are decisions and
operational work that belong to whoever deploys the system.

## What is not claimed

No production deployment. No enterprise SSO. No clinical validation. No R-86
authorization. No provider root-cause certainty. No reviewer workload metrics — every
review action recorded so far was generated by a verification script, and test traffic is
never counted as reviewer activity.
