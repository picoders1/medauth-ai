# The production go-live contract

**What this is:** every value MEDAUTH needs in production, classified by who supplies
it, plus the operational contracts the application implies. It is the handover
document between this repository and whoever runs it.

**What this is not:** a deployment. No production exists, no credentials exist, and
**nothing here has been organisationally approved.** Where a decision has an owner who
has not made it, the row says so instead of guessing.

**Companion:** `docs/deployment/production-shape-contract.md` records what was actually
verified in a local production-shaped environment. This one records what production
still needs.

---

## 1. Application architecture — frozen

These are settled and should not be redesigned during production preparation:

| chain | state |
|---|---|
| `IdP → discovery → JWKS → token validation → Principal` | frozen |
| `Principal → permission set → service-layer authorization` | frozen |
| `HUMAN_REVIEW → accept \| override \| request-info` | frozen |
| `validated identity → append-only audit` | frozen |
| `original run's evidence → historical review read model` | frozen |
| `routing explanation → AI draft → human disposition` | frozen |

**No unresolved application architecture blocker exists.** The three defects found in
the preceding phases (unknown-`kid` 500, undeclared jinja2, the `_explain` R-04 defect)
are fixed with regression tests that fail against the unfixed code.

## 2. Configuration matrix

**A** = application configuration · **S** = secret · **I** = infrastructure-provided ·
**O** = organisational decision.

| variable | | production value comes from |
|---|---|---|
| `MEDAUTH_ENVIRONMENT` | A | set to `production`; enables the refusals in `Settings.validate` |
| `MEDAUTH_AUTH_MODE` | A | `oidc`. Production **refuses** `development` |
| `MEDAUTH_OIDC_ISSUER` | A | **I** supplies the hostname; one canonical issuer per environment |
| `MEDAUTH_OIDC_AUDIENCE` | A | the client/audience the IdP is configured to stamp |
| `MEDAUTH_OIDC_DISCOVERY` | A | `true`; `MEDAUTH_OIDC_JWKS_URL` only if a provider cannot serve discovery |
| `MEDAUTH_OIDC_SECRET` | — | **must stay empty.** Production refuses a symmetric signing secret |
| `MEDAUTH_API_KEYS` | **S** | integrator caller keys |
| `MEDAUTH_DATABASE_URL` | **S** | contains credentials; treat the whole value as secret |
| `MEDAUTH_LLM_API_KEY` | **S** | revocable caller key for the firewall, never a provider key |
| `MEDAUTH_LLM_BASE_URL` | A | **I** supplies the firewall's address |
| `MEDAUTH_TRUSTED_PROXIES` | A | **I** supplies the proxy CIDR; wrong values make client IPs forgeable |
| `MEDAUTH_CLINICAL_TEXT_LOGGING` | A | `off`. Anything else is a decision with a **regulatory** dimension — **O** |
| `MEDAUTH_SECRETS_DIR` | A | `/run/secrets` if secrets are mounted; unset if injected by environment |
| `MEDAUTH_API_PORT` | A | in-container bind; the published port is **I** |
| `MEDAUTH_RETENTION_DAYS` / `_ENABLED` | — | **O.** Audit retention is a policy decision, not a default |
| TLS certificate + key | **I** | terminated in front of the application, which holds neither |
| DNS name for the API and the IdP | **I** | |
| Container platform, scaling, restart policy | **I** | |
| Who may hold `medauth-senior-reviewer` | **O** | §6 |
| Whether MFA is required | **O** | §5 |

Nothing in `app/` needs to change to move between environments. Every row above is
injected.

## 3. Secret management

**Interface, not product.** The repository does not specify a secrets manager and this
document does not choose one.

| secret | injection mechanism required |
|---|---|
| `MEDAUTH_API_KEYS` | environment **or** file at `$MEDAUTH_SECRETS_DIR/MEDAUTH_API_KEYS` |
| `MEDAUTH_DATABASE_URL` | same |
| `MEDAUTH_LLM_API_KEY` | same |
| IdP admin credentials | never reaches MEDAUTH — provider-side only |
| TLS private keys | never reaches MEDAUTH — terminated upstream |

