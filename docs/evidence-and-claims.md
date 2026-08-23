# Evidence Ledger: Claims and Their Proof

Every claim this project may make — in the README, in an interview, on a CV — is listed here with
the artefact that must exist first, how that artefact is produced, and where it will live.

**The rule:** if the artefact does not exist, the claim is not made. Not softened, not hedged — not
made.

**Status:** `Pending` (no artefact yet) · `Produced` (artefact committed, claim permitted) ·
`Refused` (the claim must not be made, with the reason).

**Every row is Pending or Refused.** No code has been written and no evaluation has been run. This
is the expected state at the end of the planning phase.

---

## Decision quality

| Claim | Evidence required | How produced | Status |
|---|---|---|---|
| Decision accuracy | Per-class precision/recall, `n`, split, Wilson interval | `python -m eval run --split test --frozen` | **Pending** (Phase 6) |
| Macro-F1 | Same, with confusion matrix | Same | **Pending** |
| **Denial precision** | Its own denominator and interval, reported separately | Same | **Pending** |
| Performance transfers to real clinical notes | An evaluation on real de-identified notes | — | **Refused.** All cases are constructed. No real-note evaluation is planned. |
| The system determines medical necessity | — | — | **Refused permanently.** This is a decision-support system. No output is a coverage determination. |

## Grounding

| Claim | Evidence required | How produced | Status |
|---|---|---|---|
| Citation precision / recall | Rates with denominators and intervals | `eval/runners/grounding.py` | **Pending** (Phase 6) |
| Unsupported-claim rate | Rate over all verdicts | Same | **Pending** |
| Citation misattribution rate | Valid-quote/wrong-attribution rate | Same | **Pending** |
| Faithfulness | Human adjudication on a stated sample | Manual, sample size recorded | **Pending** |
| **Every citation is deterministically verified** | Span + metadata validation with tests, and `NO_DECISION` on failure | `pytest tests/unit/test_citation_validation.py` | **Pending** (Phase 5) — an engineering claim, verifiable by running the suite |

## Abstention

| Claim | Evidence required | How produced | Status |
|---|---|---|---|
| Coverage / selective accuracy | Curve on dev, single scored point on test | `scripts/coverage_accuracy_analysis.py` | **Pending** (Phase 6) |
| Abstention precision / recall | Rates with intervals | Same | **Pending** |
| **Abstention improves safety rather than reducing coverage** | Unsafe-rate falling faster than coverage, paired exact McNemar, intervals stated | Same | **Pending — and may not be claimed if the result is negative** |
| Confidence is calibrated | A calibration curve with a stated method | — | **Refused unless produced.** The gate runs on deterministic features precisely because model self-report is not a probability |

## Retrieval

| Claim | Evidence required | How produced | Status |
|---|---|---|---|
| Recall@k, nDCG@k, MRR | Rates on a frozen retrieval set with `n` | `python scripts/evaluate_retrieval.py` | **Produced** (Phase 1) — see the retrieval-baseline report. **Measured on a CMS-shaped corpus** |
| **Policy-resolution accuracy** | Reported separately from semantic retrieval | Same | **Produced** (Phase 1) — reported apart, and identical across every arm because resolution uses no model |
| The chosen embedding model is best | A comparison of ≥2 candidates showing a distinguishable difference | Same | **NOT produced.** Two encoders and three rerank options were compared; at n=11 the intervals overlap. The shipped defaults are *adequate and unrefuted*, never "best" |
| Retrieval figures transfer to real CMS prose | The same measurement on real CMS documents | — | **NOT produced — refused.** CMS is unreachable from this network; the corpus is CMS-*shaped*. Figures on constructed policy text are an upper bound (R-33) |
| **Temporal correctness** | Four passing temporal tests | `pytest tests/integration/test_temporal_resolution.py tests/integration/test_retrieval_scope.py` | **Produced** (Phase 1) — all four mandatory tests pass, and each was shown to fail on a deliberately injected bug: a "latest version" query, an end-boundary off-by-one, a widened jurisdiction, a removed scope filter and a removed temporal filter |
| **Policy resolution is deterministic and embedding-free** | Resolution reachable with no encoder loaded, and invariant across encoders | Same, plus the retrieval report showing identical resolution accuracy in every arm | **Produced** (Phase 1) |
| **Retrieval cannot search unscoped** | An empty resolved set raises rather than widening | `pytest tests/integration/test_retrieval_scope.py` | **Produced** (Phase 1) — `EmptyScopeError`; there is no whole-corpus code path |
| **A chunk never spans a section boundary** | The rule asserted at every chunk size, including adversarial section shapes | `pytest tests/unit/test_chunking.py` | **Produced** (Phase 1) — 18 cases; the inverted-meaning failure is tested directly |
| **Corpus tampering is detectable** | Chunk hashes over normalized text, re-validatable | `pytest tests/integration/test_retrieval_scope.py` | **Produced** (Phase 1) — reformatting hashes identically; changed words do not |

