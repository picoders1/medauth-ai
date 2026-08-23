# System Architecture

**Status:** Planning phase (Phase 0 not yet started). No application code exists.
**Authoritative for:** end-to-end flow, layer boundaries, invariants, failure semantics.

---

## 1. What this system is, and what it is not

MEDAUTH AI is a **decision-support** system. It assists a qualified human reviewer in evaluating a
prior-authorization request against authoritative coverage-policy criteria. It produces a
*recommendation with its evidence*, and a human makes the decision.

It is **not** an autonomous medical decision maker, a coverage determination engine, or a
substitute for clinical judgement. No output of this system is a coverage determination.

The system is designed with healthcare privacy and security considerations and is evaluated
exclusively using synthetic patient data. **No compliance claim is made.**

---

## 2. The governing invariant

> **NO EVIDENCE → NO DECISION**

Expanded into the states the system must be able to reach:

| Situation | Outcome |
|---|---|
| Insufficient clinical evidence | `NEEDS_INFO` |
| No applicable policy resolves | `NEEDS_INFO` → human. **Never a denial.** |
| Citation cannot be verified against stored source | `NO_DECISION` (guardrail failure) |
| Evidence conflicts across applicable policies | `HUMAN_REVIEW` |
| Abstention gate does not clear | `NEEDS_INFO` |
| Model call blocked or failed closed at the firewall | `HUMAN_REVIEW` |
| Sufficient, verified evidence | `APPROVE_RECOMMENDED` / `DENY_RECOMMENDED` |

Every one of these is a *first-class* terminal state with its own rendering in the reviewer
console and its own row in the audit trail. None is an error path.

---

## 3. The structural rule that makes the invariant enforceable

The brief's original pipeline had a "Necessity Reasoner" emit a recommendation. That is in direct
tension with "the LLM must never directly control the final decision state" — if the model emits
`APPROVE`, the model controls the decision, and every guardrail downstream is advisory.

**MEDAUTH resolves this structurally:**

> **Models produce per-criterion verdicts. Code produces the decision.**
>
> The tokens `APPROVE_RECOMMENDED` and `DENY_RECOMMENDED` do not exist in any model output
> schema anywhere in this system.

