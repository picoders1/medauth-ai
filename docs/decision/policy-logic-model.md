# Policy Logic Model

How a policy states its own decision rule, and what the system does with it.
Design rationale is in [ADR-023](../adr/ADR-023-policy-logic-representation.md);
this is the reference.

---

## The three layers

```
per-criterion verdicts          SATISFIED · NOT_SATISFIED · INSUFFICIENT_EVIDENCE · NOT_APPLICABLE
        │                       (from the model, one call per criterion)
        ▼  leaf_value()         evidence asymmetry applied here
truth values                    TRUE · FALSE · UNKNOWN
        │
        ▼  evaluate()           Kleene, over the policy's declared expression
policy truth                    POLICY_SATISFIED · POLICY_NOT_SATISFIED · POLICY_INDETERMINATE
        │
        ▼  decide()             safety ordering, guardrail, resolution
recommendation                  APPROVE_RECOMMENDED · DENY_RECOMMENDED · NEEDS_INFO
                                HUMAN_REVIEW · NO_DECISION
```

**Policy truth is not a recommendation.** "The conditions are met" is a statement
about a regulation; "approve" is advice to a reviewer that also weighs evidence
quality, guardrail state and open questions. Keeping them apart is what lets the
system say *which* of the two it got wrong.

## Nodes

Seven, and no more. This is not a theorem prover: no quantifiers, no variables, no
inference. A policy's logic has to be readable by someone who reads regulations.

| node | meaning | YAML |
|---|---|---|
| `Leaf` | one criterion, by id | `{leaf: <criterion_id>}` |
| `All` | conjunction | `{all: [...]}` |
| `Any` | disjunction — an alternative pathway | `{any: [...]}` |
| `Not` | negation | `{not: {...}}` |
| `AtLeast` | *n* of the children | `{at_least: {n: 2, of: [...]}}` |
| `Unless` | rule holds unless the exception does | `{unless: {rule: {...}, exception: {...}}}` |
| `When` | conditional applicability | `{when: {condition: {...}, then: {...}}}` |

`Unless` is truth-identical to `Any(rule, exception)` and exists anyway: it records
that the regulation frames something as an exception to a stated requirement, which
a bare disjunction throws away and which is exactly what a reviewer needs to see.
A test asserts the two truth tables match, so the extra spelling cannot drift into
a different meaning.

## Kleene semantics

| | result |
|---|---|
| `ALL` | FALSE if any child is FALSE; TRUE if all TRUE; else UNKNOWN |
| `ANY` | TRUE if any child is TRUE; FALSE if all FALSE; else UNKNOWN |
| `NOT` | swaps TRUE and FALSE; UNKNOWN negates to UNKNOWN |
| `AtLeast(n)` | TRUE at *n* TRUEs; FALSE when even every UNKNOWN resolving TRUE cannot reach *n*; else UNKNOWN |
| `When` | TRUE if the condition is FALSE — an inapplicable rule cannot fail |

Four rows do the work:

```
ANY(TRUE, UNKNOWN)  = TRUE      ← the reason this module exists
ALL(FALSE, UNKNOWN) = FALSE
ANY(FALSE, UNKNOWN) = UNKNOWN
ALL(TRUE, UNKNOWN)  = UNKNOWN
```

A definite Kleene value means *definite under every completion of the unknowns*. So
a satisfied policy stays satisfied whatever the open questions turn out to be, and
holding the case for them would be delay, not caution.

## The evidence asymmetry

A verdict with nothing behind it must never be load-bearing. Which truth value that
constrains depends on the criterion's role, because it is always **the direction
that escapes the ordinary reading of the policy**:

| role | escaping value | with evidence | without |
|---|---|---|---|
| `REQUIRED` | FALSE (denies) | FALSE | **UNKNOWN** |
| `EXCLUSION` | TRUE (denies) | TRUE | **UNKNOWN** |
| `EXCEPTION_CONDITION` | TRUE (overrides a requirement) | TRUE | **UNKNOWN** |
| `INFORMATIONAL` | neither | taken at face value | taken at face value |

