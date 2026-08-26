# The non-production identity provider

**Provider:** Keycloak 26 · **Realm:** `medauth-nonprod` · **Issuer:**
`http://localhost:8090/realms/medauth-nonprod` · **Audience:** `medauth-api`
**Selected by:** the repository owner, 2026-08-26 (ADR-030 amendment)
**Evidence:** `scripts/verify_idp.py` 12/12 · `scripts/verify_idp_e2e.py` 39/39

> **This is not production SSO and is not enterprise-ready.** It is a real OIDC
> provider issuing real RS256 tokens, run locally so the authentication boundary can
> be exercised by something this repository did not sign. Everything in §6 is what it
> does not establish.

---

## 1. Running it

```bash
docker compose -f compose.idp.yaml up -d      # a SEPARATE file, never the default stack
set -a; . ./.env; set +a
bash scripts/bootstrap_nonprod_idp.sh         # idempotent: reconciles, does not duplicate
uv run python scripts/verify_idp.py --issuer "$MEDAUTH_OIDC_ISSUER" --audience medauth-api
uv run python scripts/verify_idp_e2e.py
```

Port 8090, because 8080–8082 are bound on the reference machine and 8010 was reclaimed
(ADR-019 and its amendment).

**No secret is committed.** Passwords are generated into `.env`, which is gitignored;
`.env.example` carries dummies. Nothing here is a real person and no PHI reaches it.

## 2. Groups, and where the mapping lives

| provider group | MEDAUTH permission set |
|---|---|
| `medauth-readonly` | `{READ_CASE}` |
| `medauth-reviewer` | `{READ_CASE, REVIEW_CASE, FINALIZE_CASE}` |
| `medauth-senior-reviewer` | `{READ_CASE, REVIEW_CASE, FINALIZE_CASE, OVERRIDE_RECOMMENDATION}` |
| anything else, or no group | `{}` |

Cumulative sets, not one group to one permission. **The mapping lives in
`_PERMISSION_FOR_ROLE`, not in the provider.** Keycloak says which groups a person is
in and nothing about what those groups may do; a provider that could grant a MEDAUTH
permission directly would be a second authorization system, and the first one would
stop being authoritative.

Two claims are read from a token — `sub` and `groups`. A `permissions` claim is not
consulted at all, verified live: a token asserting
`permissions: ["OVERRIDE_RECOMMENDATION"]` with an empty `groups` grants nothing.

## 3. The `sub` invariant

> The `sub` identifying a person must be stable, issuer-scoped, and never reassigned
> to another person for the lifetime of the audit history.

**Technically verified against this provider:**

| property | result |
|---|---|
| stable across repeated logins | same UUID both times |
| survives a credential change | same UUID after an admin password reset |
| a deleted-then-recreated username is a **new** subject | `b869ea57…` → `c031333d…` |
| issuer-scoped **in MEDAUTH's own record** | `human_review_events.identity_issuer` stores the issuer beside `principal_id` |

The last row is the one MEDAUTH controls. A subject is never recorded as a bare string:
the row says *this subject, from this issuer*, so re-pointing a deployment at a
different provider cannot silently merge two people's histories.

**External trust assumptions — MEDAUTH cannot prove these:**

1. **Non-reassignment.** Keycloak generates a UUIDv4 per user, and the third row shows
   it does not recycle one when a username is reused. But the admin API accepts an
   explicit `id` at creation, so an operator *can* mint a user carrying a retired
   subject. Nothing in MEDAUTH can detect it: the token would be valid and the subject
   would resolve to the wrong person's history.
2. **One human per account.** A shared account produces one `sub` for several people,
   and every review it performs is attributed to a single identity. This is an
   operational control, not a technical one.
3. **Directory integrity** — that the operator, not an attacker, controls group
   membership and account lifecycle.

**MEDAUTH does not claim to prove `sub` stability.** It verifies what a token asserts
and records what it verified; the guarantee behind the subject belongs to whoever runs
the provider.

## 4. What was verified, in three separable categories

Kept apart deliberately: reporting them as one number would let mocked coverage stand
in for real-provider evidence.

| | what it proves | result |
|---|---|---|
| **mocked tests** (in CI) | this repository's side of the boundary — parsing, validation options, refusals | 1360 passed |
| **real OIDC** (`verify_idp.py`) | the provider is compatible: discovery, issuer, JWKS, algorithms, `kid`s, a real token | 12/12 |
| **real E2E** (`verify_idp_e2e.py`) | the application behaves correctly on identities it did not mint | 39/39 |

The last two are **not** in the test suite, and must not be. A pytest module needing a
live Keycloak would fail in CI, fail offline and fail whenever the container was down —
none of which is a fact about MEDAUTH.

## 5. The defect real tokens found

`authenticate()` caught `jwt.InvalidTokenError`. `PyJWKClientError` is a **sibling** of
it under `PyJWTError`, not a subclass — so a token bearing a `kid` the provider never
published escaped the handler and became an unhandled exception: **HTTP 500 on an
unauthenticated request.**

Access was still denied, so it was not a bypass. What it was: a uniform-refusal
failure. Every other rejection is a 401 with a fixed message precisely so a caller
cannot tell which check failed; a 500 said *your kid is unknown* as distinct from *your
signature is bad*. And because `PyJWKClientConnectionError` subclasses it, a provider
that was simply down produced a 500 instead of the documented fail-closed refusal.

Fixed by naming it in the `except`. Two regression tests, both verified to fail against
the unfixed code. **The mocked suite could not have found this** — its rotation test
proves an unknown `kid` triggers a refetch, and this is the branch where the refetch
comes back empty.

## 6. What this does not establish

**Implementation.** Nothing under `app/` changed for Keycloak, and nothing would change
for another conformant provider — the one change was the defect fix, which is
provider-independent.

**Provider.** `start-dev`, in-memory H2, no HTTPS enforcement, no persistence across a
`down`. Disqualifying for production by design: this provider cannot be promoted by
changing an environment variable. No refresh-token rotation policy, no session
management, no MFA, no lockout policy has been configured or tested.

**Non-production.** Verified in-process via `TestClient`, not through the published
container port: the API container cannot resolve `localhost:8090`, and giving it a
routable name for the issuer would have made the token's `iss` differ from the host's
view of it. Same application, same routes, same service layer, same real tokens — but
the containerised network path is unverified. Four fixture identities in a throwaway
realm; no directory, no provisioning, no deprovisioning, no rotation-under-load.

**Production.** **No production SSO is deployed and none is claimed.** No production
IdP is selected (ADR-030 stands for deployment). No real key rotation has been
observed. No clinical validation, and an authentication boundary is not one.
