# Evidence Ledger: Claims and Their Proof

Every claim this project may make — in the README, in an interview, on a CV — is listed here with
the artefact that must exist first, how that artefact is produced, and where it will live.

**The rule:** if the artefact does not exist, the claim is not made. Not softened, not hedged — not
made.

**Status:** `Pending` (no artefact yet) · `Produced` (artefact committed, claim permitted) ·
`Refused` (the claim must not be made, with the reason).

**Last reconciled: 2026-08-23, end of Phase 3.** Rows marked `Produced` name the artefact that
produced them. A figure appearing here and nowhere in `eval/reports/` or `data/` is a defect.

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
| **Every criterion is traceable to a section, page and character span** | Span verification at parse time, rejecting unlocatable declarations | `pytest tests/evaluation/test_data_foundation.py` | **Produced** — 33/33 against the authoritative corpus, 0 failures; four rejection paths exercised including text found in the *wrong* section and in the *wrong revision* |
| **Gold labels are computed by the same function the system uses** | All labels recomputed from criterion states by `decide()` | Same | **Produced** — 222/222 reproduce exactly |
| **Criterion-level ground truth exists** | A state per applicable criterion, with the decision derived from them | `data/gold/cases/gold_v1.jsonl` | **Produced** — a decision label can never hide which criteria produced it |
| **The gold set is frozen and unscored** | Manifest hash asserted against the file; scoring budget recorded | `pytest tests/evaluation/test_data_foundation.py` | **Produced** — 156 cases, 0 of 1 scorings spent |
| **No gold label reaches the model's input** | Outcome and criterion-state vocabulary grepped out of every `input` | Same | **Produced** |
| **Case generation is deterministic** | Byte-identical rebuild from the same seed and corpus | `scripts/generate_cases.py` re-run | **Produced** |
| **No real patient identifiers are present** | SSN/email/phone/MRN/DOB patterns absent across the corpus | `pytest -m evaluation` | **Produced** |
| **Every criterion is traceable to AUTHORITATIVE policy text** | The same verification, against real government documents | `scripts/verify_criteria.py` | **Produced** (Phase 2B) — 33/33 against 42 CFR retrieved from the official eCFR API, public domain, date-addressable. Supersedes the earlier CMS-*shaped* corpus (R-33 closed) |
| The gold set is clinically validated | Review by a qualified clinician | — | **Refused unless performed.** No clinician has seen any case. The manifest records `clinically_validated: false`, and the Phase 3 audit marks all 156 cases `REQUIRES_REVIEW` |
| Inter-annotator agreement | Two or more independent labellers | — | **NOT produced, and not pending.** There is one labeller and it is a program; there is nothing to measure agreement between |
| **The provision walk is exhaustive** | Every provision at every hierarchy level enumerated and classified, with nothing left unclassified | `scripts/build_coverage_matrix.py`; `pytest -m evaluation` | **Produced** (Phase 3) — 356 provisions, 312 substantive, 0 unclassified |
| **Every excluded provision carries a recorded reason** | A reason string on each `NON_DECISION_RELEVANT` ruling | Same | **Produced** — silent exclusion is asserted impossible by test |
| **The criterion set is complete** | A qualified reviewer resolves every substantive provision | — | **NOT produced.** 247 of 312 substantive provisions await review; 7 concrete gaps confirmed. `completeness_verified` is `false` and a test forbids it flipping without review (R-50, OD-19) |
| **Code linkage is authoritative** | A source that itself establishes the policy-to-code relationship | — | **Refused for this corpus.** 42 CFR enumerates no procedure codes, so no link *can* be authoritative: 0 AUTHORITATIVE, 14 HUMAN_CURATED, 2 INFERRED. An NCD or LCD would carry the linkage itself (R-49, OD-21) |
| **The gold set was audited without being modified** | An audit report asserting the corpus is unchanged, plus a hash check | `scripts/audit_gold_set.py`; `pytest -m evaluation` | **Produced** (Phase 3) — 156 cases, `gold_set_unmodified: true`, all `REQUIRES_REVIEW`, nothing edited |
| The system reasons over local coverage policy | LCD/Article corpus ingested | — | **Refused.** LCDs sit behind an AMA/ADA/AHA licence gate that was not crossed. The corpus is statutory regulation only (R-55, ADR-022) |
| Measured performance transfers to real submissions | An evaluation on real de-identified notes | — | **Refused.** Constructed cases state each fact once, unambiguously, where a reader expects it |

## Policy logic (Phase 4)

| Claim | Evidence required | How produced | Status |
|---|---|---|---|
| **Policy logic can express AND, OR, NOT, at-least-n, exceptions, exclusions, conditional applicability and UNKNOWN** | A typed representation with a full Kleene truth table per connective | `pytest tests/unit/test_policy_logic.py` | **Produced** — every connective tested exhaustively, not sampled |
| **The 410.32 mammography exception is represented and produces the policy-consistent result** | A regression test asserting the old conjunction denies and the declared logic approves | Same | **Produced** — both halves asserted together, so the claim that the old logic was wrong is itself checked |
| **The rewrite never moves a case toward a denial** | Exhaustive comparison against the pre-Phase-4 table | Same | **Produced** — 512,460 combinations, 3,472 divergences, all `DENY_RECOMMENDED` → `NEEDS_INFO` |
| **gold_v1 is unchanged and still reproduces** | Byte hash plus label recomputation | `pytest -m evaluation` | **Produced** — 156/156 gold and 222/222 synthetic labels reproduce; gold file byte-identical |
| **nDCG cannot exceed 1** | Fuzz over random graded rankings | Same | **Produced** — 50 seeds, including degenerate and all-zero rankings |
| **Every policy version's logic form is recorded** | A generated inventory with unresolved semantics per policy | `scripts/build_logic_inventory.py` | **Produced** — 1 DECLARED, 2 ASSUMED_CONJUNCTION, 4 REVIEW_REQUIRED, 1 NO_CRITERIA |
| **The decision logic is correct for every policy in the corpus** | Declared logic for each version, confirmed by a qualified reader | — | **NOT produced.** Four versions carry exception wording and have no declared logic; the runtime assumes conjunction for them (R-59, OD-24) |
| **Passing decision-logic tests demonstrates clinical correctness** | — | — | **Refused permanently.** The tests establish that the code implements the declared logic. Whether the declared logic reads the regulation correctly is a question for a qualified reviewer, and no reviewer has seen it |

## Retrieval (Phase 4)

