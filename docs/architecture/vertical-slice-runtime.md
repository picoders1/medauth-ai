# Vertical Slice — Runtime

How the pieces are wired, and which seams exist so they can be swapped.

---

## Ports, and why

```
SliceRunner ── gateway:   ModelGateway  (protocol)  → firewall → provider
            └─ retrieval: RetrievalPort (protocol)  → pgvector | fixture corpus
```

Two seams, for two different reasons.

**`ModelGateway`** so that a direct `httpx` call in a domain package is a boundary
violation rather than a shortcut nobody notices. It existed before any caller did.

**`RetrievalPort`** so the slice runs identically against pgvector and a fixture
corpus. The scope is the **port's** responsibility: whatever implements it must
already have applied the policy type, resolved version ids and date of service. A
slice that could widen its own scope would make every containment argument
conditional on a caller.

## What is injected, and what is refused

| | |
|---|---|
| `identity` | supplied. The runner never re-resolves a case's policy |
| `semantics` | supplied and **required** by `decide()`. Reading the inventory is I/O; a runner that fetched its own could be handed a case whose policy it then re-derived |
| `criteria` | supplied. An empty tuple is **refused at construction** — a slice with no criteria would adjudicate nothing and report success for it |
| `clock` | injected, so timings are testable without sleeping |

## `run()` never raises on a case

Every failure becomes an outcome with an abstention record carrying a reason, a
remedy and an audit event. A pipeline that raised would push routing onto its caller,
and the caller is the layer least equipped to decide what a blocked model call means
for a patient's request.

The one thing that *does* raise is a malformed **construction** — no criteria. That
is a programming error, not a case, and failing loudly at wiring time is right.

## Prompts are versioned files

`prompts/intake.v1.md`, `prompts/adjudication.v1.md`. The ids
(`intake.v1`, `adjudication.v1`) travel on every `ModelRequest` and into the
`EvidenceMapping.provenance`. **Editing a template in place without incrementing the
version breaks audit reproducibility and is a defect.**

## Not built, deliberately

No LangGraph. No agent loop. No retry policy beyond the gateway's own. No reviewer
UI. One case, one pass, one policy version — which is what makes the nine scenarios
mean something.

`app/graph` currently contains a plain orchestrator and no graph library. That is
fine: the boundary rule says `langgraph` may be imported *only* here, not that it
must be.