**The mechanism itself is an external dependency.** Docker secrets, a Kubernetes
`Secret` volume, a Vault agent sidecar and systemd credentials all satisfy the file
interface; which one is used is an infrastructure decision that has not been made.

**Implemented this phase.** ADR-019 specified `/run/secrets/MEDAUTH_*` and nothing read
it — the documented production secret path did not work. `Settings` now resolves
`MEDAUTH_SECRETS_DIR` per instance, verified in the clean image with the secret present
only as a mounted file and absent from the environment. File-mounted secrets are
preferred over environment variables because an environment variable is visible in
`docker inspect`, in `/proc/<pid>/environ` to anything sharing a namespace, and in a
crash dump.

**Precedence is environment-over-file**, which is a footgun during a migration: set one,
not both. A test asserts the direction so a library change fails a test rather than
silently reversing which secret production uses.

**Current state is not production-acceptable and is not claimed to be**: secrets live in
gitignored `.env` and `.env.idp` files on one machine. What is established: nothing is
in source control (swept), nothing is in the image (built from `pyproject.toml` +
`uv.lock` only), `SecretStr` keeps values out of `repr`, and redaction is enforced at
the structlog sink rather than per call site.

## 4. Identity — production requirements

| requirement | application | provider capability | provider configured | organisationally approved |
|---|---|---|---|---|
| stable issuer over HTTPS | requires | yes | non-prod only | **no** |
| persistent storage | — | yes | non-prod verified | **no** |
| non-development startup mode | — | yes | non-prod verified (`Profile prod`) | **no** |
| signing-key rotation, old keys retained | consumes | yes | non-prod verified | **no** |
| subject stability | requires | yes (UUID, survives restart) | verified | **no** |
| non-reassignment of a subject | **cannot verify** | operator-controlled | — | **no** |
| controlled administrative access | — | yes | bootstrap admin only | **no** |
| account lockout | — | yes | non-prod configured | **no** |
| password policy | — | yes | non-prod configured | **no** |
| session/token lifetimes | — | yes | non-prod configured | **no** |
| audit/admin event logging | — | yes | non-prod configured | **no** |
| **MFA** | indifferent | **yes** | **deliberately not configured** | **no — this is the decision** |
| account lifecycle (JML) | — | yes | **not configured** | **no** |

"Organisationally approved" is **no** on every row because no organisation has been
identified. That column is not a criticism of the configuration; it records that
approval is a different thing from capability, and this repository has no standing to
supply it.

## 5. Deployment target

> **Production deployment target not yet supplied.**

What exists: three Docker Compose files — `compose.yaml` (local), `compose.idp.yaml`
(local IdP), `compose.prod-shape.yaml` (local production-shaped). No production
platform is specified.

**Corrected this phase.** ADR-019 described a standalone `compose.prod.yaml` and a set
of Kubernetes manifests as existing and `kubeconform`-validated in CI. **None of it
exists.** `kubeconform` appears in `ci.yaml` only inside a comment listing future work.
The *permitted* claim — "manifests are authored and statically validated in CI" — was
itself false, which made it the more dangerous of the two Kubernetes claims: it read as
the careful, honest version. Corrected in ADR-019, `docs/evidence-and-claims.md` and
CLAUDE.md.

Authoring manifests now would mean choosing a target nobody has chosen. The
provider-neutral requirements a target must satisfy:

1. TLS terminated in front of the application; the application holds no certificate.
2. One canonical issuer resolvable identically by clients and by the API container.
3. Readiness probe on `/ready`; liveness on `/health`; **restart on sustained
   unreadiness** (§7).
4. Ordering: the IdP must be reachable before the API starts, or the API restarts (§7).
5. Secret injection by environment or by mounted files (§3).
6. Migrations run as an explicit step before rollout, never by the application (§8).
7. The database reachable on a private network; it is never published.

