# MEDAUTH AI — Documentation

`docs/` is the source of truth. Code that contradicts it is a bug in one of the two.

**Current state:** Phases 0, 1 and the data-foundation phases are complete. The policy corpus is
**authoritative** (42 CFR via the official eCFR API); criteria are human-transcribed and
span-verified against it; clinical notes remain constructed.
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

## Data

- [data/policy-corpus-scope.md](data/policy-corpus-scope.md) — what policies, why, and how they were obtained
- [data/criteria-inventory.md](data/criteria-inventory.md) — how a criterion comes to exist, and what it carries
- [data/dataset-card.md](data/dataset-card.md) — five source categories, never blurred
- [data/mimic-readiness.md](data/mimic-readiness.md) — real clinical text: **not accessed**, and what would be required
- [data/data-foundation.md](data/data-foundation.md) — the credibility chain and where it breaks
- [data/policy-criteria-completeness.md](data/policy-criteria-completeness.md) — **is the criterion set complete?** 356 provisions walked; 247 await review (OD-19)
- [data/ground-truth-readiness.md](data/ground-truth-readiness.md) — **the twelve-question gate.** Classification: **B, partially ready**
- [data/ncd-lcd-source-assessment.md](data/ncd-lcd-source-assessment.md) — what coverage material is legitimately obtainable, and what is licence-gated (OD-20)

## Evaluation

- [evaluation/evaluation-strategy.md](evaluation/evaluation-strategy.md) — metrics, splits, leakage controls, failure families
- [evaluation/gold-set-labeling-protocol.md](evaluation/gold-set-labeling-protocol.md) — how a case gets its label, and what that label is worth
- [evaluation/data-partitioning.md](evaluation/data-partitioning.md) — development / validation / gold, and the leakage controls
- [evaluation/retrieval-dataset.md](evaluation/retrieval-dataset.md) — retrieval ground truth, measured apart from decision quality
- [evaluation/retrieval-evaluation-assessment.md](evaluation/retrieval-evaluation-assessment.md) — the set is **not difficult enough**, and why 1.0000 is not reassuring
- [evaluation/ground-truth-review-protocol.md](evaluation/ground-truth-review-protocol.md) — what a qualified reviewer must do, and what may be claimed after
- [evaluation/gold-set-audit.md](evaluation/gold-set-audit.md) — all 156 cases audited, none modified

## Governance

- [evidence-and-claims.md](evidence-and-claims.md) — every claim, its required artefact, its status
- [risk-register.md](risk-register.md) — R-* failure modes
- [open-decisions.md](open-decisions.md) — OD-* genuinely unsettled questions

## Decision records

[adr/](adr/) — ADR-001…ADR-022. Each carries Context, Problem, Options, Decision, Rationale,
Consequences and Rejected alternatives. See [adr/README.md](adr/README.md) for the index.

---

## Reading conventions

- **Pending evidence** means no artefact exists. The figure is not estimated, guessed or implied.
- **Refused claim** means an artefact would be required and either does not exist or contradicts
  the claim. A refused claim appears nowhere outside the ledger.
- Figures quoted from the sibling `llm-firewall` project carry their source report path.
- `T-*` are threats, `R-*` risks, `OD-*` open decisions, `ADR-*` decisions.
