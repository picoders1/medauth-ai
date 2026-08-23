# Policy Dependency Model

A criterion that invokes a rule it does not contain cannot be adjudicated on its own
evidence. This records which criteria those are, so none of them is ever presented
as independently sufficient.

Artefact: `data/review/policy_dependencies.json`, built by
`scripts/build_dependency_report.py`.

---

## The problem, concretely

42 CFR 410.32 **C03** says *"the appropriate level of supervision"*. The levels are
set out in paragraph **(b)(3)**, which is **not transcribed**.

```
C03  "appropriate level of supervision"
  └── depends_on ── 42 CFR 410.32 (b)(3)  "Levels of supervision..."
                      └── review_status: PENDING   (REQUIRES_HUMAN_REVIEW)
```

Adjudicating C03 means asking a model whether a case meets a standard the evidence
set **cannot contain**, because (b)(3) is not a criterion and therefore not
retrievable as that criterion's evidence. Any verdict it returns is unfounded,
however confident — and the citation contract will not catch it, because the model
can cite C03's own text perfectly while answering the wrong question. This is R-51.

## Dependencies are recorded, never detected

They come from `KNOWN_DEPENDENCIES` in `scripts/build_review_package.py`, each
established by individual inspection in Phase 3.

That is not laziness. A regex over criterion text finds **none of them**: C03 never
writes the words *"paragraph (b)(3)"* — the dependency is semantic, not textual. A
looser heuristic (*"shares a section with a criterion"*) was tried and produced
**65** false positives, each carrying a review question asserting a dependency that
was not there. **A form that tells a reviewer something false is worse than one that
tells them nothing.**

## Current state

| | |
|---|---|
| criteria | 35 |
| with a recorded dependency | **5** |
| blocked by an unresolved dependency | **5** |

| criterion | depends on |
|---|---|
| `42_CFR_410_32_2026_08_13_C03` | 410.32 `(b)(3)` — supervision levels |
| `42_CFR_410_38_2022_01_01_C02` | 410.38 `(d)(1)(ii)(A)`, `(B)` — order timing |
| `42_CFR_410_38_2022_01_01_C03` | 410.38 `(d)(1)(ii)(A)` |
| `42_CFR_410_38_2026_08_13_C02` | 410.38 `(d)(1)(ii)(A)`, `(B)` |
| `42_CFR_410_38_2026_08_13_C03` | 410.38 `(d)(1)(ii)(A)` |

Every one carries `independently_adjudicable: false`, asserted by test. A dependency
naming a provision absent from the coverage matrix is a **hard error** rather than a
skipped row — a dependency on something that does not exist is a stale record, not a
missing one.

## Relationship to the review queue

All five depended-upon provisions rank **priority 1** in the OD-19 queue — the tier
reserved for provisions a transcribed criterion may be unevaluable without. That is
the whole reason priority 1 exists, and it is why it holds five rows rather than the
65 an earlier heuristic put there.

Resolving a dependency means a reviewer ruling `REPRESENT_AS_CRITERION` on the
provision and someone transcribing it. Until then the dependent criterion stays
blocked, and the report says so.

## What this does not claim

It does **not** claim the 30 criteria without a recorded dependency are
independently adjudicable. It claims only that no dependency has been *recorded* for
them. Recorded dependencies come from inspection of seven confirmed gaps; the
remaining 246 provisions have not been read, and reading them is exactly what OD-19
gates.
