# Security evidence

**Demonstrated facts only.** Nothing here is a control that is merely possible, and
nothing is inferred from configuration — each row was produced by a test, a script or a
CI run in this repository.

Verified against a real Keycloak 26 over HTTPS through the published port, unless a row
says otherwise.

---

## Authentication

| property | evidence |
|---|---|
| asymmetric verification (RS256) | real provider tokens; `alg=none` refused |
| keys from the provider's JWKS | `jwks_uri` read from the issuer's own discovery document |
| issuer validated | a token with a forged `iss` → `401` |
| audience validated | wrong `aud` → `401` |
| expiry | expired token → `401` |
| not-before | `nbf` in the future → `401` |
| subject required | token without `sub` → `401` |
| algorithm restricted | RS256/ES256/HS256 only, listed explicitly rather than left to defaults |
| **key rotation** | a second realm key at higher priority changed the `kid`; the container held the pre-rotation JWKS, refetched, and accepted — an override on the rotated key returned `201`. The superseded key stayed published, so tokens issued under it kept verifying |
| **unknown `kid` fails closed** | `401`, repeatedly. **This was a defect**: `PyJWKClientError` is a *sibling* of `InvalidTokenError`, not a subclass, so it escaped the handler and surfaced as a `500` on an unauthenticated request. Found by real tokens; the mocked rotation test could not reach it |
| **provider outage fails closed** | Keycloak stopped entirely → `401` with the same body, never a `500`. A cached JWKS keeps existing tokens working |
| **uniform refusal** | 19 negative cases, **one identical `401` body**. Bad signature, unknown `kid` and wrong audience are indistinguishable to the caller, so no oracle is offered |
| no symmetric fallback | production refuses to start with `oidc_secret` set; a discovery failure returns no authenticator rather than a weaker one |

## Authorization

| property | evidence |
|---|---|
| enforced in the **service**, not the route | a second entry point cannot miss it |
| permission sets | `readonly {READ_CASE}` · `reviewer +{REVIEW_CASE, FINALIZE_CASE}` · `senior +{OVERRIDE_RECOMMENDATION}` |
| matrix through the published port | readonly `200/403/403/403` · reviewer `200/201/**403**/201` · senior `200/201/201/201` |
| unknown group → no permissions | an authenticated user in no group is refused everything, including read |
| **type checked before permissions** | a SERVICE principal holding **every** permission in the enum is refused all three human actions |
| caller cannot inject identity | no `reviewer_id` parameter exists — the fix is an absence, not a validation |
| caller cannot inject permissions | a token asserting its own `permissions` with empty `groups` grants nothing |
| **anti-enumeration** | a nonexistent case and another integrator's case are both `404` |

## Audit

| property | evidence |
|---|---|
| authenticated subject recorded | `principal_id` is the provider's `sub`, not a caller-supplied name |
| **issuer-scoped** | `identity_issuer` is stored beside it, so re-pointing at another provider cannot silently merge two people's histories |
| identity model recorded | `AUTHENTICATED_HUMAN`; historical rows stay labelled `LEGACY_CALLER_SUPPLIED` and are not back-filled |
| **append-only by trigger** | `UPDATE` and `DELETE` both refused. Grants alone were **inert** — PostgreSQL never restricts a table's owner — and a row-level trigger also missed `TRUNCATE` until a statement-level one was added |
| evidence provenance | the reviewer's evidence is read from the original run's trail; verified byte-identical before and after an action |
| no clinical text in the trail | asserted over the audit payloads |

## Transport

| property | evidence |
|---|---|
| HTTPS end to end | production-shaped stack; the application holds no certificate — TLS terminates at a proxy |
| **certificate trust is real** | a local CA is *added* as a trust anchor; verification is never disabled, and there is no pinning or exception in the code |
| untrusted CA refused | the same certificate without the CA → `unable to get local issuer certificate` |
| **wrong hostname refused** | the same certificate under another name → `Hostname mismatch` |
| provider HTTPS-only | `KC_HTTP_ENABLED=false`, `sslRequired=all` — no plain-HTTP fallback to misconfigure into |

## Supply chain and runtime

| property | evidence |
|---|---|
| clean image | built `--no-cache --pull`: **37 packages** |
| explicit runtime dependencies | `jinja2` is declared. **It was not**, and the image could not import the application at all — it worked locally only because an optional extra pulled it in |
| no optional-extra masking | `torch`, `transformers`, `sentence-transformers` absent from the image |
| secret hygiene | none in source, none in the image; `SecretStr` keeps values out of `repr`; redaction at the structlog sink, not per call site; `.env` and `.env.idp` gitignored and separated so the API never holds the directory's credentials |
| outbound documents | a test reads the forbidden values from `Settings` and fails the build if one appears in the escalation package — it caught a draft carrying the gateway's address |
| **mutation testing** | **47/47 caught** where the restricted corpus is present. In CI, which cannot hold that corpus, the guard reports **37 caught, 10 not verified** and names them — it does not credit a mutation whose catching test could not run |
| **remote CI** | run `33097477139` green, every step, none skipped; database-backed api/security tests genuinely execute against a real PostgreSQL service |

## Known gaps, stated rather than mitigated

- **Token revocation is not checked — measured.** With an account disabled in the realm,
  a *new* login is refused while the *existing* token still authenticates. Exposure is
  bounded only by `accessTokenLifespan`.
- **Subject reassignment cannot be detected.** An operator who mints a new user carrying
  a retired `sub` produces a valid token resolving to the wrong person's history.
- **The firewall does not protect this application's main attack surface.** Its own
  committed evidence refuses that claim; containment here is structural — closed schemas,
  span-verified quotes, code-computed decisions — and holds whether or not an injection
  is detected.
