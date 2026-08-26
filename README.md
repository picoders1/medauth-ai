# MEDAUTH AI

**Agentic Prior-Authorization & Medical-Necessity Decision Support System**

An evidence-grounded system that helps a human reviewer evaluate prior-authorization requests
against authoritative coverage-policy criteria — and that is structurally unable to make the
decision itself.

**Python 3.12+** · **Planning phase** · Evaluated exclusively on synthetic patient data

---

## Status

**Planning phase complete. No application code exists.** This repository currently contains
architecture, decision records, a threat model, an evaluation methodology and a phased
implementation roadmap. Phase 0 has not started.

Every performance, accuracy and grounding figure in this project is **pending evidence**. No number
appears anywhere here unless a committed report produces it. The ledger of what may and may not be
claimed is [docs/evidence-and-claims.md](docs/evidence-and-claims.md).

| | |
|---|---|
| Architecture | Documented — [docs/architecture/](docs/architecture/) |
| Decision records | 20 ADRs — [docs/adr/](docs/adr/) |
| Threat model | 27 threats, each becoming a test in Phase 8 — [docs/security/threat-model.md](docs/security/threat-model.md) |
| Evaluation | Methodology fixed, **nothing measured** — [docs/evaluation/](docs/evaluation/) |
| Implementation | Not started — [roadmap](docs/architecture/implementation-roadmap.md) |

---

## 1. Problem

Prior authorization asks a reviewer to decide whether a requested procedure meets a payer's coverage
criteria for a specific patient. It requires reading a clinical narrative, finding the policy that
actually applies — the right payer, jurisdiction and version *as of the date of service* — and
checking each criterion against the record.

Automating it has a well-documented failure mode: systems that issue denials at scale, faster than
humans can meaningfully review, on grounds that are frequently procedural rather than clinical.

MEDAUTH is built so that failure mode is **structurally unreachable**, not merely discouraged.

## 2. Scope

| | |
|---|---|
| **Is** | Decision support. Produces a recommendation with its evidence for a qualified human reviewer. |
| **Is not** | An autonomous decision maker. No output of this system is a coverage determination. |
| Policy corpus | Publicly available **CMS Medicare Coverage Database** material — NCDs, LCDs, Billing & Coding Articles. Payer-agnostic by construction. |
| Patient data | **Synthetic only.** No real PHI. |
| Privacy | Designed with healthcare privacy and security considerations and evaluated exclusively using synthetic patient data. **No compliance claim is made.** |

## 3. The governing invariant

> **NO EVIDENCE → NO DECISION**

| Situation | Outcome |
|---|---|
| Insufficient clinical evidence | `NEEDS_INFO` |
| No applicable policy | `NEEDS_INFO` → human. **Never a denial.** |
| Unverifiable citation | `NO_DECISION` |
| Conflicting evidence | `HUMAN_REVIEW` |
| Abstention gate not cleared | `NEEDS_INFO` |
| Model call blocked or failed closed | `HUMAN_REVIEW` |
| Sufficient, verified evidence | `APPROVE_RECOMMENDED` / `DENY_RECOMMENDED` |

Every state is first-class, with its own rendering and its own audit row. None is an error path.

## 4. The structural idea

> **Models produce per-criterion verdicts. Code produces the decision.**
>
> The tokens `APPROVE_RECOMMENDED` and `DENY_RECOMMENDED` do not exist in any model output schema
> anywhere in this system.

The decision is a pure function — no I/O, no clock, no randomness — exhaustively testable as a truth
table with no model loaded and no network. The boundary is enforced by an AST test that parses
source rather than importing it, so a violation is caught even if the offending module never runs.

A prompt injection can flip a verdict. It cannot emit a decision, because there is no field to write
one into. See [ADR-010](docs/adr/ADR-010-deterministic-decision-engine.md).

## 5. Architecture

```
  Clinical case (synthetic)
        │
        ▼  INTAKE                    [model]  facts + source spans; no coverage vocabulary
        ▼  POLICY RESOLUTION  [deterministic]  code × jurisdiction × date of service → versions
        ▼  EVIDENCE RETRIEVAL  [local encoders] scoped to resolved versions only
        ▼  PER-CRITERION ADJUDICATION [model]  verdict + span-verified citations, one call each
        ▼  GUARDRAIL          [deterministic]  validate every citation; failure ⇒ NO_DECISION
        ▼  DECISION ENGINE       [pure code]   10-row table + abstention gate
        │
   APPROVE_REC · DENY_REC · NEEDS_INFO · HUMAN_REVIEW · NO_DECISION
        ▼  HUMAN REVIEW  →  APPEND-ONLY AUDIT TRAIL

  Every chat completion:  MEDAUTH → llm-firewall :8005/v1 → OpenAI-compatible provider
```

Two steps call a model. Three are deterministic. Details:
[docs/architecture/system-architecture.md](docs/architecture/system-architecture.md).

### Why policy resolution is separate from retrieval

Semantic search always returns *something*. For a knee-MRI case it returns a plausible,
well-written, confidently-citable imaging policy — possibly from the wrong jurisdiction, or a
version retired before the date of service. The system then reasons impeccably over the wrong
document and produces a fully-cited wrong answer.

