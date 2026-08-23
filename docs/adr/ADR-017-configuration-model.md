# ADR-017: Configuration Model — Settings versus Policy

**Status:** Accepted · **Date:** 2026-08-23 · **Phase:** Planning
**Not in the original brief.** Added because abstention thresholds change clinical behaviour, so
where they live and how they are versioned is an architectural decision.

## Context

The system has two kinds of configuration with nothing in common except the word:

- **Deployment values and secrets** — database URL, firewall base URL, caller key, ports, timeouts.
- **Behavioural policy** — abstention thresholds, unsafe-rate ceilings, retrieval `k`, rerank
  cutoff, concurrency limits.

## Problem

One configuration system or two? And what stops a threshold change from being an invisible clinical
behaviour change?

## Options

| # | Option | Assessment |
|---|---|---|
| A | Everything in environment variables | One mechanism. Nested structures become flat strings; no schema; secrets sit beside behaviour. |
| B | Everything in YAML | Structured. Secrets end up in files that get committed. |
| C | **Settings from environment; policy from YAML** | Two mechanisms, each suited to its content. |
| D | A configuration service | Runtime changes without redeploy. A dependency, and behaviour becomes untraceable to a version. |

## Decision

**Option C**, following the sibling project's ADR-011.

| | Source | Contains |
|---|---|---|
| **Settings** | Environment, prefix `MEDAUTH_`, `pydantic-settings` | Secrets (`SecretStr`), URLs, ports, timeouts, feature flags |
| **Policy** | `config/decision-policy.yaml` (+ `config/environments/<env>.yaml`) | Thresholds, ceilings, retrieval parameters, gate configuration |

Precedence, lowest to highest:

```
built-in defaults  <  config/environments/<env>.yaml  <  MEDAUTH_* env vars
```

**Enforced properties:**

- **Secrets are structurally rejected in policy YAML.** Any key matching `*_key`, `*secret*`,
  `*token*` or `*password*` fails startup, so a credential cannot be committed that way.
- **Invalid policy prevents startup** and is never silently repaired.
- **Production refuses to start** with `MEDAUTH_LLM_FAIL_CLOSED=false`, with an unauthenticated
  reviewer console, with no trusted proxy range, or with `MEDAUTH_TRUSTED_PROXIES=0.0.0.0/0`.
- **`decision_config_version` is recorded on every recommendation**, so which rules were in force
  for a given case is an auditable fact rather than a reconstruction.

## Rationale

**The two kinds of configuration have different lifecycles, audiences and risks.** A database URL
differs per environment and is uninteresting. An abstention threshold is the same in every
environment, changes clinical behaviour, and must be reviewable in a diff and traceable from an
audit row. Managing both with one mechanism means either secrets in committed files or clinical
thresholds as flat environment strings that nobody reviews.

**Structural secret rejection is worth more than a convention**, because the failure mode is a
credential committed to git — irreversible in practice, since history persists after removal.

**Recording the config version on every recommendation is what makes thresholds auditable.** Without
it, "why was this case abstained?" is unanswerable after any threshold change. With it, threshold
changes are also replayable: `gate_features` are persisted, so a proposed change can be evaluated
over historical cases without re-running a single model call.

**Refusing to start beats degrading.** A system running with fail-closed disabled in production, or
with an unauthenticated console, is worse than one that will not start — the failure is loud and
immediate rather than silent and clinical.

**The decision table itself is deliberately *not* configuration** (ADR-010). Rules are the safety
property and live in version-controlled code with a test suite. Only thresholds are configuration.
Making the rules configurable would let a deployment reorder rows 6 and 8 — turning missing evidence
into a denial — without a code review.

## Consequences

**Positive.** Secrets cannot be committed through policy files. Threshold changes are reviewable
diffs and traceable from audit rows. Misconfiguration fails loudly at startup. Recalibration replays
without model calls. Both repositories are configured the same way.

**Negative.** Two mechanisms to learn and document. A threshold change requires a restart — correct
for this domain, since a clinical behaviour change should not happen silently at runtime. Policy
schema validation is work.

**Neutral.** Some values could sit in either system; the rule is *does changing this alter clinical
behaviour?* If yes, it is policy.

## Rejected alternatives

| Alternative | Rejected because |
|---|---|
| **A — everything in environment** | Nested gate configuration becomes flat strings; no schema validation; clinical thresholds get changed without review. |
| **B — everything in YAML** | Puts secrets in files that get committed. The failure is irreversible once in git history. |
| **D — configuration service** | Runtime changes to clinical behaviour without a deployment or a review, and behaviour becomes untraceable to a version. Exactly wrong here. |
| **Decision rules in configuration** | Would allow reordering the table — turning missing evidence into a denial — without code review. |
