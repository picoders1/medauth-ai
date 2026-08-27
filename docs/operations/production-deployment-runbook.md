# Production deployment runbook

**Platform-neutral, because no platform has been chosen.** Every step below is written
against a capability ("the orchestrator must restart on sustained unreadiness") rather
than a product. When a platform is supplied, this becomes its checklist without being
rewritten.

**No step in this document has been executed in production.** The smoke suite has been
executed against the local production-shaped stack only.

**Companions:** `docs/deployment/go-live-contract.md` (what production needs and who
owns it) · `docs/deployment/production-shape-contract.md` (what was actually verified).

---

## 1. The two decisions that gate everything

| | status |
|---|---|
| **Production deployment platform** | **EXTERNAL DECISION REQUIRED.** Swept for Terraform, Pulumi, Ansible, CloudFormation, Helm charts, Kustomize, `values.yaml`, systemd units, cloud-init, `fly.toml`, `render.yaml`, `Procfile`, ECS task definitions and `appspec.yml`. **None exists.** Three Docker Compose files exist, all local |
| **Production identity provider** | **EXTERNAL DECISION REQUIRED.** No production issuer, hostname, realm or owner is recorded anywhere. Keycloak 26 is the *non-production* choice (ADR-030 amendment) and must not be assumed to be the production one |

Nothing below chooses either. The runbook is written so that supplying them is
configuration.

## 2. Secret contract

| secret | consumer | injection mechanism | rotation owner | procedure |
|---|---|---|---|---|
| `MEDAUTH_API_KEYS` | MEDAUTH API | env **or** `$MEDAUTH_SECRETS_DIR/MEDAUTH_API_KEYS` | **EXTERNAL** | issue new key, add alongside old, migrate integrators, remove old. The format is a list, so rotation needs no downtime |
| `MEDAUTH_DATABASE_URL` | MEDAUTH API | same | **EXTERNAL** | change the role's password, update the secret, restart. Brief unavailability |
| `MEDAUTH_LLM_API_KEY` | MEDAUTH API | same | **EXTERNAL** | revoke at the firewall and reissue. MEDAUTH holds no model-provider credential and must never be given one |
| PostgreSQL superuser / role passwords | PostgreSQL | platform-provided | **EXTERNAL** | provider-specific |
| Keycloak admin credentials | Keycloak | provider-provided | **EXTERNAL** | **never reaches MEDAUTH** |
| Keycloak database password | Keycloak | provider-provided | **EXTERNAL** | **never reaches MEDAUTH** |
| TLS private keys | reverse proxy / ingress | platform-provided | **EXTERNAL** | **never reaches MEDAUTH** — TLS terminates in front of it |

**Injection mechanism is `EXTERNAL DECISION REQUIRED` for every row.** The application
supports two interfaces — environment variables and files in `MEDAUTH_SECRETS_DIR` —
and both are satisfied by Docker secrets, a Kubernetes `Secret` volume, a Vault agent
sidecar or systemd credentials. Which one is used is not decided here.

**Prefer the file interface.** An environment variable is readable via `docker inspect`,
via `/proc/<pid>/environ` to anything sharing a namespace, and in a crash dump.

**`.env` files are not approved production secret management** and are not proposed as
such. They are what the local stacks use.

Established today: no credential is in source control (swept every phase), none is in
the image (built from `pyproject.toml` + `uv.lock` only), `SecretStr` keeps values out
of `repr`, and redaction is enforced at the structlog sink rather than per call site.

## 3. Pre-deployment

Every item is a gate. A failure stops the deployment.

| # | check | how |
|---|---|---|
| 1 | image identity | deploy **by digest**, never by a moving tag. `docker image inspect <ref> --format '{{.Id}}'` matches the release candidate |
| 2 | release metadata | `uv run python scripts/release_candidate.py` — commit, `uv.lock` hash, `pyproject` hash, migration head all match the candidate; `tree_clean: true` |
| 3 | configuration | every row of `go-live-contract.md` §2 supplied; `MEDAUTH_ENVIRONMENT=production`, `MEDAUTH_AUTH_MODE=oidc`, `MEDAUTH_OIDC_SECRET` **empty** |
| 4 | secrets | present via the chosen mechanism; **absent from the image** — `docker history --no-trunc` shows no value |
| 5 | DNS | the API hostname and the issuer hostname resolve, from the client **and from inside the API container** |
| 6 | TLS | certificate valid, chain complete, hostname matches, expiry not imminent. **Verification is never disabled** |
| 7 | IdP | `uv run python scripts/verify_idp.py --issuer <issuer> --audience <audience>` passes every required check; then again `--token` with a real token |
| 8 | database | reachable; the application role has `INSERT`/`SELECT` on audit tables and **not** `UPDATE`/`DELETE` |
| 9 | migrations | `alembic upgrade head` run **as an explicit step**, before rollout. `alembic check` clean. Never by the application |
| 10 | backup | a backup taken **and verified restorable** before any migration (§6) |

