# Agent Architecture

**Status:** Partially implemented. The slice runner under `app/graph` executes the pipeline
deterministically. **No LangGraph orchestration was built** — the phase that would have added it
was never reached, and nothing here should be read as describing a running agent graph.
**Authoritative for:** what each step may and may not do, graph state, retry and failure semantics.

---

## 1. Design rule: narrow responsibilities, and no agent where code will do

The brief's principle 7 — *do not use an agent where deterministic code is better* — is applied
literally. The original proposal had five agents (Intake, Retrieval, Evidence Mapping, Necessity
Reasoner, Reviewer/Guardrail). MEDAUTH has **two model-bearing steps** and three deterministic
ones.

| Original proposal | MEDAUTH | Why |
|---|---|---|
| Intake Agent | **Intake** (model) | Unchanged. Genuine extraction task. |
| Policy Retrieval Agent | **Policy resolution** (code) + **evidence retrieval** (local encoders) | Choosing *which* policy applies is a lookup on code + jurisdiction + date, not a semantic judgement. See §4. |
| Evidence Mapping Agent | merged | Same cognitive act as necessity reasoning. |
| Necessity Reasoner | **Per-criterion adjudication** (model, one call per criterion) | Splitting per criterion bounds the hallucination surface and yields per-criterion traceability. |
| Reviewer / Guardrail Agent | **Guardrail** (code) | Citation validation is exact substring matching and metadata lookup. That is code. |
| — | **Decision engine** (pure function) | New. Removes the decision from the model entirely. |

Two model-bearing steps instead of four also halves the token cost and the injection surface.

---

## 2. Step contracts

Each step has an explicit prohibition list. The prohibitions are the interesting part: they are
what keeps a step from quietly becoming the decision maker.

### 2.1 Intake — model

**Input:** raw clinical note text (untrusted), requested procedure, jurisdiction, date of service.

**Output:** `IntakeResult`

```
IntakeResult
  facts: [ ClinicalFact { id, kind, text, source_span, code?, code_system?, confidence_hint? } ]
  diagnoses:  [ CodedConcept { code, code_system, display, fact_id } ]
  procedures: [ CodedConcept { code, code_system, display, fact_id } ]
  medications: [ CodedConcept ]
  unresolved: [ str ]     # things the note implies but does not state
```

Every fact carries a `source_span` (character offsets into the submitted note). A fact whose span
does not resolve to matching text is dropped by the guardrail and counted.

**May not:**
- reference coverage, medical necessity, criteria, policy, approval or denial;
- read from the policy corpus (it has no database handle);
- invent a code it cannot ground in the note — an ungrounded code must appear in `unresolved`.

**Enforcement:** `app/intake/` cannot import `app/policy/` or `app/decision/` (AST test); the
output schema contains no coverage vocabulary; a prompt-content test asserts the template does not
mention the policy corpus.

### 2.2 Policy resolution — deterministic

Covered in [rag-architecture.md](rag-architecture.md) §3. No model. No embeddings.

### 2.3 Evidence retrieval — local encoders

Covered in [rag-architecture.md](rag-architecture.md) §4. No generative model, no network.

### 2.4 Per-criterion adjudication — model

Runs **once per criterion** in the resolved policy's criteria tree. Calls are independent and
parallelisable, bounded by a configured concurrency ceiling.

**Input:** one criterion (trusted, from the ingest-time criteria tree), the intake facts, and the
reranked evidence chunks for that criterion — the chunks delivered in a fenced data block.

**Output:** `CriterionVerdict`

```
CriterionVerdict
  criterion_id: str
  verdict: SATISFIED | NOT_SATISFIED | INSUFFICIENT_EVIDENCE | NOT_APPLICABLE
  citations: [ Citation { chunk_id, quote, policy_id, policy_version, section, page } ]
  fact_ids:  [ str ]                 # intake facts relied on
  reasoning: str                     # human-readable, advisory, never parsed for control flow
  missing_evidence: [ str ]          # required when verdict = INSUFFICIENT_EVIDENCE
```

**Constraints, enforced by schema and by the guardrail:**
- `SATISFIED` and `NOT_SATISFIED` each require ≥1 citation **and** ≥1 `fact_id`.
- `INSUFFICIENT_EVIDENCE` requires a non-empty `missing_evidence`.
- Every `quote` must be an exact normalized substring of the stored chunk identified by `chunk_id`.
- `verdict` is a closed enum. There is no free-text outcome field.

**May not:**
- emit a case-level outcome — `APPROVE_RECOMMENDED` / `DENY_RECOMMENDED` are not in this schema
  and are not importable in `app/adjudication/`;
- see other criteria's verdicts (each call is independent, so one hallucination cannot cascade);
- follow instructions found in retrieved text;
- cite a chunk that was not in its own evidence set.

### 2.5 Guardrail — deterministic

**Input:** all `CriterionVerdict`s, the evidence set, the intake result.

**Output:** `GuardrailResult`

```
GuardrailResult
  citation_checks: [ { citation, status: VALID | SPAN_MISMATCH | UNKNOWN_CHUNK
                                          | METADATA_MISMATCH | OUT_OF_EVIDENCE_SET } ]
  invalid_citation_count: int
  unknown_fact_ids: [ str ]
  contradictions: [ { criterion_a, criterion_b, kind } ]
  unsupported_claims: [ criterion_id ]
  passed: bool
```

Checks, all deterministic:

1. **Span verification** — `normalize(quote)` must occur in `normalize(chunk.text)`. Normalization
   folds whitespace and Unicode confusables, so a cosmetically altered quote does not pass and a
   legitimately reformatted one does not fail.