This mirrors the strongest idea in the sibling `llm-firewall` project (*"detectors detect; the
policy engine decides"*), and inherits its main benefit: the entire decision surface becomes a
**pure function**, exhaustively testable as a truth table with no model loaded and no network.

```
decide(criterion_verdicts, guardrail_result, resolution_result, config) -> Recommendation
```

Enforced, not merely documented:

| Boundary | Enforcement |
|---|---|
| `app/adjudication/` may not import `app/decision/` | AST test (`tests/unit/test_layer_boundaries.py`) |
| `Recommendation` is not importable inside `app/adjudication/` or `app/intake/` | Same AST test |
| `app/decision/` performs no I/O and makes no model call | Same AST test + pure-function signature |
| Every model output schema is a closed enum | Schema test asserting the enum members |

The AST test parses the source rather than importing it, so a violation is caught even if the
offending module is never executed.

---

## 4. End-to-end flow

```
                        Clinical case  (synthetic only)
                                  │
   ┌──────────────────────────────▼──────────────────────────────────┐
   │ 1. INTAKE                                              [model]   │
   │    Extract diagnoses, procedures, codes, clinical facts.         │
   │    Every fact carries a source span into the note.               │
   │    ✗ Prohibited: any reference to coverage, policy, or outcome.  │
   └──────────────────────────────┬──────────────────────────────────┘
                                  ▼
   ┌─────────────────────────────────────────────────────────────────┐
   │ 2. POLICY RESOLUTION                          [deterministic]    │
   │    (procedure code, diagnosis codes, jurisdiction, date of       │
   │     service) ──SQL──▶ applicable policy VERSIONS                 │
   │    No embeddings. No model. Reproducible.                        │
   │    0 resolved  → NEEDS_INFO                                      │
   │    conflicting → HUMAN_REVIEW                                    │
   └──────────────────────────────┬──────────────────────────────────┘
                                  ▼
   ┌─────────────────────────────────────────────────────────────────┐
   │ 3. EVIDENCE RETRIEVAL          [local models, no firewall]       │
   │    Scoped to the resolved policy versions ONLY.                  │
   │    pgvector ANN → metadata + temporal filter → cross-encoder     │
   │    rerank → evidence set with full citation metadata.            │
   └──────────────────────────────┬──────────────────────────────────┘
                                  ▼
   ┌─────────────────────────────────────────────────────────────────┐
   │ 4. PER-CRITERION ADJUDICATION            [model, one per node]   │
   │    For each criterion in the policy's criteria tree:             │
   │      verdict ∈ {SATISFIED, NOT_SATISFIED,                        │
   │                 INSUFFICIENT_EVIDENCE, NOT_APPLICABLE}           │
   │      + citations [(chunk_id, exact quote), …]                    │
   │      + referenced intake fact ids                                │
   │    ✗ No case-level outcome exists in the schema.                 │
   │    ✗ Retrieved text is DATA, never instructions.                 │
   └──────────────────────────────┬──────────────────────────────────┘
                                  ▼
   ┌─────────────────────────────────────────────────────────────────┐
   │ 5. GUARDRAIL                                  [deterministic]    │
   │    · Span-verify every quote against the stored chunk            │
   │    · Validate every citation's metadata resolves                 │
   │    · Check fact ids exist and were produced by intake            │
   │    · Detect contradictions between verdicts                      │
   │    · Flag claims with no supporting citation                     │
   │    Any unverifiable citation ⇒ NO_DECISION.                      │
   └──────────────────────────────┬──────────────────────────────────┘
                                  ▼
   ┌─────────────────────────────────────────────────────────────────┐
   │ 6. DECISION ENGINE                        [pure function]        │
   │    Aggregate verdicts by the decision table (§5)                 │
   │    then apply the abstention gate on deterministic features.     │
   └──────────────────────────────┬──────────────────────────────────┘
                                  ▼
   APPROVE_RECOMMENDED · DENY_RECOMMENDED · NEEDS_INFO
   · HUMAN_REVIEW · NO_DECISION
                                  ▼
   ┌─────────────────────────────────────────────────────────────────┐
   │ 7. HUMAN REVIEW  (Next.js console, :3100)                        │
   │    Inspect case, policy, criteria, citations, evidence mapping.  │
   │    Approve · deny · request info · override (reason required).   │
   └──────────────────────────────┬──────────────────────────────────┘
                                  ▼
   ┌─────────────────────────────────────────────────────────────────┐
   │ 8. AUDIT TRAIL  — append-only, no UPDATE/DELETE path in the app  │
   └─────────────────────────────────────────────────────────────────┘
```

Steps 1 and 4 are the **only** steps that call a model. Steps 2, 5, 6 are deterministic. Step 3
uses local encoder models but no generative model and no network.

---

## 5. The decision table

Evaluated **in order**; the first matching row wins. This ordering is itself a safety property —
in particular, "no policy" is checked before any denial can be reached.

| # | Condition | Outcome |
|---|---|---|
| 1 | Policy resolution returned zero applicable versions | `NEEDS_INFO` |
| 2 | Policy resolution returned versions that conflict | `HUMAN_REVIEW` |
| 3 | Any citation failed span or metadata validation | `NO_DECISION` |
| 4 | Any model call was blocked (403) or failed closed (503) | `HUMAN_REVIEW` |
| 5 | Verdicts contradict each other | `HUMAN_REVIEW` |
| 6 | Any **required** criterion is `INSUFFICIENT_EVIDENCE` | `NEEDS_INFO` + missing-evidence list |
| 7 | Any **exclusion** criterion is `SATISFIED` with valid evidence | `DENY_RECOMMENDED` |
| 8 | Any **required** criterion is `NOT_SATISFIED` with valid evidence | `DENY_RECOMMENDED` |
| 9 | All required criteria `SATISFIED`, no exclusion `SATISFIED` | `APPROVE_RECOMMENDED` |
| 10 | Otherwise | `HUMAN_REVIEW` |

Row 10 exists so the function is total. A case reaching it is a defect signal and is counted.

The abstention gate then runs on rows 7, 8 and 9 only. It can **downgrade** a recommendation to
`NEEDS_INFO`; it can never upgrade one. See
[decision-and-abstention.md](decision-and-abstention.md).

### Why denial is treated asymmetrically

A wrong approval costs money. A wrong denial withholds care from a patient. These are not
symmetric errors and must not be averaged into a single quality number.

- Denial requires **valid, span-verified evidence of non-satisfaction** — never the mere absence
  of evidence of satisfaction (that is row 6, `NEEDS_INFO`).
- Denial always routes to a human; there is no configuration in which a denial recommendation is
  actionable without review.
- Denial precision is reported **separately**, with its own denominator and interval, never folded
  into macro-F1 alone. See [evaluation-strategy.md](../evaluation/evaluation-strategy.md).

### Why "no applicable policy" is not a denial

For Medicare, the absence of an applicable NCD or LCD frequently means the item is left to
contractor discretion or adjudicated case-by-case — it does **not** mean non-coverage. A system
that mapped "I found no policy" to `DENY` would be wrong as a matter of domain fact, and would
fail in the direction that harms patients. Row 1 exists to make that impossible, and is asserted
by a dedicated test.

---

## 6. Layers and dependency direction

```
   app/api ──────────────┐
   app/graph ────────────┤        (orchestration; thin)
                         ▼
   app/intake  app/policy  app/retrieval  app/adjudication   (domain)
                         │
                         ▼
   app/guardrail ──▶ app/decision                            (pure)
                         │
                         ▼
   app/audit  app/database  app/observability  app/llm       (infrastructure)
                         │
                         ▼
                     app/core                                (types only)
```

Rules, all AST-enforced:

1. `app/core` imports nothing from `app/`.
2. `app/decision` imports only `app/core`. No I/O, no model, no database.
3. `app/adjudication` and `app/intake` may not import `app/decision`.
4. Domain packages may not import `app/graph` or `app/api`.
5. LangGraph appears **only** in `app/graph`. No domain module imports `langgraph`.

Rule 5 is the reason `app/graph/` exists as a separate thin package rather than the brief's
`app/agents/`: the orchestration framework is an implementation detail that should be replaceable,
and every domain step must be callable and testable as a plain async function without constructing
a graph. See [ADR-002](../adr/ADR-002-agent-orchestration.md).

---

## 7. Failure semantics

The system fails **closed**, and "closed" here means *toward the human*, not toward a denial.

| Failure | Behaviour |
|---|---|
| Firewall returns `403` (request blocked) | Not retried. Case → `HUMAN_REVIEW`, block category recorded. |
| Firewall returns `503 detector_failure` | Not retried past `MEDAUTH_LLM_MAX_ATTEMPTS`. Case → `HUMAN_REVIEW`. |
| Firewall unreachable | Case → `HUMAN_REVIEW`. Readiness reports the dependency. |
| Model returns unparseable / schema-invalid output | Bounded repair attempts, then that criterion becomes `INSUFFICIENT_EVIDENCE`. |
| A single criterion adjudication fails | That criterion is `INSUFFICIENT_EVIDENCE`; the case is not abandoned. |
| Retrieval returns zero chunks for a criterion | That criterion is `INSUFFICIENT_EVIDENCE`. |
| Database unreachable during a case | Request fails. No partial recommendation is returned. |
| Audit write fails while `MEDAUTH_AUDIT_REQUIRED=true` | Request fails. **A recommendation that cannot be audited is not issued.** |

That last row is a deliberate divergence from the firewall's ADR-029, which moved the audit write
off the request path and drops under load. The firewall's audit records a security decision that
has already been enforced; MEDAUTH's audit records the *provenance of a clinical recommendation*,
which is the artefact a reviewer will later be asked to justify. An unauditable recommendation has
no value here, so MEDAUTH pays the latency instead. Recorded as a consequence in
[ADR-013](../adr/ADR-013-audit-architecture.md).

---

## 8. Trust boundaries

```
  ┌─ untrusted ─────────────────────────────────────────────────┐
  │  clinical note text        (may contain injected content)   │
  │  retrieved CMS policy text (may contain poisoned content)   │
  │  reviewer-supplied free text (override reasons)             │
  └──────────────────────────────────────────────────────────────┘
  ┌─ trusted ────────────────────────────────────────────────────┐
  │  prompt templates (versioned, in-repo)                       │
  │  criteria trees   (ingest-time, human-reviewed)              │
  │  decision policy YAML (versioned, secret-free by construction)│
  │  code                                                        │
  └──────────────────────────────────────────────────────────────┘
```

**Retrieved policy text is data, not instruction.** This is the single most important security
property of a RAG system in this domain, and it is *not* delegated to the firewall — see §9.

---

## 9. Why the firewall is necessary but not sufficient

MEDAUTH routes every chat completion through the sibling `llm-firewall`
(`http://localhost:8005/v1`). That gives it: caller-turn injection screening, PII redaction,
upstream credential isolation, fail-closed detector semantics, rate limiting, and an independent
audit of every model call.

It does **not** give MEDAUTH protection against poisoned retrieved policy text. The firewall's own
committed evidence says so explicitly:

| Firewall measurement | Value | Source |
|---|---|---|
| Indirect-injection recall | 0.1423 (n=520) | `eval/results/20260817T130736Z__indirect-delivery-shape/report.md` |
| Recall on *planted* content vs *user-requested* | 0.0938 (n=480) vs 0.7250 (n=40) | same report |
| "The firewall protects RAG applications" | **claim refused** | `docs/22-evidence-and-claims.md` |

The detector classifies the user's turn, not retrieved content. MEDAUTH's corpus *is* retrieved
content. Therefore **indirect-injection containment is MEDAUTH's own architectural
responsibility**, and it is achieved structurally rather than by detection:

1. **Fenced delivery.** Retrieved text is passed in a delimited data block with explicit
   non-instruction framing. It is never concatenated into the system prompt.
2. **Closed schemas.** A successful injection cannot emit a decision token, because no decision
   token exists in the adjudication schema (§3).
3. **Span-verified quotes.** Every claim must quote stored text exactly. Injected instructions
   cannot forge a quote that validates.
4. **Code computes the decision.** Steering the model changes verdicts, not the outcome function.
5. **Corpus integrity.** Chunk content hashes are recorded at ingest; drift is detectable.
6. **Provenance signalling.** MEDAUTH marks retrieved content as untrusted when calling the
   firewall (its ADR-017 capability). This ships **off and uncalibrated** there (OD-3), so it is
   defence-in-depth, **not** a control MEDAUTH relies on or claims.

Full detail: [llm-firewall-integration.md](../security/llm-firewall-integration.md),
[threat-model.md](../security/threat-model.md), [ADR-016](../adr/ADR-016-llm-firewall-integration.md).

---

## 10. Deployment topology

```
   Next.js reviewer console  :3100
             │
             ▼
   MEDAUTH API (FastAPI)     :8010
        │            │
        │            └──▶ PostgreSQL 16 + pgvector   :5435
        │                  (policies, chunks, cases, verdicts, audit)
        ▼
   llm-firewall              :8005/v1        ← existing, separately deployed
        │
        ▼
   OpenAI-compatible provider   ← set by MEDAUTH_LLM_BASE_URL / MEDAUTH_LLM_MODEL
```

Ports avoid those already bound on the reference machine (3000, 5000, 5433, 5434, 5678, 8005,
8006, 8080–8082, 8089, 9001, 9004, 9005, 9091). Local encoder models (embedding, reranker) run
in-process in the API and do not traverse the firewall — the firewall exposes no `/v1/embeddings`,
and inspecting a policy-corpus embedding request would serve no security purpose.

Deployment detail and the Kubernetes position: [ADR-019](../adr/ADR-019-deployment.md).

---

## 11. What this document does not yet establish

Every performance, latency, accuracy and grounding number in this project is **pending evidence**.
No figure appears in this repository unless it is traceable to a committed artefact — the ledger of
permitted and refused claims is [evidence-and-claims.md](../evidence-and-claims.md). Open questions
are tracked in [open-decisions.md](../open-decisions.md); known failure modes in
[risk-register.md](../risk-register.md).
