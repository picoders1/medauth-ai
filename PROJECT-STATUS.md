# MEDAUTH AI — project status

**This is the single authoritative status document.** Where any other document disagrees
with it, this one is current. It is written to be read by an engineer who has never seen
the repository, without requiring undocumented context.

| | |
|---|---|
| **Engineering** | **PORTFOLIO-READY / ENGINEERING-COMPLETE** |
| **Remote CI** | **VERIFIED PASS** — run `33097477139` on `4870ae3` |
| **Production shape** | **VERIFIED** |
| **Production deployment** | **NOT PERFORMED** |
| **R-86 evaluation gate** | **BLOCKED — external provider limitation** |
| **Enterprise SSO** | **NOT DEPLOYED / NOT CLAIMED** |
| **Clinical validation** | **NOT CLAIMED**, and none exists |

**Start here:** [final project brief](docs/portfolio/final-project-brief.md) ·
[interview notes](docs/portfolio/interview-notes.md) ·
[project summary](docs/portfolio/project-summary.md) ·
[five-minute demo](docs/portfolio/demo-guide.md) ·
[evidence scorecard](docs/evidence/final-scorecard.md) ·
[architecture index](docs/architecture/README.md) ·
[security evidence](docs/security/security-summary.md) ·
[why R-86 is blocked](docs/evaluation/r86-status.md) ·
[external dependency register](docs/operations/external-dependency-register.md) ·
[final blocker matrix](docs/operations/final-blocker-matrix.md) ·
[R-86 closure procedure](docs/evaluation/r86-closure-procedure.md)

Every figure below was produced by a command in this repository. Nothing is carried
forward from a previous report.

---

## 1. The governing invariant

> **Models produce per-criterion verdicts. Code produces the decision.**

The tokens `APPROVE_RECOMMENDED` and `DENY_RECOMMENDED` appear in no model output schema
anywhere in the system. This is enforced by an AST-parsing test, so a violation is caught
even in a module nobody imports.

The system produces a **recommendation for a human reviewer**. It does not make coverage
determinations.

## 2. Architecture

### Identity and authorization

```
User
 ↓ HTTPS  (terminated at a reverse proxy; the application holds no certificate)
Identity Provider  (Keycloak 26, non-production)
 ↓ OIDC token, RS256
MEDAUTH
 ↓ OIDC discovery → JWKS → signature/issuer/audience/expiry/nbf/subject validation
validated Principal  (type checked BEFORE permissions)
 ↓
existing permission set  (three permissions, cumulative sets)
 ↓
service-layer authorization  (in the service, not the route)
 ↓
case / HITL service
 ↓
review decision
 ↓
append-only audit  (enforced by trigger, not by grant)
```

### The AI decision flow

```
Case
 ↓
policy resolution / routing      deterministic: code, jurisdiction, DATE OF SERVICE
 ↓
retrieval / evidence             semantic, but only INSIDE the resolved versions
 ↓
AI recommendation                per-criterion verdicts → code computes the outcome
 ↓
HUMAN_REVIEW
 ↓
accept | request-info | override
 ↓
human disposition
 ↓
audit / history
```

**Two separations the design exists to protect:**

- **`AI recommendation ≠ human decision.`** They are distinct fields. `human_disposition`
  is `None` until a person acts, and an override preserves the original draft rather than
  replacing it.
- **`historical evidence ≠ fresh retrieval.`** A reviewer sees the evidence the original
  run used, read from its audit trail. Re-running retrieval would show today's corpus for
  yesterday's decision — and the failure would be invisible, because the citations would
  still verify.

## 3. Security evidence — demonstrated facts only

