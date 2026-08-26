# Reviewer authentication and authorization (OD-43)

**Code:** `app/identity/` · **Migration:** `0006_reviewer_identity` ·
**Tests:** `tests/security/test_reviewer_identity.py` (25),
`tests/integration/test_reviewer_audit.py` (5) · **Mutations:** 5

---

## 1. What was wrong

The audit trail recorded who **claimed** to decide. `reviewer_id` arrived in the request
body; the API key identified the integrating *system*; nothing connected them.

In an otherwise append-only, trigger-enforced, tamper-proof record, the one field
anybody would actually ask about after a bad outcome was the one field a client chose.

## 2. Two identities, never one

| | establishes | credential | may |
|---|---|---|---|
| **Caller** | the integrating system | `x-api-key` | submit and read its own cases |
| **Reviewer** | the authenticated person | `Authorization: Bearer` | review, override, finalise |

Separate FastAPI dependencies returning separate types, so a route cannot satisfy one
with the other. **An API key can never review**, whatever it is granted.

## 3. `SERVICE` and `HUMAN` are different kinds, not different permissions

`Principal.require()` checks the **type first**:

```python
if permission in HUMAN_ONLY and not self.is_human:
    raise NotAuthorised(...)  # before permissions are consulted at all
```

A service that somehow acquired `REVIEW_CASE` — a mapping typo, an over-broad IdP group
— still cannot review. If this were "a principal holding the permission may review",
OD-43 would be reintroduced under a better-looking name, and the property would depend
on a permission mapping being correct forever.

## 4. Permissions are mapped, never read from the token

`_PERMISSION_FOR_ROLE` maps **recognised** role names onto permissions and ignores
everything else. A token asserting `"permissions": ["FINALIZE_CASE"]` grants nothing,
because that claim is never consulted; a new group in the IdP cannot silently become
authority here.

| role | permissions |
|---|---|
| `medauth-readonly` | `READ_CASE` |
| `medauth-reviewer` | `READ_CASE`, `REVIEW_CASE`, `FINALIZE_CASE` |
| `medauth-senior-reviewer` | the above **+** `OVERRIDE_RECOMMENDATION` |

Override is a separate authority from review: **disagreeing with the engine is not the
same permission as agreeing with it.**

## 5. Token validation

Signature, issuer, audience, `exp`, `nbf`, `iat`, and a required `sub`. Every option is
listed explicitly rather than left to a default, so a future edit has to say out loud
which verification it is switching off. `algorithms` is an allow-list that **excludes
`none`** — an unsigned token is not weakly authenticated, it is unauthenticated wearing
the shape of authentication.

**The refusal message does not name the failed check.** The first version interpolated
`type(failure).__name__` — `InvalidIssuerError`, `ExpiredSignatureError`,
`InvalidAudienceError` — each of which tells a caller how to craft the next token. Its
own test caught it. The cause still reaches the log via the exception chain.

## 6. Authorization is in the service

`HumanReviewService.record()` calls `reviewer.require(...)` before touching the case. A
route-only check is one a second entry point can miss.

`REVIEW_CASE` is checked **first, on every action** — and that ordering matters more than
it looks. `REQUEST_INFO` does not finalise, so it deliberately skips the
`FINALIZE_CASE` check, which makes `REVIEW_CASE` its **only** guard. A mutation that
removed it survived at first, because the test used `APPROVE` where finalisation still
refused. The check looked redundant when it is the sole guard on that path.

## 7. The request body cannot name the reviewer

`reviewer_id`, `accepted_by` and `finalized_by` are **absent from `ReviewRequest`**, and
`HumanReviewService.record()` has no such parameter. The fix is an absence, not a
validation rule — a validation rule is somewhere an exception gets added.

`extra="forbid"` means a client sending one gets a **422 naming the field**, rather than
having it silently ignored: a silently-dropped identity field is worse than a rejected
one, because the caller believes it worked.

`stated_qualification` remains, and is not an authority claim. It says *on what basis*
someone decided; the token says *who*. This project cannot enumerate clinical
credentials and a dropdown would imply it had.

## 8. Production refuses the development adapter

`Settings` refuses `auth_mode=development` when the environment is production — it
would authenticate anybody who guessed a configured token name — and refuses
`auth_mode=oidc` without an issuer and an audience, which would verify tokens against
nothing in particular. Both fail at **startup**, not at the first review.

