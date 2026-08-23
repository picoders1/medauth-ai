# Fail-Closed Policy Semantics

**Unverified policy semantics cannot adjudicate.** This is how R-59 was closed, what
changed, and what it cost.

Design rationale: [ADR-024](../adr/ADR-024-fail-closed-semantics-and-coverage-layer.md).

---

## The hole

Phase 4 gave policies a way to *state* their logic and gave `decide()` a rule that
refuses a `REVIEW_REQUIRED` one. It did not give `decide()` any way to know whether
anyone had looked.

```python
def decide(criteria, guardrail, resolution, *, logic: PolicyLogic | None = None, ...):
    policy = logic if logic is not None else assumed_conjunction(criteria)   # R-59
```

A caller who never consulted the logic inventory got a silent adjudication under a
rule shape nobody had established. The inventory classifies **four of eight** policy
versions `REVIEW_REQUIRED`. The record stated a doubt the runtime did not act on.

## The fix

The fallback is **deleted**, not defaulted. `semantics` is a required positional
argument with no default, and nothing in the tree manufactures one. Reintroducing
the hole means *adding* a line that invents semantics from nothing — a visible
addition in a diff, not a flipped default.

```python
def decide(criteria, guardrail, resolution, semantics: PolicySemantics, *, ...)
```

## Two failure causes, never collapsed

| | means | fixed by | rule |
|---|---|---|---|
| `POLICY_SEMANTICS_UNRESOLVED` | the **corpus** is unqualified — nobody has read this regulation | qualified review (OD-19) | 12 |
| `POLICY_SEMANTICS_UNVERIFIED` | the **runtime** cannot establish that what it holds is verified | fixing the caller | 13 |

Both route to `HUMAN_REVIEW`, and both fire before any denial *and* before any
approval. They are kept apart because a misconfigured deployment must not be
indistinguishable from an honestly-unreviewed corpus — least of all in the audit
trail.

## The invariant is a construction rule

`PolicySemantics` is built only through classmethods, and each **demotes** to
`POLICY_SEMANTICS_UNKNOWN` when an executable status arrives without both a matching
`PolicyLogic` and an `Attestation`:

```python
PolicySemantics.assumed(..., logic=tree, attestation=None)
#  -> status POLICY_SEMANTICS_UNKNOWN, logic None, notes explaining why
```

There is no validation anyone can forget to call. **The type cannot represent an
unattested assumption.** Demotion rather than a raise keeps `decide()` total: a
misconfigured caller routes cases to a human instead of raising inside an
adjudication.

## `POLICY_SEMANTICS_UNKNOWN` is a separate axis

Not a fourth `PolicyTruth`. `PolicyTruth` is the total image of `Tri` under
`evaluate()`, and rule 5a returns *before* `evaluate()` runs — a value carried there
would require fabricating a `PolicyEvaluation`, inventing `unknown_criteria` and
`decisive_criteria` for a policy that was never evaluated. That is fabricated
provenance in the exact field a reviewer uses to check an outcome.

It surfaces on the output instead, as `Recommendation.policy_semantics` and
`Recommendation.semantics_origin`, alongside the truth axis and never inside it.

## The invariant, stated

> `NO_DECISION_WITH_UNVERIFIED_POLICY_SEMANTICS` — for every input, if
> `semantics.logic is None` or `status is REVIEW_REQUIRED`, then
> `outcome ∉ {APPROVE_RECOMMENDED, DENY_RECOMMENDED}`.

**Naming trap:** `Outcome.NO_DECISION` already means something else (an unverifiable
citation, rule 3). This invariant uses "no decision" in the English sense — no
*adjudication*. Assert on the set, never on `outcome is NO_DECISION`. It
deliberately permits `NEEDS_INFO` from rule 1 and `NO_DECISION` from rule 3.

### Proven by pairing

Quantifying over generated inputs and asserting "never approves or denies" passes
trivially if the space contains nothing that *would* have adjudicated. So every
input is decided twice:

1. **The invariant** — unverified never approves or denies.
2. **Positive control** — the same space, attested, reaches both `APPROVE` and
   `DENY`. Without this, clause 1 describes a space that never adjudicates.
3. **Anti-vacuity** — wherever the attested run adjudicates, the unverified run's
   rule is one of the two semantics rules. This proves the *new gate* stopped it.
   Without it, an implementation firing rule 1 on everything would satisfy 1 and 2.

Two mutations the paired test cannot catch have their own tests: giving `semantics`
a default (signature test), and weakening the demotion rule (normalisation test).
All four injections were run and all four fail as they should.

## What it cost

**Three of eight policy versions remain adjudicable in production.**

| | adjudicable | blocked |
|---|---|---|
| policy versions | 3 | 5 |
| gold_v1 cases | 78 | **78 (50%)** |
| synthetic cases | 111 | **111 (50%)** |

Measured by `scripts/report_adjudicability.py` into
`data/policy_logic/production_coverage.json`, with a test asserting the counts
against the datasets so the documentation cannot drift from the data.

**Half the corpus is now non-adjudicable, and that is the finding, not a bug.** It
was always true that nobody had read those policies; what changed is that the
system now says so instead of assuming a shape.