## 6. Authorization governance

The mapping is unchanged and is not a deployment concern:

```
medauth-readonly        → {READ_CASE}
medauth-reviewer        → {READ_CASE, REVIEW_CASE, FINALIZE_CASE}
medauth-senior-reviewer → {READ_CASE, REVIEW_CASE, FINALIZE_CASE, OVERRIDE_RECOMMENDATION}
unknown                 → {}
```

What production needs and **this repository cannot supply**:

| question | owner |
|---|---|
| who may be granted `medauth-reviewer` | **undecided — no owner identified** |
| who may be granted `medauth-senior-reviewer` — the authority to overturn a recommendation | **undecided** |
| joiner / mover / leaver handling | **undecided** |
| periodic access review, and by whom | **undecided** |
| emergency access, and whether it exists at all | **undecided** |
| account disablement on termination | **undecided** |

These are governance decisions, not application features. Nothing in MEDAUTH should
grow to encode them: group membership is the provider's job, and the mapping from group
to permission is one table that a deployment configures.

**Blocker, stated plainly:** a production deployment where nobody owns senior-reviewer
membership means the authority to overturn an AI recommendation is granted by whoever
happens to administer the directory. That is an organisational decision that must be
made before go-live, and it is not made here.

## 7. Startup, readiness and failure

**Application contract:**

| condition | behaviour |
|---|---|
| startup, IdP reachable | `OidcAuthenticator` built; `/ready` `200` |
| startup, IdP unreachable | authenticator is `None`; `/ready` `503` with `reviewer_identity` failing; **reviews refused**. Does *not* degrade to a laxer verifier |
| database unreachable | `/ready` `503`, `database` check failing |
| invalid authentication configuration | `Settings.validate` **refuses to start** in production: `auth_mode=development`, a symmetric `oidc_secret`, or an issuer/audience missing |
| IdP outage after startup | cached JWKS keeps serving; any token needing a refetch is `401`, never a 500 |
| firewall/model path down | `/ready` still `200` — advisory, so a model outage does not take the reviewer console down |

`reviewer_identity` is **REQUIRED**: a deployment that cannot authenticate a reviewer
cannot finalise a case, and every case ends at a human.

**Infrastructure responsibility, and it is not optional:** discovery happens **once, at
startup**. An instance that lost the race with the IdP stays un-ready until restarted.
The deployment must therefore probe `/ready` and restart on sustained unreadiness. This
was observed for real in the production-shaped stack, and it is fixed by ordering, not
by making the application retry — an authenticator that recovered silently would be
harder to reason about than one that fails closed and says so.

## 8. Database

**Established:** six linear migrations, single head `0006_reviewer_identity`, `alembic
check` clean, **zero destructive operations in any `upgrade()`**, and nothing runs
`alembic upgrade` automatically — not the application, not the image, not compose. The
audit trail is append-only by **trigger**, not by grant, because PostgreSQL does not
restrict a table's owner. Pool: `pool_pre_ping`, size 10, overflow 5.

**Rollback hazard, recorded rather than smoothed over:** downgrading past `0003`
executes `DELETE FROM policy_versions WHERE effective_date IS NULL`. It is deliberate —
the `0002` schema cannot represent an undated version, and inventing a sentinel date is
exactly what that migration exists to remove — but it means **a downgrade past 0003
destroys data**. Roll back by restoring a backup, not by downgrading.

**External dependency:** backup schedule, retention, restore procedure and a tested
restore drill. None exists. No restore has been performed on any system.

## 9. Observability

Present: structured logging via structlog with redaction **at the sink**; Prometheus
`/metrics`; optional OpenTelemetry.

Production should collect — **operational telemetry**: authentication failures by
reason (server-side only; the client still sees a uniform 401), authorization denials,
JWKS refresh failures, readiness-check failures, IdP availability, API latency,
database health, audit-event insert counts.

