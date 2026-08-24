# First Slice — Evaluation

## `MODEL_REASONING_QUALITY_NOT_YET_EVALUATED`

**Zero model calls.** Every response came from a deterministic fixture. This
measures the pipeline, and it is careful to say so.

Report: `eval/reports/first-vertical-slice/report.json`, carrying its git commit,
Python version, platform and an explicit `model_calls: 0`.

---

## What was measured

| | result |
|---|---|
| decision-table agreement on controlled fixtures | **9 / 9** |
| structured-output validity | 5 assessments per run, all schema-valid |
| citation validity | 5 / 5 verified on the complete case |
| evidence completeness | 5 / 5 asserting mappings cite both a fact and a span |
| audit events per run | 3 (intake, assessment, decision) |
| pipeline latency, complete case | intake 1.9 ms · assessment 1.9 ms · citations 1.9 ms · decision 0.07 ms |

**Those latencies are the cost of the code path, not of inference.** A fixture
gateway returns instantly; a real model call would dominate all four numbers. The
figure worth keeping from this run is the deterministic tail — `decision` at 0.07 ms
— because that stage will still cost that when the model call does not.

A stage that did not run is **absent** from the timing map, never recorded as zero.
Zero is a measurement; absent is the truth.

## What was NOT measured, and must not be claimed

| claim | status |
|---|---|
| clinical accuracy | **Refused.** No qualified reviewer, no clinical labels |
| clinical validation | **Refused.** Nothing in this repository establishes it |
| model reasoning quality | **Not yet evaluated.** No model was called |
| retrieval configuration quality | **Refused.** Benchmark is `NOT_READY`; the configuration is unevaluated, not selected |
| end-to-end latency in production | **Not produced.** Fixture latencies only |
| token usage or cost | **Not produced.** No tokens were consumed |

## Why the expectations are trustworthy

Each scenario's `expected` outcome is derived from the decision table's own rows —
row 6 before rows 7 and 8, row 1 never reaching a denial — **not** from observing a
run. A scenario whose expectation came from watching the system would confirm
whatever the system did, and a 9/9 built that way would mean nothing.

## Relationship to gold_v1

None. This slice runs on nine hand-built scenarios, not on the gold set. gold_v1 is
byte-identical at `ca990b80…`, its test split has been scored **0** times, and no
gold case was used, read or relabelled here.

The 26 gold cases that sit on 42 CFR 410.33 are now adjudicable in principle. Scoring
them is a separate, deliberate act under the pre-registration regime — it needs an
ADR fixing the hypothesis, the denominators and the direction **before** the run.

## What would make this a real evaluation

1. A live model behind the gateway, so the assessments are the model's.
2. A pre-registered protocol for scoring gold_v1's 410.33 cases.
3. Denial precision reported separately, with its own denominator and interval.
4. `retrieval_v3` scored under OD-28, so the retrieval configuration is chosen on
   evidence rather than left unevaluated.

None of the four has happened. Until they do, the honest summary of this slice is:
**the architecture runs end to end and every refusal is explainable by pointing at a
rule.**