| Claim | Evidence required | How produced | Status |
|---|---|---|---|
| **A retrieval benchmark exists that discriminates between configurations** | Non-zero spread across arms on a frozen set | `eval/reports/20260823T151741Z__retrieval-v2/` | **Produced at rank 1** — Recall@1 spans 0.6429–0.8095. **Not produced at rank 3**: 0.9762 in every arm, and Recall@5 is 1.0000 in every arm |
| **The benchmark contains negative, ambiguous, temporal and exception queries** | The frozen set, asserted by test | `pytest -m evaluation` | **Produced** — 6 negative, 3 ambiguous, 8 historical, 4 cross-version pairs, 7 exception |
| **Every criterion is covered by a retrieval query** | Coverage check against the inventory | Same | **Produced** — 35 of 35 |
| **`ms-marco-MiniLM` outperforms the shipped reranker** | Separation at this denominator | The report | **NOT produced.** It leads on R@1, MRR and nDCG, but intervals overlap at n=42 and no default was changed |
| **Encoder choice affects the reranked pipeline** | Separation between encoders sharing a reranker | The report | **Refuted here.** `top_k` (40) exceeds the largest scope (25 chunks), so first-stage retrieval never filters and both reranked pairs are byte-identical across encoders (R-58) |
| **Resolution generalises to codes outside the linkage table** | A query resolving through a code nobody curated | — | **Refused.** No such code resolves to anything. Resolution accuracy of 1.0000 measures the table's self-consistency; recorded as a `KNOWN_LIMITATION` in the leakage audit |
| **The system declines to retrieve when nothing is relevant** | An abstention threshold with a calibration report | — | **NOT produced.** False retrieval rate is 1.0000 (6/6) in every arm; dense retrieval has no abstention mechanism and none is implemented |

## Fail-closed semantics (Phase 5)

| Claim | Evidence required | How produced | Status |
|---|---|---|---|
| **Unverified policy semantics cannot approve or deny** | Exhaustive check over the generated input space, with a positive control and an anti-vacuity clause | `pytest tests/unit/test_fail_closed_semantics.py` | **Produced** — three unverified states × the full space; the attested control reaches both APPROVE and DENY, and every adjudicating input is stopped by a semantics rule |
| **The `assumed_conjunction` fallback is gone, not defaulted** | Signature assertion plus an injection test | Same | **Produced** — `semantics` has no default; restoring the fallback fails the invariant test |
| **An unattested assumption cannot execute** | Constructor demotion, tested directly | Same | **Produced** — the type cannot represent an unattested executable status |
| **Corpus and wiring failures are distinguishable in the audit** | Distinct rules on the recommendation | Same | **Produced** — rule 12 vs rule 13, plus `policy_semantics` and `semantics_origin` fields |
| **The gold_v1 replay is refused in production** | Origin and digest checks, each tested separately | `pytest tests/security/test_replay_refused_in_production.py` | **Produced** — refused on two independent grounds; the positive control shows it genuinely executes outside production |
| **Production adjudication is safe for every policy in the corpus** | — | — | **Refused.** 3 of 8 policy versions are adjudicable. The other 5 route to a human, and that is the intended behaviour, not a gap to be closed by relaxing the gate |

## Coverage layer (Phase 5)

| Claim | Evidence required | How produced | Status |
|---|---|---|---|
| **A CMS NCD corpus was acquired with full provenance** | Source URL, acquisition timestamp, content hash and version identity per version | `data/coverage/registry.yaml`; `pytest -m evaluation` | **Produced** — 10 documents, 19 versions, all four fields present on every version |
| **Acquisition coverage is stated, not implied** | Selected / acquired / refused / unreachable, reconciling | Same | **Produced** — 11 selected, 10 acquired, 1 refused, 0 unreachable |
| **The complete CMS NCD corpus was acquired** | — | — | **Refused.** 11 determinations were selected deliberately and the record says so. This must never be described as "the CMS NCD corpus" |
| **An undated determination cannot be temporally resolved** | Unreachable by resolution AND retrieval, with a dated positive control | `pytest tests/integration/test_temporal_resolution.py` | **Produced** — 3 of 19 versions; no date of service reaches them |
| **NCD temporal coverage is complete** | — | — | **Refused.** 3 of 19 acquired versions have no published effective date. That is a property of the source, and no derived date is substituted |
| **Version history is not truncated by probing** | Enumeration from the authoritative version list | `app/coverage/ncd.py::version_list` | **Produced** — a 200-with-empty-data response is `NO_VERSION_DATA`, never `END_OF_HISTORY` |
| **Regulation and coverage cannot cross in retrieval** | Two layers, same code, same date, identical text; each scope returns only its own | `pytest tests/integration/test_retrieval_scope.py` | **Produced** — neither similarity nor the temporal predicate can separate them, so only the partition can |
| **Absence of an NCD is not a denial** | `NOT_ESTABLISHED` distinct from `NOT_COVERED`, tested | `pytest tests/unit/test_ncd_temporal.py` | **Produced** — and no `CoverageStatus` member names an outcome |
| **CMS supplies NCD-to-procedure-code linkage** | — | — | **Refused.** The NCD record carries no procedure-code field: 19 fields, none of them codes, verified by live probe. Linkage is `HUMAN_CURATED` (OD-27) |
| **The coverage layer establishes coverage for any specific item** | A reviewer-recorded status per NCD version | — | **NOT produced.** Every governing NCD resolves `UNKNOWN`; status is never inferred from `indications_limitations` prose (R-61, OD-26) |
| **This system reasons over local contractor policy** | An LCD corpus | — | **Refused.** LCD and Article endpoints sit behind an AMA/ADA/AHA licence gate; no agreement was accepted and neither was requested (OD-21) |

## Policy identity and coverage substantiation (Phase 6)