**Citations do not catch this.** They are genuine; the quotes verify; the policy simply does not
apply. So applicability is decided by rules — procedure code, diagnosis codes, jurisdiction, date of
service — and semantic search runs only *inside* the resolved set.
[ADR-004](docs/adr/ADR-004-policy-resolution-and-temporal-versioning.md).

## 6. Citation contract

Every citation carries `chunk_id`, an exact `quote`, and claimed policy id, version, section and
page. The quote must be an exact normalized substring of the stored chunk; the claimed metadata must
match the chunk's own; the chunk must have been in that criterion's evidence set. `source_url`,
`effective_date` and `document_title` are **joined from the database, never accepted from the
model** — a URL cannot be fabricated because it is never requested.

**Any citation failing any check ⇒ `NO_DECISION`.** Not a warning, not a lowered score.
[ADR-009](docs/adr/ADR-009-evidence-and-citation-contract.md).

## 7. Abstention

Not a model-reported confidence — that is a token sequence, not a probability, and it is manipulable
by anything in the context. The gate reads **deterministic features**: criteria coverage, citation
validity rate, rerank margin, policy-resolution uniqueness, contradiction count, criteria-tree
review status.

Thresholds are calibrated on **dev only** (enforced at the library boundary, not by discipline) and
validated **once** on a frozen test split with a scoring budget. Denial carries a stricter threshold
than approval, because a wrong denial withholds care while a wrong approval costs money.
[ADR-011](docs/adr/ADR-011-abstention-and-calibration.md).

## 8. Security

Every model call traverses the sibling **LLM Firewall** project — but **MEDAUTH does not
rely on it for its primary threat.** The firewall's own committed evidence refuses the claim that it
protects RAG applications: indirect-injection recall **0.1423**, planted-content recall **0.0938**.
It classifies the *user's turn*; MEDAUTH's threat is content the user never wrote.

Containment is therefore structural and lives in MEDAUTH: fenced data delivery, closed output
schemas with no decision token, span-verified quotes, a decision computed by code, per-criterion
isolation, and corpus content hashing.

27 threats in [docs/security/threat-model.md](docs/security/threat-model.md), each becoming a test
in Phase 8. Integration boundary:
[docs/security/llm-firewall-integration.md](docs/security/llm-firewall-integration.md).

## 9. Evaluation methodology

Four layers measured separately, because they fail differently and are fixed differently: policy
resolution, retrieval, grounding, decision. Ground truth is **by construction** — cases are built
from a human-reviewed criteria tree and the label is computed by the same decision table the system
uses, so no model labels a case it will later adjudicate.

**Stated before any result exists:** with ~150 gold cases split dev/test, per-class denominators are
in the tens and 95% Wilson intervals span roughly ±10–15 pp. Differences smaller than that are not
detectable and will not be claimed.
[docs/evaluation/evaluation-strategy.md](docs/evaluation/evaluation-strategy.md).

## 10. Results

**None.** No evaluation has been run. This section will be populated only from committed reports
under `eval/reports/`, each carrying its dataset hash, split, denominators, intervals, model id and
git commit.

## 11. Limitations

Stated now, not after results.

1. **Constructed cases are cleaner than real clinical notes.** Any measured performance is an upper
   bound. The claim that it transfers to real documentation is **refused**, permanently.
2. **Small denominators.** ~25–40 cases per class bound what can be concluded.
3. **Criteria trees are model-extracted.** A systematic extraction error becomes a systematic
   adjudication error. Human review is the control; extraction accuracy is not claimed.
4. **Injection containment is unmeasured** until Phase 8. Layers exist by design; no containment
   claim is made before the report exists.
5. **No Kubernetes cluster run.** Manifests are authored and statically validated with
   `kubeconform`. "Runs on Kubernetes" is a refused claim.
6. **No self-hosted vLLM.** The reference machine has 4 GB VRAM. vLLM is a documented target, not a
   validated one.
7. **No reviewer pilot.** Override rate, human/AI agreement and review-time claims are refused.
8. **Corpus is bounded** to 5–8 procedures initially, limiting generality.
9. **No penetration test.**

## 12. Repository

```
app/        intake · policy · retrieval · adjudication · guardrail · decision · audit · llm · graph
config/     decision-policy.yaml — thresholds are configuration, versioned and audited
eval/       harness; datasets/ frozen + hashed + committed; reports/ the source of every number
tests/      unit · integration · security · evaluation
ui/         Next.js reviewer console
deploy/     docker · k8s
docs/       architecture · adr · evaluation · security · runbooks
```

[docs/architecture/repository-structure.md](docs/architecture/repository-structure.md)

| Service | Port |
|---|---|
| API | 8015 |
| PostgreSQL + pgvector | 5435 |
| Reviewer console | 3100 |
| llm-firewall (consumed) | 8005 |

## 13. Getting started

Not yet runnable. Phase 0 creates the skeleton and the compose stack. Follow
[docs/architecture/implementation-roadmap.md](docs/architecture/implementation-roadmap.md).

## 14. Engineering conventions

- **No fabricated numbers.** Every figure traces to a committed report, or it is not written.
- **Negative results are first-class.** A failed experiment honestly reported is the expected
  output.
- **Frozen corpora are never edited.** Extend by adding a version.
- **`docs/` is the source of truth.** Code contradicting it is a bug in one of the two.
- **Commits are manual.**