The development adapter is not a bypass: it produces a `Principal` and nothing else, so
every downstream check is identical. A test asserting a development principal exercises
the same authorization path as production.

## 9. What the trail records now

`identity_model`, `principal_id`, `principal_type`, `authentication_method`,
`identity_issuer` — alongside the existing action, outcome, rationale and
`recommended_outcome_at_review`.

A `CHECK` constraint refuses an `AUTHENTICATED_HUMAN` row with no principal, because the
API is not the only writer a deployment might ever have.

## 10. Historical rows are preserved, not rewritten

Every pre-existing review event is labelled `LEGACY_CALLER_SUPPLIED` and **no principal
is back-filled onto it**, because there was none at the time. A reader can tell, per
row, how much the identity on it is worth — which is strictly more useful than a uniform
column that quietly means two different things.

## 11. The contract the future UI will use

```
UI  →  OIDC/OAuth2 login  →  access token
    →  FastAPI: Authorization: Bearer <token>  +  x-api-key: <integrator>
    →  reviewer_from_headers  →  Principal
    →  HumanReviewService: require(REVIEW_CASE | OVERRIDE | FINALIZE)
    →  human_review_events + audit_events, both append-only
```

The UI never sends a reviewer identity. It sends a token, and the token decides.

## 12. Identity-provider integration — and what "integrated" means here

**No provider is named by this project.** No ADR chose one, and this phase did not.
`discover()` reads the standard `.well-known/openid-configuration` document, so a
deployment configures an **issuer** and nothing vendor-specific. Any conformant OIDC
provider works.

```
MEDAUTH_OIDC_ISSUER      → .well-known/openid-configuration → jwks_uri → PyJWKClient
MEDAUTH_OIDC_AUDIENCE    → audience check
MEDAUTH_OIDC_DISCOVERY   → true (default)
```

**The discovery document must advertise the issuer it was fetched for.** A document
claiming a different issuer is either misconfiguration or an attacker redirecting key
discovery, and both are refused — trusting a `jwks_uri` you have not tied to your
expected issuer is how discovery becomes the attack.

**Discovery is fetched at startup, not per request.** A discovery call on the
authentication path would make every review depend on the provider's availability and
would point a request amplifier at somebody else's service.

**A discovery failure refuses reviews. It never degrades.** Not to a symmetric secret,
not to the API key. An authenticator that got laxer when its key source was unreachable
would be least trustworthy exactly when something was wrong.

**Key rotation** is `PyJWKClient`'s: an unknown `kid` triggers a refetch, so a rotation
does not need a restart. Asserted over the library's own source, because a wrong
assumption here fails only *during* a rotation — when every reviewer is locked out and
nobody knows why.

### A weakness this phase found and closed

Production started happily with `MEDAUTH_OIDC_SECRET` set. HS256 means the **verifier
holds the key that signs**: anyone with the application's configuration could mint a
reviewer token, and the audit trail would record it as a verified human identity. That
is a shared password with extra steps.

Production now refuses to start with it, and refuses `auth_mode=oidc` with neither
discovery nor a JWKS endpoint — there would be no public key to verify against. Both
fail at startup. The symmetric path survives for tests, which need no key server.

### Readiness

`reviewer_identity` is a **REQUIRED** readiness check, not advisory. A deployment that
cannot authenticate a reviewer cannot finalise any case, and every case ends at a human —
so it is a stopped system, not a degraded one. It reports the mechanism, never a
credential.

### Four claims that are not the same claim

| | status |
|---|---|
| provider integration **implemented** | **yes** — discovery, validation, rotation, tests |
| provider configuration **verified against a real IdP** | **no** — no issuer has been pointed at a live provider |
| deployment **performed** | **no** |
| **production-ready** | **no** — see the row above and §13 |

Local integration working is not enterprise SSO deployed, and this document does not
say it is.

## 13. What this does NOT establish

- **No enterprise SSO is deployed.** The OIDC adapter is implemented and tested against
  a symmetric key and a JWKS client, and **no real identity provider is integrated**.
  Standing up one is a deployment task this repository has not performed.
- **No RBAC beyond three permissions.** There is no specialty, no delegation, no
  case-assignment model. A reviewer with `REVIEW_CASE` may review *any* case their
  integrator can see.
- **No proof the person is a clinician.** `stated_qualification` is what they said. The
  system verifies identity, not competence, and OD-19 remains the open question about
  qualified review.
- **Not a session model.** No refresh, no revocation list, no logout. A token is valid
  until it expires.