| Claim | Evidence required | How produced | Status |
|---|---|---|---|
| **Policy type participates in identity** | A composite key with type first, and no constructor that omits it | `pytest tests/unit/test_policy_identity.py` | **Produced** — `(policy_type, policy_id, version)`; a mismatched prefix is refused |
| **A regulation and a coverage determination cannot be confused** | An end-to-end collision with every other discriminator removed | `pytest -m integration` | **Produced** — same code, revision id, date and byte-identical text; each scope returns only its own chunk |
| **R-62 is resolved** | Both eval runners and the linkage loader corrected, with a regression test | Same | **Produced** — dropping type from the identity key fails the unit tests |
| **An engineering-inferred link cannot establish applicability** | A resolution filter, tested with a curated positive control | Same | **Produced** — removing the filter fails the test |
| **A coverage status is never derived from metadata** | The absence of title/code/similarity parameters, asserted | `pytest tests/unit/test_coverage_status.py` | **Produced** — plus demotion of any substantive status with no located evidence |
| **Any NCD establishes coverage for anything** | A reviewer-recorded status | — | **NOT produced.** 19 versions await review; all establish `UNKNOWN` (R-65, OD-26) |
| **Any code link is authoritative** | A source that states the relationship | — | **Refused for these sources.** The MCIM NCD record has no procedure-code field; 0 of 22 links are `SOURCE_STATED` |
| **Review decisions are versioned and history is not mutated** | Supersession rules, tested | `pytest tests/unit/test_review_and_contracts.py` | **Produced** — a version may supersede only an earlier one, only with a reason |
| **The blast radius of a review decision is known before it is made** | A traced impact report over the frozen corpora | `scripts/analyse_review_impact.py` | **Produced** — 10 of 15 reviewable subjects reach gold; 69 of 156 cases reachable |
| **gold_v1 is unchanged** | Byte hash against the manifest | `pytest -m evaluation` | **Produced** — byte-identical; no gold_v2 |
| **Abstention is representable without a calibrated threshold** | Eight structural states, each with a remedy, and an explicit `UNCALIBRATED` gate | `pytest tests/unit/test_review_and_contracts.py` | **Produced** — no reason yields an approval or a denial |
| **A confidence threshold has been calibrated** | A dev-split sweep under ADR-011 | — | **Refused.** `ScoredGate` is `UNCALIBRATED` and records it |
| **A policy version is admissible for a first AI vertical slice** | Seven conditions, all passing | `scripts/assess_slice_admissibility.py` | **NOT produced.** The nearest fails one: 42 CFR 410.32 C03 depends on untranscribed `(b)(3)` (R-66) |
| **The preferred model is better at clinical reasoning** | A measured comparison | — | **Refused.** Phase 0 measured structured-output support, not reasoning quality |

## Pre-agent gate (Phase 7)

| Claim | Evidence required | How produced | Status |
|---|---|---|---|
| **42 CFR 410.32(b)(3) is located in the authoritative source** | The eCFR document already in the corpus, with its hash | `data/cms/CFR-410_32-2026-08-13.md`, sha256 `d87f3242f432…` | **Produced** — no summary, no secondary site, no paraphrase |
| **Its transcription is span-verified** | The gate rejecting wrong text, wrong section, wrong version and a malformed record | `scripts/verify_criteria.py`; injection of all four | **Produced** — 37/37 verified, 0 failures; the fourth mode was *not* caught until Phase 7 fixed it |
| **Source verification is not qualified review** | Two disjoint vocabularies, and a resolution state that does not permit adjudication | `pytest tests/evaluation/test_phase7_gate.py` | **Produced** — treating source-verified as permission fails the test |
| **C03's dependency is closed** | A reviewer ruling that C03 is adjudicable | — | **NOT produced.** `PARTIALLY_RESOLVABLE_FROM_SOURCE`: which supervision level applies is set by the physician fee schedule, absent from 42 CFR (R-51) |
| **A policy version is admissible for the first slice** | Seven conditions, all passing | `scripts/assess_slice_admissibility.py` | **NOT produced.** 410.32 passes six; the seventh is FOCUS-001 |
| **The admissibility gate was not loosened to obtain a pass** | The gate still refusing 410.32, on the same condition | `pytest -m evaluation` | **Produced** — an unconditional pass on that check fails the test |
| **gold_v1 is byte-identical** | Hash against the manifest | Same | **Produced** — 156 cases, 0 scorings, no gold_v2; no gold case references a Phase 7 criterion |
| **Every evaluation query can prove its provenance chain** | A per-query classification against the corpus as it stands | `scripts/audit_evaluation_provenance.py` | **Produced** — v1 16/23 and v2 36/52 usable; **0 are `VALID_AUTHORITATIVE`, and none can be** |
| **Inferred-linkage queries are flagged, not repaired** | Every 410.61-targeting query classified `INVALID_INFERRED` | `pytest -m evaluation` | **Produced** — reclassifying them as valid fails the test; the links were **not** restored |
| **`retrieval_eval_v3` is derived by provenance, not by results** | A recorded exclusion list and a selection basis | `eval/datasets/retrieval_v3/questions.yaml` | **Produced** — 36 of 52 kept, every exclusion carrying its reason |
| **v3 measures anything** | A committed report | — | **NOT produced.** v3 has never been scored, and no v2 number may be attributed to it (OD-28) |
| **Any criterion is qualified-reviewed** | A signed reviewer decision | — | **NOT produced.** 37 `SOURCE_VERIFIED`, **0 `QUALIFIED_REVIEWED`** |
| **Anything is clinically validated** | — | — | **Refused permanently unless performed.** No enum in this codebase has a member for it |

## Domain decision gate (Phase 8)

| Claim | Evidence required | How produced | Status |
|---|---|---|---|
| **FOCUS-001 is unanswered** | A committed record with empty reviewer fields | `data/review/focus_001_decision.json` | **Produced** — `PENDING`, `is_resolved: false`, every reviewer field `null` |
| **No code path can answer it** | No constructor yielding an accepted gate; submission and acceptance separate | `pytest tests/unit/test_decision_gate.py` | **Produced** — `pending()` is the only classmethod; treating `SUBMITTED` as resolving fails the suite |
| **Production stays blocked while it is open** | The admissibility gate reading the record | `pytest -m evaluation` | **Produced** — ignoring the open gate fails a test |
| **Every possible outcome's impact is computed in advance** | A deterministic four-way table | `app/review/focus_impact.py` | **Produced** — same inputs, same table; `OTHER` deliberately unmodelled |
| **The impact table recommends nothing** | Costs stated for every option, including what each gives up | Same | **Produced** — the cheapest option is also the one that checks least, and the table says so |
| **A qualified reviewer has answered FOCUS-001** | A signed, accepted decision | — | **NOT produced.** This is the one thing Phase 8 cannot produce |
| **Every retrieval query proves its provenance chain** | Six-way classification over all three sets | `scripts/audit_evaluation_provenance.py` | **Produced** — v1 16/23, v2 36/52, **v3 36/36** |
| **A retrieval benchmark is trustworthy enough for a configuration comparison** | Clean provenance **and** demonstrated discrimination | `scripts/assess_retrieval_readiness.py` | **NOT produced.** `RETRIEVAL_BENCHMARK_NOT_READY` — v2 discriminates but is contaminated; v3 is clean and unscored |
| **Any retrieval configuration is better than another** | A comparison on a ready benchmark | — | **Refused.** No comparison may be run while the status is NOT_READY; nominating the least bad set would manufacture a result |
| **A policy version is admissible for the first slice** | Eleven conditions, all passing | `scripts/assess_slice_admissibility.py` | **NOT produced.** `BLOCKED`. 410.32 passes nine; the two it fails are both FOCUS-001 |
| **gold_v1 is unchanged** | Hash against the manifest | `pytest -m evaluation` | **Produced** — 156 cases, 222 synthetic, 0 scorings, no gold_v2 |

