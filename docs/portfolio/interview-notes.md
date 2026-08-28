# Interview notes

Answers to the questions this design actually invites. Everything here is implemented and
verifiable in the repository; nothing is aspirational.

---

### Why OIDC and JWKS rather than an API key per reviewer?

Because an API key identifies a **system**, not a person, and the audit trail has to
survive the question *"who decided this?"* asked a year later after a bad outcome.

A per-reviewer API key looks like a fix and is not: it is still a shared secret held by
an integrating system, so the trail would look authenticated while recording only who
*claimed* to decide. OIDC gives an identity the application verifies rather than accepts —
signature checked against keys fetched from the issuer's own discovery document, with
issuer, audience, expiry, not-before and subject all enforced.

Two identity kinds now exist and cannot substitute for each other: an API key establishes
a **SERVICE** caller, a validated token establishes a **HUMAN** reviewer.

### Why is authorization enforced in the service rather than the route?

A route-only check is one a second entry point can miss. The reviewer UI and the JSON API
are two entry points to the same operation; putting the check in `HumanReviewService`
means adding a third cannot forget it.

`Principal.require()` also checks the principal's **type before its permissions**, so a
service integration that acquired `REVIEW_CASE` — through a mapping typo, an over-broad
group — still cannot review. That ordering is asserted by a test, because the natural
phrasing ("a principal holding the permission may review") would silently reintroduce the
problem the design exists to prevent.

### Why is qualification separate from identity?

They answer different questions. **Identity** is *who is this* — established, cryptographically.
**Qualification** is *what are they credentialed to do* — a sentence the person typed,
`SELF_ASSERTED`, verified by nobody. **Competence** is *can they decide this case* — not
modelled at all; no symbol for it exists.

A qualification grants nothing, and the separation is an **absence rather than a rule**:
there is no function from a qualification to a permission and no call site that could pass
one. `VERIFIED_BY_REGISTRY` exists in the vocabulary and is unreachable, so the record can
distinguish "checked and qualified" from "nobody checked" if a registry ever exists — and
it still would not grant anything. A licence number that becomes a bypass is exactly the
failure being designed out.

### Why is reviewer assignment deliberately absent?

Because nothing assigns anything yet. A `CaseAssignment` table with
`UNASSIGNED`/`ASSIGNED`/`COMPLETED` would be a schema nobody writes to and a status nobody
reads, and its presence would imply a workflow guarantee that does not exist.

The honest description of the current model is: a case in `HUMAN_REVIEW` is reviewable by
any authorised human whose integrator can see it. There is no default assignee, hidden or
otherwise. When a real queue needs assignment, it arrives with the code that uses it.

### How does HITL stop the AI recommendation from becoming the decision?

Four mechanisms, none of which is a convention:

1. **The model cannot express an outcome.** `APPROVE_RECOMMENDED` and `DENY_RECOMMENDED`
   appear in no model output schema; code computes the outcome from per-criterion verdicts.
   An AST-parsing test enforces it.
2. **Separate fields.** `human_disposition` is `None` until a person acts, and an override
   *preserves* the draft rather than replacing it — so "did this person agree, and with
   what" is answerable from the row alone.
3. **No state edge.** `RECOMMENDATION_READY` cannot reach `FINALIZED`. The transition table
   has no such entry, so a recommendation cannot finalise itself. A mutation test adds the
   edge and requires a test to fail.
4. **Ordering.** The routing explanation renders *above* the recommendation. Showing the
   proposed answer before the question is how an interface manufactures agreement — R-04.
   The mitigation is structural; **its effectiveness on real reviewers is not measured and
   is not claimed.**

### How is historical evidence preserved?

The reviewer's evidence is read from the audit events the original run emitted, never
re-retrieved. Re-running retrieval when someone opens a case would return **today's**
corpus for **yesterday's** decision under a heading saying "supporting evidence".

That failure would be invisible: the citations would verify, the passages would look
relevant, and the reviewer would be judging a different case from the one the engine
decided. The E2E asserts the evidence is byte-identical before and after an action.

### How is the audit protected?

Append-only, enforced by a **database trigger**. It was originally enforced by revoking
`UPDATE`/`DELETE` from the application role — which showed correctly in
`information_schema` and did nothing, because **PostgreSQL never restricts a table's
owner**. Every mutation still succeeded. A row-level trigger then missed `TRUNCATE`, so a
statement-level one was added too.

Retention deletes by `created_at` and by nothing else: a purge that can be aimed at
particular rows is a mechanism for erasing the record of a specific recommendation.

