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
| [architecture/phase9-transition.md](architecture/phase9-transition.md) | **Where the repository stands: engineering complete, production `BLOCKED` on one external decision** |

## Architecture

- [system-architecture.md](architecture/system-architecture.md) — flow, invariants, trust boundaries
- [agent-architecture.md](architecture/agent-architecture.md) — step contracts and prohibitions
- [rag-architecture.md](architecture/rag-architecture.md) — corpus, resolution, retrieval, citations
- [data-architecture.md](architecture/data-architecture.md) — schema, classification, retention
- [decision-and-abstention.md](architecture/decision-and-abstention.md) — decision engine, gate, calibration
- [repository-structure.md](architecture/repository-structure.md) — layout, dependency rules, ports
- [vertical-slice-admissibility.md](architecture/vertical-slice-admissibility.md) — the eleven-condition gate; **BLOCKED**
- [first-vertical-slice.md](architecture/first-vertical-slice.md) — the entry condition, stage by stage
- [vertical-slice-contract.md](architecture/vertical-slice-contract.md) — the contract the first AI slice must satisfy, written before the agents
- [first-vertical-slice-contract.md](architecture/first-vertical-slice-contract.md) — **the consolidated contract**: the gate, eight stages, nine abstention states, eight fixtures
- [intake-contract.md](architecture/intake-contract.md) — extraction only; spans required, no outcome vocabulary
- [evidence-mapping-contract.md](architecture/evidence-mapping-contract.md) — an assertion must cite both a fact and a span
- [llm-assessment-contract.md](architecture/llm-assessment-contract.md) — three states, and what is absent from them
- [llm-gateway-contract.md](architecture/llm-gateway-contract.md) — the seam; a 403 is never retried
- [phase9-transition.md](architecture/phase9-transition.md) — what Phase 9 built, and the one thing it could not
- [first-ai-vertical-slice.md](architecture/first-ai-vertical-slice.md) — **implemented and running**: one policy, nine scenarios, zero model calls
- [vertical-slice-runtime.md](architecture/vertical-slice-runtime.md) — ports, injection, what raises and what abstains
- [phase12-preconditions.md](architecture/phase12-preconditions.md) — **what an independent audit found, and what closed it**
- [phase12-model-activation.md](architecture/phase12-model-activation.md) — **the first live model call, and the three defects it exposed**
- [phase13-guardrail-closure.md](architecture/phase13-guardrail-closure.md) — **row 5 made reachable, evidence ids hardened, retrieval scored once**
- [phase15-applicability-resolution.md](architecture/phase15-applicability-resolution.md) — **R-93 closed: which policy applies is now resolved, not asserted**
- [model-gateway.md](architecture/model-gateway.md) — the seam a model call crosses; interface only
- [implementation-roadmap.md](architecture/implementation-roadmap.md) — Phases 0–9

## Decision logic

- [decision/policy-logic-model.md](decision/policy-logic-model.md) — how a policy states its own rule; three-valued, seven nodes, and where the safety ordering lives
- [decision/fail-closed-policy-semantics.md](decision/fail-closed-policy-semantics.md) — **R-59 closed.** Unverified semantics cannot adjudicate, and what that cost
- [decision/policy-logic-inventory.md](decision/policy-logic-inventory.md) — every policy version's logic form and what remains unresolved (**4 of 8 are REVIEW_REQUIRED**)

## Coverage determinations

- [coverage/ncd-architecture.md](coverage/ncd-architecture.md) — the NCD layer, and why regulation and coverage never merge
- [coverage/ncd-data-model.md](coverage/ncd-data-model.md) — what CMS provides, what is stored, what is not invented
- [coverage/ncd-status-model.md](coverage/ncd-status-model.md) — what a determination establishes, and on whose authority
- [coverage/ncd-review-workflow.md](coverage/ncd-review-workflow.md) — the two NCD review queues; nothing pre-filled
- [coverage/ncd-code-linkage.md](coverage/ncd-code-linkage.md) — three authority levels; **no link is authoritative**
- [coverage/ncd-temporal-resolution.md](coverage/ncd-temporal-resolution.md) — version windows, and when the honest answer is *none*

## Security

- [security/phase12-model-security.md](security/phase12-model-security.md) — seven attacks against a real model, and which layer stopped each
- [security/first-slice-security.md](security/first-slice-security.md) — **containment that holds at detection recall zero**
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
- [data/od19-review-package.md](data/od19-review-package.md) — the 246 provisions awaiting qualified review, ranked by consequence
- [data/od19-review-workflow.md](data/od19-review-workflow.md) — the states a provision moves through, and why none of them moves without a person
- [data/410-32-b3-review.md](data/410-32-b3-review.md) — the transcription, and the question it leaves for a reviewer
- [data/vertical-slice-admissibility.md](data/vertical-slice-admissibility.md) — seven conditions; **six pass, one does not**
- [data/policy-identity.md](data/policy-identity.md) — **R-62 closed.** Policy type participates in identity
- [data/policy-dependency-model.md](data/policy-dependency-model.md) — criteria that cannot be adjudicated on their own evidence (R-51)