## Pre-slice readiness (Phase 9)

| Claim | Evidence required | How produced | Status |
|---|---|---|---|
| **An external decision cannot be forged in one act** | Submission and acceptance as separate entry points with separate attribution | `pytest tests/unit/test_phase9_contracts.py` | **Produced** — self-acceptance, acceptance without submission and acceptance predating submission are each refused; all three mutations fail the suite |
| **One authority decides whether inference may run** | A single gate reading committed artefacts, failing closed on any read error | `app/production_gate.py` | **Produced** — five checks; `_load()` returns `None` on any error and `None` is `BLOCKED`; `require()` raises |
| **Production inference is blocked today** | The real repository's gate evaluated | `pytest -k the_real_repository_gate_is_blocked` | **Produced** — `BLOCKED` on `domain_decisions_accepted` and `policy_slice_admissible` |
| **A gold_v2 can be planned without creating or touching one** | A planner with no write path, and gold_v1's digest unchanged | `app/review/migration.py`, `data/review/gold_v2_migration_plan.json` | **Produced** — no filesystem import at all, asserted over the AST; all four outcomes planned; gold_v1 `ca990b80…` unchanged |
| **Every slice boundary has a closed schema** | Frozen, `extra="forbid"` models with validators that refuse unsupported assertions | `app/contracts/slice.py` | **Produced** — a decided assessment without evidence, and an asserting mapping without a citation, are each refused; both mutations fail |
| **The slice vocabulary narrows the adjudication vocabulary totally** | A mapping asserted total and injective | `pytest -k vocabulary_narrows` | **Produced** — R-77; adding a member to either enum fails the test |
| **The contract fixtures involved no model call** | Hand-written fixtures, committed, with a stated provenance | `tests/fixtures/slice/README.md` | **Produced** — 8 fixtures; **0 model calls in Phase 9** |
| **The fixtures do not presume an answer to FOCUS-001** | C03 absent from every fixture | Same | **Produced** — only C01, C02 and C04 appear |
| **Historical replay cannot enable production** | Replay refused on origin and on digest; no path from replay into the gate | `pytest tests/unit/test_layer_boundaries.py` | **Produced** — two AST rules; the gate neither imports nor names the replay constructor |
| **A reviewer has answered FOCUS-001** | A submitted and accepted decision with full attribution | `data/review/focus_001_decision.json` | **Produced (2026-08-24)** — `LEAVE_C03_NOT_ADJUDICABLE`, submitted and accepted by `picoders1`, marked `SINGLE_PARTY_EXEMPTED` under ADR-026. The wording was drafted by the assistant and adopted by the reviewer, who confirmed it as their own reading |
| **FOCUS-001 was accepted independently** | A second party accepting | — | **Refused.** The submitter accepted their own decision under the ADR-026 exemption; the record says so on its face |
| **The answer made 42 CFR 410.32 admissible** | The gate reporting it admissible | `data/review/slice_admissibility.json` | **NOT produced.** `LEAVE_C03_NOT_ADJUDICABLE` leaves C03 as written, so the dependency blocker stands. The impact table predicted this before the answer existed |
| **The first vertical slice works** | A slice run against an admissible policy | — | **NOT produced.** Not implemented. No agent, prompt or model call exists |
| **The system is clinically validated** | A study with qualified clinicians on real cases | — | **Refused.** No field, enum member or flag anywhere in the codebase represents it, asserted by `test_clinical_validation_has_no_member_anywhere`. `SOURCE_VERIFIED` and `QUALIFIED_REVIEWED` are different claims and neither implies this one |

## Domain decision attribution (ADR-026)

| Claim | Evidence required | How produced | Status |
|---|---|---|---|
| **A single-party acceptance is visible in the record** | A permanent marker on the decision, not droppable | `app/review/decision_gate.py` | **Produced** — `SINGLE_PARTY_EXEMPTED`; a record claiming `TWO_PARTY` while naming one identity for both acts is refused at construction |
| **The exemption cannot be taken silently** | Three separate declarations, none inferred | `pytest tests/evaluation/test_focus_packet_integrity.py` | **Produced** — opt-in, authority checked as a constant, ≥12-word justification; six mutations all fail |
| **The exemption relaxes exactly one check** | Every other refusal still fires under it | Same | **Produced** — ordering, missing date and wrong-status refusals all hold |
| **FOCUS-001 was accepted under separation of duties** | An independent second party accepting | — | **Refused for any decision carrying the marker.** The permitted claim is narrower and true: a reviewer's decision was recorded, and the independent-acceptance control was deliberately exempted under ADR-026 |
| **This exemption is appropriate outside a synthetic-data portfolio system** | An ADR arguing that case on its own facts | — | **Refused.** ADR-026 is scoped and says so; OD-32 records what is unsettled |

## Policy logic review (OD-19)

| Claim | Evidence required | How produced | Status |
|---|---|---|---|
| **The OD-19 target was selected by the gate, not by preference** | The only version whose failed checks are a subset of the semantics pair | `pytest -k chosen_by_the_gate` | **Produced** — 42 CFR 410.33 is the sole such version; a different choice would have to change the admissibility report |
| **Every quoted provision matches the regulation verbatim** | Build-time location with a declared end | `scripts/build_od19_packet.py` | **Produced** — 5 provisions located; a moved or reworded provision fails the build, and every quoted line is asserted present in the source |
| **The packet builder cannot answer its own question** | No transition call, one constructor | AST test | **Produced** — `DecisionGate.pending` is the only constructor reached; adding a `submit`/`accept` call fails the suite |
| **42 CFR 410.33 has a declared decision logic** | A committed logic file that loads and executes | `data/policy_logic/42-CFR-410.33.yaml` | **Produced (2026-08-24)** — engineering-curated on the same terms as 410.32's, with three provisions recorded as UNRESOLVED rather than guessed |
| **A policy version is admissible for the first slice** | Eleven conditions, all passing | `scripts/assess_slice_admissibility.py` | **Produced (2026-08-24)** — `READY`, designated slice `REGULATION:42 CFR 410.33:2026-08-13` |
| **The 410.33 criteria are the right ones** | A qualified reviewer answering `OD-19-410.33` | — | **NOT produced.** The declaration states how five transcribed criteria combine; it does not claim they are the right five, and 38 of 59 provisions remain unreviewed |
| **The declared conjunction is correct for every case that can reach 410.33** | No (a)(2)-exempt code linked to the policy | `pytest -k a2_exemption` | **Produced, conditionally** — true while R0075 is the only linked code; the test fails the moment that changes (OD-34, R-83) |

