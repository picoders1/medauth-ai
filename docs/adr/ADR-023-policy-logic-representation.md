# ADR-023 — Policy Logic as Data: Three-Valued Expressions, Declared per Policy

**Status:** Accepted (2026-08-23)
**Amends:** ADR-010 (deterministic decision engine). **Resolves:** OD-23. **Opens:** OD-24.

---

## Context

ADR-010 established the invariant this system rests on: *models produce
per-criterion verdicts, code produces the decision*. It did not say what shape that
code's rule should be, and the implementation chose one — **every required
criterion must hold** — and applied it to every policy.

42 CFR 410.32(a)(1) disproves that in one sentence. A physician qualified as an
interpreting physician may order a diagnostic mammogram from screening findings
"even though the physician does not treat the beneficiary." Paragraph (a) requires
the ordering physician to be treating the beneficiary; paragraph (a)(1) provides a
route through that requirement. Under a conjunction the case denies, and the
regulation says it should not.

This was found in Phase 3 and recorded as OD-23 and R-52 rather than fixed
immediately, because changing the decision table is a clinical behaviour change.

The general problem is larger than one exception. A conjunction cannot express
alternatives, exceptions, conditional applicability, or thresholds — all of which
appear in coverage policy as a matter of course. A lexical scan of the corpus finds
exception, alternative or conditional wording in **four of eight** policy versions.

## Problem

Give a policy a way to state its own logic, deterministically and inspectably,
without (a) inventing a rules engine nobody can read, (b) letting a model produce
the logic, or (c) invalidating the frozen gold set.

## Options

**A — Keep the conjunction; special-case 410.32 in code.** Smallest change. Also
the worst: the next exception needs another branch, the decision table stops being
a table, and the policy's logic lives in Python rather than beside the policy.

**B — A general rules engine (Drools-style, or a Datalog subset).** Expressive
enough for anything. Far too much: it introduces a language nobody reviewing
coverage policy can read, and reviewability is the property this layer exists to
have. Expressiveness bought at the cost of inspectability is a bad trade here.

**C — A small typed expression tree, three-valued, declared per policy version in
YAML.** Seven node types, no quantifiers, no variables, no inference. Serialisable,
diffable, and reviewable by someone who reads regulations rather than code.

**D — Have a model derive each policy's logic at ingest.** Rejected outright. The
logic *is* the decision rule; a model-authored decision rule is the invariant in
ADR-010 inverted.

## Decision

**Option C**, with four specific choices that matter more than the shape.

### 1. Three-valued Kleene logic, not two-valued

`UNKNOWN` is a truth value, not a missing input:

```
ANY(TRUE, UNKNOWN)  = TRUE      an alternative route already carries it
ALL(FALSE, UNKNOWN) = FALSE     the failure is decisive on its own
ANY(FALSE, UNKNOWN) = UNKNOWN   genuinely open
ALL(TRUE, UNKNOWN)  = UNKNOWN   genuinely open
```

The first line is the whole gain. A case can now be satisfied *despite* an
unanswered question, when the policy provides a path that does not depend on it.
Under two-valued logic the unknown must first be guessed, and guessing it false is
how automated prior authorization denies people for paperwork nobody requested.

### 2. Policy truth and recommendation are separate layers

```
criterion verdicts  →  PolicyTruth              →  Outcome
                       POLICY_SATISFIED            APPROVE_RECOMMENDED
                       POLICY_NOT_SATISFIED        DENY_RECOMMENDED
                       POLICY_INDETERMINATE        NEEDS_INFO / HUMAN_REVIEW
```

"The policy's conditions are met" and "approve this authorization" are different
claims. The second also weighs evidence quality, guardrail state and open
questions. A system that conflates them cannot say which of the two it got wrong.

### 3. The safety ordering is a choice of this system, made outside the logic

Kleene FALSE is decisive whatever else is unknown — logically, a denial follows.
This system holds the case instead, because an unresolved question is a reason to
ask, not a reason to refuse. That is **not** a property of the connectives, and
putting it inside them would hide a clinical policy inside a truth table. It lives
in `app/decision/table.py`, ordered and tested.

