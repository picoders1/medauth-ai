# ADR-028 — Runtime policy applicability, and a pre-registered experiment-validity rule

**Status:** Accepted (2026-08-25). Two decisions, one phase, because the second is
worthless without the first.
**Resolves:** R-93. **Pre-registers:** `provider-failure-validity.v1`.
**Depends on:** ADR-004 (deterministic resolution), ADR-010 (decision table),
ADR-011 (pre-registration regime). **Amends:** ADR-004's runtime claim.

---

## Part 1 — Applicability is resolved at runtime, not asserted

### Context

ADR-004 decided in Phase 1 that applicability would be deterministic: rules over
`policy_code_links` — procedure code, code system, jurisdiction, date of service —
with no embeddings and no model. `app/policy/resolve.py` has implemented that
correctly since Phase 2, and `tests/integration/test_temporal_resolution.py` has
covered it.

**Nothing called it.** The first AI vertical slice (Phase 11) took a `PolicyIdentity`
at construction and passed a literal to the decision table:

```python
ResolutionState(status=ResolutionStatus.RESOLVED, version_count=1)
```

Rows 1 and 2 of the decision table — the rows that refuse to decide when no policy
applies, or when several might — were therefore **unreachable from the live runtime
for the whole of Phases 11 to 14**. The table was right. Nobody asked it.

Phase 14's frozen run made the consequence concrete. CASE-0073, whose gold record
expects `NEEDS_INFO` via rule 1, produced:

| | |
|---|---|
| actual | `DENY_RECOMMENDED` |
| citations | **7 verified, 0 failures** |
| guardrail | `PASSED` |
| contradiction | `NO_CONTRADICTION` |

Every grounding metric passed it. They had to: the quotes were real, the chunks were
in the evidence set, the metadata matched the database. The system reasoned
correctly, cited honestly, and applied a regulation the case does not fall under —
which is the exact failure ADR-004 was written to prevent, and the reason ADR-004
says citations cannot catch it.

### Decision

**Applicability becomes an explicit runtime stage, and it runs first.**

```
case → applicability [SQL, six states] → intake [model] → retrieval → adjudication
```

Before intake, before retrieval, before any model call. Not only because a case whose
policy does not govern should not cost a token, but because **every later stage's
output is meaningless without it**, and nothing downstream can detect the problem.

**Six states, and none may be collapsed into `RESOLVED`.**

| state | routes to | rule |
|---|---|---|
| `RESOLVED` | continues to retrieval | — |
| `NOT_APPLICABLE` (= `NONE_APPLICABLE`) | `NEEDS_INFO` | 1 |
| `MULTIPLE_CANDIDATES` (= `CONFLICTING`) | `HUMAN_REVIEW` | 2 |
| `TEMPORALLY_UNRESOLVED` | `HUMAN_REVIEW` | **14** |
| `INSUFFICIENT_INFORMATION` | `NEEDS_INFO` | **15** |
| `RESOLUTION_ERROR` | `HUMAN_REVIEW` | **16** |

Rows 14–16 sit in the same block as rows 1 and 2, at the top of the table, so every
guardrail row and every approval and denial is downstream of them. The routing is a
**dict**, not a branch chain, and a test asserts it is total over every non-`RESOLVED`
member — a seventh state fails a test instead of falling through to adjudication.

`NOT_APPLICABLE` and `MULTIPLE_CANDIDATES` are enum **aliases** of the existing
`NONE_APPLICABLE` and `CONFLICTING`: same member, same serialised value. Renaming
would have rewritten `gold_v1.jsonl` and four immutable reports to gain nothing a
reader could check.

**`PRODUCTION` and `REPLAY` are separate modes with no default.** A designated policy
remains legitimate for a controlled fixture, a historical replay and a known-policy
test. It is not legitimate as production's *proof* that the policy governs. A
`PRODUCTION` runner constructed without an `ApplicabilityPort` raises — at
construction, not per case, because a per-case refusal is 26 abstentions in a report
and reads as a hard corpus rather than as a defect. A `REPLAY` finding carries the
reason `DESIGNATED_WITHOUT_RESOLUTION`, so a replay can never be read as a resolution
that happened to agree.

**Filtering stays in SQL; classification is pure.** `LiveApplicability` calls
`resolve()` and three census counts, all reusing `in_force_on` and
`applies_in_jurisdiction`. This system still has exactly one temporal predicate — a
second copy in Python would pass every test written against today's corpus and start
disagreeing the moment a version is superseded. `classify()` receives counts and
identities and decides the six states, so the machine is a truth table with no
database.

### Alternatives rejected

**Keep the designated policy and add a warning.** A warning is a string; the runtime
would still adjudicate. This is what Phase 14 effectively had — the gold record said
`POLICY_NOT_APPLICABLE` in a field nobody consulted.

**Let applicability read the clinical note.** CASE-0073's note says "unlisted
procedure 99199" while its structured `requested_procedure.code` is `R0075`, which the
corpus genuinely links to 42 CFR 410.33. A resolver that recovered the "intended"
answer from prose would be a semantic resolver wearing a deterministic one's clothes,
and would resolve differently for the same structured request depending on wording.
The disagreement is a **dataset defect** (R-97) and is reported as one.

**One state, `APPLICABLE`/`NOT_APPLICABLE`.** Rejected: "no policy governs this",
"several might", "the corpus has the policy and not for that date", "the request
under-specifies", and "the resolver was unreachable" are five different sentences to
put in front of a reviewer, and four of them have different next actions.

### Consequences