## First AI vertical slice (Phase 11)

| Claim | Evidence required | How produced | Status |
|---|---|---|---|
| **The architecture runs end to end** | A slice from note to audit event on an admissible policy | `scripts/run_first_slice.py` | **Produced (2026-08-24)** — `REGULATION:42 CFR 410.33:2026-08-13`, 9 scenarios, `eval/reports/first-vertical-slice/report.json` |
| **Every refusal is explainable by a rule** | Expected outcomes derived from the decision table, not from a run | Same | **Produced** — 9/9 agreement; expectations come from the table's rows |
| **The model cannot emit an outcome** | No approval or denial token in instructions, evidence block or schema | `pytest -k never_sees_an_outcome_token` | **Produced** — asserted over all three |
| **Retrieved text reaches the model only as fenced data** | A single chokepoint, framed, delimiter-neutralised | `app/adjudication/evidence_block.py` | **Produced** — merging it into instructions fails the suite |
| **Every gateway failure routes to a human** | Parameterised over the whole enum | `pytest -k routes_to_a_human` | **Produced** — none routes to a denial |
| **A blocked request is never retried** | Exactly one call, asserted by count | `pytest -k called_once_and_never_re_run` | **Produced** — strengthened after a mutation showed the prose-based version was vacuous |
| **No audit event carries clinical text** | The serialised events searched for note content | `pytest -k no_audit_event_carries` | **Produced** — there is no field it could go in |
| **The slice ran against a live model** | A gateway call to the firewall | — | **NOT produced.** `model_calls: 0`; every response came from a fixture |
| **The measured latencies reflect production** | A run with inference in the loop | — | **Refused.** They are the cost of the pipeline; a real call would dominate all four stages |
| **Clinical accuracy / clinical validation** | A study with qualified clinicians | — | **Refused.** Unchanged, and nothing in this slice moves it |
| **The retrieval configuration was chosen on evidence** | A comparison on a ready benchmark | — | **Refused.** `RETRIEVAL_BENCHMARK_NOT_READY`; the configuration is unevaluated, not selected |

## Pre-Phase-12 remediation (2026-08-25)

| Claim | Evidence required | How produced | Status |
|---|---|---|---|
| **The suite runs from a clean checkout** | A run with `data/cms/*.md` absent | simulated: corpus moved aside | **Produced** — 522 passed, 44 skipped, 0 failed. Previously aborted at collection |
| **Corpus-dependent tests are visibly classified** | A skip reason naming the missing files | `pytest -rs` | **Produced** — the reason names the files and the acquisition command |
| **The production gate is enforced at the runtime boundary** | A refusal on direct construction | `pytest -k blocked_gate_prevents` | **Produced** — enforced in `SliceRunner.__init__`; 4 mutations caught |
| **A concrete `ModelGateway` exists** | A class satisfying the protocol | `app/llm/firewall_gateway.py` | **Produced** — 19 contract tests over `MockTransport`; **no provider called** |
| **The test double satisfies the protocol** | `isinstance` and a static assignment | `mypy --strict tests/support_slice.py` | **Produced** — was `False` before this pass |
| **Safety mutations are caught repeatably** | A harness in CI | `scripts/mutation_guard.py` | **Produced** — 11/11 caught, tree verified unchanged |
| **The model gateway works against a real provider** | A live call | — | **NOT produced.** No model call has been made in any phase |
| **Real model behaviour is verified** | Inference in the loop | — | **NOT produced.** `MODEL_REASONING_QUALITY_NOT_YET_EVALUATED` |

## Live model activation (Phase 12, 2026-08-25)

| Claim | Evidence required | How produced | Status |
|---|---|---|---|
| **A model has been called through the full path** | One live structured call reaching the internal contract | smoke call, `OK` 1050 ms | **Produced** — `MEDAUTH → FirewallGateway → firewall → provider` |
| **The deployment supports strict `json_schema`** | n=5 per arm on the live path | `eval/reports/20260825T070854Z__model-capabilities/` | **Produced, scoped** — 5/5 on the probe schema. **Not** a blanket claim: the same model fails to terminate on `IntakeResult` (R-86, R-87) |
| **`json_object` is not a usable fallback** | Schema validity under the unconstrained mode | Same | **Produced** — 5/5 returned, **0/5 schema-valid** |
| **The deterministic engine still owns the recommendation** | No live run producing an approval or denial from the model | `eval/reports/first-slice-live/` | **Produced** — every case reached `NEEDS_INFO`, `HUMAN_REVIEW` or `NO_DECISION` |
| **No outcome token reaches the model or its free text** | Scan of every assessment across the matrix | Same | **Produced** — zero occurrences |
| **A firewall 403 fails closed and is not retried** | A live block, attempt count | Same | **Produced** — one real 403 in 22.6 ms, one attempt, routed to a human |
| **Live latency and token usage** | Per-stage measurement on real calls | Same | **Produced** — decision 0.1–0.2 ms, citations 1.7–3.1 ms, 24 calls / 14,526 in / 3,370 out |
| **Verdicts are reproducible** | Repeated identical requests | Same | **Produced, narrow** — 3/3 identical on one case. Bytes are **not** deterministic (probe) |
| **Cost per case** | A price basis for this deployment | — | **NOT produced.** None is recorded; inventing one would be fabricated |
| **Injection is contained** | The attack assessed and refused | Same | **Partly.** D contained structurally; E contained by the firewall — a layer with 0.1423 recall that we do not rely on; **G was never assessed at all** and is not evidence of containment |
| **Clinical accuracy / clinical validation** | A study with qualified clinicians | — | **Refused.** No scenario carries an expected answer |
| **Model reasoning quality** | A held-out benchmark | — | **`MODEL_REASONING_QUALITY_NOT_YET_EVALUATED`** |
| **Retrieval configuration is justified** | A ready benchmark | — | **Refused.** `NOT_READY`, and Phase 12 tuned nothing |

