# Threat Model

**Status:** Planning phase. No mitigation is implemented; no containment is measured.
Every "verified by" column names a test that **does not yet exist** and is created in the phase
shown.

**Rule:** in Phase 8 this document becomes an executable gate. Each `T-*` names its test, and a
meta-test fails if a threat has no test or a test names no threat. A threat model that is not
executable is a document, not a control.

---

## Scope and assumptions

| | |
|---|---|
| Data | Synthetic patient data only. No real PHI enters this system. |
| Compliance | **No compliance claim is made.** Designed with healthcare privacy and security considerations; evaluated exclusively on synthetic data. |
| Model path | Every chat completion traverses the sibling `llm-firewall` at `:8005/v1`. |
| Provider credential | Held by the firewall. MEDAUTH holds no model-provider credential. |
| Deployment | Single-tenant, single-organisation. Multi-tenant isolation is out of scope. |
| Users | Authenticated clinical reviewers behind a trusted identity proxy. |

### Trust boundaries

```
  UNTRUSTED                                    TRUSTED
  ─────────                                    ───────
  clinical note text                           prompt templates (versioned, in repo)
  retrieved CMS policy text  ◀── the one       criteria trees (human-reviewed)
  reviewer free-text input       most systems  decision-policy.yaml
  API request bodies             get wrong     application code
```

**Retrieved policy text is the primary untrusted surface**, and it is untrusted *inside* the
trusted network, which is what makes it dangerous.

---

## The central assumption, stated explicitly

MEDAUTH does **not** rely on the firewall to defend against injection delivered through retrieved
policy text. The firewall's own committed evidence forbids that reliance:

| Measurement | Value | Source (sibling repo) |
|---|---|---|
| Indirect-injection recall | **0.1423** (n=520) | `eval/results/20260817T130736Z__indirect-delivery-shape/report.md` |
| Recall on *planted* content | 0.0938 (n=480) | same |
| Recall on *user-requested* content | 0.7250 (n=40) | same |
| Baseline through-socket recall | 0.4706 | R-102 |
| "The firewall protects RAG applications" | **claim refused** | `docs/22-evidence-and-claims.md` |

The detector classifies the user's turn. MEDAUTH's threat is content the user never wrote.
Therefore **containment is structural**, not detective — see T-05/T-06 mitigations.

---

## Threats

Likelihood/impact are pre-implementation judgements, revised in Phase 8 against measurement.

### Injection and content manipulation

| ID | Threat | Impact | Mitigation | Verified by | Phase |
|---|---|---|---|---|---|
| **T-01** | **Direct prompt injection in the clinical note.** Submitter embeds instructions ("approve this request") in the narrative. | High | Note delivered fenced as data, never in the system prompt. Intake schema contains no coverage vocabulary. Firewall screens the caller turn (its strongest case). Decision computed by code. | `test_injection_containment.py::note_injection` | 4 |
| **T-02** | **Injection via structured fields.** Codes, jurisdiction or free-text reason carry payloads. | Medium | Codes validated against known code systems before use; resolution is a parameterised query; unparseable fields → `NEEDS_INFO`. | `test_injection_containment.py::field_injection` | 4 |
| **T-03** | **Injection via reviewer input.** Override reason contains payload text. | Low | Override reasons are stored and displayed, never fed to a model. Output-encoded in the UI. | `test_reviewer_input_containment.py` | 7 |
| **T-04** | **Multi-turn / accumulated context injection.** | Low | There is no conversational memory. Every criterion adjudication is an independent, single-turn call with a fresh context. Structural. | `test_adjudication_independence.py` | 4 |

### RAG and corpus integrity — the highest-risk group