The single exception: when the policy is *already satisfied*, remaining unknowns
cannot change the answer and must not delay it. Asking anyway is delay dressed as
diligence.

### 4. An undeclared policy gets an explicit `ASSUMED_CONJUNCTION`

The old behaviour survives, unchanged, for every policy that has not declared its
logic — but it is now built explicitly, labelled, carried on the recommendation and
listed in the logic inventory. The behaviour is identical; what changed is that the
assumption is **visible**. That is the difference between a rule someone checked and
a default nobody has.

### 5. Evidence is required in whichever direction escapes the ordinary reading

One rule, applied in different directions per role:

| role | escaping value | without valid evidence |
|---|---|---|
| `REQUIRED` | FALSE (denies) | UNKNOWN |
| `EXCLUSION` | TRUE (denies) | UNKNOWN |
| `EXCEPTION_CONDITION` | TRUE (overrides a requirement) | UNKNOWN |

The third row was added during implementation, after a test showed an unevidenced
exception claim could approve a case. Claiming the exception would then have been
the cheapest possible attack on this system.

## Consequences

**Behaviour change, quantified.** Exhaustive comparison of the new engine against
the pre-Phase-4 table over 512,460 input combinations (up to 3 required + 2
exclusion criteria × all verdicts × all evidence states × all guardrail and
resolution states) found **3,472 divergences in two classes, both
`DENY_RECOMMENDED` → `NEEDS_INFO`**:

| divergence | n | cause |
|---|---|---|
| exclusion established, required criterion unevidenced-NOT_SATISFIED | 3,440 | old table checked the exclusion denial first |
| evidenced failure elsewhere, required criterion unevidenced-NOT_SATISFIED | 32 | old table checked the denial first |

Both share one cause: the old table treated `NOT_SATISFIED` with no evidence as a
*lesser* thing than `INSUFFICIENT_EVIDENCE` and checked it after the denial rows.
They are the same thing wearing different labels, and both are now open questions
evaluated before any denial — which is what ADR-010 said all along.

**No divergence moves a case toward a denial.** Asserted exhaustively by test, not
argued for here.

**gold_v1 is unaffected.** 0 of 156 gold cases and 0 of 222 synthetic cases sit in a
divergent class: case generation sets `has_valid_evidence` from the criterion state,
so an unevidenced `NOT_SATISFIED` never occurs. That is also a **dataset gap** — the
corpora cannot detect a regression in the behaviour that changed (R-57).

**The declared logic is not yet used by any case.** 410.32's logic exists, loads and
is tested, but gold_v1 was generated under assumed conjunction and is frozen.
Adopting declared logic for evaluation requires gold_v2 (OD-24).

**Four policy versions carry exception wording and remain undeclared.** The
inventory marks them `REVIEW_REQUIRED`; the runtime still assumes conjunction for
them. **The record states a doubt the runtime does not act on**, and closing that
gap means either declaring their logic — which requires reading them, i.e. OD-19 —
or routing them to human review, which invalidates gold_v1. Recorded as OD-24
rather than resolved by picking whichever is convenient.

**Purity is preserved.** `app/decision` still imports only `app/core` and its own
modules, performs no I/O and reads no clock — the date of service is an argument.
YAML loading lives in `app/policy/logic_loader.py`. The AST boundary test is
unchanged and still passes.

## Rejected alternatives, recorded

- **Inferring policy logic from wording.** A scan finds "except" in four versions;
  it cannot tell an exception from a cross-reference. Signals are search terms for
  a reviewer, and the inventory says so.
- **Making the safety ordering configurable.** A flag on a clinical safety property
  is a way of not deciding. It is decided, in one place, and tested.
- **Weakening `Unless` to a plain `Any`.** Truth-identical, but the inventory would
  lose the fact that the regulation frames something as an exception — which is
  what a reviewer most needs to see.
