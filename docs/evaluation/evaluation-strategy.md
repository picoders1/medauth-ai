# Evaluation Strategy

**Status:** Planning phase. **No evaluation has been run. No number in this document is a result.**
Every metric below is a definition and a commitment, not a finding.

**The rule:** if the artefact does not exist, the claim is not made. Not softened, not hedged — not
made. The ledger is [evidence-and-claims.md](../evidence-and-claims.md).

---

## 1. What is being measured, and separately

Four different things fail in four different ways and are fixed by four different actions. Averaging
them into one "accuracy" number would hide exactly the failures that matter here.

| Layer | Question | Unit | Denominator |
|---|---|---|---|
| **Policy resolution** | Did the deterministic step select the policy version a human says applies? | case | ~150 gold cases |
| **Retrieval** | Did the right passage reach the adjudicator? | criterion-query | ~1,000+ judgements |
| **Grounding** | Is every claim traceable to real, correctly-attributed source text? | citation | thousands |
| **Decision** | Is the recommendation right, and is abstention safe? | case | ~150 gold cases |

Retrieval and grounding are measured at a far larger denominator than decision quality, and that is
deliberate: it is where statistically meaningful statements are actually available.

---

## 2. The statistical limitation, stated before any result exists

The target corpus is ~200 constructed cases, ~150 gold-labelled, split dev/test by the rule in §4.

```
   ~150 gold cases
        ├── dev  ~30   (20% of cases, by the split rule)
        └── test ~120
   across 3–5 outcome classes → per-class denominators in the tens
```

At n ≈ 25–40 per class, a 95% Wilson interval on a rate near 0.85 spans roughly **±10–15
percentage points**. Consequences, accepted in advance:

- Differences smaller than roughly 15 pp between per-class rates are **not detectable**. The
  evaluation will not claim them.
- Every per-class figure is reported with `n` and its interval. A bare percentage is not permitted.
- Comparisons between configurations use **exact McNemar** on paired same-corpus runs, which is
  materially more sensitive than comparing two intervals — but still limited.
- Where a stronger statement is needed, it comes from the retrieval or grounding layer, where the
  denominator supports it.

This is written here, before results, so that it cannot be quietly omitted afterwards.

---

## 3. Ground truth by construction

If a model authors both the case and its label, the evaluation measures the model's
self-consistency and nothing else.

```
   criteria tree (Phase 2, human-reviewed)
        │
        ▼  choose a satisfaction PATTERN
   {c1: satisfied, c2: satisfied, c3: not_satisfied, exclusion_e1: absent}
        │
        ▼  the pattern IS the label — computed by the same decision table the system uses
   gold outcome = DENY_RECOMMENDED
        │
        ▼  narrative written to realise the pattern
   clinical note text
```

The label is therefore a **property of the construction**, not an opinion. Two consequences:

1. **Label quality is not a model-dependent variable.** It is as good as the criteria tree, and the
   tree is human-reviewed.
2. **Failure families are constructible on purpose** rather than hoped for in a random sample.

### Guards against circularity

| Risk | Guard |
|---|---|
| Narrative leaks the label ("this clearly satisfies criterion 3") | Adversarial lint over generated text for criterion and outcome vocabulary; human spot-check specifically targets this |
| Case construction and adjudication share prompt lineage | Different prompts, different phases, recorded in ADR-015 |
| Cases constructed from the same chunks that will be retrieved | Expected and acceptable — grounding is what is being tested. **What is not claimed** is generalisation to real notes |

### The limitation that is not hidden

Constructed cases are cleaner, better-structured and less ambiguous than real clinical notes.
Performance on them is an **upper bound** on performance in the field.

> The claim *"this system's measured performance transfers to real clinical documentation"* is
> **refused**, permanently, until an evaluation on real (de-identified, IRB-appropriate) notes
> exists. No such evaluation is planned in this project.

---

## 4. Splits, freezing and leakage control

### Split rule

Byte-exact, reused from the sibling project so both repositories split identically:

```python
int(sha256(normalised_key(text).encode()).hexdigest()[:8], 16) % 100   #  < 20 → dev
```

Both the `[:8]` slice and the boundary `20` are load-bearing. Using the full digest, or `21`,
silently moves samples between splits and can leak a prior experiment's tuning data into a later
split. Changing either requires a **new dataset version** that reproduces the old rule
byte-for-byte for the old data.

### Freezing

- Splits are hashed; hashes pinned in `eval/datasets/registry.yaml` and asserted by test.
- **Frozen corpora are never edited.** Editing one destroys the record of a completed experiment.
  Extend only by adding a version.
- A test asserts no case appears in both splits.

### Scoring budget

The test split records how many times it has been scored. Phase 6 spends **one**. Any further
scoring must be declared in an ADR **in advance**, with its reason. Re-scoring a frozen split until
a number improves is how an evaluation becomes fiction.

### Leakage controls

| Leakage | Control | Test |
|---|---|---|
| Train/test | Hash-based split; membership asserted | `test_dataset_splits.py` |
| Gold-set contamination | Thresholds tuned on dev only, enforced at the library boundary by `require_tunable(split)`, which raises on a frozen split | `test_require_tunable.py` |
| Policy leakage | A case's constructed pattern is never injected into its own retrieval context | `test_no_pattern_leakage.py` |
| Prompt leakage | No gold label, expected outcome or criterion answer appears in any rendered prompt — asserted by scanning outgoing prompts for label vocabulary | `test_prompt_leakage.py` |
| Corpus leakage | Retrieval scoped to resolved versions; out-of-scope chunks cannot enter an evidence set | `test_retrieval_scope.py` |

---

## 5. Metrics

### 5.1 Decision quality

Accuracy · per-class precision and recall · macro-F1 · confusion matrix over
`APPROVE_RECOMMENDED` / `DENY_RECOMMENDED` / `NEEDS_INFO` / `HUMAN_REVIEW` / `NO_DECISION`.

**Denial precision is always reported separately**, with its own denominator and interval, and is
never folded into macro-F1 alone. A system that is strong overall and weak at denial is not
acceptable, and an aggregate hides precisely that. See
[decision-and-abstention.md](../architecture/decision-and-abstention.md) §2.

### 5.2 Grounding

| Metric | Definition |
|---|---|
| Citation precision | valid citations ÷ citations offered |
| Citation recall | criteria with ≥1 valid citation ÷ criteria requiring one |
| Faithfulness | verdicts entailed by their cited text (human-adjudicated on a sample; sample size stated) |
| Evidence completeness | required criteria addressed ÷ required criteria |
| Unsupported-claim rate | verdicts asserting satisfaction with no valid citation ÷ all verdicts |
| **Citation misattribution rate** | valid quote, wrong policy/version/section/page ÷ citations |

Misattribution is tracked separately from fabrication because it is the more dangerous failure: the
quote is real, so a human spot-check passes, while the policy it is attributed to does not apply.

### 5.3 Abstention

Coverage · selective accuracy · abstention precision · abstention recall · **unsafe-decision rate**.

Unsafe is not the same as wrong:

| Error | Class |
|---|---|
| Denial where gold is approve | **Unsafe** — withholding indicated care |
| Approval where gold is deny | Costly, not unsafe |
| Decision issued on an invalid citation | **Unsafe** — should have been `NO_DECISION` |
| Decision on the wrong policy version | **Unsafe** — correct-looking, ungrounded |
| `NEEDS_INFO` where gold is a decision | Coverage loss, not unsafe |

The gate is judged on removing **unsafe** decisions, not errors in general. A gate that only reduces
coverage has failed, and the report will say so.

### 5.4 Operations

p50 / p95 latency per case and per step · prompt and completion tokens per case · cost per case ·
schema-repair rate · firewall 403/503 rate.

Cost per case is reported with the model id and the price basis on the run date; a price is not a
property of the system and is labelled as an input.

### 5.5 Human review — instrumented, not claimed

