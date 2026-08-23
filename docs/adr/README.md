# Architecture Decision Records

Each ADR carries **Context · Problem · Options · Decision · Rationale · Consequences · Rejected
alternatives**. ADRs are not created to increase document count; each one below records a decision
with real alternatives that were weighed.

From ADR-011 onward, ADRs covering experiments are **pre-registered protocols**: they fix
hypotheses, success criteria (with denominators, interval method and direction) and failure modes
*before* execution. Criteria are never retuned after seeing results, and a pre-registered failure
mode is never later presented as a discovery.

| ADR | Decision | Status |
|---|---|---|
| [001](ADR-001-system-architecture.md) | System architecture and the decision-support boundary | Accepted |
| [002](ADR-002-agent-orchestration.md) | Agent orchestration — LangGraph, confined to `app/graph/` | Accepted |
| [003](ADR-003-policy-corpus.md) | CMS Medicare Coverage Database as the initial corpus | Accepted |
| [004](ADR-004-policy-resolution-and-temporal-versioning.md) | Deterministic policy resolution and temporal versioning | Accepted |
| [005](ADR-005-postgres-pgvector.md) | PostgreSQL + pgvector as the only datastore | Accepted |
| [006](ADR-006-chunking-embedding-reranking.md) | Section-aware chunking, embedding and reranking | Accepted (models provisional) |
| [007](ADR-007-ingest-time-criteria-extraction.md) | Criteria extraction at ingest time | Accepted |
| [008](ADR-008-model-strategy.md) | Model strategy and the gateway contract | Accepted (probe pending) |
| [009](ADR-009-evidence-and-citation-contract.md) | Evidence and citation contract | Accepted |
| [010](ADR-010-deterministic-decision-engine.md) | Deterministic decision engine and LLM containment | Accepted |
| [011](ADR-011-abstention-and-calibration.md) | Abstention strategy and calibration protocol | Pre-registered |
| [012](ADR-012-human-in-the-loop.md) | Human-in-the-loop review workflow | Accepted |
| [013](ADR-013-audit-architecture.md) | Audit architecture | Accepted |
| [014](ADR-014-evaluation-methodology.md) | Evaluation methodology | Pre-registered |
| [015](ADR-015-synthetic-case-construction.md) | Synthetic case construction and ground-truth provenance | Accepted |
| [016](ADR-016-llm-firewall-integration.md) | LLM Firewall integration and RAG-injection containment | Accepted |
| [017](ADR-017-configuration-model.md) | Configuration model — settings versus policy | Accepted |
| [018](ADR-018-observability.md) | Observability | Accepted |
| [019](ADR-019-deployment.md) | Deployment strategy | Accepted |
| [020](ADR-020-reviewer-ui.md) | Reviewer console — Next.js | Accepted |
| [021](ADR-021-authoritative-corpus-and-curated-criteria.md) | Authoritative corpus, curated criteria, verification gate | Accepted |
| [022](ADR-022-coverage-policy-source.md) | Coverage policy source — 42 CFR, NCDs adopted, LCDs deferred behind the licence gate | Accepted |

## Reconciliation with the original brief

The brief proposed two overlapping lists of 12–13 ADRs. The set above covers all of them and adds
four decisions the brief did not name but which turned out to be load-bearing:

| Added | Why it needed its own record |
|---|---|
| **004** — policy resolution and temporal versioning | The brief treated retrieval as one step. Splitting deterministic applicability from semantic search is the largest change made to the proposed architecture and the main defence against a fluent, well-cited, inapplicable answer. |
| **007** — ingest-time criteria extraction | Moving criteria structuring out of the request path changes latency, cost, consistency, auditability and — decisively — makes ground truth by construction possible. |
| **015** — synthetic case construction | Ground-truth provenance determines whether the evaluation measures anything at all. |
| **017** — configuration model | Abstention thresholds change clinical behaviour. Where they live and how they are versioned is an architectural decision, not a detail. |

The brief's "ADR-002 Agent Orchestration" and "ADR-012 LLM Firewall Integration" are preserved as
002 and 016. Its separate "evidence/citation" and "abstention" entries are preserved as 009 and 011.
