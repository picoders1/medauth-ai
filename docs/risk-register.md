# Risk Register

Failure modes with evidence. An item leaves this list only with the artefact that resolved it.

**Status:** planning phase. Every risk is `Open` and unmitigated — no code exists. Likelihood and
impact are pre-implementation judgements, revised against measurement in the phase shown.

| | |
|---|---|
| **Open** | identified, not yet mitigated |
| **Mitigated** | a control exists and a test asserts it |
| **Accepted** | will not be fixed; the reason is recorded |
| **Resolved** | an artefact demonstrates it no longer applies |

---

## Clinical and domain risk

| ID | Risk | Impact | Mitigation | Status | Phase |
|---|---|---|---|---|---|
| **R-01** | **A denial is issued for missing documentation rather than for evidenced non-satisfaction.** The most common harm pattern in automated prior authorization. | Critical | Rows 6 and 8 of the decision table are separate and row 6 is evaluated first; denial requires positive, span-verified evidence of non-satisfaction. Asserted by the truth-table suite. | Open | 5 |
| **R-02** | "No applicable policy" is treated as non-coverage. | Critical | Row 1 → `NEEDS_INFO`; a test asserts `DENY_RECOMMENDED` is unreachable when resolution is empty. | Open | 5 |
| **R-03** | The wrong policy version is used — correct-looking, correctly-cited, inapplicable. | Critical | Deterministic resolution on code × jurisdiction × date of service; retrieval scoped to resolved versions; four temporal tests. | Open | 1 |
| **R-04** | **Automation bias.** Reviewers rubber-stamp, making human oversight nominal. The system's own UI can cause this. | High | Evidence rendered before the recommendation; `NEEDS_INFO`/`NO_DECISION` equally prominent; override reason enforced at the database; override rate and review duration instrumented. **Effectiveness is unmeasured** and the mitigation claim is refused. | Open | 7 |
| **R-05** | A `DENY_RECOMMENDED` is read as a determination rather than a draft rationale. | High | Denial is always human-mandatory; console framing; stricter evidence bar and gate threshold; denial precision reported separately. | Open | 5, 7 |
| **R-06** | Criteria trees are model-extracted, so a systematic extraction error becomes a systematic adjudication error. | High | Human review before evaluation use; provenance chunk ids per criterion; correction rate recorded. Extraction accuracy is **not claimed**. | Open | 2 |
| **R-07** | Coverage policy is genuinely ambiguous and a criteria tree imposes false precision. | Medium | `INFORMATIONAL` criteria for material that does not decompose; ambiguity routes to `NEEDS_INFO`/`HUMAN_REVIEW` rather than forcing a verdict. | Open | 2 |

## GenAI and grounding risk

| ID | Risk | Impact | Mitigation | Status | Phase |
|---|---|---|---|---|---|
| **R-08** | Hallucinated citation. | Critical | Deterministic span verification; failure ⇒ `NO_DECISION`. | Open | 5 |
| **R-09** | **Citation misattribution** — a real quote attributed to the wrong policy. More dangerous than fabrication because a human spot-check passes it. | Critical | Claimed metadata must match stored metadata; derived fields joined, never accepted from the model. Tracked as its own metric. | Open | 5 |
| **R-10** | Span validation is tuned too loosely to reduce `NO_DECISION` volume, quietly weakening the contract. | High | The contract is fixed in ADR-009; normalization may be fixed, the contract may not. Any change requires an ADR amendment. | Open | 5 |
| **R-11** | The model does not support reliable structured output, making closed schemas unenforceable in practice. | High | **Retired on evidence (Phase 0).** The primary model supports grammar-constrained `json_schema` at 5/5 schema-valid, so conformance is structural rather than cooperative. The long-context model uses `tool_call`, where conformance is learned - its repair rate is reported as a metric from Phase 4. | **Resolved** | 0 |
| **R-12** | Per-criterion adjudication cost or latency is impractical at realistic tree sizes. | Medium | Measured in Phase 4; independent calls parallelise; criteria per case bounded. | Open | 4 |
| **R-13** | The model refuses clinical content, or hedges into unusable output. | Medium | Detected and counted as a capability finding, not silently prompted around. | Open | 4 |

## Security risk

