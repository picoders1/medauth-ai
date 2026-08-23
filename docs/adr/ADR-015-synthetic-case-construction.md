# ADR-015: Synthetic Case Construction and Ground-Truth Provenance

**Status:** Accepted · **Date:** 2026-08-23 · **Phase:** Planning
**Not in the original brief.** Added because ground-truth provenance determines whether the
evaluation measures anything at all.

## Context

The project needs ~200 synthetic cases, ~150 gold-labelled. No real PHI may be used. The brief
names Synthea.

## Problem

**Where does the label come from?**

If a model writes the case and also assigns its label, the evaluation measures the model's
self-consistency. That is the failure mode that quietly invalidates a great many LLM evaluations,
and it is invisible in the results.

## Options

| # | Option | Assessment |
|---|---|---|
| A | Model generates cases and labels | Fast, scalable, **circular**. |
| B | Model generates cases; humans label | Non-circular. Slow, needs domain expertise not available here. |
| C | **Construct cases from the criteria tree; the construction determines the label** | Non-circular by design. Requires ADR-007's persisted tree. |
| D | Real de-identified cases | Highest validity. Requires data access, IRB and de-identification. Out of scope. |

## Decision

**Option C**, with human spot-check.

```
   criteria tree (Phase 2, HUMAN_REVIEWED)
        │
        ▼  choose a satisfaction PATTERN
   {c1: satisfied, c2: satisfied, c3: not_satisfied, exclusion_e1: absent}
        │
        ▼  the pattern IS the label — computed by the SAME decision table the system uses
   gold outcome = DENY_RECOMMENDED
        │
        ▼  narrative written to realise the pattern
   clinical note text  ← Synthea supplies demographic/clinical skeletons
```

- The label is a **property of the construction**, computed by `decide()`, never assigned by a
  model.
- Synthea provides demographics, conditions, procedures and medications; its output is gitignored.
- All 14 failure families (evaluation strategy §6) are constructed as explicit patterns.
- Split by the byte-exact hash rule; hashed; frozen; pinned in `eval/datasets/registry.yaml`.
- A documented human spot-check samples the corpus, targeting label leakage specifically.

### Guards against circularity

| Risk | Guard |
|---|---|
| Narrative leaks its label ("this clearly satisfies criterion 3") | Adversarial lint over generated text for criterion and outcome vocabulary; the spot-check targets this specifically |
| Construction and adjudication share prompt lineage | Different prompts, different phases, recorded here |
| Cases constructed from the same chunks that will be retrieved | Expected and acceptable — grounding is what is being tested. What is **not** claimed is generalisation to real notes |

## Rationale

**The label is not an opinion.** It is computed from the pattern by the same decision table the
system uses, so label quality equals criteria-tree quality — and the tree is human-reviewed
(ADR-007). This converts "is the label right?" into "is the tree right?", which is a question a
human can actually answer once per policy version instead of once per case.

**Failure families become constructible on purpose** rather than hoped for in a random sample. A
random sample of 150 cases would contain almost no citation-misattribution cases and no poisoned
chunks. Construction guarantees each family has a countable denominator.

**Synthea is convenience, not foundation.** It produces FHIR-shaped records, not prior-authorization
narratives with clinical justification — the narrative is the hard part and Synthea does not
generate it. Treating Synthea as the source of cases would have produced records that cannot be
adjudicated. It provides plausible skeletons; the pattern provides the substance.

**No real PHI, ever.** A test asserts no real-identifier patterns appear in the corpus.

## The limitation, stated permanently

Constructed cases are cleaner, better-structured and less ambiguous than real clinical notes.
Measured performance on them is an **upper bound**.

> The claim *"this system's measured performance transfers to real clinical documentation"* is
> **refused**, permanently, until an evaluation on real de-identified notes exists. No such
> evaluation is planned in this project.

This is recorded in the evidence ledger as a refused claim, not as a caveat in a footnote.

## Consequences

**Positive.** Ground truth is non-circular and inspectable. Failure families have real denominators.
The corpus is reproducible from the criteria trees plus a seed. No PHI risk. Label errors are
traceable to a specific criterion rather than to a labelling opinion.

**Negative.** Depends entirely on ADR-007 — no tree, no cases. Constructed narratives are unrealistic
in ways that flatter the system (R-22). Adversarial lint cannot catch every form of label leakage.
Case difficulty is bounded by the pattern space of the tree, so subtle real-world ambiguity is
under-represented.

**Neutral.** The corpus is tightly coupled to the Phase 1 procedure set. Extending the corpus means
extending the corpus of policies first — which is the correct dependency direction.

## Rejected alternatives

| Alternative | Rejected because |
|---|---|
| **A — model generates cases and labels** | Circular. Measures self-consistency and reports it as accuracy. The single most damaging shortcut available here. |
| **B — model generates, humans label** | Non-circular but requires clinical coverage expertise that this project does not have; labels would be no better than the tree, at far greater cost. |
| **D — real de-identified cases** | Highest validity and out of scope: data access, IRB, de-identification and re-identification risk. Its absence is why the generalisation claim stays refused. |
| **Synthea as the primary source** | Generates FHIR records, not narratives with clinical justification. The narrative is the input this system reasons over. |