## Evaluation

- [evaluation/evaluation-strategy.md](evaluation/evaluation-strategy.md) — metrics, splits, leakage controls, failure families
- [evaluation/gold-set-labeling-protocol.md](evaluation/gold-set-labeling-protocol.md) — how a case gets its label, and what that label is worth
- [evaluation/data-partitioning.md](evaluation/data-partitioning.md) — development / validation / gold, and the leakage controls
- [evaluation/retrieval-dataset.md](evaluation/retrieval-dataset.md) — retrieval ground truth, measured apart from decision quality
- [evaluation/retrieval-evaluation-assessment.md](evaluation/retrieval-evaluation-assessment.md) — the set is **not difficult enough**, and why 1.0000 is not reassuring
- [evaluation/ground-truth-review-protocol.md](evaluation/ground-truth-review-protocol.md) — what a qualified reviewer must do, and what may be claimed after
- [evaluation/gold-set-audit.md](evaluation/gold-set-audit.md) — all 156 cases audited, none modified
- [evaluation/retrieval-evaluation-methodology.md](evaluation/retrieval-evaluation-methodology.md) — how a benchmark for this corpus is built and scored, and what it cannot support
- [evaluation/retrieval-evaluation-v2.md](evaluation/retrieval-evaluation-v2.md) — v2 results: discriminates at rank 1, saturates by rank 3
- [evaluation/gold-set-protection.md](evaluation/gold-set-protection.md) — what freezing gold_v1 means, and what would force a gold_v2
- [evaluation/retrieval-provenance-audit.md](evaluation/retrieval-provenance-audit.md) — six classifications across all three sets
- [evaluation/frozen-410-33-results.md](evaluation/frozen-410-33-results.md) — **the first controlled evaluation: 6/26, and the gap it found**. Sealed; `EVALUATION_NOT_INTERPRETABLE`
- [evaluation/phase15-410-33-results.md](evaluation/phase15-410-33-results.md) — **the same 26 cases, a different system: 8/26, zero unsafe decisions, still degraded**
- [evaluation/measurement-recovery.md](evaluation/measurement-recovery.md) — **Phase 16 in one page: what was restored, what was withdrawn, what is not ours**
- [evaluation/r86-provider-reliability.md](evaluation/r86-provider-reliability.md) — **two controlled experiments; the length hypothesis withdrawn, the real conjunction found**
- [evaluation/failure-taxonomy.md](evaluation/failure-taxonomy.md) — a bad answer is not a provider failure; 11 kinds, 4 attributions, 6 dispositions
- [evaluation/gold-v2-data-contract.md](evaluation/gold-v2-data-contract.md) — every fact needed to derive an outcome, in structured data
- [evaluation/gold-v2-migration.md](evaluation/gold-v2-migration.md) — all 156 cases audited; 18 fixed, 0 relabelled, gold_v1 untouched
- [evaluation/retrieval-v4.md](evaluation/retrieval-v4.md) — a provenance-clean benchmark and its baseline, not a winner
- [evaluation/phase16-experiment.md](evaluation/phase16-experiment.md) — **frozen, and deliberately not authorised to run**
- [evaluation/r86-gate-recheck.md](evaluation/r86-gate-recheck.md) — **identical conditions, identical result; the gate FAILS**
- [evaluation/phase16-official-run.md](evaluation/phase16-official-run.md) — **14 of 15 preconditions pass; the run did not happen**
- [evaluation/phase16-metrics.md](evaluation/phase16-metrics.md) — NOT PRODUCED, and why that is the correct entry
- [evaluation/phase16-failure-analysis.md](evaluation/phase16-failure-analysis.md) — one failure, and it is not a case
- [evaluation/od42-grounding-scope.md](evaluation/od42-grounding-scope.md) — what "grounding" may and may not mean here
- [evaluation/official-evaluation-gate.md](evaluation/official-evaluation-gate.md) — **the sole authorisation boundary; no override exists to pass**
- [evaluation/evaluation-hold.md](evaluation/evaluation-hold.md) — **what is frozen, and the one thing that lifts it**
- [operations/r86-provider-escalation.md](operations/r86-provider-escalation.md) — **the handoff: one question, and it is not answered here**
- [operations/r86-revalidation.md](operations/r86-revalidation.md) — the runbook for "they say it's fixed"
- [operations/r86-firewall-capture.md](operations/r86-firewall-capture.md) — **the proxy is exonerated**; two records of one hop, agreeing to the character
- [operations/r86-provider-attribution.md](operations/r86-provider-attribution.md) — `PROVIDER_SIDE`, and everything that is still `UNKNOWN`
- [operations/r86-provider-root-cause.md](operations/r86-provider-root-cause.md) — **the question is termination, not whitespace**; ten secondary questions and the evidence we need
- `data/escalations/r86-provider-package.md` — **the one document that leaves the building**; generated, self-contained, digests only
- [operations/r86-provider-remediation.md](operations/r86-provider-remediation.md) — what would close it, and what would only look like it
- [operations/r86-temperature-perturbation.md](operations/r86-temperature-perturbation.md) — one variable, six trials; **the trial that escaped still did not terminate**
- [evaluation/r86-closure-gate.md](evaluation/r86-closure-gate.md) — **the partial fix that would have passed**, and the rule that stops it
- [engineering/parallel-track-assessment.md](engineering/parallel-track-assessment.md) — what exists, what does not, and what R-86 actually blocks
- [architecture/audit-trail.md](architecture/audit-trail.md) — **append-only by trigger, because the grants were inert**
- [engineering/final-closure-audit.md](engineering/final-closure-audit.md) — **three controls this project documented and nobody called**, and what closing them did and did not buy
- [evaluation/retrieval-configuration-decision.md](evaluation/retrieval-configuration-decision.md) — **v3 scored once; no winner forced**
- [evaluation/first-slice-live-results.md](evaluation/first-slice-live-results.md) — **PROBE / SMOKE / MATRIX**, kept apart
- [evaluation/model-capability-evaluation.md](evaluation/model-capability-evaluation.md) — what the decoder does, scoped to the schema tested
- [evaluation/first-slice-evaluation.md](evaluation/first-slice-evaluation.md) — 9/9 on controlled fixtures, and everything it does **not** measure
- [evaluation/retrieval-benchmark-readiness.md](evaluation/retrieval-benchmark-readiness.md) — **NOT READY**, and why no result is manufactured
- [evaluation/evaluation-provenance.md](evaluation/evaluation-provenance.md) — every query proves its chain, or is classified
- [evaluation/410-61-evaluation-repair.md](evaluation/410-61-evaluation-repair.md) — `retrieval_eval_v3`, derived by provenance
- [evaluation/gold-v1-impact.md](evaluation/gold-v1-impact.md) — byte-identical; what resolving C03 would reach
- [evaluation/gold-v2-migration-plan.md](evaluation/gold-v2-migration-plan.md) — planned for all four outcomes; **creates nothing, edits nothing**
- [evaluation/gold-impact-analysis.md](evaluation/gold-impact-analysis.md) — what a review decision would reach, before it is made
- [evaluation/phase6-readiness.md](evaluation/phase6-readiness.md) — **one named blocker** stands before the first AI slice
- [evaluation/phase5-impact.md](evaluation/phase5-impact.md) — **gold_v1_impact.** Byte-identical, and half of it can no longer validate production

