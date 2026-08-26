# The production-shape deployment contract

**What this is:** the minimum topology MEDAUTH's current architecture requires, and
what was actually verified in a local environment built to that shape.

**What this is not:** production. No production deployment was performed, no production
credentials exist, no domain or certificate authority is owned, and nothing here is
organisationally approved. The classification in §8 says which items are which, and
several are explicitly not this repository's to decide.

**Verified against:** `compose.prod-shape.yaml` — Keycloak 26 in `start` (profile
`prod`) on PostgreSQL with a named volume, HTTPS throughout with a local CA, stable
hostnames, a TLS-terminating proxy, and the MEDAUTH image built clean with `--no-cache`.
**45/45** end-to-end.

---

## 1. The chain, unchanged

```
client ──HTTPS──► idp.medauth.localhost:8443   Keycloak (prod profile, PostgreSQL volume)
   │                        ▲
   │ RS256 token            │ discovery + JWKS, TLS verified against the CA
   ▼                        │
api.medauth.localhost:8444 ─┘
   │  nginx: TLS termination only. Authorization header passes through untouched.
   ▼
MEDAUTH api container (HTTP on a private network, holds no certificate)
   → OidcAuthenticator → Principal → permission set → service authorization
   → HITL → append-only audit (principal_id + identity_issuer)
```

Nothing in this chain was redesigned. The only application change this phase required
is a reviewer-facing display fix (§7), unrelated to deployment.

**TLS termination is a deployment concern and stays one.** The proxy stands in for
whatever an environment actually uses — ingress controller, ALB, mesh sidecar. MEDAUTH
speaks HTTP on a private network and holds no certificate. A proxy that *validated*
tokens would become a second, weaker authenticator, so it forwards `Authorization`
untouched.

## 2. Canonical issuer

**One issuer per environment. Never two.**

| environment | issuer | resolves for the client | resolves for the API container |
|---|---|---|---|
| local dev (`compose.idp.yaml`) | `http://172.17.0.1:8090/realms/medauth-nonprod` | docker0 is a local interface | it is the container's default route |
| **production-shape** (`compose.prod-shape.yaml`) | `https://idp.medauth.localhost:8443/realms/medauth-nonprod` | `*.localhost` → 127.0.0.1 (RFC 6761) | `extra_hosts: host-gateway` |
| production | `https://<owned-idp-host>/realms/<realm>` | DNS | DNS |

The IP literal is **gone from the production-shaped contract**. It was correct for the
bridge-network topology and is not a deployment identity: it is one machine's docker0
address.

`KC_HOSTNAME` pins what Keycloak stamps into `iss`, so the discovery document, the
`jwks_uri` and every token's `iss` are the same string — verified from both sides.
Moving to a real DNS name changes `KC_HOSTNAME` and `MEDAUTH_OIDC_ISSUER` and nothing
else. **No second issuer is accepted during a migration**: two accepted issuers means a
token from either is honoured, and `identity_issuer` in the audit stops discriminating.

## 3. TLS

MEDAUTH **adds a trust anchor**; it never disables verification. `SSL_CERT_FILE` points
at the CA and the standard library does full chain construction, hostname matching and
expiry checking. There is no certificate exception, no pinning and no `verify=False`
anywhere in the application.

Demonstrated rather than asserted:

| | result |
|---|---|
| both endpoints verify against the local CA | CN and SANs correct |
| the same certificate with **no** CA in the trust store | refused — `unable to get local issuer certificate` |
| the same certificate under a **wrong hostname** | refused — `Hostname mismatch` |
| the API container fetching discovery over TLS | succeeds with `SSL_CERT_FILE=/etc/tls/ca.crt` |

A CA rather than a self-signed certificate is the point: a self-signed cert can only be
trusted by turning verification off or by pinning, and both are habits that survive
into production. **This is not production TLS** — the CA is local, throwaway, and its
key never leaves the machine.

## 4. Keycloak, production-shaped