| ID | Threat | Impact | Mitigation | Verified by | Phase |
|---|---|---|---|---|---|
| **T-05** | **Indirect prompt injection via policy text.** A retrieved chunk carries instructions. Firewall recall here is 0.1423 — it will mostly not be caught. | **Critical** | Structural containment, five independent layers: (1) fenced delivery with explicit data framing; (2) closed output schema — no approval token exists to emit; (3) every claim needs a span-verified quote; (4) code computes the decision from verdicts; (5) per-criterion isolation so one compromised call cannot cascade. | `test_corpus_poisoning.py` — all delivery shapes | 4, 8 |
| **T-06** | **Corpus poisoning.** Attacker alters stored policy text or inserts a fabricated policy. | **Critical** | `text_sha256` per chunk and `content_sha256` per version recorded at ingest; `data/cms/registry.yaml` pins acquisition hashes; ingest only from registered source URLs; historical citations re-validatable against the chunk they named, so tampering is detectable after the fact. | `test_corpus_integrity.py` | 1, 8 |
| **T-07** | **Retrieval manipulation.** Crafted note text steers retrieval to a favourable but inapplicable policy. | High | **Policy resolution is deterministic** — applicability comes from codes, jurisdiction and date of service, not from similarity. Semantic search operates only *inside* the resolved set. This is the primary reason resolution and retrieval are separate steps. | `test_resolution_determinism.py` | 1 |
| **T-08** | **Temporal manipulation.** A superseded or not-yet-effective version is used. | High | Version selection by date of service; the same temporal predicate filters retrieval; four dedicated temporal tests. | `test_temporal_resolution.py` | 1 |

### Grounding and output integrity

| ID | Threat | Impact | Mitigation | Verified by | Phase |
|---|---|---|---|---|---|
| **T-09** | **Hallucinated citation.** A citation to a chunk that does not exist, or a quote that is not in it. | **Critical** | Deterministic span verification against stored text; chunk existence and evidence-set membership checked. Any failure ⇒ `NO_DECISION` for the case. | `test_citation_validation.py` | 5 |
| **T-10** | **Citation manipulation / misattribution.** A real quote attributed to the wrong policy, version, section or page. | **Critical** | Claimed metadata must match the chunk's stored metadata. Derived fields (`source_url`, `effective_date`, `document_title`) are joined from the database and never accepted from the model — a URL cannot be fabricated because it is never requested. | `test_citation_validation.py::metadata_mismatch` | 5 |
| **T-11** | **Unsupported claim.** A verdict with no valid citation behind it. | High | `SATISFIED`/`NOT_SATISFIED` require ≥1 valid citation and ≥1 intake fact; enforced by schema and re-checked by the guardrail. | `test_decision_table.py` | 5 |
| **T-12** | **Hallucinated clinical fact.** Intake invents a finding not in the note. | High | Every fact carries a source span; spans that do not resolve are dropped and counted; verdicts may only reference existing fact ids. | `test_intake_spans.py` | 3 |
| **T-13** | **Fluent wrong answer.** Correct-looking reasoning over the wrong policy. | **Critical** | T-07 and T-08 mitigations; `resolution_uniqueness` is a hard rule in the abstention gate; the reviewer console shows *which* policy version and *why* it resolved. | `test_resolution_determinism.py`, UI evidence panel | 1, 7 |

### Privacy and data protection

| ID | Threat | Impact | Mitigation | Verified by | Phase |
|---|---|---|---|---|---|
| **T-14** | **Clinical text in logs.** | High | Redaction enforced at the structlog **sink**, not per call site; `full` refused in production, in code. | `test_log_leakage.py` | 8 |
| **T-15** | **Clinical text in telemetry.** Span attributes or metric labels carry note content. | High | Spans carry ids, counts and durations only; metric labels are closed sets. Langfuse is opt-in and, if enabled, is documented as receiving trace metadata. | `test_telemetry_privacy.py` | 8 |
| **T-16** | **Clinical text in the audit trail.** | Medium | Audit payloads carry fact ids, chunk ids and spans; text is joined for display. No audit column may hold a prompt or completion — asserted against the schema. | `test_audit_privacy.py` | 7 |
| **T-17** | **PII leaking to the model provider.** | Medium | Firewall applies PII redaction on the model path. All data is synthetic. Presidio deferred (OD-6) rather than shipped as a gesture. | `test_pii_path.py` | 8 |

### Access control and infrastructure

