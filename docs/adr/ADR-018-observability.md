# ADR-018: Observability

**Status:** Accepted · **Date:** 2026-08-23 · **Phase:** Planning

## Context

The system needs traces of multi-step case processing, per-step latency and token accounting, and
operational metrics — without logging clinical text. The brief names Langfuse.

The reference machine has ~16 GB free RAM with the sibling firewall stack already running.

## Problem

1. What is the always-on baseline?
2. Is Langfuse required, optional, or absent?
3. How is clinical text kept out of telemetry?

## Options

| # | Option | Assessment |
|---|---|---|
| A | Langfuse self-hosted, always on | Best LLM-native trace UI. **v3 needs ClickHouse + Redis + object storage** — four extra containers and several GB, for a system that is otherwise one API and one database. |
| B | **OTel + Prometheus baseline; Langfuse as an opt-in overlay** | Vendor-neutral, light, always available. Deep LLM trace inspection requires opting in. |
| C | Langfuse Cloud | Lightest to run, best UI. Sends trace metadata to a third party. |
| D | Structured logs only | Minimal. No distributed view of a multi-step case. |

## Decision

**Option B.**

| Layer | Choice |
|---|---|
| Logging | `structlog`, redaction enforced **at the sink** |
| Metrics | `prometheus-client`, `/metrics`; optional Prometheus overlay on **:9092** |
| Tracing | OpenTelemetry, OTLP, disabled by default |
| LLM traces | Langfuse **opt-in overlay** on **:3200** (OD deferred, never required) |

### Span structure

```
case
 ├── intake
 ├── resolve
 ├── retrieve ── embed · search · rerank
 ├── adjudicate ── one span per criterion
 ├── guardrail
 └── finalize
```

### Privacy

- Spans carry **ids, counts and durations only** — never clinical text, never policy text, never
  prompts or completions.
- Metric labels are **closed sets** (outcome, step, model, error kind). No label is derived from
  user input, since a label keyed on something an attacker chooses is an unbounded-cardinality
  problem with a privacy problem attached.
- `MEDAUTH_CLINICAL_TEXT_LOGGING=off`; `full` is refused in production, in code.
- Redaction at the sink rather than per call site, so a new log statement is safe by default.

### Metrics catalogue

Cases by outcome · abstention rate · citation validity rate · guardrail failures by kind · firewall
`403`/`503` counts · schema-repair rate · latency histograms per step · token counters ·
`oldest_audit_row_age_seconds` · resolution outcomes (resolved / none / conflicting).

Configuration is **exported as metrics** (thresholds, retention period, queue sizes) so an alert rule
can never hardcode a value the application owns.

### Alert discipline

Two severities: `critical` (wake someone) and `warning` (a ticket). No third level. Every rule has a
runbook entry, and a test fails if a rule has no entry, an entry has no rule, or a rule names a
metric the registry does not export.

## Rationale

**The baseline must not require infrastructure heavier than the system.** Langfuse v3 self-hosted
would add ClickHouse, Redis and object storage to a stack that is otherwise one API container and
one database. On a machine already running the firewall stack, that makes observability something
you turn on for a session rather than something that is simply always true. Requiring it would make
the system harder to operate than to build.

**OTel is vendor-neutral**, so the trace backend is a deployment choice rather than an architectural
commitment — Langfuse, Jaeger, Tempo or none, without touching instrumentation.

**Langfuse remains genuinely useful** for token-level cost attribution and prompt-version comparison
during evaluation runs, which is exactly when its weight is affordable. Hence an overlay.

**Cloud is rejected on principle rather than on this data.** Everything here is synthetic, so
sending metadata off-box would be harmless today — and the architecture must be correct for a real
deployment, where it would not be. Building the habit on synthetic data is how it survives into
production.

**Sink-level redaction over call-site discipline** because call-site discipline fails: the leak
arrives in a log line added six months later by someone who did not read this document.

**`/metrics` must be asserted as scrapeable, including its content type.** The sibling project
shipped `/metrics` that Prometheus could not scrape for seventeen phases because the content type
said OpenMetrics while the body was text format. Asserting the endpoint exists is not the same as
asserting it works.

## Consequences

**Positive.** Full case tracing with no mandatory heavy infrastructure. Vendor-neutral. Clinical text
cannot reach telemetry by construction. Metric cardinality is bounded. Alerts are tied to runbooks by
test.

**Negative.** Without Langfuse, LLM-specific trace inspection is less convenient. OTLP needs a
collector when enabled. Span attributes carrying only ids mean debugging often requires a database
join — the correct trade for a healthcare system.

**Neutral.** Cost tracking derives from token counters and a stated price basis rather than from a
vendor dashboard.

## Rejected alternatives

| Alternative | Rejected because |
|---|---|
| **A — Langfuse always on** | Four extra containers and several GB for a two-container system, on a machine already running the firewall stack. Observability that is expensive to run gets turned off. |
| **C — Langfuse Cloud** | Third-party egress of trace metadata. Harmless for synthetic data, wrong as a default for a healthcare architecture. |
| **D — logs only** | No distributed view of a multi-step case; per-criterion latency and token attribution would be manual. |
| **Custom tracing** | Reinvents OpenTelemetry with fewer integrations and no ecosystem. |