## Phase 13 — guardrail closure and retrieval evaluation

| Claim | Evidence required | How produced | Status |
|---|---|---|---|
| **Contradiction detection is reachable in the real runtime** | Decision-table row 5 produced by a live pipeline, not a unit call | `pytest -k contradiction_stops_the_case` | **Produced** — R-89 closed; 3 mutations catch a regression |
| **The detector does not fire on ordinary cases** | A control case that must stay quiet | `pytest -k not_flagged_as_contradictory` | **Produced** — half the contradiction tests exist for this; a detector that over-fires is switched off |
| **UNDETERMINED is non-decisive** | It neither stops a case nor clears one | `pytest -k undetermined` | **Produced** — "could not check" is kept apart from "checked and clean" |
| **Semantic contradiction is detected** | Conflicting values across different spans | — | **Refused.** Out of scope by design: judging it requires reading, and a detector that inferred clinical meaning would be adjudicating the adjudicator |
| **A fabricated evidence id cannot support a verdict** | Adversarial ids rejected structurally | `pytest -k forged_evidence_id` | **Produced** — 13 adversarial ids incl. the fence delimiter R-88 observed live |
| **R-86 is fixed** | A change in the decoder | — | **Refused.** Mitigated only. `docs/escalations/R-86-unbounded-whitespace.md` — reproducible 3/3 both ways, and not ours to fix |
| **The application lifecycle works end to end** | Submit -> run -> audit -> recommendation -> human review -> finalize, with a deterministic fixture and no live provider | `pytest tests/integration/test_application_lifecycle.py` (14) | **Permitted, scoped.** `APPLICATION_LIFECYCLE_VERIFIED_INDEPENDENT_OF_LIVE_PROVIDER`. A property of this code. Says **nothing** about model quality - a fixture returns what it is told |
| **A recommendation cannot become a disposition without a human** | No `RECOMMENDATION_READY -> FINALIZED` edge in the transition table | `pytest tests/unit/test_case_lifecycle.py` + 2 mutations | **Permitted.** A graph property, not a convention |
| **The audit trail is immutable** | — | — | **Refused as stated.** A superuser can drop a trigger. The earned claim is narrower: *no application code path can mutate recorded audit events* - `tests/integration/test_audit_append_only.py`, proven against non-empty tables |
| **The reviewer who decided a case is authenticated** | A validated OIDC token whose subject becomes the audit identity | `pytest tests/security/test_reviewer_identity.py tests/integration/test_reviewer_audit.py` (30) | **Permitted (OD-43).** The request body cannot name a reviewer - the field does not exist - and a SERVICE principal is refused human-only actions before its permissions are read. Historical rows stay labelled `LEGACY_CALLER_SUPPLIED` |
| **Enterprise SSO is deployed** | A real identity provider integrated and exercised | — | **Refused.** The OIDC adapter is implemented and tested against a symmetric key and a JWKS client. No IdP is integrated; that is a deployment task this repository has not performed |
| **The reviewer is qualified to decide** | Verified credentials | — | **Refused.** The system verifies identity, not competence. `stated_qualification` is what the person said. Whether the right people are reviewing is **OD-19**, and it is open |
| **R-86 is attributed to a provider component** | A provider-internal trace | — | **Refused.** `PROVIDER_SIDE` is established - the proxy is eliminated by its owner's own records - but which component inside the provider is `NOT_ESTABLISHED`, and six hypotheses are listed with none selected |
| **retrieval_v3 is provenance-clean and scored once** | Integrity check before scoring, budget respected | `eval/reports/20260825T100405Z__retrieval-v3/` | **Produced** — 36 queries, sha `c8a7d9e2…`, budget 1/1 |
| **A retrieval configuration is empirically selected** | A statistically supported separation | exact McNemar, 15 pairs | **NOT produced.** Best p = 0.0625, which is the **minimum achievable at n=31**. `RETRIEVAL_CONFIGURATION_UNRESOLVED` |
| **The adopted reranker is an engineering default** | Point estimates and latency, labelled as such | `docs/evaluation/retrieval-configuration-decision.md` | **Produced** — and explicitly not a selection |
| **The retrieval configuration is optimal** | A ready benchmark that separates arms | — | **Refused** |
| **The encoder choice matters** | A measurable difference | — | **Refused.** Both encoders identical on every query at `top_k=40` (R-92) |
| **The 26-case evaluation is ready to run** | A manifest frozen before any number exists | `data/review/eval_410_33_frozen.json` | **Produced** — `FROZEN_NOT_RUN`, 24 metrics named in advance |
| **The 26-case evaluation result** | A run against the frozen split | — | **NOT produced.** Running it spends a scoring from the gold_v1 budget |
| **Clinical accuracy** | — | — | **Refused**, unchanged |

## Frozen 410.33 evaluation (Phase 14)

| Claim | Evidence required | How produced | Status |
|---|---|---|---|
| **The experiment was frozen before it ran** | A manifest with an earlier timestamp than the run | `eval/reports/frozen-410-33/manifest.json` | **Produced** — frozen 10:59:18, ran 11:07:42 |
| **All 26 cases attempted, none excluded** | Per-case records for the full frozen set | `per_case.json` | **Produced** — 26/26, `cases_excluded: 0` |
| **Decision accuracy on this set** | A scored run against frozen labels | `metrics.json` | **Produced** — 6/26 = 0.2308 (0.1103–0.4205). **Right for the right reason: 3/26** |
| **Safety invariants hold** | Seven rates, all zero | Same | **Produced** — 0/26 on every one |
| **Citation validity** | Deterministic span verification | Same | **Produced** — 1.0000 (16/16), zero failures, no LLM-as-judge |
| **The system produced any approval** | — | — | **NOT produced.** Zero approvals against 7 expected |
| **Denial precision** | Own denominator | Same | **Produced** — 0/1. The single denial was the unsafe one |
| **This measures system reasoning performance** | An evaluation not dominated by a provider defect | — | **Refused.** `EVALUATION_MATERIALLY_DEGRADED_BY_PROVIDER_FAILURE` — R-86 removed 38% of cases, and the survivors are not a random sample |
| **The slice resolves policy applicability** | Row 1 reachable | — | **Refused.** It does not resolve; R-93. One denial resulted from adjudicating an inapplicable policy |
| **Clinical accuracy / validation** | — | — | **Refused**, unchanged |
| **The retrieval configuration is justified by this run** | — | — | **Refused.** Fixed as a pre-registered engineering default, deliberately not a variable |