## 4. Deployment

1. Ensure the IdP is reachable **before** the API starts. Discovery happens once, at
   startup; an instance that loses the race stays un-ready until restarted (§5).
2. Deploy the immutable image by digest.
3. Wait for `/ready` → `200`. A `503` naming `reviewer_identity` means the API could not
   reach the IdP: fix reachability and restart. **Do not** work around it by changing
   authentication configuration.
4. Confirm the API performed discovery and JWKS retrieval itself — a real token
   authenticating end to end is the proof.
5. Run the smoke suite (§7), safe mode first.

## 5. Readiness and failure

**Application contract — fixed, do not weaken:**

| condition | behaviour |
|---|---|
| IdP reachable at startup | authenticator built · `/ready` `200` |
| IdP unreachable at startup | authenticator `None` · `/ready` `503` (`reviewer_identity`) · **reviews refused** · no degraded verifier |
| IdP outage after startup | cached JWKS keeps serving; anything needing a refetch is `401`, never a 500 |
| database unreachable | `/ready` `503` |
| invalid auth configuration | **refuses to start** in production: `auth_mode=development`, a symmetric `oidc_secret`, or a missing issuer/audience |
| model path / firewall down | `/ready` stays `200` — advisory, so a model outage does not take the reviewer console down |

**Infrastructure responsibility, not optional:** readiness probe on `/ready`, liveness
on `/health`, **restart on sustained unreadiness**, and startup ordering behind the IdP.
The application fails closed and says so; recovering is the orchestrator's job.

## 6. Backup, restore and DR

| | |
|---|---|
| PostgreSQL (application + audit) backup | **required — does not exist** |
| Keycloak database backup (realm, users, **signing keys**) | **required — does not exist** |
| backup verification | **required — does not exist.** An unverified backup is a belief |
| documented restore procedure | **required — does not exist** |
| restore **drill** | **required — never performed on any system** |
| RPO | **EXTERNAL DECISION REQUIRED** |
| RTO | **EXTERNAL DECISION REQUIRED** |

No RPO or RTO is proposed. Both are business decisions about tolerable loss, and
inventing numbers would make an unmade decision look made.

**Losing the Keycloak database loses the signing keys**, and every token issued under
them stops verifying. It also loses group membership — which is the authorization model
— so an identity backup is not a lesser concern than the application's.

**Audit preservation:** append-only is enforced by trigger, so no ordinary operation
deletes history and no rollback path does either. A restore, by definition, returns the
trail to an earlier state — that is a **loss of audit history**, and it is why the RPO
decision is an audit decision as much as a data decision.

## 7. Smoke tests

`scripts/production_smoke.py`, platform-neutral, run with operator-supplied tokens.

**Two modes, and the distinction is the point.** Six checks are reads and four are
denials — a refused request writes nothing — so ten of the twelve are safe against
production. Two are not: a review action and an override **finalise a real case and
write to an append-only trail that cannot be undone**. They run only when
`--smoke-case-id` names a case the operator has designated, and the suite prints which
mode it ran in.

A smoke test that quietly finalises a case to prove it can finalise cases has corrupted
the record it was checking.

| # | check | mode |
|---|---|---|
| 1 | unauthenticated request denied | safe |
| 2 | valid authenticated identity accepted | safe |
| 3 | readonly can read | needs a designated case |
| 4 | readonly cannot review | safe (denial) |
| 5 | a review action is recorded and finalises | **mutating** |
| 6 | reviewer cannot override | safe (denial) |
| 7 | senior reviewer can override | **mutating** |
| 8 | unknown identity denied | safe |
| 9 | audit records the authenticated subject | **mutating** |
| 10 | history append-only: the AI draft survives the override | **mutating** |
| 11 | evidence provenance present on the read model | needs a designated case |
| 12 | readiness healthy | safe |

The script **never creates a case** and **never mints a token** — one that could mint
tokens would hold credentials letting it impersonate a reviewer. It refuses to start
without operator-supplied credentials and prints none of them.

