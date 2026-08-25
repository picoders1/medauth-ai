# Parallel engineering track — what actually exists

**Assessed at:** 2026-08-26 · **Baseline:** `5976178`, working tree clean ·
**Scope:** everything the runtime needs that does not depend on R-86.

R-86 blocks *scoring*. It does not block the application, and this track exists to
make that separation real rather than asserted. What the inspection found is that the
separation is already sound at the boundary — and that the layer above it, the part a
reviewer or an auditor would actually touch, is largely absent.

---

## 1. The headline

Phases 0–22 built a **decision engine** and an **evaluation regime**, both to a high
standard. They did not build an **application**. There is no case, no persisted
recommendation, no reviewer, no audit row, and no endpoint that does anything.

`app/api/v1/` contains an `__init__.py` and nothing else. `app/audit/` contains an
`__init__.py` and nothing else.

That is not a criticism of the phases — the vertical slice was the right thing to
prove first, and it is proven. It is the honest statement of where the work now is.

## 2. Already complete — do not rebuild

| area | state | evidence |
|---|---|---|
| Decision engine | **VERIFIED** | pure `decide()`, 16 rules, AST-enforced layer boundaries, truth-table suite |
| Applicability resolution | **VERIFIED** | six total states, runtime stage before intake, 4 mutations |
| Policy identity and scope | **VERIFIED** | `(policy_type, policy_id, version)`; `RetrievalScope` cannot be constructed empty or mislabelled; no "latest" fallback |
| Evidence/citation contract | **VERIFIED** | span verification, metadata joined from the database not the model, `NO_DECISION` on failure |
| LLM gateway boundary | **VERIFIED** | `FirewallGateway`, no provider SDK in domain code, `403` never retried |
| Provider failure taxonomy | **VERIFIED** | 11 kinds × 5 attributions, accuracy-blind by construction, `MODEL_WRONG` exists nowhere |
| Structured-output containment | **VERIFIED** | closed schemas, `harden_schema`, bounded repair that cannot invent evidence |
| Log redaction | **VERIFIED** | structlog processor at the sink, not per call site |
| Official-evaluation gate | **VERIFIED** | sole authority, no override parameter, wired into all three artefact writers |
| Dataset boundary | **VERIFIED** | `eval/schema.py`, refusal by absence, undeclared budget is zero |
| OD-19 review workflow | **VERIFIED** | reviewer identity + qualification + rationale required; no code path fabricates approval |
| Container + CI | **PARTIALLY VERIFIED** | `deploy/docker/api.Dockerfile`, `compose.yaml`, CI runs lint/type/test/mutation/secret-scan |

## 3. Missing — and one of them is a Critical risk's stated mitigation

### The audit trail does not exist

**R-16** (audit tampering, **Critical**) records its mitigation as:

> Append-only grants; retention deletes by `created_at` and nothing else, asserted
> against the compiled SQL.

There is no audit table. No grants, no retention, no compiled SQL to assert against.
`AuditEvent` exists as an in-memory Pydantic contract, is produced correctly by the
slice, and is **discarded when the run returns**.

**R-17** (clinical text in audit payloads, High) records "schema-level assertion that
no column holds a prompt or completion". There is no schema to assert over.

This is the R-103 pattern again — a control that is documented, believed, and absent —
and it is the third time. It is the single most important gap here, because every
other item below wants to write to it.

### There is no case

No table, no identity, no lifecycle, no persisted recommendation. `SliceRunner.run()`
returns a `SliceOutcome` to its caller and nothing keeps it. A submitted case cannot be
retrieved, a recommendation cannot be shown to anyone, and no disposition survives the
process.

### There is no clinical human review

`app/review/` is the **OD-19 criteria-transcription** workflow — whether the
transcribed criteria are the right ones. It is good, and it is a different thing.
Nothing lets a reviewer see a case, its evidence and its recommendation, and act.

`APPROVE` / `DENY` / `REQUEST_INFO` / `OVERRIDE` appear nowhere in `app/review/`.

### There are no endpoints

`/health`, `/ready`, `/metrics`. That is the entire API. Nothing to submit a case,
retrieve one, fetch evidence, request review, or read an audit trail.

### Observability stops at logs

`langfuse` is a dependency in `pyproject.toml` and is imported by nothing. There is no
tracing abstraction, so there is currently no way to see a case's stages, latencies or
token usage other than by reading structured logs.

## 4. Blocked by R-86 — and only these

- the official end-to-end evaluation (`phase16-evaluation-001`)
- any decision-quality, criterion-quality or grounding metric
- gold_v2's single scoring

**Nothing else.** No runtime capability below depends on it, and the point of Part B is
to keep it that way structurally rather than by intention.

## 5. Safe to implement now, in dependency order

1. **Audit persistence, append-only** — closes R-16/R-17's stated mitigation. Everything
   else writes to it, so it is first.
2. **Case lifecycle persistence** — case, input digest, applicability, recommendation,
   disposition.
3. **Human review on top of both** — append-only events; an override never erases the
   AI recommendation, it records a decision beside it.
4. **API v1** over those three.
5. **Tracing abstraction** — configurable, no-op when disabled.
6. **Deployment hardening** — non-root, read-only rootfs, resource limits.

## 6. What this track deliberately does not touch

Model, prompt, schema, temperature, ceiling, request shape, R-86 threshold, gold_v1,
gold_v2, retrieval_eval_v4, frozen manifests, retrieval configuration. No official
evaluation. No new production model. No clinical validation claim.

## 7. Honest scope note

Items 1–4 above are a substantial body of work with real schema and safety
consequences. This track implements them in that order and reports precisely how far
it got, rather than sketching all six thinly. Where an item is incomplete, the final
report says so and names what is missing — a half-built audit trail reported as
"complete" would be worse than none, because the thing it exists to provide is
trust in the record.