| property | evidence |
|---|---|
| asymmetric OIDC verification (RS256 via JWKS) | real tokens from Keycloak 26 |
| issuer validation | forged issuer → `401` |
| audience validation | wrong audience → `401` |
| expiry / not-before | expired and future-`nbf` → `401` |
| subject required | token without `sub` → `401` |
| unsupported algorithm | `alg=none` → `401` |
| JWKS key rotation | new realm key → new `kid`; the container refetched its cached JWKS and accepted it; an override on the rotated key returned `201`; the superseded key stayed published |
| unknown `kid` fail-closed | `401`, repeatedly — **fixed this project**: it was an unhandled `500` |
| IdP outage fail-closed | provider stopped entirely → `401`, same body, never a `500` |
| uniform authentication failure | 19 negative cases, **one identical `401` body**; bad signature, unknown `kid` and wrong audience are indistinguishable |
| service-layer authorization | enforced in the service, verified through the published port |
| unknown group denied | grants the empty set |
| permission-set enforcement | full matrix, §4 |
| type-before-permission | a SERVICE principal holding **every** permission is refused all three human actions |
| 404 anti-enumeration | a nonexistent case and another integrator's case are indistinguishable |
| audit identity integrity | `principal_id` is the provider `sub`, recorded with `identity_issuer` |
| append-only history | `UPDATE` and `DELETE` both refused by trigger — grants alone were inert, because PostgreSQL never restricts a table's owner |
| TLS trust verification | verified against a local CA; **refused** without it; **refused** on a wrong hostname |
| secrets excluded | none in source, none in the image; `SecretStr` plus redaction at the structlog sink |
| runtime reproducibility | clean `--no-cache` build, 37 packages, no optional extra masking a runtime dependency |
| mutation evidence | **47/47 caught** where the restricted corpus is present. In CI, which cannot hold that corpus, the guard reports **37 caught, 10 not verified** and names them — it does not credit a mutation whose catching test could not run |

## 4. Authorization

```
medauth-readonly        → {READ_CASE}
medauth-reviewer        → {READ_CASE, REVIEW_CASE, FINALIZE_CASE}
medauth-senior-reviewer → {READ_CASE, REVIEW_CASE, FINALIZE_CASE, OVERRIDE_RECOMMENDATION}
unknown / no group      → {}
```

Cumulative sets, not one group to one permission. The mapping lives in MEDAUTH; the
provider says which groups a person is in and nothing about what those groups may do.
Verified through the published HTTPS port:

| | read | accept | request-info | override |
|---|---|---|---|---|
| readonly | 200 | 403 | 403 | 403 |
| reviewer | 200 | 201 | 201 | **403** |
| senior reviewer | 200 | 201 | 201 | 201 |
| outsider | 403 | 403 | 403 | 403 |

## 5. HITL safety — verified properties

- routing explanation is rendered **before** the recommendation (anti-anchoring, R-04)
- AI output is labelled *"AI-generated recommendation — not a decision"*
- AI recommendation and human disposition are distinct fields
- override requires a rationale; request-info requires the information requested
- accept requires **no** rationale — agreeing with a cited, rule-derived recommendation
  adds nothing a later reader lacks; disagreeing does
- finalization is possible only from `HUMAN_REVIEW`, enforced in the service
- evidence comes from the original run's audit trail, never re-retrieved
- history is append-only; a later action is a new entry
- **reviewer assignment does not exist**, by design, and there is no default assignee
- **competence is not modelled** — no symbol for it exists
- qualification is informational: `SELF_ASSERTED`, grants nothing, and
  `VERIFIED_BY_REGISTRY` is unreachable (verified by walking every `return`)

> **R-04 mitigation: structural mitigation implemented; effectiveness not clinically
> measured.** Ordering, labelling and field separation are in place and asserted by
> tests. Whether they actually reduce automation bias in real reviewers is an empirical
> question this project has not answered and does not claim to have.

## 6. R-86 — the evaluation limitation

| | |
|---|---|
| **Current result** | **6/12 failures = 50%** |
| **Threshold** | **≤ 10%** (pre-registered, unchanged) |
| **Gate** | **`BLOCKED`** |
| **Cause classification** | **PROVIDER-SIDE / UPSTREAM** |
| **Confidence** | **high** in localisation · **low** in the exact internal decoder mechanism |

**What it is.** Grammar-constrained decoding guarantees output *shape*, not *termination*.
On the registered reproducer — the production `IntakeExtraction` schema with a long
clinical note — the provider emits about 190 non-whitespace characters, never closes the
JSON document, and spends the remaining ~1350 tokens on whitespace until the completion
ceiling stops it. Deterministic at temperature 0: byte-identical across six trials, hours
apart.

**Ruled out, each by measurement:** MEDAUTH application defect · gateway request path ·
gateway response path · output-budget insufficiency (a *longer* prompt with the same
schema terminates cleanly at 67% of the ceiling, emitting ten times more content) ·
context exhaustion · prompt length alone · schema alone · content alone · a defective
reproducer.

**Control boundary.** MEDAUTH and the gateway are locally controllable; the gateway
forwards the payload verbatim and has no structured-output handling at all. The provider's
decoder and runtime are externally controlled — no administrative surface, no runtime
version reported, and no local alternative exists. **MEDAUTH cannot legitimately remediate
the root cause locally.**