| property | dev stack | production-shape | evidence |
|---|---|---|---|
| startup mode | `start-dev` | **`start`** | log: `Profile prod activated` |
| storage | in-memory | **PostgreSQL, named volume** | realm, users and signing `kid` identical across a restart |
| transport | HTTP | **HTTPS only** (`KC_HTTP_ENABLED=false`) | no plain-HTTP fallback exists to misconfigure into |
| `sslRequired` | `none` | **`all`** | read back from the realm |
| brute-force lockout | none | **on**, 5 failures, 60s→900s backoff | read back |
| password policy | none | **length 12, upper, lower, digit, not-username** | a `"short"` password is refused `400` |
| access-token lifetime | default | **900s** | read back |
| session idle / max | default | **1800s / 28800s** | read back |
| event + admin-event logging | off | **on** | read back |
| MFA | — | **available, deliberately NOT enforced** | §8 |
| key rotation | verified | verified | new provider → new `kid`, container refetched, old key stays published |

Persistence is what makes several of these testable at all: in-memory storage cannot
demonstrate key continuity, because every restart is a new realm.

## 5. Application configuration

Entirely environment-injected; no code change moves between environments.

`MEDAUTH_AUTH_MODE`, `MEDAUTH_OIDC_ISSUER`, `MEDAUTH_OIDC_AUDIENCE`,
`MEDAUTH_OIDC_DISCOVERY`, optional `MEDAUTH_OIDC_JWKS_URL`, `MEDAUTH_API_KEYS`,
`MEDAUTH_DATABASE_URL`, `SSL_CERT_FILE`.

Secrets live in two gitignored files. `.env` holds what the application needs and is
injected into the API container. `.env.idp` holds the Keycloak admin password, the
identity database password and the fixture users' passwords, and is read only by the
scripts — **the API verifies tokens, it does not mint them**, and it has no business
holding the credentials of the directory that authenticates its own reviewers.

### Startup is fail-closed, and that is a deployment obligation

`build_authenticator` performs discovery **once, at startup**. If the provider is
unreachable it returns `None` and reviews are refused until the process restarts. It
does not fall back to a laxer verifier — an authenticator that degraded when its key
source was unreachable would be least trustworthy exactly when something was wrong.

This was observed for real: the API came up before Keycloak was healthy, discovery
failed, and the container served `401`s indefinitely while `/ready` correctly reported
`reviewer_identity: no human authenticator is configured; reviews would be refused`.

**The behaviour is correct and the deployment must account for it.** Required:

1. an ordering dependency on provider availability (`depends_on … service_healthy`, an
   init container, or equivalent);
2. a **readiness probe wired to `/ready`**, so an orchestrator does not route to an
   instance that cannot authenticate a reviewer;
3. **restart on sustained unreadiness**, which is what recovers an instance that lost
   the race at boot.

`reviewer_identity` is `REQUIRED`, not advisory: a deployment that cannot authenticate a
reviewer cannot finalise a case, and every case ends at a human. `llm_firewall` is
advisory on purpose — a model-path outage must not take the reviewer console down.

## 6. Runtime reproducibility

Built with `--no-cache --pull`, from `pyproject.toml` + `uv.lock` only:

- **37 packages**; `jinja2`, `fastapi`, `pyjwt`, `sqlalchemy`, `asyncpg` all present;
- `torch`, `sentence-transformers`, `transformers` **absent** — so no optional extra can
  mask a missing runtime dependency, which is exactly how jinja2 went undeclared;
- `/ready` `200`, `/openapi.json` `200`, and the **reviewer UI renders** — `200`,
  5.8 KB, no unevaluated Jinja markup, no `<script>` and no external `<link>`;
- no host Python is involved at any point.

## 7. What the production-shaped run found

**A reviewer-facing defect, on the normal path.** `_explain()` fell back to
`abstention_reason or resolution_reason`, and `DESIGNATED_POLICY_APPLIES` — what
resolution reports when it *found* the governing policy, set on essentially every
healthy run — has no entry in the routing table. So a perfectly ordinary case told its
reviewer *"Routed for review: DESIGNATED_POLICY_APPLIES. No explanation is recorded for
this reason yet."*