| ID | Risk | Impact | Mitigation | Status | Phase |
|---|---|---|---|---|---|
| **R-14** | **Indirect prompt injection via retrieved policy text, with the firewall providing little protection** (its measured indirect recall is 0.1423, planted-content recall 0.0938). | Critical | Five structural layers in MEDAUTH (fenced delivery, closed schemas, span-verified quotes, code-computed decision, per-criterion isolation). **Containment is unmeasured until Phase 8** and no containment claim is made before then. | Open | 4, 8 |
| **R-15** | Corpus poisoning — stored policy text altered or a fabricated policy inserted. | Critical | Content hashes at document and chunk level; ingest only from registered sources; historical citations re-validatable. | Open | 1, 8 |
| **R-16** | Audit tampering — selective deletion to hide a recommendation. | Critical | Append-only grants; retention deletes by `created_at` and nothing else, asserted against the compiled SQL. | Open | 7 |
| **R-17** | Clinical text leaks into logs, spans or audit payloads. | High | Redaction at the sink; audit payloads carry ids and spans; schema-level assertion that no column holds a prompt or completion. | Open | 7, 8 |
| **R-18** | The provider credential leaks. | High | MEDAUTH never holds it — the firewall does. `gitleaks` over full history in CI. **The key was shared in a planning conversation and should be rotated.** | Open | 0 |
| **R-19** | Firewall false positives block legitimate clinical notes. | Medium | Measured from Phase 0; `403` is never retried; the case routes to `HUMAN_REVIEW`. A material rate is a finding recorded in both repositories. | Open | 0 |

## Evaluation risk

| ID | Risk | Impact | Mitigation | Status | Phase |
|---|---|---|---|---|---|
| **R-20** | **Denominators too small for the differences of interest.** ~25–40 per class gives ±10–15 pp intervals. | High | Stated before any result; every per-class figure carries `n` and its interval; paired exact McNemar for comparisons; stronger statements sourced from the retrieval and grounding layers where `n` is larger. | Open | 3, 6 |
| **R-21** | Circular ground truth — a model authoring both case and label. | Critical | Labels computed by construction from the human-reviewed criteria tree, via the same decision table. | Open | 3 |
| **R-22** | Constructed cases are cleaner than real notes, so results are an upper bound. | High | **Documented as a permanent limitation.** The generalisation claim is refused. | Open (accepted) | 3 |
| **R-23** | The frozen test split is re-scored until a number improves. | High | Scoring budget in the registry; further scorings require a prior ADR; `require_tunable` raises at the library boundary. | Open | 3, 6 |
| **R-24** | Generated narratives leak their own label. | Medium | Adversarial lint for criterion and outcome vocabulary; targeted human spot-check. | Open | 3 |
| **R-25** | Thresholds are tuned on the test split. | Critical | Enforced at the library boundary, not by discipline. | Open | 6 |

## Engineering and operational risk

| ID | Risk | Impact | Mitigation | Status | Phase |
|---|---|---|---|---|---|
| **R-26** | The "LLM cannot decide" invariant decays into a convention as the code grows. | Critical | Five AST-enforced boundary rules, written in Phase 0 before there is anything to violate. | Open | 0 |
| **R-27** | Documentation drifts from code. | High | `docs/` is the source of truth; documentation updates ship in the same change; the Phase 9 sweep re-checks every claim. | Open | 9 |
| **R-28** | Audit on the request path adds material latency. | Medium | Measured and accepted — a recommendation that cannot be audited is not issued. A deliberate divergence from the firewall's ADR-029, recorded in ADR-013. | Open (accepted) | 7 |
| **R-29** | Kubernetes manifests are never validated against a real cluster. | Medium | `kubeconform` in CI; the "runs on Kubernetes" claim stays refused (OD-9). | Open (accepted) | 9 |
| **R-30** | The reference machine (4 GB VRAM, ~16 GB free RAM) cannot run the full stack with optional overlays. | Medium | Langfuse is opt-in; encoders run on CPU by default; no generative model runs locally. | Open (accepted) | 8 |
| **R-31** | Next.js adds an npm supply-chain surface to a healthcare project. | Medium | Lockfile committed, `npm audit` in CI, no runtime CDN, UI renders only backend data. | Open | 7, 9 |
| **R-32** | Corpus refresh silently changes historical case behaviour. | High | Versions are added, never edited; cases pin `corpus_snapshot_id` and `policy_version_id`; a test asserts a refresh does not change a historical resolution. | Open | 1 |

## Phase 1 findings

| ID | Risk | Impact | Mitigation | Status | Phase |
|---|---|---|---|---|---|
| **R-33** | CMS is unreachable from the development network, so the corpus is CMS-*shaped* rather than CMS. | High | Acquisition is a source adapter; real documents drop into `data/cms/` with no code change. `registry.yaml` marks every document `synthetic`, and that flag is carried into each report. **The claim that retrieval figures transfer to real CMS prose is refused.** | Open (accepted) | 1 |
| **R-34** | A wrapped prose line satisfies every lexical test for a section heading, so structure detection fills with body text masquerading as sections. | High | **Found and fixed in Phase 1.** Local headings now require structural evidence - a preceding blank line and following content - and only canonical headings are accepted without it. Asserted by `test_wrapped_prose_is_not_mistaken_for_a_heading`. | **Resolved** | 1 |
| **R-35** | A section with no sentence boundary (an enumeration or code table) produces a chunk wider than the encoder context and is silently truncated at embedding time. | High | **Found and fixed in Phase 1.** Word-boundary hard split as a last resort, never mid-word. Asserted by `test_an_unpunctuated_section_is_still_bounded`. | **Resolved** | 1 |
| **R-36** | Version scoping and the temporal predicate are redundant on the happy path, so a test exercising only that path proves neither. | **Critical** | **Found and fixed in Phase 1.** The first version of the scoping tests passed with either filter deleted. Each is now tested on the path where it alone is load-bearing, and both injections fail the suite. | **Resolved** | 1 |
| **R-37** | Billing & Coding Articles cannot be resolved to from a procedure code, so their content is unreachable. | Medium | Recorded as OD-15 and excluded from the retrieval denominator with the reason stated, rather than silently dropped. | Open | 1 |