**Integrity:** seal intact · registered schema, gold note and request shape unchanged ·
threshold `0.10` unchanged · evaluator unchanged · `gold_v1 = 2/2` · `gold_v2 = 0/1`
**unspent** · official revalidation **not re-run** · **26-case evaluation not run**.

**R-86 is not authorised, and nothing here should be read as authorising it.** It is an
external provider-dependent evaluation limitation, not an unresolved MEDAUTH defect.

## 7. Evidence matrix

| Capability | Status | Evidence |
|---|---|---|
| Application | **COMPLETE** | 102 modules, 6 migrations, 1414 backend tests |
| Reviewer console | **NOT production-ready** | builds, type-checks, 35 frontend tests; two interfaces, and the Jinja page is the reference — [reviewer-ui.md](docs/architecture/reviewer-ui.md) |
| Authentication | **COMPLETE** | real RS256 tokens end to end; 19 negative cases |
| Authorization | **COMPLETE** | matrix in §4, through the published port |
| HITL | **COMPLETE** | accept / request-info / override verified live |
| Audit | **COMPLETE** | authenticated `sub` + issuer; `UPDATE`/`DELETE` refused |
| Runtime | **COMPLETE** | clean `--no-cache` build; reviewer UI renders |
| Remote CI | **PASSING** | run `33310007211` on `21f94bc` (final): every step green, none skipped. Test step **952 passed, 117 skipped** — the skips are corpus-gated (ADR-003), and the database-backed api/security tests execute against a real PostgreSQL service |
| Real IdP | **VERIFIED NON-PRODUCTION** | Keycloak 26, `verify_idp.py` 12/12, `verify_idp_e2e.py` 39/39 |
| Production-shaped E2E | **COMPLETE** | `verify_idp_container_e2e.py` **45/45** over HTTPS |
| Production deployment | **NOT PERFORMED** | no platform, domain, CA or operator exists |
| R-86 | **BLOCKED** | 6/12 vs 0.10 |
| 26-case evaluation | **NOT RUN** | `AUTHORISATION.json` records `authorised: false`; no results exist |
| Clinical validation | **NOT CLAIMED** | none performed; a reviewer workflow is not one |

## 8. Production limitations

**None of these is an application defect.** They are decisions and evidence that belong
to whoever deploys the system.

**Infrastructure:** deployment platform not selected · DNS/domain not established ·
certificate authority not established · secrets mechanism not selected · backup, restore
and a tested restore drill not performed · HA/DR not architected · alerting does not
exist.

**Provider:** production IdP ownership not established; the verified Keycloak is
non-production (in-memory in one stack, a local CA in the other, four fixture identities).

**Organisation:** MFA policy · identity lifecycle · **who may hold senior-reviewer
membership** — the authority to overturn a recommendation · access-token lifetime, which
is the entire revocation window · audit and identity-log retention · DR targets ·
enterprise SSO approval.

**Production-only evidence:** real certificates and DNS · key rotation under traffic ·
load and soak testing · a restore drill · anything about behaviour at production scale.

**No enterprise SSO is deployed. No production deployment has occurred. No organisational
approval exists.**

## 9. Two known operational gaps worth stating plainly

- **Token revocation is not checked — measured, not inferred.** With an account disabled
  in the realm, a *new* login is refused by the provider while the *existing* token still
  authenticates. Exposure is bounded only by `accessTokenLifespan`.
- **Subject reassignment cannot be detected.** If an operator mints a new user carrying a
  retired `sub`, the token is valid and resolves to the wrong person's history. This is a
  property of the directory, not of MEDAUTH, and it is not mitigated.

## 10. Where to go next

| | |
|---|---|
| how it works | [docs/architecture/](docs/architecture/) |
| why, with alternatives | [docs/adr/](docs/adr/) — 30 ADRs |
| what may and may not be claimed | [docs/evidence-and-claims.md](docs/evidence-and-claims.md) |
| risks and open decisions | [docs/risk-register.md](docs/risk-register.md) (101), [docs/open-decisions.md](docs/open-decisions.md) |
| threat model | [docs/security/threat-model.md](docs/security/threat-model.md) — 27 threats |
| deployment | [docs/deployment/go-live-contract.md](docs/deployment/go-live-contract.md), [runbook](docs/operations/production-deployment-runbook.md) |
| the R-86 escalation | [docs/operations/r86-provider-escalation.md](docs/operations/r86-provider-escalation.md) |
| **run it yourself** | [README §13](README.md) |