## Policy applicability and the Phase-15 run (Phase 15)

| Claim | Evidence required | How produced | Status |
|---|---|---|---|
| **Policy applicability is resolved at runtime** | A stage that runs before intake, over six states, and refuses on five of them | `app/policy/applicability.py`, `app/policy/live_applicability.py`; `pytest tests/unit/test_policy_applicability.py` | **Produced** (Phase 15) — 26/26 cases recorded a resolved state and a reason; `run_mode: PRODUCTION` on every one |
| **An inapplicable policy cannot produce a definitive decision** | A regression reproducing the Phase-14 conditions, proven load-bearing | `pytest tests/integration/test_case_0073_regression.py`; `python scripts/mutation_guard.py` | **Produced** (Phase 15) — 4 of 19 mutations target this rule and all 4 are caught |
| **No model output can bypass policy applicability** | Seven attack shapes against five refusing states, asserting on model calls and not only on outcomes | `pytest tests/security/test_applicability_cannot_be_bypassed.py` | **Produced** (Phase 15) — 15 tests; applicability decides before the model is called |
| **The Phase-15 run exercised a refusing applicability state** | At least one case reaching a non-`RESOLVED` state | — | **NOT produced.** All 26 cases resolved. The refusing states are verified by fixtures and mutations, **not by this run** |
| **The unsafe denial was removed by the applicability fix** | CASE-0073 taking a different path because applicability refused | — | **Refused.** CASE-0073 **resolves** (R-97), so the fix did not change its path. The Phase-14 denial did not recur, and that is a different fact from having been prevented |
| **Decision accuracy on this run** | A scored run against frozen labels | `eval/reports/phase15-410-33/metrics.json` | **Produced** — 8/26 = 0.3077 (0.1650–0.4999). **Right for the right reason: 4/26.** Carries `DEGRADED_BY_PROVIDER_FAILURE` |
| **This measures system reasoning performance** | An experiment the pre-registered rule classifies as valid | — | **Refused.** `provider-failure-validity.v1` returns `DEGRADED_BY_PROVIDER_FAILURE` on condition 1 (10/26 = 0.3846) |
| **Phase 15 is an improvement over Phase 14** | Two runs both interpretable as performance | — | **Refused.** Neither run is interpretable as performance, and comparing two degraded numbers compares two outage draws |
| **Safety invariants hold** | Seven rates, all zero | Same | **Produced** — 0/26 on every one, **and zero unsafe definitive decisions** (Phase 14 had one) |
| **Citation validity** | Deterministic span verification | Same | **Produced** — 1.0000 (16/16), 59 citations verified, no LLM-as-judge |
| **The system produced any approval or denial** | — | — | **NOT produced.** Zero of each, against 7 expected of each. Coverage 0.0000 |
| **R-86 is fixed** | A change in the decoder, evidenced by the provider | — | **Refused.** Not fixed. Phase 15 established it is input-length dependent; ownership is still undetermined |
| **gold_v1's not-applicable cases are labellable from their input** | Structured input that a deterministic resolver refuses | — | **Refused (R-97).** Three cases encode non-applicability only in the narrative. Reported as `DATASET_DEFECT`, never excluded; a gold_v2 is OD-37 |

## Measurement recovery (Phase 16)

| Claim | Evidence required | How produced | Status |
|---|---|---|---|
| **Provider failures are classified, not conflated with model errors** | A taxonomy that cannot see accuracy, with an attribution per kind | `app/llm/failure_taxonomy.py`; `pytest tests/unit/test_provider_failure_taxonomy.py` | **Produced** (Phase 16) — 11 kinds, 4 attributions; a test asserts the classifier has no accuracy parameter |
| **R-86 is input-length dependent** | A controlled experiment varying only length | `eval/reports/r86-gradient/results.json` | **WITHDRAWN.** The Phase-15 reading is not supported: 0/56 up to 908 prompt tokens. It came from arms that varied three factors at once |
| **R-86 needs schema + length + real content together** | A crossed factorial with per-cell denominators | `eval/reports/r86-gradient/factorial_results.json` | **Produced** (Phase 16) — 6/6 in `intake/gold_note/long`, 0/42 elsewhere; 522 filler tokens succeed where 512 clinical tokens fail |
| **The responsible layer is the provider / the firewall** | A request issued provider-side | — | **Refused.** `PROVIDER_DECODER` and `FIREWALL_PROXY` remain indistinguishable from this side. `OUTSIDE_ENGINEERING_CONTROL` |
| **R-86 is fixed** | A change in the decoder, evidenced by its owner | — | **Refused**, unchanged |
| **A local mitigation for R-86 exists** | A request property that predicts the failure | — | **Refused.** No length threshold is supported: filler at 522 tokens succeeds, clinical text at 512 fails |
| **gold_v2 encodes applicability in structured data** | Every case's state re-derived from input plus the committed linkage | `pytest tests/evaluation/test_gold_v2.py` | **Produced** (Phase 16) — 156/156, and all 156 labels reproduce under `decide()` |
| **gold_v1 is unchanged** | Byte-identical to its manifest | Same | **Produced** — `ca990b80…`; the migration refuses to run if it moved |
| **The retrieval benchmark's provenance is clean** | Every query's authority chain resolving against committed artefacts | `data/review/retrieval_v4_provenance.json` | **Produced** (Phase 16) — 36/36 scorable, 0 invalid, 10 categories, and the audit is proven able to fail |
| **Retrieval baseline of the shipped configuration** | One arm, frozen configuration, correct arithmetic | `eval/reports/retrieval-v4-baseline/results.json` | **Produced** — Recall@1 0.7742 (24/31), nDCG@5 0.8987, false retrieval 5/5 on negatives |
| **This retrieval configuration is best** | A comparison with a detectable difference | — | **Refused.** `ENGINEERING_DEFAULT_UNRESOLVED`; 36 queries cannot separate arms |
| **Two denominators are reported, never one** | Operational coverage and decision quality side by side | `eval/reports/phase15-410-33/coverage.json` | **Produced** — 12/26 operational, 4/12 decision quality, 8/26 whole-run; none is "the accuracy" |
| **No case is silently excluded** | Buckets summing to attempted, every case named | Same | **Produced** — six dispositions, arithmetic asserted |
| **Cost per case** | Token counts with a price basis on the run date | — | **NOT produced — `COST_NOT_AVAILABLE`.** No price basis is recorded; MEDAUTH holds no provider account and the model id is a deployment value |
| **`phase16-evaluation-001` was run** | A completed run under the frozen manifest | — | **NOT produced.** The manifest is frozen and the gate STOPS on provider reliability; gold_v2's single scoring is unspent |
| **The measurement foundation is restored** | Valid gold data, clean benchmark, pre-registered experiment, classified failures | ADR-029; the artefacts above | **Produced, with one exception stated** — provider reliability remains an external limitation |

