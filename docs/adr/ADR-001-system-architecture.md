# ADR-001: System Architecture and the Decision-Support Boundary

**Status:** Accepted · **Date:** 2026-08-23 · **Phase:** Planning

## Context

MEDAUTH AI evaluates prior-authorization requests against coverage-policy criteria. The domain has
a specific and well-documented harm pattern: automated systems that issue denials at scale, faster
than humans can meaningfully review them, on grounds that are frequently procedural rather than
clinical.

Any architecture here is therefore not only a technical choice. It determines whether the system
*can* cause that harm, independently of how carefully it is operated.

## Problem

Two problems, and the second is the one that decides the architecture.

1. How should the pipeline be decomposed so each stage is narrow, testable and auditable?
2. **What structurally prevents the language model from determining the outcome?** The brief states
   the invariant "the LLM must never directly control the final decision state" — but its own
   proposed pipeline has a *Necessity Reasoner* emitting a recommendation. If the model emits
   `APPROVE`, the model decides, and every downstream guardrail is advisory.

## Options

| # | Option | Assessment |
|---|---|---|
| A | Single reasoning call producing a decision with citations | Simplest. The model decides. Every safety property becomes a post-hoc filter over a decision already made. |
| B | Multi-agent pipeline, final agent emits the recommendation (the brief) | Better separation, but the invariant is still a convention: the last agent decides. |
| C | Model emits per-criterion verdicts; **deterministic code computes the decision** | More moving parts. The invariant becomes structural and testable. |
| D | Fully rule-based, no model | Maximally safe, cannot read a clinical narrative. Not a solution to this problem. |

## Decision

**Option C.**

1. Models produce **per-criterion verdicts only**. The tokens `APPROVE_RECOMMENDED` and
   `DENY_RECOMMENDED` do not exist in any model output schema anywhere in this system.
2. A pure function computes the recommendation:
   `decide(verdicts, guardrail, resolution, criteria_tree, config) -> Recommendation`.
3. Model-bearing steps are reduced from four to **two**: intake, and per-criterion adjudication.
   Policy resolution, guardrail validation and the decision are deterministic.
4. The boundary is enforced by an AST test that parses source rather than importing it, so a
   violation is caught even if the offending module never runs.
5. Every terminal state — including `NEEDS_INFO`, `HUMAN_REVIEW` and `NO_DECISION` — is
   first-class, not an error path.

## Rationale

**The invariant becomes checkable.** "The LLM does not decide" stops being a claim about intent and
becomes a property a test asserts: no decision token in any schema, and no import path from
adjudication to the decision module.

**The decision surface becomes a pure function.** No I/O, no clock, no randomness. It is
exhaustively testable as a truth table with no model loaded and no network — which is the only way
to gain real confidence in the branch that matters most: the one that produces a denial.

**Injection resistance follows for free.** A successful prompt injection can change a verdict. It
cannot produce a decision token, because none exists in the schema it is filling. Given that the
firewall's measured indirect-injection recall is 0.1423, a structural property is worth considerably
more here than a detective one.

**Per-criterion granularity is better reasoning, not just better plumbing.** Each call sees one
criterion and its evidence, bounding both the context and the hallucination surface, and produces
traceability a single large call cannot: a reviewer sees which criterion failed and why, not a
paragraph of prose about the case.

This borrows directly from the sibling `llm-firewall` project, whose strongest structural idea is
*detectors detect; the policy engine decides*. The same shape applies, with the same benefit.

## Consequences

**Positive.** The safety invariant is enforced rather than described. The decision is testable
without a model. Denial logic is inspectable line by line. Injection cannot directly produce an
outcome. Recommendations are reproducible given the same inputs.

**Negative.** More components. The criteria tree becomes a hard dependency — no tree, no
adjudication (ADR-007). Per-criterion calls cost more tokens than one combined call, quantified in
Phase 4. Aggregation logic in code must handle combinations a model would have papered over, which
is more work and is the point.

**Neutral.** The system can no longer produce a "confidence-weighted holistic judgement". It
produces a decision derived from stated criteria. In this domain that is a feature.

## Rejected alternatives

| Alternative | Rejected because |
|---|---|
| **A — single reasoning call** | The model decides. Guardrails become filters over an existing decision, and the invariant is unenforceable. |
| **B — final agent emits the recommendation** | The invariant stays a convention, and conventions decay under maintenance pressure. There is no test that can catch its violation. |
| **D — fully rule-based** | Cannot extract structured facts from a clinical narrative, which is the actual difficulty. |
| **LLM-as-judge over the final decision** | Adds a second model whose output is also unverifiable, and creates the impression of independent verification without the substance. |
