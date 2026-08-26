# ADR-030 — Identity-provider selection is an unresolved deployment dependency

**Status:** Accepted, **amended 2026-08-26** · **Date:** 2026-08-26 · **Supersedes:** nothing ·
**Related:** ADR-012 (human-in-the-loop), ADR-017 (configuration), ADR-019 (deployment),
ADR-020 (reviewer UI), OD-43

---

## Context

MEDAUTH's reviewer authentication boundary is implemented and tested: OIDC discovery
tied to the configured issuer, asymmetric signature verification via the provider's
`jwks_uri`, issuer/audience/expiry/not-before/subject validation, rotation on an unknown
`kid`, and a production configuration that refuses to start on any weaker arrangement.

The next step is to point it at a real identity provider and prove the path end to end.

**No identity provider has been selected.** An exhaustive sweep of every tracked file
found no vendor named anywhere:

| looked in | found |
|---|---|
| all 30 ADRs | no vendor. ADR-020 treats auth as a UI concern; ADR-012 says identity is derived server-side; ADR-017 refuses an unauthenticated console — none picks one |
| `compose.yaml` | two services, `api` and `postgres`. No IdP |
| `deploy/` | one Dockerfile |
| Kubernetes manifests | **none exist**, despite ADR-019 describing them as authored |
| `.github/workflows/ci.yaml` | no identity service |
| `docs/operations/` | seven runbooks, all R-86; no deployment or identity runbook |

So the choice is not merely undocumented — there is no infrastructure, no environment
and no convention from which one could be inferred.

## Decision

**Do not select an identity provider.** Record the selection as an unresolved
**deployment** dependency, and keep the integration boundary provider-neutral.

Concretely:

1. The code names no vendor and will not. A deployment configures an **issuer**, and
   `jwks_uri` is read from that issuer's own discovery document.
2. What MEDAUTH needs from any conformant provider is specified once, in
   `docs/security/identity-provider-contract.md`.
3. `scripts/verify_idp.py` verifies a candidate provider against that contract in one
   command, so selecting one is a configuration task rather than an engineering task.
4. Until a provider is configured and verified, **no claim of real-provider integration
   is made** anywhere in this repository.

## Alternatives considered

| | why not |
|---|---|
| **A — Pick a common open-source IdP and integrate it** | It is the choice that makes the phase *look* finished. Selecting a vendor is a deployment decision with operational, licensing and security consequences that this repository has no basis to make, and a compose service added on that basis would become the de-facto answer by inertia. The brief's own instruction is not to invent one. |
| **B — Run a throwaway IdP container purely for a test** | Superficially "just test infrastructure", but it adds a service to the stack, a vendor to the lockfile-equivalent, and an operational convention — and it would produce evidence about a provider nobody will deploy. It would let "verified against a real IdP" be written down while remaining untrue of the eventual one. |
| **C — Assert readiness on the strength of the mocked tests** | The mocked tests are good and they are not the same claim. A discovery document served by `respx` proves the parser; it does not prove that a real provider's document, key rotation cadence, clock skew or audience convention are compatible. |
| **D — Record the dependency and make verification a one-command task** | **Chosen.** It is honest about what is unknown and it removes every engineering obstacle from the eventual decision. |

## Consequences

**Accepted:** the phase ends without real-provider evidence, and that is reported as
`BLOCKED` rather than dressed up. Enterprise SSO remains undeployed.

**Gained:** the eventual selection costs configuration and one verification run. Nothing
in `app/` changes when a provider is chosen.

**Residual, stated:** the mocked tests exercise this repository's side of the boundary
only. A real provider can still surprise it — an audience convention that differs from
the `aud` claim, clock skew beyond PyJWT's leeway, a `jwks_uri` on a different host from
the issuer, or roles under a claim other than `groups`. `verify_idp.py` checks exactly
those, which is why it exists.

**Not decided here:** which provider, who operates it, how reviewers are provisioned
into it, and how the three MEDAUTH permissions map onto that provider's group names.
The last is deliberately configuration — `_PERMISSION_FOR_ROLE` — and not a new
authorization model.

## What this ADR does not change

The three permissions, the service-layer authorization boundary, the separation of
identity from qualification and competence, the append-only audit, the HITL workflow,
and the 404 anti-enumeration behaviour are all untouched. This ADR records an absence;
it does not create an architecture.


---

## Amendment, 2026-08-26 — a provider was selected by the operator

**This ADR's decision was overridden by the repository owner**, who directed that the
phase be unblocked rather than left waiting on provider values. Recorded as their
decision, not as a reversal this repository made on its own judgement: the reasoning
above still stands for the case where nobody has chosen.

**Selected: Keycloak 26**, run from `compose.idp.yaml` as a **non-production-only**
overlay on host port 8090, realm `medauth-nonprod`, audience `medauth-api`.

This is alternative **B** above, which this ADR rejected. The objection was that a
throwaway container "would produce evidence about a provider nobody will deploy". That
objection is still true and is why the claim made below is narrow. What changed is the
balance: with no vendor forthcoming, the alternative was not a better provider but an
indefinite block, and a boundary nobody has ever run a real token through is a boundary
whose defects are still undiscovered. That turned out to be literally true — see the
defect below.

### What the container's constraints buy

`start-dev`, in-memory H2, no HTTPS enforcement, no state across a `down`. These are
disqualifying for production, deliberately: **this provider cannot be promoted by
changing an environment variable.** It is a separate compose file for the same reason —
`docker compose up` cannot start it by accident, so it cannot drift into being the
deployment.

### What it proved that the mocked tests could not

`app/identity/authenticator.py` caught `jwt.InvalidTokenError`. `PyJWKClientError` is
**not a subclass of it** — they are siblings under `PyJWTError`. So a token carrying a
`kid` the provider never published escaped the handler and surfaced as an unhandled
exception: **HTTP 500 on an unauthenticated request**, triggerable by anyone able to
construct a JWT.

Not an authentication bypass — access was still denied. But the 500 was a different
answer from every other refusal's uniform 401, which told a caller their `kid` was
unknown rather than their signature bad: the exact oracle the fixed refusal message
exists to deny them. `PyJWKClientConnectionError` subclasses it, so an unreachable
provider produced a 500 rather than the documented fail-closed refusal.

The mocked suite could not have found it. Its rotation test proves an unknown `kid`
*triggers a refetch*; this is the branch where the refetch comes back empty, and only
a real key set that genuinely lacks the `kid` reaches it. Fixed, with two regression
tests that fail against the unfixed code.

**That finding is the justification for this amendment.** A provider-neutral boundary
verified only against mocks was carrying a live defect for as long as it existed.

### What is still not decided

Which provider a **deployment** uses. Nothing in `app/` changed to accommodate
Keycloak, and nothing would change for another conformant provider — the selection
above is scoped to non-production verification. `docs/security/identity-provider-contract.md`
remains the contract, and `scripts/verify_idp.py` remains the way to check a candidate.
