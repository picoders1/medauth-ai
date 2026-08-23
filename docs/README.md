# MEDAUTH AI — Documentation

`docs/` is the source of truth. Code that contradicts it is a bug in one of the two.

**Current state:** planning phase complete. No application code exists. Phase 0 has not started.
Every performance, accuracy and grounding figure in this project is **pending evidence**.

---

## Start here

| Document | What it settles |
|---|---|
| [architecture/system-architecture.md](architecture/system-architecture.md) | End-to-end flow, the governing invariant, layer boundaries, failure semantics |
| [architecture/implementation-roadmap.md](architecture/implementation-roadmap.md) | Phases 0–9, executable phase by phase |
| [architecture/decision-and-abstention.md](architecture/decision-and-abstention.md) | The decision table and the calibration protocol |

## Architecture

- [system-architecture.md](architecture/system-architecture.md) — flow, invariants, trust boundaries
- [agent-architecture.md](architecture/agent-architecture.md) — step contracts and prohibitions
- [rag-architecture.md](architecture/rag-architecture.md) — corpus, resolution, retrieval, citations
- [data-architecture.md](architecture/data-architecture.md) — schema, classification, retention
- [decision-and-abstention.md](architecture/decision-and-abstention.md) — decision engine, gate, calibration
- [repository-structure.md](architecture/repository-structure.md) — layout, dependency rules, ports
- [implementation-roadmap.md](architecture/implementation-roadmap.md) — Phases 0–9

## Security

- [security/threat-model.md](security/threat-model.md) — T-01…T-27, each becoming a test in Phase 8
- [security/llm-firewall-integration.md](security/llm-firewall-integration.md) — the boundary, and what it does **not** cover

## Evaluation

- [evaluation/evaluation-strategy.md](evaluation/evaluation-strategy.md) — metrics, splits, leakage controls, failure families

## Governance

- [evidence-and-claims.md](evidence-and-claims.md) — every claim, its required artefact, its status
- [risk-register.md](risk-register.md) — R-* failure modes
- [open-decisions.md](open-decisions.md) — OD-* genuinely unsettled questions

## Decision records

[adr/](adr/) — ADR-001…ADR-020. Each carries Context, Problem, Options, Decision, Rationale,
Consequences and Rejected alternatives. See [adr/README.md](adr/README.md) for the index.

---

## Reading conventions

- **Pending evidence** means no artefact exists. The figure is not estimated, guessed or implied.
- **Refused claim** means an artefact would be required and either does not exist or contradicts
  the claim. A refused claim appears nowhere outside the ledger.
- Figures quoted from the sibling `llm-firewall` project carry their source report path.
- `T-*` are threats, `R-*` risks, `OD-*` open decisions, `ADR-*` decisions.