`NOT_APPLICABLE` takes whichever value is inert for the role: TRUE for a
requirement (a rule that does not apply cannot block), FALSE for an exclusion.

The `EXCEPTION_CONDITION` row was added after a test showed an unevidenced
exception claim could approve a case. Claiming the exception would then have been
the cheapest available attack on this system.

## The safety ordering

Evaluated in this order, in `app/decision/table.py`:

| # | condition | outcome |
|---|---|---|
| 1 | resolution empty | `NEEDS_INFO` — **never a denial** |
| 2 | resolution conflicting | `HUMAN_REVIEW` |
| 3 | citation unverifiable | `NO_DECISION` |
| 4 | model path failed or blocked | `HUMAN_REVIEW` |
| 5 | contradictory verdicts | `HUMAN_REVIEW` |
| 5a | policy logic `REVIEW_REQUIRED` | `HUMAN_REVIEW` |
| 5b | policy out of its temporal window | `HUMAN_REVIEW` |
| **9/11** | **policy satisfied** | `APPROVE_RECOMMENDED` |
| 6 | any criterion UNKNOWN | `NEEDS_INFO` |
| 7 | exclusion established | `DENY_RECOMMENDED` |
| 8 | policy not satisfied | `DENY_RECOMMENDED` |
| 10 | anything else | `HUMAN_REVIEW` |

Two things about this order are deliberate and neither follows from the logic:

**Satisfaction is checked before unknowns.** If a pathway already holds, no
unanswered question can change the answer.

**Unknowns are checked before every denial.** Kleene FALSE is decisive whatever
else is unknown, so pure logic would deny. This system holds the case instead. That
is a safety choice of this system, made here rather than inside the connectives,
where it can be read, ordered and tested.

Rule 11 (`EXCEPTION_SATISFIED`) replaces rule 9 when a **required** criterion
evaluated FALSE and the policy holds anyway — so an approval reached through an
alternative pathway says so, instead of reporting that everything was met.

## Purity

`app/decision` imports only `app/core` and its own modules. No I/O, no clock, no
network, no randomness — the date of service is an argument, never a reading of the
current time. A temporal predicate that consulted a clock would make the truth table
a statement about the day it ran. YAML loading lives in
`app/policy/logic_loader.py`; the AST boundary test enforces the separation.

## Declaring logic

`data/policy_logic/<policy>.yaml`:

```yaml
policy_id: "42 CFR 410.32"
policy_version: "2026-08-13"
form: DECLARED          # or REVIEW_REQUIRED
requirements:
  all:
    - unless:
        rule: {leaf: 42_CFR_410_32_2026_08_13_C01}
        exception:
          all:
            - {leaf: 42_CFR_410_32_2026_08_13_C05}
            - {leaf: 42_CFR_410_32_2026_08_13_C06}
    - {leaf: 42_CFR_410_32_2026_08_13_C02}
exclusions: {any: [...]}          # optional
review_notes: ["UNRESOLVED: ..."] # what declaring this did NOT settle
```

The parser is strict. An unknown node type, a missing key, an empty branch, two
keys in one mapping, or a criterion id absent from the inventory **raises**. A typo
that silently degraded `unless` into `all` would turn an alternative pathway back
into an absolute requirement — reintroducing the exact defect this exists to
remove, with no error and no failing test to show for it.

## What is not modelled

- **Cross-policy logic.** Each policy is evaluated alone; conflicts between
  resolved policies route to a human (rule 2).
- **Numeric comparison.** `AtLeast` counts children, it does not compare values. A
  threshold like "within 6 months" is adjudicated as a criterion and enters as a
  verdict.
- **Cross-references to untranscribed provisions.** 410.32 C03 invokes supervision
  levels set out in paragraph (b)(3), which is not transcribed, so the criterion is
  not independently checkable (R-51). The representation cannot fix this; only
  transcribing the referenced provision can, and that is gated on OD-19.
