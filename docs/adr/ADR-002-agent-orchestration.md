# ADR-002: Agent Orchestration — LangGraph, Confined to `app/graph/`

**Status:** Accepted · **Date:** 2026-08-23 · **Phase:** Planning

## Context

MEDAUTH's pipeline has six stages, of which two call a model, one fans out over criteria, and
several branch to terminal states early (no policy resolved, guardrail failure, firewall block).
State must be carried through and must be reconstructable afterwards for audit.

The brief specifies LangGraph and an `app/agents/` package.

## Problem

Two questions, often conflated:

1. What orchestrates the stages?
2. **How much of the system knows about the orchestrator?**

The second matters more. A framework that reaches into domain logic means every step needs the
framework to be tested, the framework's state model becomes the domain model, and replacing it
later means rewriting the application.

## Options

| # | Option | Assessment |
|---|---|---|
| A | Plain async Python — explicit calls and conditionals | No dependency; total control. Retry, fan-out, state threading and tracing hand-rolled. |
| B | LangGraph, with domain logic inside node functions | Idiomatic; every step becomes framework-coupled. |
| C | **LangGraph confined to `app/graph/`, nodes are thin adapters** | Framework benefits; domain stays plain async functions. |
| D | A workflow engine (Temporal, Prefect) | Durable execution, retries, replay. Substantial operational weight for a request that completes in seconds. |

## Decision

**Option C.**

- LangGraph wires the stages and lives **only** in `app/graph/`. No domain module imports
  `langgraph`; an AST test enforces it.
- Each node is a thin adapter: read from `CaseState`, call a plain async domain function, write one
  key back.
- `CaseState` is **append-only within a run** — a node adds its own key and never mutates another's.
- Every domain step is independently callable and testable without constructing a graph.
- The package is named `app/graph/`, not `app/agents/`; domain packages are named for what they do
  (`intake`, `policy`, `retrieval`, `adjudication`, `guardrail`, `decision`).

## Rationale

**LangGraph earns its place on three specifics**, not on being the default choice: conditional
edges express the early-termination branches (rows 1–4 of the decision table) directly; the
fan-out/fan-in over criteria with bounded concurrency is built in; and the state model matches the
audit requirement, since an append-only state *is* a reconstructable trail.

**Confinement is the actual decision.** With rule 5 of the layer boundaries, `app/adjudication` is
a module with a function that takes a criterion and evidence and returns a verdict. It can be unit
tested with a stub client, in milliseconds, with no graph. If LangGraph is later replaced, one
package changes.

**Naming matters more than it appears.** "Agent" is an orchestration concept. Naming a package
`app/agents/intake.py` invites intake to grow orchestration concerns — retries, state, routing —
until the domain logic cannot be extracted. Naming it `app/intake/` keeps the question "what does
this module do?" answerable without reference to a framework.

## Consequences

**Positive.** Domain logic is framework-independent and fast to test. Fan-out and conditional
routing are declarative. Append-only state feeds the audit trail directly. The framework is
replaceable.

**Negative.** An adapter layer that a direct LangGraph implementation would not need. Two places to
look when tracing a call — though the split is by kind, not arbitrary. LangGraph is a young
dependency with API churn; confinement bounds the blast radius, which is part of why confinement
was chosen.

**Neutral.** The system is "agentic" in a specific and defensible sense: independent steps with
narrow contracts and conditional routing. It is not agentic in the sense of a model choosing its
own tools and control flow — deliberately, since in this domain that would place the model back in
control of the outcome.

## Rejected alternatives

| Alternative | Rejected because |
|---|---|
| **A — plain async Python** | Viable, and reconsidered if LangGraph proves unstable. Rejected for now because the fan-out over criteria and conditional termination are exactly what the framework does well, and hand-rolling them adds code without adding clarity. |
| **B — domain logic inside nodes** | Couples every step to the framework, makes unit testing require a graph, and makes replacement a rewrite. |
| **D — Temporal / Prefect** | Durable execution solves a problem this system does not have: a case completes in seconds and, on failure, is simply re-run. Adds a server, a worker model and an operational surface for no benefit here. |
| **CrewAI / AutoGen** | Conversational multi-agent frameworks built around agents negotiating in natural language. This system needs deterministic routing and typed hand-offs; agent-to-agent conversation would add an unverifiable channel between steps. |