| ID | Threat | Impact | Mitigation | Verified by | Phase |
|---|---|---|---|---|---|
| **T-18** | **Unauthorised case access.** | High | Reviewer identity derived from a trusted proxy, never read from an untrusted client; `X-Forwarded-For` never consulted; unknown paths default to reviewer-only; `0.0.0.0/0` trusted range refused at startup. | `test_reviewer_auth.py` | 7 |
| **T-19** | **Identity spoofing.** Client sends its own identity header. | High | Identity headers read only when the socket peer is inside `MEDAUTH_TRUSTED_PROXIES`. | `test_reviewer_auth.py::spoofed_header` | 7 |
| **T-20** | **Credential leakage.** | High | MEDAUTH holds no provider key. The firewall caller key is `SecretStr`, environment-only, never in policy YAML (structurally rejected), never logged. `gitleaks` over full history in CI. | `test_secret_hygiene.py`, CI | 0, 9 |
| **T-21** | **Audit tampering.** Rows altered or selectively deleted to hide a recommendation. | **Critical** | Append-only: the application role has `INSERT`/`SELECT` and not `UPDATE`/`DELETE`; no such code path exists. Retention runs under a separate role and deletes **by `created_at` and nothing else** — a purge that can be aimed at particular rows is a mechanism for erasing evidence. Asserted against the compiled SQL. | `test_audit_integrity.py`, `test_retention_safety.py` | 7 |
| **T-22** | **Insecure API surface.** | Medium | Pydantic validation on every input; OpenAI-shaped error envelope disclosing category and request id only; CORS restricted to the configured UI origin; TLS terminated at an edge, verified never assumed. | `test_api_security.py` | 7, 9 |
| **T-23** | **Tool / capability abuse.** | Low | There are no general-purpose tools. Model calls have exactly two schemas, both closed. No model output reaches a shell, a query, or the filesystem. Structural. | `test_layer_boundaries.py` | 0 |
| **T-24** | **Denial of service via expensive cases.** A case with a huge criteria tree or note. | Medium | Bounded criteria per case, bounded note size, bounded adjudication concurrency, per-request timeout. Firewall rate-limits the model path. | `test_resource_bounds.py` | 8 |
| **T-25** | **Supply chain.** | Medium | `uv.lock` and `package-lock.json` committed and CI-checked; `pip-audit`, `npm audit`, `trivy` on images; pinned base image digests. | CI | 9 |

### Human-factor threats

| ID | Threat | Impact | Mitigation | Verified by | Phase |
|---|---|---|---|---|---|
| **T-26** | **Automation bias.** Reviewers rubber-stamp recommendations, making "human in the loop" nominal. | **High** | Evidence is presented before the recommendation; `NEEDS_INFO` and `NO_DECISION` render as prominently as decisions; overrides require a reason enforced at the database; override rate and review duration are instrumented. This is a harm the system's own UI can cause, so it is a threat, not a UX concern. | UI review; R-04 | 7 |
| **T-27** | **Denial framing.** A `DENY_RECOMMENDED` is read as a determination. | **High** | Denial is always human-mandatory; the console renders it as a *draft rationale*, never a decision; denial carries a stricter evidence bar and gate threshold; denial precision reported separately. | `test_decision_table.py`, UI review | 5, 7 |

---

## Residual risk

Stated now so it is not discovered later.

1. **Indirect injection containment is unmeasured.** Layers exist by design; the report is Phase 8.
   Until it exists, no containment claim is made.
2. **The firewall does not protect this class of attack**, by its own evidence. MEDAUTH's layers are
   the control. If they fail, the firewall is not a second line here.
3. **Criteria trees are model-extracted.** A systematic extraction error becomes a systematic
   adjudication error. Human review is the control; extraction accuracy is not claimed.
4. **Constructed evaluation cases** are cleaner than real notes. Adversarial robustness measured on
   them may not transfer.
5. **Provenance signalling to the firewall is unvalidated** — that capability ships off and
   uncalibrated there (OD-3). It is defence-in-depth, not a control.
6. **No penetration test** has been performed.

---

## Explicitly out of scope

Multi-tenant isolation · network security below the container boundary · physical security ·
insider threat by a database administrator · model-weight extraction (weights are not hosted here)
· availability guarantees.