- Row 1 is reachable from the runtime for the first time. Three gold cases will
  finally exercise it — **if the dataset lets them**, and R-97 says it does not.
- A `PRODUCTION` runner now needs a database. Every fixture-only test declares
  `RunMode.PRODUCTION` with a fixture port, so the suite still runs without one.
- `SliceRunner.__init__` gained a required argument. Every call site had to declare a
  mode, which is the point.
- **R-93 is closed.** Not by argument: by
  `tests/integration/test_case_0073_regression.py`, which reconstructs the Phase-14
  conditions exactly and is proven load-bearing by four mutations in
  `scripts/mutation_guard.py`.

---

## Part 1b — A second scoring of the gold split, declared in advance

`gold_v1` carries a scoring budget of **1**, spent on 2026-08-25 by the Phase-14 run.
The rule is that additional scorings must be declared in an ADR *in advance*, and
this is that declaration. It is written before the Phase-15 run, and the pre-run gate
refuses to start if `scorings_spent >= allowed_scorings`.

**Allowance raised to 2.** Scoring #2 is the Phase-15 run of the same 26 cases.

**Why this is not re-scoring until a number improves** — the thing the budget exists
to prevent:

- The system under test is **different code**. Phase 14 measured a runtime with no
  applicability stage; three of its 26 cases could not reach the row their labels
  name, and one produced a fully-cited denial against an inapplicable policy. That is
  not the same system with a better draw.
- **Nothing was tuned against the Phase-14 result.** No prompt, no model, no
  retrieval parameter, no threshold changed. The gate checks this against the Phase-13
  freeze, and the Phase-15 manifest carries the same prompt ids, encoder, reranker,
  `top_k` and ceilings.
- Phase 14's artefacts are **sealed with checksums** and superseded, not replaced. Its
  numbers remain published exactly as measured, under the status
  `EVALUATION_DEGRADED_BY_R-86_AND_R-93`.

**What this does not license.** A third scoring needs its own ADR. If Phase 15 comes
back degraded, the answer is to fix R-86 with the provider and declare scoring #3 —
not to re-run under this allowance until an undegraded draw appears.

---

## Part 2 — `provider-failure-validity.v1`, pre-registered

**Fixed 2026-08-25, before the Phase-15 run existed and before any Phase-15 number
did.** Recorded here rather than in the runner so that "the rule was chosen in
advance" is checkable against a commit rather than asserted.

### Context

Phase 14 published decision accuracy 6/26 = 0.2308 while 10 of those 26 cases never
reached adjudication: R-86 removed 38% of the sample, and the survivors were not a
random subset — the defect correlates with note length, which is not independent of
case difficulty. The report said so, in prose, at length.

Prose is the wrong mechanism. It can be softened, moved to a footnote, or simply
dropped by whoever quotes the figure next — and the figure is the part that travels.

### Decision

Every experiment is classified, by code, as exactly one of:

- `VALID_FOR_PERFORMANCE_ANALYSIS`
- `DEGRADED_BY_PROVIDER_FAILURE`

**Three conditions. Any one demotes.** Direction is fixed: there is no evidence this
rule can be shown that promotes.

| # | condition | threshold | why this number |
|---|---|---|---|
| 1 | provider-failure rate | **> 0.10** | at n = 26 this is three cases — enough to move a proportion by more than its own Wilson interval |
| 2 | **class erasure** — every case of an expected-decision class failed | any | a class with no survivor is one the experiment cannot speak about *at any rate*. Phase 14's 0 approvals against 7 expected is exactly this shape |
| 3 | **concentration** — a gold category's failure rate is ≥ 2× the overall rate **and** ≥ 0.50, in a category of ≥ 3 cases | both, plus the size floor | a 2× multiple on a 1% base rate is noise; 1 of 2 is not a pattern. Requiring all three is what stops the condition demoting everything |

### What the status does and does not mean

It governs whether **decision-level metrics may be quoted as evidence about the
system's reasoning**. It does not:

- decide whether an experiment ran;
- license excluding any case — **no case may ever be excluded**, and a demoted status
  is a label on the numbers, not permission to drop the rows that produced it;
- affect safety metrics. "Did anything unsafe happen" is answerable over the cases
  that ran; "how well does it reason" is not answerable over a biased 62% of them.

`classify_validity()` has **no access to any accuracy figure**. It reads which cases
the provider failed and how they are distributed, and nothing about whether the
answers were right — a validity rule that could see the score would be a rule that a
good score could satisfy.

### Pre-registered failure mode

**The Phase-15 run may well come back `DEGRADED_BY_PROVIDER_FAILURE` again.** R-86 is
not fixed, it is not fixable here, and the Phase-15 investigation found it is input-
length dependent — which means the long-note cases most likely to fail are not a
random third of the corpus. If that happens it is a **pre-registered outcome, not a
discovery**, and the correct response is to report the metrics in full with the
status attached and to leave the corresponding claims refused. It is specifically not
a reason to raise the ceiling, re-run until a good draw appears, or drop the affected
cases.

### Consequences

- Rule id `provider-failure-validity.v1` is frozen into every manifest that uses it.
  A manifest naming a different id was run under a different rule and the two are not
  comparable on this axis.
- Applied retrospectively to Phase 14, it returns `DEGRADED_BY_PROVIDER_FAILURE` on
  condition 1 (10/26 = 0.3846). That is a check of the rule against a known case, not
  a re-scoring of Phase 14 — its artefacts are immutable.
- Changing any threshold requires a new rule id and an ADR amendment. Editing the
  numbers in place would silently re-interpret every experiment that cited them.
