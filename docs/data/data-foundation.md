# Data Foundation

**Status:** Machinery complete and verified. **Data not authoritative.**

The overview: what exists, what it is worth, and what must be built on it next.

---

## 1. The credibility chain, and where it currently breaks

```
AUTHORITATIVE POLICY        <-- UNFILLED. CMS unreachable; corpus is CMS-shaped
        v
POLICY VERSION              <-- built, temporally resolved, 4 mandatory tests
        v
POLICY CRITERION            <-- declared, span-verified to section/page/offset
        v
SYNTHETIC CLINICAL CASE     <-- 210, generated FROM criteria
        v
CRITERION-LEVEL TRUTH       <-- primary label; decision derived, never assigned
        v
FROZEN GOLD SET             <-- 155 cases, stratified, hashed, budget 1
        v
RETRIEVAL EVALUATION        <-- 21 queries, criterion-linked
        v
AGENTIC REASONING           <-- not built
```

Every link below the first is real machinery. The first is not filled, and nothing
downstream can be stronger than it. This document does not soften that, and neither
does any report derived from the data.

---

## 2. What was built

| Component | Artefact |
|---|---|
| Criterion model with span verification | `app/policy/criteria.py` |
| Declared criteria in policy front matter | `tests/fixtures/cms/*.md` |
| Criteria inventory | `data/criteria/inventory.jsonl` (27) |
| Case template layer | `data/synthetic/case_templates.yaml` (19 fact keys) |
| Criterion-driven generator | `eval/casegen.py` |
| Pure decision table | `app/decision/table.py` |
| Case corpus | `data/synthetic/cases/cases.jsonl` (210) |
| Partitions | development 40 / validation 15 / gold 155 |
| Frozen gold set | `data/gold/cases/gold_v1.jsonl` |
| Retrieval set | `eval/datasets/retrieval/questions.yaml` (21) |
| Quality report | `eval/reports/*__data-foundation/report.md` |

---

## 3. The three decisions that carry the phase

### Criteria are declared and verified, never inferred

A criterion is declared in the policy document with a section anchor and its exact
source text. Ingestion locates that text in that section using the same normalizer
that verifies citations, and **rejects the document if it cannot**.

Four rejection paths are exercised by test: text absent from the document, text
present but in a *different* section, a section that does not exist, and a duplicate
fact key. The third is the interesting one - it is the misattribution case, where a
criterion quotes something real and attributes it to the wrong place.

This is what a human reviewer does with a real determination, and it is why a real
document slots in without code changes: a human transcribes its criteria into the
same structure and the identical verification runs.

### Labels come from the same function the system uses

`app.decision.table.decide` computes every case-level label from its criterion
states. Building it during a *data* phase was deliberate: ADR-015 requires the gold
label and the runtime decision to come from one function, and a separate labelling
implementation would drift - the evaluation would then measure the gap between two
pieces of code rather than the behaviour of one.

A test recomputes all 210 labels from their criterion states. Disagreement fails the
build.

The abstention gate is **not** built. It reads thresholds that Phase 6 must
calibrate on the development split, and inventing one now would be a fabricated
threshold with clinical consequences.

### UNKNOWN is an omission

A criterion with no evidence produces **no sentence in the note**. Not "duration
unknown" - real submissions do not annotate their own gaps, and a system that reads
such a hint has not detected anything.

This is what makes `NEEDS_INFO` a real test rather than a keyword match, and a test
asserts the word does not appear in any note.

---

## 4. Evaluation taxonomy

Fixed now so later results are attributable. Failures are never collapsed into one
accuracy number: the six layers fail differently and are fixed differently.

| Layer | Question | Measured against | Status |
|---|---|---|---|
| 1 Policy resolution | Right policy version for this date of service? | gold `expected.policy_id` + `policy_revision` | data ready; measured Phase 1 |
| 2 Evidence retrieval | Right section for this query? | retrieval set, criterion-linked | data ready; baseline exists |
| 3 Criterion adjudication | Right state per criterion? | gold `expected.criteria[]` | data ready; **needs Phase 4** |
| 4 Final decision | Right recommendation? | gold `expected.decision` | data ready; **needs Phase 5** |
| 5 Citation grounding | Every claim span-verified and correctly attributed? | chunk text + criterion provenance | machinery exists; **needs Phase 5** |
| 6 Abstention | Declines when it should, and only then? | `UNKNOWN` states, missing-information list | data ready; **needs Phase 6** |

Layer 3 is the one this phase makes possible. Without criterion-level ground truth a
wrong decision cannot be attributed to a wrong criterion, and the system's most
important property - that a decision never hides which criteria produced it - is
unmeasurable.

---

## 5. What is verified, and what is not

**Verified by test:** criterion provenance to section/page/offset; rejection of
unlocatable criteria; label recomputation for all 210 cases; partition disjointness
and completeness; absence of gold vocabulary from inputs; no duplicate case or
criterion ids; gold-set hash matches its manifest; category, policy-version,
decision and temporal coverage of the gold set; absence of identifier patterns;
retrieval queries linked to real criteria and not copied from them.

**Not verified, and not claimed:** that the policies are authoritative; that the
criteria match any real determination; that labels reflect clinical judgement; that
measured performance transfers to real documentation; inter-annotator agreement -
one labeller, and it is a program.

---

## 6. Open items

| Item | Status |
|---|---|
| **R-33** corpus is CMS-shaped, not CMS | Open, accepted |
| **OD-15** Articles unreachable by resolution | Open. Excluded from denominators with reason |
| **OD-16** integration tests share one database | Open |
| Reranking reduces recall@1 | **Retained.** Not tuned away; ADR-006 claim withdrawn |
| Clinician review | Not performed, not scheduled |
| Inter-annotator agreement | Not measurable with one labeller |

---

## 7. What must not be built on this yet

The gold set is frozen with a budget of one scoring. Until Phases 4-6 exist there is
nothing to score, and the correct thing to do with it is nothing at all.

Prompt wording, retrieval parameters, thresholds and model selection are tuned on
`development` (40 cases) with `validation` (15) for intermediate checks. Touching
gold before a final scoring converts a held-out set into a slow-motion training set,
and the loss is undetectable afterwards.