Verified against the local production-shaped stack: **safe mode 7/7 writing zero rows**
(review-event count unchanged, 16 → 16), **mutating mode 15/15**.

**This is a deployment check, not clinical validation**, and must never be cited as
evidence about recommendations.

## 8. Security acceptance criteria

Deployment is not accepted until every row passes. Status is against the local
production-shaped environment; production evidence does not exist.

| criterion | verified where |
|---|---|
| TLS valid, chain complete, hostname enforced | production-shape: verified; untrusted CA and wrong hostname both refused |
| verification never disabled in application code | structural — no `verify=False`, no pinning, no certificate exception |
| one canonical issuer, enforced | verified |
| audience enforced | verified |
| JWKS reachable, asymmetric signing (RS256) | verified |
| key rotation supported; superseded keys retained | verified against real Keycloak |
| authentication failures fail closed, uniformly | 19 negative cases, one identical `401` body |
| provider outage fails closed, never 500 | verified with the IdP stopped |
| no secret in image or source | swept; image built from lock files only |
| unauthorized actions denied at the **service** layer | verified through the published port |
| audit records the authenticated subject with its issuer | verified |
| 404 anti-enumeration intact | verified |
| **production certificates, DNS, rotation under load** | **PENDING — production only** |

## 9. Rollback

| element | state |
|---|---|
| image | immutable, reproducible; reference by digest |
| application | replace the image; the application holds no state |
| configuration | injected, so it rolls back with the deployment |
| **database** | **forward-only.** Downgrading past `0003` executes `DELETE FROM policy_versions WHERE effective_date IS NULL`. Roll back by **restore**, not downgrade |
| IdP configuration | **gap** — realm configuration is not version-controlled. The bootstrap script reconciles; that is not a rollback |
| audit/history | preserved: append-only, and no rollback path deletes rows |

**No zero-downtime guarantee is offered.** None has been designed or tested.

## 10. Incident hooks

None of these is implemented; all are required operational procedures.

| incident | response |
|---|---|
| signing-key compromise | rotate at the IdP. MEDAUTH refetches on an unknown `kid` — verified. Tokens under the retired key stay valid until expiry unless the key is **removed**, not merely superseded |
| IdP outage | MEDAUTH fails closed; restore the provider. Cached JWKS keeps existing tokens working |
| revoked/disabled identity | **MEDAUTH does not check revocation — measured.** A disabled account cannot obtain a new token, and its existing token still authenticates. Exposure is bounded only by `accessTokenLifespan`, which is therefore a **decision**, not a default |
| leaked `MEDAUTH_API_KEYS` | rotate; the audit records the caller |
| database compromise | audit rows are append-only by trigger, but a superuser can drop the trigger. Off-host shipping of audit events is **not implemented** |
| audit integrity incident | no external attestation exists; integrity rests on the trigger and on database access control |
| unauthorized reviewer | remove group membership at the IdP; existing tokens remain valid until expiry |
| suspected subject reassignment | **MEDAUTH cannot detect this.** The token is valid and resolves to the wrong person's history. Detection is entirely operator-side |

## 11. Observability

**Operational telemetry** production should collect: authentication failures by reason
(server-side only — the client still sees a uniform `401`), authorization denials, JWKS
refresh failures, readiness-check failures, IdP availability, API latency, database
health, audit-event insert counts.

**Clinical/reviewer metrics are a separate category and are not reportable.** Every
review action recorded so far was generated by a verification script, and **test traffic
must never be counted as reviewer activity**. `docs/evaluation/human-review-metrics.md`
defines the metrics; none can be produced until real review activity exists.

Present: structured logging with sink-level redaction, Prometheus `/metrics`, optional
OpenTelemetry. **Alerting does not exist**, and thresholds are an organisational
decision.

## 12. Governance questions — not answered here

Membership in the three groups is the authorization model, and no owner is recorded for
any of it:

- who may create or approve `medauth-reviewer` membership?
- who may create or approve **`medauth-senior-reviewer`** membership — the authority to
  overturn a recommendation?
- joiner / mover / leaver process?
- periodic access review, by whom, how often?
- emergency access — does it exist, who grants it, how is it recorded?
- account disablement on termination, and how quickly?
- who sets `accessTokenLifespan`, given it is the whole revocation window?

**All `EXTERNAL DECISION REQUIRED`.** Nothing in MEDAUTH should grow to encode them:
group membership belongs to the provider, and the mapping from group to permission is
one table a deployment configures.
