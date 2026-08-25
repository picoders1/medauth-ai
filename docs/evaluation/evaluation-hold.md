# Evaluation hold

**In force.** Everything below is frozen until the R-86 gate returns `PASS`.

---

## What is held

| artefact | state | pinned by |
|---|---|---|
| `gold_v1` | byte-identical, `ca990b80…` | its manifest, a mutation, and two tests |
| `gold_v2` | frozen, `000cba13…`, **scoring 0 of 1 — unspent** | its manifest and the experiment manifest |
| `retrieval_v4` | 36 queries, scoring 1 of 1 spent on the baseline | the experiment manifest |
| retrieval baseline | R@1 24/31, `ENGINEERING_DEFAULT_UNRESOLVED` | asserted configuration-for-configuration |
| `phase16-evaluation-001` manifest | frozen, `NOT_AUTHORISED` | its own digest, recorded in `AUTHORISATION.json` |
| the acceptance threshold | **0.10** | `ValidityRule`, compared across three artefacts |

## What "held" means in practice

**No tuning.** Not the model, prompt, schema, input formatting, encoder, reranker,
chunking, `top_k`, firewall path or denominator.

**No relabelling.** gold_v1 and gold_v2 are not edited, and gold_v2 is specifically
not edited to improve a metric.

**No re-scoring.** `retrieval_v4`'s budget is spent; the next official run interprets
against *this* baseline. Re-scoring under different settings would be
`SYSTEM_CONFIGURATION_DRIFT`, and the drift would be invisible in a report quoting
only the newer number.

**No new evaluation numbers.** No accuracy, no model comparison, no end-to-end score.
Only an R-86 revalidation may change the readiness state, and a test asserts that no
revalidation file contains an accuracy, an F1 or a confusion matrix — a diagnostic
carrying those would be an evaluation wearing a diagnostic's name.

**No reinterpretation.** Phase 15's and Phase 16's records stand exactly as measured.
Phase 14's seal still verifies. The bytes are checked, because the cheapest
reinterpretation is an edit.

## The absence is asserted

A gate that blocks a run and lets the artefacts appear anyway has blocked nothing, and
a partial `per_case.json` is indistinguishable from a completed one to whoever reads
the directory next. So the experiment directory is asserted to contain **exactly**
`manifest.json` and `AUTHORISATION.json`, and nothing else.

## One recorded, benign difference

The gold_v2 *manifest file* gained a `supersedes_reason` field after the experiment
manifest was frozen — later in Phase 16, before anything was ever scored. Its bytes
therefore differ from the recorded digest while **the dataset does not**.

Recorded here rather than papered over: the fields that determine what a run would
measure — dataset digest, case count, case ids — are compared individually and all
agree. The experiment manifest is not re-frozen to make a hash match, because a freeze
that gets refreshed when it becomes inconvenient is not a freeze.

## What lifts the hold

Exactly one thing: `scripts/r86_revalidate.py` returning `PASS` under the sealed
configuration, followed by `scripts/phase16_authorisation.py` returning `AUTHORISED`.

Not a decision, not a deadline, not a judgement call that enough time has passed.

## What does not lift it

- lowering the threshold;
- changing the request shape to avoid the defect;
- excluding the failing cell;
- running anyway and labelling the result degraded;
- a `--force` flag, an environment variable, a debug mode or a replay.

The last one is structural: `eval/official_gate.py` has no parameter and no
environment read through which any of it could arrive.

## What is *not* held

Reading, writing and thinking. Documentation, risk-register hygiene, escalation
material and test hardening all continue — none of them touches a frozen artefact or
produces a number.

What is held is **scoring**, because that is the only thing here that cannot be
undone.
