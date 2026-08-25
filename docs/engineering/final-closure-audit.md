# Final engineering closure audit

**Audited at:** 2026-08-25 · **Baseline:** `ded0e9b` (Phase 19), working tree clean ·
**Scope:** every issue genuinely controllable inside this repository.

This is not a phase. Nothing here adds capability, changes a model, a prompt, a
schema, a threshold, a retrieval parameter or a dataset. It asks one question of the
whole repository — *which of the controls this project claims are actually enforced,
and which are merely written down?* — and closes the gap where the answer was the
second one.

The short version: **three of them were written down.** Each was correct, complete,
tested, and consulted by nobody.

---

## 1. Baseline state, as measured

| | |
|---|---|
| HEAD | `ded0e9b`, working tree clean, nothing staged |
| modules under `app/` | 85 typed source files, `mypy --strict` clean |
| tests | 1141 passed, 1 warning, 29.7 s |
| lint | `ruff check` clean; 362 files formatted |
| mutation harness | 19/19 caught, working tree unchanged |
| `alembic check` | **FAILING** — a constraint reported for removal (R-105, §2) |
| official evaluation | **BLOCKED** — R-86 revalidation FAIL, 6/12 = 0.5000 against 0.10 |
| gold_v1 | 156 cases, budget 2/2, **exhausted** |
| gold_v2 | 156 cases, budget 0/1, **unspent** |
| retrieval_eval_v4 | 36 queries, budget 1/1, spent, `ENGINEERING_DEFAULT_UNRESOLVED` |
| R-86 seal | `r86-reproducer-001`, `sha256:271127edace3d94d`, self-verifying, intact |

Everything above was read, not assumed. The gate state was obtained by calling
`OfficialEvaluationGate.evaluate()`, the budgets by parsing the committed manifests,
the seal by recomputing its own digest.

---

## 2. What the audit found

### R-103 — a documented control with no caller

`eval/official_gate.py` opens with the sentence *"the one authority that may
authorise an official evaluation"*. It is well built: `AuthorisationState` has no
fourth member, `evaluate()` and `require()` take no arguments, there is no `force`
parameter and no environment read, and an AST test asserts both. Nineteen behavioural
tests exercise every branch.

**No script called it.** Every reference outside the module was in `tests/`.

Three scripts can write an official evaluation result — `per_case.json`,
`metrics.json`, `failures.json` — and all three reached those writes without asking:

| script | writes | checked |
|---|---|---|
| `scripts/run_frozen_410_33_evaluation.py` | `per_case.json` | the production gate only (readiness, not R-86) |
| `scripts/run_phase15_evaluation.py` | `per_case.json` | the Phase-15 pre-run gate + production gate |
| `scripts/score_frozen_410_33.py` | `metrics.json`, `failures.json` | **nothing** |

This is not a hypothetical. R-101 already recorded the residual that *"the check is a
test, not a filesystem permission"* — but the situation was weaker than that residual
described, because there was no runtime check on the runner path at all. The property
"no official evaluation path bypasses the gate" held only because nobody had run one.

There is also **no runner for `phase16-evaluation-001`.** When R-86 clears, one must
be written, and the failure mode was that its author would copy a runner that never
consulted the boundary.

### R-104 — a freeze that could be re-taken

`scripts/phase16_prerun_gate.py --freeze-manifest` wrote
`eval/reports/phase16-410-33/manifest.json` unconditionally. That file is already
frozen and `AUTHORISATION.json` records its digest. Re-running the command would have
rewritten the manifest and left the authorisation attesting to a configuration that
was no longer there — with neither file looking wrong.

This is the general shape of R-102 seen from the other side. R-102 was a freeze that
drifted for a benign reason; this was a freeze that could be *refreshed on purpose*.

### R-103, second face — a boundary CLAUDE.md names that did not exist

CLAUDE.md has said since Phase 0:

> Selection and threshold calibration use **dev only**, enforced at the library
> boundary: `eval/schema.py:require_tunable(split)` raises on a frozen split, and
> every calibration entry point calls it.