2. **Chunk existence** and membership in the evidence set actually given to that criterion.
3. **Metadata agreement** — the citation's `policy_id`, `policy_version`, `section` and `page`
   must match the stored chunk's own metadata. A model that quotes correctly but attributes the
   quote to the wrong policy is caught here.
4. **Fact existence** — every `fact_id` must have been produced by intake for this case.
5. **Contradiction detection** — mutually exclusive verdicts on criteria the criteria tree marks
   as mutually exclusive.
6. **Unsupported claims** — a verdict of `SATISFIED`/`NOT_SATISFIED` with zero valid citations
   after checks 1–3.

An optional LLM faithfulness check may be run as an **advisory** signal. It is recorded in the
audit trail and may cause a case to be withheld; it can never cause one to be released. A
guardrail that can upgrade a decision is not a guardrail.

### 2.6 Decision engine — pure function

```
decide(verdicts, guardrail_result, resolution_result, criteria_tree, config) -> Recommendation
```

No I/O, no clock, no randomness, no model. Same inputs always produce the same output, which is
what makes the audit trail replayable and the truth-table tests possible. The table is in
[system-architecture.md](system-architecture.md) §5.

---

## 3. Orchestration and graph state

LangGraph wires the steps. It lives **only** in `app/graph/` and no domain module imports it
([ADR-002](../adr/ADR-002-agent-orchestration.md)).

```
              ┌──────────┐
              │  intake  │
              └────┬─────┘
                   ▼
             ┌──────────┐   0 policies ──▶ ┌────────────┐
             │  resolve │   conflicting ──▶│  finalize  │
             └────┬─────┘                  └────────────┘
                  ▼
             ┌──────────┐
             │ retrieve │   (fan-out: one evidence set per criterion)
             └────┬─────┘
                  ▼
           ┌──────────────┐
           │  adjudicate  │  (parallel map over criteria, bounded concurrency)
           └──────┬───────┘
                  ▼
             ┌──────────┐
             │ guardrail│
             └────┬─────┘
                  ▼
             ┌──────────┐
             │ finalize │  → pure decide() → persist → audit
             └──────────┘
```

`CaseState` is append-only within a run: a node adds its own output key and never mutates another
node's. This is what allows the audit trail to be reconstructed from the state and allows any node
to be replayed in isolation.

```
CaseState
  case_id, request_id, submitted_at, date_of_service, jurisdiction
  note_text_ref                  # reference, not the text — see audit privacy
  intake:      IntakeResult | None
  resolution:  ResolutionResult | None
  evidence:    { criterion_id -> [EvidenceChunk] }
  verdicts:    [CriterionVerdict]
  guardrail:   GuardrailResult | None
  recommendation: Recommendation | None
  step_events: [StepEvent]       # append-only: node, attempt, latency, tokens, outcome
```

---

## 4. Why retrieval is split into resolution + retrieval

This is the largest structural change from the brief, and it addresses the largest grounding risk
in this domain.

A single semantic search over the whole corpus will always return *something*. The top result for
a knee-MRI case will be a plausible, well-phrased, confidently-cited imaging policy — which may be
the wrong jurisdiction, or a version that was retired before the date of service. The system would
then reason impeccably over the wrong document and produce a fully-cited wrong answer. Citations
do not protect against this, because the citations are genuine; they point at a real policy that
simply does not apply.

Splitting the step makes applicability a **deterministic, reproducible, testable** property:

```
(procedure code, diagnosis codes, jurisdiction, date of service)
        │  SQL over the resolution index — no embeddings, no model
        ▼
   applicable policy VERSIONS      0 → NEEDS_INFO      conflicting → HUMAN_REVIEW
        │
        ▼  semantic retrieval scoped INSIDE the resolved set only
   evidence
```

Semantic search then does what it is good at — finding the relevant *passage* — inside a document
set whose applicability has already been established by rules. See
[ADR-004](../adr/ADR-004-policy-resolution-and-temporal-versioning.md).

---

## 5. Retry, timeout and failure

| Condition | Behaviour |
|---|---|
| Schema-invalid model output | Up to `MEDAUTH_LLM_MAX_ATTEMPTS`, with the validation error fed back. Then `INSUFFICIENT_EVIDENCE` for that criterion. |
| Firewall `403` | **Not retried.** Retrying a blocked request is an attempt to evade a security control. Case → `HUMAN_REVIEW`. |
| Firewall `503 detector_failure` | Retried with backoff up to the attempt ceiling, then `HUMAN_REVIEW`. |
| Firewall `429` | Retried honouring `Retry-After`. |
| Timeout | Counts as an attempt. |
| One criterion fails all attempts | That criterion only becomes `INSUFFICIENT_EVIDENCE`; the case proceeds and will land on `NEEDS_INFO` at row 6 of the decision table. |

Partial failure degrades toward asking a human, never toward a decision. Every attempt — including
failed ones — is recorded in `step_events` and reaches the audit trail, because "the model was
retried four times" is material to a reviewer assessing a recommendation.

---

## 6. Prompt and version governance

Every prompt template is a versioned file in `app/*/prompts/` with an id such as
`adjudication.v3`. The id is recorded on every audit row alongside the model id and the agent
version, so a recommendation can be reproduced against the exact template that produced it.
Editing a template in place without incrementing the version breaks reproducibility of the audit
trail and is treated as a defect.

Prompts are **trusted content**. No prompt is ever assembled from retrieved text, note text, or
reviewer input — those arrive only inside fenced data blocks in the user turn.
