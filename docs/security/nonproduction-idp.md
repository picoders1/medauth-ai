# The non-production identity provider

**Provider:** Keycloak 26 · **Realm:** `medauth-nonprod` · **Issuer:**
`http://172.17.0.1:8090/realms/medauth-nonprod` · **Audience:** `medauth-api`
**Status:** a project-level decision for MEDAUTH's non-production integration
(ADR-030 amendment). No organisational or enterprise approval exists or is claimed.
**Evidence:** `verify_idp.py` 12/12 · `verify_idp_e2e.py` 39/39 (in-process) ·
`verify_idp_container_e2e.py` 45/45 (published port)

> **This is not production SSO and is not enterprise-ready.** It is a real OIDC
> provider issuing real RS256 tokens, run locally so the authentication boundary can
> be exercised by something this repository did not sign. Everything in §6 is what it
> does not establish.

---

## 1. Running it

```bash
docker compose -f compose.idp.yaml up -d      # a SEPARATE file, never the default stack
set -a; . ./.env; . ./.env.idp; set +a
bash scripts/bootstrap_nonprod_idp.sh         # idempotent: reconciles, does not duplicate
uv run python scripts/verify_idp.py --issuer "$MEDAUTH_OIDC_ISSUER" --audience medauth-api
uv run python scripts/verify_idp_e2e.py
```

Port 8090, because 8080–8082 are bound on the reference machine and 8010 was reclaimed
(ADR-019 and its amendment).

Secrets are split across two gitignored files. `.env` holds what the **application**
needs and is injected wholesale into the API container by `compose.yaml`. `.env.idp`
holds the Keycloak admin password and the fixture users' passwords, and is read only by
the scripts. The API verifies tokens; it does not mint them, and it has no business
holding the credentials of the directory that authenticates its own reviewers.

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

## 7. Network topology — one canonical issuer

```
  host / client ─────────────► :8090  Keycloak  (medauth-idp_default, 192.168.16.0/20)
        │                        ▲
        │  real RS256 token      │  discovery + JWKS
        ▼                        │
  :8015 ──► medauth-api-1 ───────┘
            (medauth_default, 172.31.0.0/16) ──► medauth-postgres-1
```

The two compose projects sit on **separate bridge networks** and cannot address each
other by name. That is deliberate — §3 — and it is also what broke the first attempt.

### Why `localhost` could never work

`http://localhost:8090/...` is not one address. On the host it means the host. Inside
the API container it means *that container's* loopback, where nothing listens —
measured, not assumed: `ConnectionRefusedError [Errno 111]`. A token whose `iss` says
`localhost` therefore names a different machine depending on who reads it, and the
container could not fetch the JWKS to verify it.

### The canonical issuer

**`http://172.17.0.1:8090/realms/medauth-nonprod`** — the docker bridge gateway.

| who | how it reaches it |
|---|---|
| host / client | `172.17.0.1` is a local interface (`docker0`), and Keycloak publishes on `0.0.0.0:8090` |
| API container | the same address is the container's **default route**; no DNS, no hosts file, no shared network needed |

`KC_HOSTNAME` pins Keycloak's frontend URL to it, so the discovery document, the
`jwks_uri` and the `iss` claim in every issued token are all **the same string**,
verified from both sides. Issuer validation is unchanged and unweakened.

### What was rejected, and why

| | why not |
|---|---|
| disable or relax issuer verification | the stop condition. It converts a networking problem into a security one |
| rewrite the received `iss` | a verifier that edits its input before checking it is not a verifier |
| accept a second issuer | two issuers means a token from either is accepted, and the audit's `identity_issuer` stops being a discriminator |
| a Docker-internal name (`keycloak:8080`) | the container resolves it and **the client cannot**, so the client could never obtain a token whose `iss` the API would accept |
| a dedicated hostname (`idp.medauth.local`) | the better answer, and it needs a line in the host's `/etc/hosts`, which requires privileges this environment does not grant non-interactively. `MEDAUTH_IDP_HOST` exists so this is a config change when those privileges are available |
| put Keycloak on the API's network | it would make the IdP part of the default stack's topology, eroding §3, and still leaves the client's view unresolved |

**Portability, stated plainly:** `172.17.0.1` is this Docker daemon's default bridge
gateway. It is stable here and it is not universal — another machine may use a
different subnet. Derive it with
`docker network inspect bridge -f '{{(index .IPAM.Config 0).Gateway}}'` and set
`MEDAUTH_IDP_HOST`.

## 8. Two defects the container path exposed

Neither was reachable from the in-process tests. Both had been latent for days.

**The image could not start.** `app/api/reviewer_ui.py` imports `Jinja2Templates` at
module scope and `app/api/main.py` imports that router, so jinja2 is a hard runtime
requirement — and it was declared nowhere. It worked locally only because `torch`, an
*optional* `retrieval` extra that the image excludes, pulled it in. The image is built
with `uv export --no-dev`, so the container got no jinja2 and uvicorn died at import:
`ImportError: jinja2 must be installed to use Jinja2Templates`. Declared now, with two
tests in `tests/unit/test_runtime_dependencies.py`.

**The running container was three days stale.** It was built on 2026-08-23 and served
code predating the entire reviewer, identity and HITL work — which is why every request
first returned `{"detail":"Not Found"}`. `docker compose up -d` reuses an existing
image; only `--build` rebuilds. The two defects hid each other: the stale image had no
reviewer UI, so it had no jinja2 problem either.

The lesson is the one this phase was for. A deployment nobody rebuilds is a deployment
nobody tests, and every guarantee proven in-process says nothing about it.

## 9. Key rotation — real evidence

Performed against the isolated non-production realm, not simulated:

1. a token on the current key verified through `:8015`;
2. a second RS256 provider added to the realm at higher priority — the realm's key set
   went from 2 keys to 3 and newly issued tokens carried a **different `kid`**;
3. the container held the **pre-rotation** JWKS cached, refetched on the unknown `kid`,
   and accepted the token — an `OVERRIDE` on the rotated key returned `201`;
4. the superseded signing key remains published, so tokens issued under it keep
   verifying until they expire;
5. a `kid` that was never published stayed a `401` on three consecutive attempts — the
   refetch does not become a retry loop, and a failed refetch does not become a 500.

## 6. What this does not establish

**Implementation.** Nothing under `app/` changed for Keycloak, and nothing would change
for another conformant provider — the one change was the defect fix, which is
provider-independent.

**Provider.** `start-dev`, in-memory H2, no HTTPS enforcement, no persistence across a
`down`. Disqualifying for production by design: this provider cannot be promoted by
changing an environment variable. No refresh-token rotation policy, no session
management, no MFA, no lockout policy has been configured or tested.

**Non-production.** Four fixture identities in a throwaway realm; no directory, no
provisioning, no deprovisioning, no rotation under load. The realm is in-memory and
does not survive a `docker compose down`. The issuer is an **IP literal** — correct and
stable for this machine (see §7), but a deployment with DNS should set
`MEDAUTH_IDP_HOST` to a real name; the whole arrangement is one variable.

**Production.** **No production SSO is deployed and none is claimed.** No production
IdP is selected (ADR-030 stands for deployment). No real key rotation has been
observed. No clinical validation, and an authentication boundary is not one.