The identity written there is the provider's `sub` **with its issuer**, so re-pointing a
deployment at another provider cannot silently merge two people's histories.

### Why does an unknown `kid` fail closed?

Because a key the provider never published means the token cannot be verified, and an
authenticator that degrades when its key source is unreachable is least trustworthy exactly
when something is wrong.

**This was a real defect, found by real tokens.** `PyJWKClientError` is a *sibling* of
`jwt.InvalidTokenError`, not a subclass, so it escaped the handler and surfaced as an
unhandled **`500` on an unauthenticated request**. Not an auth bypass — but it broke the
uniform refusal: every other rejection is an identical `401` precisely so a caller cannot
learn which check failed, and a `500` announced *your kid is unknown* as distinct from
*your signature is bad*. The mocked rotation test could not have caught it; it proves an
unknown `kid` triggers a refetch, and this is the branch where the refetch comes back empty.

### What did mutation testing reveal?

Beyond confirming 47 safety rules are defended: it caught **the guard itself being
vacuous**. It decided "caught" from `returncode != 0` — and a test that *cannot run* also
exits non-zero. On any checkout without the restricted corpus, ten mutations were reported
CAUGHT by runs in which nothing had examined them.

The harness built to catch vacuous safety tests was scoring itself vacuously. It now has a
third verdict, `NOT VERIFIED`, printed with the rule it was meant to defend rather than
credited as a pass.

### What did cold-state testing reveal?

That everything never actually executed was hiding something. Running the documented path
from zero containers, zero volumes, no TLS material and no images found:

- the documented **teardown** fails in a fresh shell — Compose interpolates `${VAR:?}` on
  `down` too;
- **TLS regeneration under a running stack silently serves the old certificate**, because
  Keycloak reads its certificate once at startup and Compose will not recreate an unchanged
  service;
- `verify_idp.py` performs **7** checks without a token, not the twelve documented;
- and **"1369 passed" required an undocumented corpus ingest** — without it the retrieval
  audit cannot score its own control query, and the failure reads as a broken test rather
  than an empty index.

Earlier phases found the same shape three times: CI had never passed, the container image
had never been rebuilt, and a compliance guard had been failing since the phase that wrote
it. In each case the check was green because nothing had run it.

### Why is R-86 still blocked?

Because the provider, given the production extraction schema and a long clinical note,
emits ~190 non-whitespace characters, never closes the JSON document, and pads whitespace
to the 1536-token ceiling — **6 of 12 trials against a 10% ceiling**, deterministic at
temperature 0 and byte-identical across runs hours apart.

Refuted by measurement: an application defect, gateway mutation in either direction,
prompt length (a *longer* prompt with the same schema succeeds), context exhaustion, an
insufficient completion budget (the succeeding cell finishes at 67% of the ceiling while
emitting ten times more content), the schema alone, the content alone, and a defective
reproducer. It requires the conjunction of schema, clinical content and length.

The decoder is behind an endpoint with no administrative surface and no local alternative.
Every remaining discriminator — decoder state, EOS eligibility, grammar state, token trace,
runtime version, speculative-decoding participation — is provider-internal.

### Why was the experiment not modified to obtain a pass?

Because every available modification produces a green gate and a meaningless number.
Lowering the threshold, simplifying the schema, shortening the note, dropping the failing
cell or adding retries would each make the symptom disappear without changing what the
provider does.

The gate is built so that saying yes for the wrong reason requires **editing the gate** —
no `force`, no `override`, no environment variable, asserted over its own AST — and that
edit would be visible in the diff. `gold_v2` is unspent at 0/1 and the 26-case evaluation
has never run. The honest output of this project is a blocked gate and an escalation
package, not a number.

### What would real production deployment require?

Nothing from the application. Every environment difference is injected, and the topology is
verified in production *shape* — HTTPS, a stable hostname issuer, persistent identity
storage, non-development mode, a clean image.

What is missing is external: a deployment platform, DNS, a certificate authority, a secrets
mechanism, backup with a **tested** restore, HA/DR, alerting, an owner for the production
identity provider — and the governance decisions, of which the sharpest is **who may hold
`medauth-senior-reviewer`**, the authority to overturn a recommendation. Without an owner,
that authority is granted by whoever administers the directory.

Two gaps would remain even then, and neither is mitigated: **token revocation is not
checked** (a disabled account's unexpired token still authenticates — measured; exposure is
bounded only by `accessTokenLifespan`), and **subject reassignment cannot be detected**.