## Provider-gate closure attempt (Phase 17)

| Claim | Evidence required | How produced | Status |
|---|---|---|---|
| **The registered reproducer was re-run unchanged** | Live configuration compared to the pre-registration field by field, before any call | `eval/reports/r86-gate-recheck/results.json` | **Produced** — no drift across model digest, temperature, ceiling, mode, firewall path, design and threshold |
| **R-86 persists under verified-identical conditions** | Cell-for-cell comparison with the Phase-16 run | Same | **Produced** — 6/6 in `intake/gold_note/long`, 0/42 elsewhere, identical to Phase 16 |
| **The failure is deterministic** | Repeated observations with identical response shape | Same | **Produced** — six identical responses at temperature 0; a clean reproducer to escalate |
| **R-86 is fixed** | A change in the decoder, evidenced by its owner | — | **Refused.** The recheck is evidence it is *not* |
| **The responsible layer is known** | A request issued provider-side | — | **Refused.** `INDETERMINATE`, unchanged |
| **The provider gate result** | The pre-registered rule applied, not reinterpreted | Same | **Produced** — **FAIL**, 6/12 = 0.5000 against a 0.10 ceiling |
| **A live provider signal can gate the experiment** | An endpoint that can see the failure | — | **NOT produced.** Both candidates probed; R-86 returns HTTP 200 and is invisible to both. OD-40 stays open |
| **`phase16-evaluation-001` was run** | A completed run under the frozen manifest | — | **NOT produced.** `NOT_AUTHORISED`; gold_v2's scoring is unspent |
| **Every other precondition passed** | An exhaustive, non-short-circuiting check | `eval/reports/phase16-410-33/AUTHORISATION.json` | **Produced** — 14 of 15 pass; the only blocker is the provider gate |
| **gold_v2 integrity holds** | Digests, budget, and applicability re-derived from input plus linkage | Same | **Produced** — 156 cases, gold_v1 byte-identical, no narrative-only ground truth |
| **The frozen configuration is unchanged** | Every frozen digest against the live one | Same | **Produced** — prompts, model, applicability and gateway digests all match |
| **The retrieval baseline matches the frozen configuration** | Baseline settings against the manifest | Same | **Produced** — R@1 24/31 under the same settings; no `SYSTEM_CONFIGURATION_DRIFT` |
| **Any decision-quality, criterion, grounding or safety metric for this experiment** | A completed run | — | **NOT produced.** Not zero, not estimated, not carried over from an earlier run |
| **Grounding accuracy** | Chunk-level ground truth | — | **Refused (OD-42).** Citation *validity* is reportable and is marked `GROUNDING_SCOPE_LIMITED_BY_OD42`; accuracy is `unavailable`, never `0.0` |
| **Cost** | A price basis for the deployed model | — | **`COST_NOT_AVAILABLE`**, unchanged |

## R-86 handoff and evaluation hold (Phase 18)

| Claim | Evidence required | How produced | Status |
|---|---|---|---|
| **The reproducer is frozen in one exportable artefact** | A self-verifying manifest carrying every value needed to reproduce the failing request | `data/escalations/r86-reproducer.manifest.json` | **Produced** — `r86-reproducer-001`, seal verifies against its own digest |
| **It carries no secret and no clinical text** | Checked against the live secrets themselves, not a pattern | `pytest tests/evaluation/test_evaluation_hold.py` | **Produced** — caller key appears only as a salted digest |
| **An external owner can reproduce the exact request** | Model, schema, prompt, gateway and firewall digests, temperature, ceiling, prompt tokens, cell | Same | **Produced** — and the escalation quotes the digests, pinned by test |
| **The responsible layer is named** | A request issued provider-side | — | **Refused.** `INDETERMINATE`; the escalation asks and does not answer, asserted by test |
| **A revalidation path exists and works** | The harness run end to end against the live path | `eval/reports/r86-revalidation/20260825T155710Z.json` | **Produced** — FAIL, 12/12 trials, configuration matching the seal |
| **R-86 is fixed** | A PASS under the sealed configuration | — | **Refused.** The first revalidation is evidence it is not |
| **The official evaluation cannot be run while R-86 is unresolved** | A single authority with no override parameter and no environment read | `eval/official_gate.py`; `pytest tests/evaluation/test_official_gate.py` | **Produced** — asserted over the module's AST, and over every script's argparse flags |
| **No forced evaluation path exists** | Every runner parsed for bypass flags | Same | **Produced** |
| **A replay cannot authorise an official evaluation** | Replay excluded by absence, not by branch | Same | **Produced** |
| **The frozen artefacts are unchanged** | Digests for gold_v1, gold_v2 and retrieval_v4 | `pytest tests/evaluation/test_evaluation_hold.py` | **Produced** — gold_v2 scoring 0 of 1, unspent |
| **No new evaluation metric was produced** | Revalidation records checked for accuracy-shaped fields | Same | **Produced** — no accuracy, F1 or confusion matrix in any revalidation |
| **Earlier phases were not reinterpreted** | Phase 14's seal and Phase 15's source digests re-verified | Same | **Produced** |

## Engineering

| Claim | Evidence required | How produced | Status |
|---|---|---|---|
| **The LLM cannot emit a decision** | No approval/denial member in any model schema, plus AST-enforced import boundaries | `pytest tests/unit/test_layer_boundaries.py` | **Produced** (Phase 0) — 8 checks over 5 rules; each was shown to fail on a deliberately injected violation before being trusted |
| **The decision surface is a pure function** | Truth-table suite passing with no model and no network | `pytest tests/unit/test_decision_table.py` | **Produced** — AST test asserts `app/decision` performs no I/O and imports only `app/core` |
| No policy → never a denial | An assertion over all verdict/guardrail combinations | Same | **Produced** — row 1 returns `NEEDS_INFO`; asserted exhaustively |
| Policy resolution is deterministic and reproducible | Same inputs, same versions, across corpus refreshes | `pytest -m integration` | **Produced** — 38 integration tests pass against PostgreSQL |
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
