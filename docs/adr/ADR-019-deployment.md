# ADR-019: Deployment Strategy

**Status:** Accepted · **Date:** 2026-08-23 · **Phase:** Planning

## Context

The system comprises a FastAPI application, PostgreSQL with pgvector, and a Next.js console. It
consumes — but does not deploy — the separately-owned LLM Firewall.

The reference machine has **no Kubernetes tooling**: no `kubectl`, `kind`, `minikube` or `helm`, and
no cluster.

## Problem

1. What is the local and production topology?
2. What can honestly be claimed about Kubernetes?

## Options

| # | Option | Assessment |
|---|---|---|
| A | Docker Compose only | Simple, runnable, verifiable. Does not demonstrate orchestration. |
| B | Compose + Kubernetes manifests, statically validated | Both artefacts exist. Manifests never run. |
| C | Compose + Kubernetes validated on a real cluster | Strongest. No cluster available. |
| D | Kubernetes only | No lightweight local path; slows every phase. |

## Decision

**Option B**, with the claim scoped precisely to what has been done.

### Local — `compose.yaml`

API on **8010**, PostgreSQL + pgvector on **5435**, UI on **3100**. Optional overlays:
`compose.observability.yaml` (Prometheus **9092**), `compose.langfuse.yaml` (**3200**). The firewall
is consumed at **8005** and is not started by this stack.

Ports avoid everything bound on the reference machine (3000, 5000, 5433, 5434, 5678, 8005, 8006,
8080–8082, 8089, 9001, 9004, 9005, 9091).

### Production reference — `compose.prod.yaml`, **standalone**

Not an overlay, because **an overlay cannot un-publish a port**. Only the edge publishes; the
database sits on an `internal: true` network; secrets arrive as mounted files at
`/run/secrets/MEDAUTH_*`; `/ready` is the health gate, so a container that lost its security
configuration never has traffic routed to it. Asserted by tests against the manifests.

### Containers

Non-root, read-only root filesystem, dropped capabilities, pinned base image digests. UI built in
its own container with a committed lockfile.

### Kubernetes — authored and statically validated

Deployment, Service, ConfigMap, Secret (by reference, never literal), HPA, Ingress; readiness and
liveness probes wired to `/ready` and `/health`; resource requests and limits. Validated in CI with
`kubeconform`.

> **The claim "runs on Kubernetes" is refused** until a real cluster run produces an artefact
> (OD-9). The permitted claim is *"Kubernetes manifests are authored and statically validated in
> CI"* — a different and weaker statement, and the accurate one.

### CI/CD

`ruff` → `mypy --strict` → `uv lock --check` → unit/api/security → integration (compose) →
evaluation guards → `kubeconform` → image build → `trivy` → `gitleaks` (full history) → `npm audit`.

**CI never depends on a paid API.** Model-calling tests are marked and skipped unless a secret is
configured; evaluation regression runs against committed reports, not live inference. CI must pass
from a clean clone with no key and no network egress.

## Rationale

**Compose is the honest local artefact**, and `docker compose up -d` reaching a passing `/ready` is
a claim that can be demonstrated in seconds.

**Standalone production rather than an overlay**, because what makes a deployment production is
mostly what it *removes* — published ports, permissive defaults, development credentials — and
Compose overlays can only add. This follows the sibling project's ADR-028, which is asserted by
tests against its manifests.

**Kubernetes manifests are authored because the design questions are real** — probes, limits,
secret references, autoscaling — and answering them clarifies the system. They are not *claimed*,
because no cluster has ever run them, and a manifest that passes `kubeconform` has been checked for
schema validity, not for whether the application starts, becomes ready, scales, or survives a
rolling update.

This is the same position the sibling project took (its OD-41), for the same reason, and it is the
distinction between an engineering artefact and a résumé claim.

**CI must be key-free** so the repository is verifiable by anyone, and so a fork does not silently
lose test coverage.

## Consequences

**Positive.** One-command local stack. A production topology asserted by test rather than described
in prose. Manifests exist and are schema-valid. CI runs anywhere. No secret in any manifest or image
layer.

**Negative.** Manifests may contain runtime errors that only a cluster would reveal — stated, not
hidden (R-29). Resource limits are guesses until measured under load. Compose and Kubernetes
descriptions can drift, mitigated by asserting both against the same settings contract.

**Neutral.** No CD to a live environment. There is no environment to deploy to.

## Rejected alternatives

| Alternative | Rejected because |
|---|---|
| **A — Compose only** | The orchestration design questions are real and worth answering; manifests are cheap to author and honest to label. |
| **C — validated on a real cluster** | Preferred, and unavailable. It is recorded as OD-9 rather than quietly assumed. |
| **D — Kubernetes only** | Removes the fast local path that every earlier phase depends on. |
| **Claiming "production-ready Kubernetes deployment"** | Untrue. The manifests have never run. This is exactly the claim the evidence ledger exists to prevent. |
| **Helm chart** | Templating over manifests that have never been applied adds a layer of indirection to an unvalidated artefact. |
