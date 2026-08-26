# What MEDAUTH needs from an identity provider

**No provider is selected** (ADR-030). This is the complete list of what any conformant
OIDC provider must supply, so that selecting one is a configuration task.

Verify a candidate in one command:

```bash
uv run python scripts/verify_idp.py --issuer https://… --audience medauth-api
uv run python scripts/verify_idp.py --issuer https://… --audience medauth-api --token "$TOKEN"
```

---

## 1. Required of the provider

| # | requirement | why | checked by |
|---|---|---|---|
| 1 | `.well-known/openid-configuration` served at the issuer | the only vendor-neutral way to find keys | `discovery reachable` |
| 2 | the document's `issuer` **equals** the configured issuer | a document advertising elsewhere is misconfiguration or key-discovery redirection | `document advertises the configured issuer` |
| 3 | a `jwks_uri` | asymmetric verification; MEDAUTH never holds a signing key | `document advertises a jwks_uri` |
| 4 | signing with **RS256** or **ES256** | `none` and HS256 are refused — see §3 | `an asymmetric algorithm…` |
| 5 | a `kid` on every key | rotation matches an unknown `kid` to a refetch | `every key has a kid` |
| 6 | tokens carrying `sub`, `iss`, `aud`, `exp` | all required; `nbf` and `iat` validated when present | `the application accepts the token` |
| 7 | a stable, non-reassignable `sub` | it becomes the audit identity, forever | operator judgement — **not machine-checkable** |
| 8 | role/group names in a claim (default `groups`) | see §2 | `roles arrive under the groups claim` |

**Requirement 7 is the one no script can check.** If a provider reassigns a `sub` when a
person leaves and another joins, the audit trail attributes an old decision to a new
human. Ask the provider's operator directly.

## 2. Roles → the existing three permissions

Configuration, not a new authorization model. `_PERMISSION_FOR_ROLE` in
`app/identity/authenticator.py`:

| group name the provider asserts | permissions granted |
|---|---|
| `medauth-readonly` | `READ_CASE` |
| `medauth-reviewer` | `READ_CASE`, `REVIEW_CASE`, `FINALIZE_CASE` |
| `medauth-senior-reviewer` | the above **+** `OVERRIDE_RECOMMENDATION` |

**An unrecognised group grants nothing.** A `permissions` claim in the token is never
read. A new group in the provider cannot silently become authority in MEDAUTH — the
mapping is the authorization decision and the claim is only its input.

Adopting a provider whose group names differ means editing that table. It does not mean
adding roles, hierarchies or RBAC.

**No qualification and no competence participate.** Group membership grants a MEDAUTH
permission and asserts nothing about clinical credentials; those remain `SELF_ASSERTED`
and grant nothing (OD-43, `docs/architecture/hitl-workflow.md` §5).

## 3. What MEDAUTH refuses

| refused | why |
|---|---|
| `alg: none` | not weakly authenticated — unauthenticated, wearing the shape of authentication |
| HS256 **in production** | the verifier holds the key that signs; anyone with the config could mint a reviewer token |
| discovery with no issuer match | key-discovery redirection |
| `auth_mode=oidc` with no discovery and no JWKS | nothing to verify a signature against |
| `auth_mode=development` in production | authenticates anybody who guessed a configured token name |
| a caller-supplied `reviewer_id` | the field does not exist to be sent |

All five configuration refusals happen at **startup**, not at the first review.

## 4. Configuration

```
MEDAUTH_AUTH_MODE=oidc
MEDAUTH_OIDC_ISSUER=https://…            # the only vendor-shaped value
MEDAUTH_OIDC_AUDIENCE=…                  # client id or configured audience
MEDAUTH_OIDC_DISCOVERY=true
MEDAUTH_OIDC_JWKS_URL=                   # only to pin an endpoint when discovery is unavailable
MEDAUTH_OIDC_SECRET=                     # tests only; production refuses it
```

Supplied as environment variables (ADR-017). **MEDAUTH holds no client secret**: it
validates tokens it is given and never obtains one, so there is no confidential-client
credential in this application at all. Whatever performs the login holds that.

## 5. Deployment prerequisites, in order

1. Select a provider — **unresolved** (ADR-030).
2. Create a non-production realm/tenant.
3. Register MEDAUTH as an audience, and whatever performs login as a client.
4. Create the three groups in §2, or edit the mapping to match existing names.
5. Assign a test user.
6. Run `verify_idp.py` with and without a token.
7. Record the result against ADR-030.
8. Only then configure a deployment.

Steps 1–8 are **not done**. Nothing in `app/` changes when they are.

## 6. Four claims that are not the same

| | status |
|---|---|
| integration **implemented** | **yes** — discovery, validation, rotation, 35 tests |
| conformance **verified against a real provider** | **no** — no provider exists to point at |
| deployment **performed** | **no** |
| **production-ready** | **no** |