## Domain review

- [review/FOCUS-001.md](review/FOCUS-001.md) — **the one open question**, with its source excerpts and no recommendation
- [review/FOCUS-001-impact.md](review/FOCUS-001-impact.md) — what each possible answer costs, computed before any answer
- [review/OD-19-410.33.md](review/OD-19-410.33.md) — **the open question**: how 42 CFR 410.33's five criteria combine, and whether (a)(2) permits any declaration at all

The decision travels through `scripts/ingest_focus_decision.py`: two commands, because
submission and acceptance are two acts. Neither can be performed by this repository.

- [review/FOCUS-001-submission-instructions.md](review/FOCUS-001-submission-instructions.md) — how to record an answer, step by step
- [adr/ADR-026-single-party-decision-exemption.md](adr/ADR-026-single-party-decision-exemption.md) — **the independent-acceptance control, deliberately relaxed and marked**
- [adr/ADR-028-runtime-applicability-and-experiment-validity.md](adr/ADR-028-runtime-applicability-and-experiment-validity.md) — **applicability at runtime, and a validity rule fixed before the run**
- [adr/ADR-029-phase16-experiment-preregistration.md](adr/ADR-029-phase16-experiment-preregistration.md) — **the third experiment, pre-registered on gold_v2 and not executed**

## Escalations

- [escalations/R-86-unbounded-whitespace.md](escalations/R-86-unbounded-whitespace.md) — **grammar-constrained decoding that never terminates**; reproducible, and not ours to fix

## Governance

- [evidence-and-claims.md](evidence-and-claims.md) — every claim, its required artefact, its status
- [risk-register.md](risk-register.md) — R-* failure modes
- [open-decisions.md](open-decisions.md) — OD-* genuinely unsettled questions

## Decision records

[adr/](adr/) — ADR-001…ADR-025. Each carries Context, Problem, Options, Decision, Rationale,
Consequences and Rejected alternatives. See [adr/README.md](adr/README.md) for the index.

---

## Reading conventions

- **Pending evidence** means no artefact exists. The figure is not estimated, guessed or implied.
- **Refused claim** means an artefact would be required and either does not exist or contradicts
  the claim. A refused claim appears nowhere outside the ledger.
- Figures quoted from the sibling `llm-firewall` project carry their source report path.
- `T-*` are threats, `R-*` risks, `OD-*` open decisions, `ADR-*` decisions.
