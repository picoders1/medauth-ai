# Phase 13 — Guardrail Closure, Provider Hardening, Retrieval Evaluation

Three gaps that only real execution could have exposed, closed to the extent they
can be. One of them cannot be closed here at all, and that is stated rather than
worked around.

---

## R-89 — contradiction detection is now reachable · **RESOLVED**

Decision-table row 5 and the `CONTRADICTORY_EVIDENCE` abstention existed through
Phases 11 and 12 and **nothing could produce them**: the slice passed
`GuardrailState.PASSED` unconditionally. An abstention state nothing can reach reads
as coverage.

`app/guardrail/contradiction.py` runs as a pipeline stage. Three states, and the
third is not a hedge:

| | |
|---|---|
| `CONTRADICTION` | a structural conflict, with the facts, evidence and reason that show it |
| `NO_CONTRADICTION` | checked, and clean |
| `UNDETERMINED` | **could not check.** Non-decisive in both directions |

It is routed **through** `decide()` rather than short-circuited before it, so row 5
is genuinely reachable. An earlier version abstained directly and produced the same
outcome while leaving row 5 exactly as dead as R-89 found it — the bug wearing a fix.

### What it will not do

It reads **structured evidence only**: assessments, the chunks they cite, and facts
with spans. It never re-reads the note and never asks a model, because a detector
that inferred clinical content would be adjudicating the adjudicator.

So `"supervisor covers two sites"` and `"supervisor covers five sites"` in different
sentences is **not** detected. That is a stated limitation, not a gap being hidden —
and the live `C-contradictory` case confirms it: it reached `NEEDS_INFO` via row 6,
not row 5.

### R-90, found immediately

The first implementation compared `evidence_ids` across criteria. Those are assigned
**per criterion** — `E1` for one is a different passage from `E1` for another. It was
comparing labels rather than sources and fired on every ordinary fixture case. It
compares chunk ids now, and only when the source sets are **identical**: overlap is
normal, and a detector that flagged it would be switched off within a week.

**Half the contradiction tests exist to prove it stays quiet.**

## R-88 — evidence-id confusability · **structurally blocked**

The first live call returned `evidence_ids: ["MEDAUTH-DATA-8f2a"]` — the model cited
the **fence delimiter**. It was contained, but only because that string happened not
to be in the criterion's set. Containment by coincidence.

Two independent barriers now: an id must **have the shape we issue** (`E<digits>`,
`EVIDENCE_ID_PATTERN`) *and* be in this criterion's set. `EvidenceEntry` refuses a
malformed id at construction, so the known set cannot contain values its own
validator rejects. 13 adversarial ids are tested, including the observed one.

The two checks are redundant given that invariant, and the mutation harness says so:
removing the shape check survives, because membership alone catches every forged id.
**Recorded rather than dressed up** — the load-bearing guard is the one on
`EvidenceEntry`, and that is the one the harness targets.

## R-86 — bounded, classified, **escalated, not fixed**

[`docs/escalations/R-86-unbounded-whitespace.md`](../escalations/R-86-unbounded-whitespace.md).

Reproducible 3/3 in both directions. Same endpoint, model, schema and parameters;
the only difference is one sentence asking for compact output:

| compact instruction | `finish_reason` | tokens | whitespace |
|---|---|---|---|
| present | `stop` | 37 | 9.0% |
| absent | `length` (ceiling) | 1536 | 97.7% |

**JSON permits arbitrary whitespace between tokens, so a constrained decoder can
satisfy the grammar forever without closing the document.** The grammar guarantees
the output *shape*, not that it *ends*.

Classification, as far as our evidence reaches: `REQUEST_SHAPE`,
`TIMEOUT_HANDLING` and `MODEL_CONFIGURATION` are **excluded** by controlled
comparison. `PROVIDER_DECODER` and `FIREWALL_PROXY` remain, and **we cannot
distinguish them** — MEDAUTH reaches the provider only through the firewall, by
design. Separating them is the escalation.

Bounded on our side: timeout enforced, retries capped, `max_output_tokens` set, and
every failure routes to `HUMAN_REVIEW`. A truncation becomes `SCHEMA_INVALID`, never
a recommendation. **This is an availability and cost problem, not a safety one** —
which is why it is a risk rather than an incident.

## Retrieval — scored once, and no winner forced

[`docs/evaluation/retrieval-configuration-decision.md`](../evaluation/retrieval-configuration-decision.md).

v3 was integrity-checked **before** scoring, scored once (budget 1/1), and the
dataset was not touched — including a query flagged at 1.000 word overlap, which
turned out to be the single-word probe `"home"`, an artefact of the metric at length
1 rather than leakage. **Removing a difficult query after seeing a flag is exactly
what the regime forbids.**

The result is decisive in an unexpected direction: **no pair of arms reaches
p < 0.05**, and the best comparison — 5 discordant queries, all one way — gives
p = 0.0625, which is the *minimum achievable* with 31 paired observations. The set
discriminates on point estimates and **cannot separate the arms statistically, by
construction**.

So `RETRIEVAL_CONFIGURATION_UNRESOLVED` stands. The adopted reranker is labelled an
**engineering default**, and the encoder question is not merely unresolved but
**unmeasurable at `top_k=40`** (R-92): both encoders were identical on every query.

## 26-case evaluation — frozen, not run

`data/review/eval_410_33_frozen.json`, status `FROZEN_NOT_RUN`. 26 cases, digest
`sha256:6268b92cf44e8536`, 24 metrics named **before any of them has a value**, and
15 required per-failure fields so no hard case can be quietly dropped.

Running it spends a scoring from the gold_v1 budget and is a separate, deliberate
act. gold_v1 is unchanged and no gold_v2 is required — FOCUS-001's answer changed no
criterion, and that state is recorded explicitly rather than left as an absence.
