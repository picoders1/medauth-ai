# NCD Coverage Layer

The corpus now has two layers of authority, and they are never merged.

```
   42 CFR                         NCD
   REGULATION                     COVERAGE DETERMINATION
   statutory conditions           is this item covered
   of payment                     nationally?
        │                              │
        └──────────┬───────────────────┘
                   ▼
        deterministic resolution   (code × jurisdiction × date of service)
                   │
        ┌──────────┴───────────┐    partitioned by document_type
        ▼                      ▼    a scope names ONE layer
   REGULATION scope       NCD scope
        │                      │
        ▼                      ▼
   policy evaluation      coverage resolution
   POLICY_SATISFIED       COVERED / NOT_COVERED / CONDITIONAL
   POLICY_NOT_SATISFIED   NOT_ESTABLISHED / NOT_APPLICABLE / UNKNOWN
        │                      │
        └──────────┬───────────┘
                   ▼
          future adjudication layer  (NOT built in Phase 5)
                   ▼
          recommendation for a human reviewer
```

---

## Why they must not merge

**Satisfying a regulation is not coverage.** 42 CFR states conditions of payment; an
NCD states whether an item is covered at all. A case can satisfy every statutory
condition and still not be covered, and can be covered while failing one.

**Absence of an NCD is not a denial.** No national determination generally means
contractor discretion or case-by-case adjudication. `NOT_ESTABLISHED` exists so that
"nobody has ruled nationally" has a name of its own and cannot be typed as
`NOT_COVERED`. This is the single most damaging error available in the layer.

Neither `CoverageStatus` nor anything in `app/coverage/` names `APPROVE` or `DENY`,
and a test asserts it. Mapping a coverage state to a recommendation is a clinical
policy decision that belongs to an adjudication layer that does not exist yet.

## How the layers are kept apart

**In the database.** `policy_documents.document_type` now carries a CHECK
constraint. ADR-022 made the separation non-negotiable; Phase 5 makes it a database
property rather than a Python convention.

**In retrieval.** `ResolutionResult.version_ids` is **deleted**. It flattened every
resolved version into one list, and one ANN query over both layers would rank a
statutory chunk against a coverage-determination chunk on cosine distance. Its
replacement is `scope_for(document_type)`, which partitions by each version's
*actual* type — so a scope whose ids disagree with its label is unconstructible.

**In the query.** `build_search_statement` filters on `document_type` as well as on
ids. That predicate is defence-in-depth and the two are not equally load-bearing:
the id partition does the work in practice, and the predicate catches a hand-built
scope whose label and ids disagree. Both facts are measured — see
`test_a_hand_built_scope_cannot_borrow_another_layers_ids`.

## What an ingested NCD can and cannot do

An NCD arrives with **no transcribed criteria**, so it lands on
`SemanticsStatus.NO_CRITERIA` and routes to `HUMAN_REVIEW`. It is corpus and
evidence for a human; it is structurally incapable of producing an adjudication
until someone transcribes criteria and declares logic through OD-19.

**That is what makes ingesting a criteria-free coverage layer safe.** The
fail-closed gate from Part A is the precondition for this part existing at all.

## Code linkage is curated, and cannot be otherwise

The MCIM NCD record carries **no procedure-code field** — 19 fields, none of them
codes, verified by live probe. So NCD applicability cannot come from the document,
and the linkage is `HUMAN_CURATED`, exactly as it is for 42 CFR and for the same
reason. **Nothing may claim CMS supplies it.**

## What is not here

LCDs and Billing & Coding Articles. Their endpoints return `401` behind an
AMA/ADA/AHA licence gate. No agreement was accepted and no gated endpoint was
requested (ADR-022, OD-21). A test asserts the selection record requests neither.