Override rate · human/AI agreement (Cohen's κ) · review duration · agreement by outcome class.

> **No value for any of these may be claimed.** They require a pilot with real clinical reviewers,
> which has not happened and is not scheduled. The instrumentation exists; the numbers do not.
> Tracked as OD-7.

---

## 6. Failure-oriented case families

Each family is **constructed on purpose**, with the expected outcome fixed by the decision table
before the case is written. Any family whose observed behaviour differs from the expected column is
a defect or a documented deviation — never a re-labelled expectation.

| # | Family | Expected outcome | Tests |
|---|---|---|---|
| 1 | Missing diagnosis | `NEEDS_INFO` | Row 6; missing-evidence list is specific |
| 2 | Missing procedure code | `NEEDS_INFO` | Resolution cannot proceed → row 1 |
| 3 | Insufficient clinical evidence | `NEEDS_INFO` | Row 6, not row 8 — the core distinction |
| 4 | Conflicting evidence within the note | `HUMAN_REVIEW` | Row 5 |
| 5 | No applicable policy | `NEEDS_INFO` | Row 1. **Never a denial** |
| 6 | Multiple applicable policies, agreeing | decision | Both recorded; NCD precedence honoured |
| 7 | Multiple applicable policies, conflicting | `HUMAN_REVIEW` | Row 2 |
| 8 | Outdated / superseded policy | correct version used | Temporal resolution (T-08) |
| 9 | Invalid citation (chunk id does not exist) | `NO_DECISION` | Row 3 |
| 10 | Hallucinated citation (quote not in chunk) | `NO_DECISION` | Span verification |
| 11 | Malicious policy text (poisoned chunk) | containment | No verdict flip; T-05 |
| 12 | Prompt injection in the clinical note | containment | No verdict flip; T-01 |
| 13 | Ambiguous clinical note | `NEEDS_INFO` or `HUMAN_REVIEW` | Not a confident decision |
| 14 | **Citation misattribution** (real quote, wrong policy) | `NO_DECISION` | Metadata agreement; T-10 |

Family 14 is added beyond the brief's twelve because it is the failure a human spot-check is least
likely to catch — the quote is genuine.

Families 11 and 12 are scored as **containment**, not accuracy: the question is whether the injected
instruction changed a verdict, not whether the final outcome happened to be right.

---

## 7. Statistical conventions

| Situation | Method |
|---|---|
| A single rate | **Wilson** score interval, 95% |
| Two configurations, same corpus, paired | **Exact McNemar** |
| Human/AI agreement | Cohen's κ with interval |
| Threshold selection | Lowest threshold whose dev unsafe-rate upper Wilson bound is within the ceiling — iterate **upward**, return the first hit |

Implemented once in `eval/metrics/` and reused, never reimplemented per runner.

The upward-iteration instruction is not stylistic. Computing "smallest *k* satisfying a bound" by
scanning downward returns the endpoint instead of the first qualifying value — a bug that has
occurred three times in the sibling project. A unit test asserts the direction.

---

## 8. Reporting

Every run writes a report under `eval/reports/<ISO8601>__<slug>/` containing: dataset hash and
version, split, `n` per class, git commit, model id, prompt versions, corpus snapshot id,
decision-config version, machine metadata, and every metric with its interval.

**A figure that cannot be traced to such a report does not appear in any document in this
repository** — not in the README, not in an ADR, not in a CV, not in an interview.

### Pre-registration

ADR-011 (abstention) and ADR-014 (evaluation) fix hypotheses, success criteria — with denominators,
interval method and **direction** — and failure modes *before* execution. Criteria are never retuned
after seeing results, and a pre-registered failure mode is never later presented as a discovery.

### Negative results

A failed experiment honestly reported is the expected output. If abstention reduces coverage without
reducing unsafe decisions, that is the finding, it is committed, and the corresponding claim stays
refused. No configuration is promoted on a partial win.

---

## 9. Regression gates

From Phase 9, CI fails if a committed metric moves beyond a declared tolerance. The evaluation
regression runs against **committed reports**, not live inference, so CI stays green from a clean
clone with no API key and no network egress.