Two harms: it presents an ordinary case as an unexplained anomaly, and it suppressed
the sentence that does apply — that a recommendation is a draft requiring a human
disposition. Telling a reviewer the system cannot explain why they are looking at
something primes them to defer to it, which is R-04.

Only an abstention reason now reaches that branch. Resolution *problems* are unaffected:
they arrive with abstention reasons the table already has sentences for. Three tests;
the regression one fails against the unfixed code. The pre-existing test asserted only
that the string was non-empty and longer than 40 characters — which the wrong sentence
satisfied.

Found by rendering the page, not by reading the JSON.

## 8. Readiness classification

### APPLICATION-READY — MEDAUTH code supports it
Canonical issuer by configuration · TLS via trust anchor, never bypass · issuer,
audience, signature, expiry, nbf, subject and algorithm validation · uniform
authentication refusal · fail-closed on provider outage · three-permission model
unchanged · HITL semantics unchanged · append-only audit with `principal_id` +
`identity_issuer` · declared runtime dependencies · readiness reflecting authentication.

### DEPLOYMENT-READY — verified in the production-shaped environment
HTTPS end to end · TLS-terminating proxy with the application holding no certificate ·
stable hostnames resolving identically on both sides · persistent identity storage ·
clean no-cache image · ordering dependency and readiness-gated startup · the full
authorization matrix, HITL flow, audit and 19 negative cases through the published
HTTPS port.

### PROVIDER-READY — Keycloak supports it technically
Production startup mode · persistent database · HTTPS · signing-key rotation with old
keys retained · brute-force lockout · password policy · session and token lifetimes ·
event and admin-event logging · **MFA capability**.

### ORGANIZATION-DECISION REQUIRED — not this repository's to make
Whether MFA is **required**, and for whom · production domain and DNS · a real
certificate authority and renewal process · who **owns and operates** production
Keycloak · production secrets management (this is `.env` files on one machine) · account
lifecycle: joiners, movers, leavers, and who approves a `medauth-senior-reviewer` ·
retention for identity and admin event logs · disaster recovery, backup and restore for
the identity database · enterprise SSO approval · whether `172.17.0.1`-style local
topologies are permitted anywhere.

**None of these is fabricated as decided.** Configuring MFA on a fixture realm would
have let "MFA is configured" be written down when what is true is "MFA is available".

## 9. `sub` integrity, restated for this topology

**MEDAUTH verifies:** the token's signature against the issuer's published keys, that
`iss` is exactly the configured issuer, that `aud` contains this application, expiry,
not-before, and that a subject is present. It records `principal_id` **and**
`identity_issuer` together, so a subject is never a bare string and re-pointing at a
different provider cannot silently merge two people's histories.

**The provider guarantees technically:** a stable UUID per user, unchanged across
logins, credential resets and now a full restart with persistent storage; a
deleted-then-recreated username gets a **new** subject.

**The operator remains responsible for:** non-reassignment — Keycloak's admin API
accepts an explicit `id` at creation, so a retired subject *can* be minted onto a new
user; one human per account; and directory integrity generally.

**MEDAUTH cannot detect malicious reassignment of a `sub`.** The token would be valid
and the subject would resolve to the wrong person's history. Nothing in this design
changes that, and no control here should be read as mitigating it.

## 10. What remains untrue of production

No production deployment. No owned domain, no real CA, no HA, no backups, no restore
drill, no load or soak testing, no MFA policy, no account lifecycle, no operator. Four
fixture identities in a realm that exists on one machine. Plain HTTP inside the
container network between proxy and application, which is correct only because that
network is private — an environment where it is not requires mTLS or equivalent, and
that has not been designed here.

**No production SSO is claimed. No enterprise approval is claimed. No clinical
validation is claimed, and an authentication boundary is not one.**