**Clinical/reviewer metrics are a different category and are not reportable.**
`docs/evaluation/human-review-metrics.md` defines them; none can be produced until real
review activity exists, and **test traffic must never be counted as reviewer activity**.
Every review action recorded so far was generated by a verification script.

No alerting exists. Thresholds are an organisational decision.

## 10. Security response — required runbooks

The application implements no incident-management system and should not. Required
operational hooks, none of which exist yet:

| incident | required response |
|---|---|
| signing-key compromise | rotate at the IdP; MEDAUTH refetches on unknown `kid` — verified. Tokens signed by the retired key remain valid until expiry unless the key is **removed**, not merely superseded |
| IdP outage | MEDAUTH fails closed; restore the provider. Cached JWKS keeps existing tokens working |
| revoked/disabled identity | **MEDAUTH does not check revocation — measured, not inferred.** With `nonprod-senior` disabled in the realm, a *new* login was refused by the provider (`400`) while the *existing* token still authenticated through the published API. The provider advertises an `introspection_endpoint`; MEDAUTH does not call it. The exposure is bounded only by `accessTokenLifespan` (900s in the non-prod realm), and shortening that lifetime is the only control the application respects |
| leaked `MEDAUTH_API_KEYS` | rotate and redeploy; the audit records the caller |
| database compromise | audit rows are append-only by trigger, but a superuser can drop the trigger. Off-host shipping of audit events is **not implemented** |
| audit integrity incident | no external attestation exists; integrity rests on the trigger and on database access control |
| unauthorized reviewer | remove group membership at the IdP; existing tokens remain valid until expiry, as above |
| suspected subject reassignment | **MEDAUTH cannot detect this.** The token is valid and resolves to the wrong person's history. Detection is entirely operator-side |

The revocation gap and the reassignment gap are the two most important sentences in
this document. Neither is a defect to be fixed in the application — both are properties
of bearer tokens and of a directory MEDAUTH does not control — and neither should be
described as mitigated.

**On the revocation gap specifically:** introspecting every request would close it, at
the cost of making the IdP a synchronous dependency of every call and giving it a new
way to take the reviewer console down. That is a real trade with an owner, and the
owner is not this repository. What the deployment can do without any code change is
choose `accessTokenLifespan`: it is the entire exposure window, and it is an
**organisational decision** that should be made deliberately rather than left at a
provider default. It is listed as one in §12.

## 11. Rollback

| element | state |
|---|---|
| immutable image | **available** — build is reproducible from `pyproject.toml` + `uv.lock`; reference by digest, never by a moving tag |
| application rollback | replace the image; the application holds no state |
| configuration rollback | all configuration is injected, so it rolls back with the deployment |
| database | **forward-only.** See §8: downgrading past `0003` deletes rows. A rollback that crosses a migration needs a restore, not a downgrade |
| IdP configuration rollback | realm configuration is not version-controlled — **gap.** The bootstrap script is idempotent and reconciles, which is not the same as a rollback |
| audit/history preservation | preserved by construction: append-only, and no rollback path deletes rows |

**No zero-downtime guarantee is offered.** None has been designed or tested.

## 12. What must be true before go-live, and is not

**Code:** nothing outstanding.

**Infrastructure:** deployment platform · production DNS · certificates and renewal ·
secret-injection mechanism · backup and a **tested** restore · HA and load balancing ·
alerting.

**Provider:** a production Keycloak (or approved enterprise IdP) — owned, operated,
persistent, HTTPS, with administrative access controlled.

**Organisation:** MFA policy · identity lifecycle · **who may hold senior-reviewer** ·
**access-token lifetime**, which is the whole revocation exposure window (§10) · audit
and identity-log retention · DR policy · enterprise SSO approval · who owns production
Keycloak · whether clinical-text logging may ever be enabled.

**Production-only evidence:** real certificates, real DNS, rotation under traffic, load
and soak testing, a restore drill, and any statement about behaviour at production
scale.

**No production SSO is claimed. No enterprise approval is claimed. No clinical
validation is claimed.**
