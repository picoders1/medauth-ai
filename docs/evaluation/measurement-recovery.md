# Measurement recovery: what Phase 16 restored, and what it could not

**Classification: MEASUREMENT FOUNDATION RESTORED + PROVIDER RELIABILITY REMAINS AN
EXTERNAL LIMITATION.**

Phase 16 changed almost nothing about how MEDAUTH decides. It changed what can be
believed about a measurement of it.

---

## The four preconditions

    PROVIDER RELIABILITY  +  VALID GOLD DATA  +  CLEAN RETRIEVAL BENCHMARK
                          +  PRE-REGISTERED EXPERIMENT
                                      ↓
                            TRUSTWORTHY EVALUATION

| | status |
|---|---|
| valid gold data | **restored** — gold_v2, R-97 fixed, 156 cases, applicability re-derived per case |
| clean retrieval benchmark | **restored** — retrieval_v4, 36/36 provenance-clean, baseline scored |
| pre-registered experiment | **restored** — ADR-029, manifest frozen, ten-condition gate |
| provider reliability | **not restored, and not ours** — `OUTSIDE_ENGINEERING_CONTROL` |

## What "restored" means concretely

**Every number now has a denominator, and most have two.** `eval/coverage.py` refuses
to produce one figure: operational coverage over every attempted case with provider
failures included, and decision quality over assessed cases labelled as *not overall
accuracy*. Applied to Phase 15's record, "8/26" becomes three separate honest
statements.

**Every failure now has an owner.** Eleven provider-failure kinds, four attributions,
six case dispositions — and no `MODEL_WRONG` anywhere. A firewall block is not an
outage; a 400 is ours; a decoder that never terminates is `INDETERMINATE` because
MEDAUTH sees one hop.

**Every gold label is derivable from its input.** Re-derived by test from the case
plus the committed linkage, not read from the case's own assertion.

**Every benchmark query proves its chain.** And the audit is proven able to fail.

## What Phase 16 withdrew

**Phase 15's "R-86 is input-length dependent" is withdrawn.** A controlled gradient
varying only length returned **0/56** up to 908 prompt tokens. The earlier reading
came from arms that varied three things at once.

The factorial replacement is narrower and much stronger: R-86 needs the
**conjunction** of the production schema, a longer input and real clinical content.
522 tokens of filler succeed 6/6; 512 tokens of clinical text fail 6/6.

## What Phase 16 found in its own instruments

The failure classifier tested "did the body parse?" before "is this a runaway?" — and
a runaway never closes its document. Every R-86 occurrence was reported as
`MALFORMED_RESPONSE`. The experiment found the bug in the thing measuring the
experiment. Corrected, re-executed unchanged, recorded in the artefact.

## What was deliberately not done

- **No run.** gold_v2's single scoring is unspent. The gate stops on provider
  reliability, and spending a hold-out on a run known in advance to be
  uninterpretable would have destroyed the budget to confirm a prediction.
- **No local R-86 mitigation.** No length threshold is supported by the evidence; a
  content heuristic gating clinical evidence would be worse than the defect; raising
  the ceiling converts a bounded truncation into a hang.
- **No tuning of anything.** Prompts, model, retrieval and thresholds are byte-identical
  to the Phase-13 freeze, and the gate checks it.
- **No agents, no graph expansion, no UI, no Kubernetes.**

## The honest summary

The instrument is calibrated. The subject is available. The **channel between them**
is not, and fixing it requires someone who can issue a request MEDAUTH is correctly
forbidden from issuing.

That is a good place to be stopped: everything that was ours to fix is fixed, and the
one thing that is not is named, measured, deterministic, reproducible and escalated
with the exact question its owner has to answer.
