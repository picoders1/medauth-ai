# The five-minute demonstration

Everything below runs locally, needs no cloud account and **makes no model calls**. It
does not touch the blocked evaluation gate, `gold_v1` or `gold_v2`.

Executed end to end from a torn-down state before this document was written; the
numbers quoted are what it printed.

---

## Prerequisites

Docker with Compose, and `uv`. Roughly 3 GB of disk for images.

```bash
uv sync --all-groups --all-extras
cp .env.example .env          # then fill in the generated values (see §6)
```

## 1. Start the non-production identity provider

```bash
docker compose -f compose.idp.yaml up -d
set -a; . ./.env; . ./.env.idp; set +a
bash scripts/bootstrap_nonprod_idp.sh
```

A **separate compose file, deliberately**: `docker compose up` must never start an
identity provider by accident. The bootstrap creates a realm, three groups matching the
permission model, and four fixture identities — a read-only user, a reviewer, a senior
reviewer, and one belonging to no group at all. The fourth is the one most worth having:
"authenticated but authorised for nothing" is the case an all-users-are-reviewers
fixture never covers.

## 2. Check the provider before trusting it

```bash
uv run python scripts/verify_idp.py --issuer "$MEDAUTH_OIDC_ISSUER" --audience medauth-api
```

**Seven checks without a token** — discovery reachable, the advertised issuer matches the
configured one, `jwks_uri` published and on the issuer's host, keys retrievable, an
algorithm MEDAUTH accepts, every key carrying a `kid` — and it says plainly that issuance
was *not* verified rather than implying a clean bill of health. Add `--token "$TOKEN"` and
it becomes twelve, adding signature, issuer, audience, subject and the role mapping.

## 3. Start MEDAUTH

```bash
docker compose up -d --build
uv run alembic upgrade head
curl -s localhost:8015/ready
```

`/ready` returns `200` only when `reviewer_identity` passes. If the provider is
unreachable the API starts, refuses reviews and **says so** — it does not fall back to a
weaker verifier.

## 4. The whole path, with real tokens

```bash
uv run python scripts/verify_idp_container_e2e.py      # 45/45
```

This is the demonstration. In order it shows:

**Authorization** — the matrix, through the published port, with tokens the script did
not mint:

| | read | accept | request-info | override |
|---|---|---|---|---|
| readonly | 200 | 403 | 403 | 403 |
| reviewer | 200 | 201 | 201 | **403** |
| senior reviewer | 200 | 201 | 201 | 201 |
| no group | 403 | 403 | 403 | 403 |

**The reviewer's read model** — and the property worth pausing on: the *routing
explanation* is rendered **above** the recommendation, which is labelled
*"AI-generated recommendation — not a decision"* and held in a different field from the
human disposition. Showing the proposed answer before the question is how an interface
manufactures agreement (R-04).

**The three actions** — accept finalises; request-info returns the case to `NEEDS_INFO`;
a reviewer is refused an override and a senior reviewer is not. The override **preserves
the draft it disagreed with** rather than overwriting it.

**Evidence provenance** — the evidence shown after the action is byte-identical to the
evidence shown before, because it is read from the original run's audit trail. Re-running
retrieval would show today's corpus for yesterday's decision, and the citations would
still verify, which is what makes that failure invisible.

**Audit** — the provider's `sub` recorded with its issuer, and `UPDATE`/`DELETE` on the
history refused by a database trigger.

**Nineteen negative cases** — no token, malformed, bad signature, wrong issuer, wrong
audience, expired, future `nbf`, no subject, `alg=none`, unknown `kid`, a token claiming
its own permissions — every one returning **the same `401` body**, so a caller cannot
learn which check failed.

## 5. Optional: the production-shaped stack

```bash
docker compose -f compose.prod-shape.yaml down -v     # see the note below
bash scripts/make_local_tls.sh
docker compose -f compose.prod-shape.yaml up -d --build

export MEDAUTH_OIDC_ISSUER="https://idp.medauth.localhost:8443/realms/medauth-nonprod"
export MEDAUTH_IDP_URL="https://idp.medauth.localhost:8443"
export MEDAUTH_IDP_SSL_REQUIRED=all
export CURL_CA_BUNDLE="$PWD/deploy/local-tls/ca.crt"
export SSL_CERT_FILE="$CURL_CA_BUNDLE" REQUESTS_CA_BUNDLE="$CURL_CA_BUNDLE"
bash scripts/bootstrap_nonprod_idp.sh
MEDAUTH_DATABASE_URL="postgresql+asyncpg://medauth:medauth@localhost:5436/medauth" \
  uv run alembic upgrade head

uv run python scripts/production_smoke.py \
  --api-url https://api.medauth.localhost:8444 \
  --issuer "$MEDAUTH_OIDC_ISSUER" --audience medauth-api      # 7/7, writes nothing
```

> **The `down -v` is not optional, and this bit me while writing the guide.**
> `make_local_tls.sh` writes a new CA and new certificates, but Keycloak reads its
> certificate **once, at startup**, and Compose does not recreate a service whose
> definition has not changed. Regenerating TLS under a running stack therefore leaves
> the old certificate being served while the new CA sits on disk, and every request
> fails with `invalid padding` — a confusing error that looks like a broken script and
> is actually a stale process. Bring the stack down first, or add `--force-recreate`.

Keycloak in production mode on persistent PostgreSQL, HTTPS with a local CA that MEDAUTH
genuinely verifies — an untrusted CA and a wrong hostname are both refused.

The smoke suite defaults to **safe mode**: ten of its twelve checks are reads or
denials and it writes nothing (verified — the review-event count is unchanged). The two
that finalise a case run only against a case you name with `--smoke-case-id`, because a
smoke test that quietly finalises a case has corrupted the append-only record it was
checking.

## 6. Configuration

`.env.example` holds placeholders only. Generate real values:

```bash
python3 -c "import secrets; print(secrets.token_urlsafe(24))"
```

`.env` and `.env.idp` are gitignored and must stay so. `.env.idp` holds the identity
provider's credentials separately, because `compose.yaml` injects `.env` wholesale into
the API container and the API has no business holding the directory's admin password —
it verifies tokens, it does not mint them.

## 7. Tear down

```bash
set -a; . ./.env; . ./.env.idp; set +a     # required — see below
docker compose down
docker compose -f compose.idp.yaml down -v
docker compose -f compose.prod-shape.yaml down -v
```

> **Source the environment before tearing down, not just before starting.** The IdP compose files
> declare required variables as `${VAR:?}`, and Compose interpolates them on **every** command
> including `down` — so a teardown in a fresh shell fails with *"required variable
> MEDAUTH_IDP_ADMIN_USER is missing a value"* and leaves the containers running. Found by following
> this guide in a clean shell.

## What this demonstration does not show

No production deployment. No clinical validation. **No evaluation result** — the 26-case
run is blocked by R-86 and has never executed. See
[../evaluation/r86-status.md](../evaluation/r86-status.md).