## Security

| Claim | Evidence required | How produced | Status |
|---|---|---|---|
| Indirect-injection containment | Containment rate per delivery shape, with denominators | `pytest -m security`, adversarial report | **Pending** (Phase 4/8) |
| Prompt-injection resistance | Same, per attack family | Same | **Pending** |
| **The LLM Firewall protects this RAG application** | — | — | **Refused.** The firewall's own ledger refuses it: indirect recall 0.1423 (n=520), planted-content recall 0.0938 (n=480) — its `eval/results/20260817T130736Z__indirect-delivery-shape/report.md`. MEDAUTH's containment is structural and separate (ADR-016). |
| Corpus tampering is detectable | Chunk hashes recorded and re-validatable | `pytest tests/security/test_corpus_integrity.py` | **Pending** (Phase 1/8) |
| Audit trail is append-only | Grant-level assertion plus absence of any update/delete path | `pytest tests/security/test_audit_integrity.py` | **Pending** (Phase 7) |
| No clinical text reaches logs or telemetry | Sink-level enforcement plus a leakage test | `pytest tests/security/test_log_leakage.py` | **Pending** (Phase 8) |
| **HIPAA compliance** | — | — | **Refused permanently.** Designed with healthcare privacy and security considerations, evaluated exclusively on synthetic data. No compliance claim is made. |
| Penetration tested | A test report | — | **Refused.** None performed. |

## Model capability

| Claim | Evidence required | How produced | Status |
|---|---|---|---|
| **The primary model constrains output structurally** | Schema-valid rate against the real nested verdict schema, with `n` | `python scripts/probe_model_capabilities.py` | **Produced** (Phase 0) — `json_schema` 5/5 schema-valid; conformance enforced by the decoder, not by cooperation. [`eval/reports/20260823T091726Z__model-capabilities/report.md`](../eval/reports/20260823T091726Z__model-capabilities/report.md) |
| **`json_object` does not guarantee our schema** | The same measurement in that mode | Same run | **Produced** — 0/5 against the verdict schema despite 5/5 valid JSON |
| **The long-context model rejects grammar-constrained decoding** | Per-mode support with the provider's stated reason | Same run, confirmed against the provider directly | **Produced** — speculative decoding; `tool_choice: auto` works, forced choice does not |
| The primary model reasons better than the alternate | Decision quality on the frozen gold corpus | — | **NOT produced.** The probe measures schema conformance only. No reasoning claim is made before Phase 6 |
| Model output is byte-reproducible | Identical payloads at temperature 0 across repeats | Same run | **NOT produced — refused.** The primary model varies on the full verdict schema. Reproducibility is scoped to the deterministic half of the pipeline (ADR-013) |

## Data foundation