## Data-foundation findings

| ID | Risk | Impact | Mitigation | Status | Phase |
|---|---|---|---|---|---|
| **R-38** | The whole chain is self-referential: the same author wrote the policies, declared the criteria, and built the cases from them. Internal consistency is guaranteed and is therefore not evidence. | **Critical** | Stated in the dataset card, the labelling protocol and every derived report. The generalisation claim is refused. Only real CMS documents resolve it (R-33). | Open (accepted) | Data foundation |
| **R-39** | Gold labels could drift from the runtime decision if labelling used a separate implementation. | **Critical** | `app/decision/table.py` computes both. A test recomputes all 210 labels from their criterion states; disagreement fails the build. | **Mitigated** | Data foundation |
| **R-40** | An `UNKNOWN` criterion annotated as unknown in the note would hand the system a hint no real submission contains. | High | `unknown` is an omission in every case template, and a test asserts the word does not appear in any note. | **Mitigated** | Data foundation |
| **R-41** | Partition proportions drift on small strata, starving a partition. | Medium | **Found and fixed.** Rank-percentile assignment gave development 26% and validation 5%; exact per-stratum counts replaced it. | **Resolved** | Data foundation |
| **R-42** | A retrieval query copied from the criterion it targets makes retrieval look excellent and measures string matching. | High | Content-word overlap between query and criterion source must stay below 0.6; asserted by test. | **Mitigated** | Data foundation |
| **R-43** | Editing policy text that a criterion cites would silently invalidate the criterion. | Medium | Criterion verification runs at parse time and refuses the document. Discovered by an integration test whose edit tripped it. | **Mitigated** | Data foundation |

## Phase 2B findings

| ID | Risk | Impact | Mitigation | Status | Phase |
|---|---|---|---|---|---|
| **R-44** | Structural identifiers overlap: `(i)` is both the ninth letter and the first roman numeral, so a classifier reading a marker in isolation promotes sub-paragraphs to sections. Real 42 CFR 410.38 produced two sections both named "Paragraph (i)", and a criterion citing either would have collided. | **Critical** | `app/policy/hierarchy.py` resolves depth from sequence within a known parent. `tests/unit/test_hierarchy.py` **reproduces the defect against the naive rule** before proving the tracker prevents it. | **Resolved** | 2B |
| **R-45** | Body text detected as a section heading. A wrapped line beginning with a paragraph marker became a section name, anchoring criteria to prose rather than structure. | High | A heading may not itself begin with a paragraph marker. Section paths across all documents are now real headings or honest `Paragraph (x)` labels. | **Resolved** | 2B |
| **R-46** | **Integration tests destroyed the working corpus.** They TRUNCATE the corpus tables on setup; pointed at the working database, a full test run wiped an ingested 42 CFR corpus, left fixture rows behind, and the next retrieval evaluation reported 0.0000 recall because nothing resolved. Silent in both directions. | **Critical** | Tests now use a dedicated `medauth_test` database, and a regression test asserts the two URLs differ. This was OD-16, previously deferred to Phase 9; the corpus becoming real made it bite immediately. | **Resolved** | 2B |
| **R-47** | A criterion transcribed against one revision may not exist in another. 42 CFR 410.38 was restructured in 2019 and its 2026 criteria do not locate in that text. | High | Verification is per revision and refuses a mismatch. The 2019 revision has no transcription and generates no cases; the refusal is recorded rather than worked around. | **Mitigated** | 2B |
| **R-48** | A real, authoritative policy may still not support a decision. 42 CFR 411.15 declares only exclusions, so every standalone case reached the decision table's totality guard. | Medium | Marked `EXCLUSION_OVERLAY`; excluded from case generation with the reason recorded. Its criteria remain in the inventory and retrievable. | **Mitigated** | 2B |
| **R-49** | Curated code linkage could be mistaken for CMS policy. A regulation enumerates no procedure codes, so the mapping is engineering judgement. | High | Labelled `HUMAN_CURATED_ENGINEERING_LINKAGE`, header states it is authoritative for nothing, every link carries a rationale and confidence, and low-confidence entries exist deliberately. Asserted by test. | **Mitigated** | 2B |
| **R-50** | Transcription **completeness** is unverified. Span verification proves each transcribed criterion is faithful; nothing checks that the right criteria were chosen or that none was missed. | **High** | Not mitigated. Stated in the criteria inventory, the dataset card and every derived report. Only clinician review would resolve it. | **Open** | — |