`eval/schema.py` did not exist. Neither did `require_tunable`. **R-23** ("the frozen
test split is re-scored until a number improves", Critical) and **R-25** ("thresholds
are tuned on the test split", Critical) both recorded that boundary as their
mitigation, with R-25 adding *"enforced at the library boundary, not by discipline."*
It was discipline, plus two inline checks that had already drifted apart:

- `scripts/score_retrieval_v4_baseline.py` compared spend against
  `dataset.get("scoring_budget", 1)` — **a default of one**, so a dataset that
  declared no budget silently acquired a free scoring;
- `scripts/phase16_prerun_gate.py` did the same arithmetic against a differently
  shaped file, in its own second implementation;
- `scripts/evaluate_retrieval_v3.py` — the one script that actually **sweeps arms
  across a frozen benchmark**, and which exposes `--top-k` and `--rerank-top-n` as
  command-line parameters — checked neither, against a set whose budget reads 1/1.

That last one is R-25's exact wording as an executable path.

### R-105 — a safety constraint that lived only in a migration

`uv run alembic check` — which CLAUDE.md lists in the standard verification set —
**was failing at the baseline**, and had been:

```
remove_constraint(CheckConstraint(name='ck_policy_versions_temporal_status_matches_dates'))
```

Migration `0003_coverage_determinations` creates that constraint. `PolicyVersion`
never declared it. So the ORM metadata read as though the rule should not exist, and
the next `alembic revision --autogenerate` would have emitted a migration **dropping**
it.

The rule is not a formality. It ties nullability to `temporal_status` — the
database-level half of *an undated NCD version is stored and never resolvable*.
Without it an `UNDATED` row may carry dates, and "we do not know when this took
effect" becomes a date somebody can query against: the precise conversion
`app/policy/temporal.py` exists to prevent, and the one the Phase-5 design rejected a
sentinel in order to avoid.

A drop like that would have arrived inside a generated migration that reads as
housekeeping.

---

## 3. What was changed

Six changes. Nothing else.

| | change | why |
|---|---|---|
| 1 | `eval/schema.py` (new) | the boundary CLAUDE.md specifies: `require_tunable`, `budget_for`, `require_scoring_budget`. `TUNABLE_PARTITIONS` holds exactly one member and everything else is refused **by absence** |
| 2 | `OfficialEvaluationGate.require()` wired into all three official-artefact writers | before the live flag, before any dataset is opened, before any write |
| 3 | `--freeze-manifest` refuses an existing manifest | with no flag to override it, because a flag would be the thing being prevented |
| 4 | the two divergent inline budget checks read through the boundary | one implementation of "may this be scored", not three |
| 5 | `.gitignore` covers local assistant tooling | it was covered by `.git/info/exclude`, which is not cloned and not shared |
| 6 | `temporal_status_matches_dates` declared in `app/policy/models.py` | text identical to the migration's; `alembic check` is clean for the first time in this audit's memory |

`scripts/evaluate_retrieval_v3.py` now refuses two distinct mistakes rather than one:
moving `--top-k` or `--rerank-top-n` off the frozen constants is a **sweep**, and a
sweep on a frozen split is selection whatever the report calls it; re-running the
frozen arms at all spends a budget that reads 1/1. `--render-only` reaches neither,
because re-rendering prose from a committed `results.json` scores nothing.

**No production decision path was touched.** The single change under `app/` is a constraint declaration that makes the ORM agree with the database it already runs against; no decision, resolution, retrieval or adjudication behaviour differs.

### Proven, not asserted

`tests/evaluation/test_schema_boundary.py`, 18 tests, weighted deliberately towards
**call-graph** rather than behaviour — a behavioural test proves the gate works, and
what was broken is that nobody used it.

The writers are **discovered by parsing**, never enumerated: a hand-maintained list of
runners is a list somebody forgets to add the next runner to, and the next runner is
exactly the one that would not call the gate. Ordering is asserted too, because a run
that scores 156 cases and *then* learns it was unauthorised has already spent the
budget.

Six new mutations, 25/25 caught.

One of them earned its place immediately. The first draft of the presence check
searched the source for the string `"OfficialEvaluationGate"` — and was satisfied by
the surviving **import line**, so deleting the call while leaving the import passed
it. The mutation harness caught that; reading it had not. The check reads the call out
of the AST now. A test written to catch "a control that looks present" had itself been
a control that looked present.

---

## 4. Classification of every open item

Counts from the committed register: **55 risks** not closed (46 `Open`, 6
`Open (accepted)`, 1 `Partially mitigated`, 2 `Contained`, R-86), and **28 open
decisions** of 35.

| class | items | disposition |
|---|---|---|
| `ENGINEERING_CONTROLLABLE` | **R-103, R-104, R-105** (all three opened and closed by this audit); R-23 and R-25's stated mitigation | **Resolved in this commit.** These were the only ones the audit found that code in this repository could close |
| `EXTERNAL_PROVIDER` | R-86, R-94, OD-40, OD-41 | Not fixable here. MEDAUTH observes one hop through the firewall and holds no provider credential, so `PROVIDER_DECODER` and `FIREWALL_PROXY` are indistinguishable from this side. No fix fabricated |
| `EXTERNAL_DOMAIN_REVIEW` | R-06, R-50, R-51, R-54, R-61, R-63, R-65, OD-19, OD-26, OD-27, OD-30 | Need a qualified clinical or coverage reviewer. 247 provisions await review; `completeness_verified` is `false` and a test forbids it flipping. **No reviewer approval was fabricated** |
| `LICENSING/LEGAL` | R-37, OD-15, OD-21 | LCDs and Billing & Coding Articles sit behind AMA/ADA/AHA licence terms. Not bypassed, not scraped, not worked around |
| `KNOWN_LIMITATION` | R-04, R-07, R-12, R-13, R-20, R-24, R-53, R-55, R-56, R-57, R-58, R-91, R-92, R-95, OD-22, OD-35, OD-36, OD-42 | Documented with the reason. Several are deliberately preserved: R-56's asymmetry was kept rather than silently changed, and R-58/R-92's `top_k` was **not** lowered after seeing the result, because that is the tuning-after-the-fact this regime forbids |
| `FALSE_POSITIVE` | none | |
| `SUPERSEDED` | R-97 (by gold_v2), OD-23, OD-24, OD-37 | Already struck in the register |

The standing structural risks — R-01, R-02, R-03, R-08, R-09, R-14, R-16, R-21, R-26,
R-32 — carry controls asserted by tests and are `Open` in the sense that the *risk
class* never goes away. See §5.

---

## 5. One stale status, corrected; thirty not re-adjudicated

The register's header still read *"planning phase. Every risk is `Open` and
unmitigated — no code exists."* That is false and has been for eighteen phases. It is
corrected.

The individual rows in the R-01…R-33 block are a different matter. They are marked
`Open` while carrying mitigations that tests assert, because the register is using
`Open` in a second sense the legend never gave it: *a standing risk class that a
control reduces but cannot retire.* "Automation bias" does not become `Resolved`
because a UI renders evidence first.

The legend now says so. **The thirty rows were not re-adjudicated**, and that is a
decision rather than an omission: re-scoring a clinical risk register during an
engineering closure audit would be a large, unreviewed change of meaning presented as
tidying — precisely the manufactured progress this audit was told not to produce.
Whoever re-adjudicates them should be the person qualified to, and it should be its
own change.

---

## 6. What was verified and left alone

Checked, found sound, **not modified**:

- **Production/replay separation.** `RunMode.REPLAY ∉ PRODUCTION_MODES`;
  `GOLD_V1_REPLAY ∉ PRODUCTION_ORIGINS`; `eval/replay.py` lives outside `app/` so a
  production import is a layer-boundary failure. `SliceOutcome.mode` defaults to
  `REPLAY` — the fail-closed direction, so a hand-built outcome cannot read as a
  resolution. The runner's `mode` has no default at all.
- **Applicability ordering.** Resolution runs at `slice.py:389`, retrieval at 450.
  Applicability precedes every model and retrieval call. `_ROUTE_FOR_RESOLUTION` is
  total over all six states and a test asserts totality; a `PRODUCTION` runner
  without an `ApplicabilityPort` cannot be constructed.
- **No dangerous implicit conversions.** No `date.min` sentinel survives (the
  unreachable one in `parse.py` was deleted in Phase 5, and the comment explaining
  why remains). No `latest` fallback in resolution — selection is by date of service
  and `in_force_on` carries an explicit `temporal_status == 'DATED'` conjunct. Kleene
  three-valued logic keeps `UNKNOWN` first-class: a criterion nobody adjudicated is
  `UNKNOWN`, never `FALSE`.
- **Provider failure never becomes a wrong answer.** `MODEL_WRONG` exists nowhere in
  `eval/` or `app/`; `CaseDisposition` has no such member and a test asserts its
  absence. `classify_provider_failure` has no accuracy parameter.
- **Cost.** No hardcoded pricing. `COST_NOT_AVAILABLE` remains the official state and
  `cost_report()` returns token counts with a stated refusal unless a real price
  basis is supplied.
- **Security.** No `.env` tracked; no deployment base URL or model identifier in any
  tracked file; the caller key appears in the escalation only as a digest salted with
  the firewall base URL. `403` is never retried. Redaction is a structlog processor
  at the sink, not per call site. No debug or test endpoint is exposed.
- **Evaluation reconciliation.** `coverage_report()` asserts the six dispositions sum
  to `attempted`; no case can be dropped silently. `classify_validity` has no access
  to any accuracy figure and every condition can only demote.

---

## 7. R-86 — unchanged, deliberately

Still `VERIFIED FAILURE · attribution INDETERMINATE · OUTSIDE_ENGINEERING_CONTROL`.

Nothing in this audit touched the threshold, the request shape, the schema, the
model, the temperature or the firewall route. The seal verifies against its own
digest. The gate reads the **latest** revalidation, not the best one, and a
`FAIL` and an `INCONCLUSIVE` block identically — "we could not tell" is not
permission.

The only valid transition remains:

```
FAIL → external owner evidence → exact revalidation → PASS → authorisation
```

The change this audit makes is that the last arrow is now the *only* arrow. Before it,
three scripts could reach a scored hold-out without passing through any of them.

---

## 8. What this does not claim

The boundary guards the entry points that call it. It is **not** a filesystem
permission, and a new script that opens `data/gold/cases/gold_v2.jsonl` directly still
can. What has been removed is the accidental path and the divergent second
implementation; the deliberate path remains visible in `grep`, in the diff and in the
call graph. Claiming more would be the same defect this audit exists to close.

No clinical validation is claimed. No production clinical readiness is claimed. The
official evaluation is not ready, and will not be while R-86 fails.