| Claim | Evidence required | How produced | Status |
|---|---|---|---|
| **Every criterion is traceable to a section, page and character span** | Span verification at parse time, rejecting unlocatable declarations | `pytest tests/evaluation/test_data_foundation.py` | **Produced** — 27/27, and four rejection paths exercised including text found in the *wrong* section |
| **Gold labels are computed by the same function the system uses** | All labels recomputed from criterion states by `decide()` | Same | **Produced** — 210/210 reproduce exactly |
| **Criterion-level ground truth exists** | A state per applicable criterion, with the decision derived from them | `data/gold/cases/gold_v1.jsonl` | **Produced** — a decision label can never hide which criteria produced it |
| **The gold set is frozen and unscored** | Manifest hash asserted against the file; scoring budget recorded | `pytest tests/evaluation/test_data_foundation.py` | **Produced** — 155 cases, 0 of 1 scorings spent |
| **No gold label reaches the model's input** | Outcome and criterion-state vocabulary grepped out of every `input` | Same | **Produced** |
| **Case generation is deterministic** | Byte-identical rebuild from the same seed and corpus | `scripts/generate_cases.py` re-run | **Produced** |
| **No real patient identifiers are present** | SSN/email/phone/MRN/DOB patterns absent across the corpus | `pytest -m evaluation` | **Produced** |
| **Every criterion is traceable to AUTHORITATIVE policy text** | The same verification, against real CMS documents | — | **NOT produced.** CMS is unreachable; the corpus is CMS-*shaped*. The machinery is verified, the authority is not (R-33) |
| The gold set is clinically validated | Review by a qualified clinician | — | **Refused permanently unless performed.** No clinician has seen any case. The manifest records `clinically_validated: false` |
| Inter-annotator agreement | Two or more independent labellers | — | **NOT produced, and not pending.** There is one labeller and it is a program; there is nothing to measure agreement between |
| Measured performance transfers to real submissions | An evaluation on real de-identified notes | — | **Refused.** Constructed cases state each fact once, unambiguously, where a reader expects it |

## Engineering

| Claim | Evidence required | How produced | Status |
|---|---|---|---|
| **The LLM cannot emit a decision** | No approval/denial member in any model schema, plus AST-enforced import boundaries | `pytest tests/unit/test_layer_boundaries.py` | **Produced** (Phase 0) — 8 checks over 5 rules; each was shown to fail on a deliberately injected violation before being trusted |
| **The decision surface is a pure function** | Truth-table suite passing with no model and no network | `pytest tests/unit/test_decision_table.py` | **Pending** (Phase 5) |
| No policy → never a denial | An assertion over all verdict/guardrail combinations | Same | **Pending** (Phase 5) |
| Policy resolution is deterministic and reproducible | Same inputs, same versions, across corpus refreshes | `pytest tests/integration/test_resolution_determinism.py` | **Pending** (Phase 1) |
| Recommendations are reproducible | Corpus snapshot, prompt, model and config versions on every row | Schema plus replay test | **Pending** (Phase 5/7) |

## Operations and deployment

| Claim | Evidence required | How produced | Status |
|---|---|---|---|
| p50 / p95 latency | Measured on stated hardware with `n` | Benchmark run | **Pending** |
| Cost per case | Token counts with the model id and price basis on the run date | Evaluation run | **Pending** |
| **Runs under Docker Compose** | A stack that starts and passes readiness | `docker compose up -d && curl :8010/ready` | **Produced** (Phase 0) — API and pgvector healthy; all four readiness checks pass; container non-root, read-only rootfs, all capabilities dropped |
| **Runs on Kubernetes** | A real cluster run producing an artefact | — | **Refused until produced.** No cluster exists on the reference machine (no `kubectl`/`kind`/`minikube`/`helm`). Manifests are *authored and statically validated with `kubeconform`* — that is the permitted claim, and it is a different claim. |
| Self-hosted on vLLM | A served model with measured latency | — | **Refused.** 4 GB VRAM cannot serve a useful model at the required context. vLLM is a documented target, not a validated one (OD-2). |
| CI gates on evaluation regression | A workflow that fails on a metric moving beyond tolerance | `.github/workflows/evaluation.yaml` | **Pending** (Phase 9) |

## Human-in-the-loop

| Claim | Evidence required | How produced | Status |
|---|---|---|---|
| Reviewers can trace every recommendation to its evidence | The console rendering citations, spans and the rule that fired | Phase 7 demo plus API tests | **Pending** |
| Override rate | A pilot with real reviewers | — | **Refused.** No pilot has happened or is scheduled (OD-7). |
| Human/AI agreement | Same | — | **Refused** |
| Review time reduction | A controlled study with a baseline | — | **Refused.** This would need a comparison arm that does not exist. |
| Automation bias is mitigated | A study of reviewer behaviour | — | **Refused.** Design choices exist (evidence-first ordering, mandatory override reasons); their effectiveness is unmeasured (R-04). |
