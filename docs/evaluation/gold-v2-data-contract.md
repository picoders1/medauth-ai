# gold_v2 data contract

**Dataset:** `data/gold/cases/gold_v2.jsonl` · **Manifest:**
`data/gold/manifests/gold_v2.manifest.json` · **Builder:** `scripts/build_gold_v2.py`
**Tests:** `tests/evaluation/test_gold_v2.py` · **Resolves:** R-97 · **Budget:** 1, unspent

---

## The one claim

> **Every fact needed to derive a case's expected outcome is in structured data.**
> No ground truth lives only in narrative prose, in fixture behaviour, in a code
> comment, or in a test-only assumption.

R-97 was that claim being false for eighteen cases. It survived four phases because
nothing checked it — the runtime asserted `RESOLVED`, and a stage that never runs
cannot disagree with a label.

## Shape

`input` and `expected` are separate objects. The system is handed `input` only, and a
test asserts no gold token appears inside it.

```jsonc
{
  "case_id": "CASE-0073",
  "case_version": "gold_v2",
  "schema_version": "2",
  "scenario_type": "POLICY_NOT_APPLICABLE",
  "derived_from": { "dataset": "gold_v1", "case_id": "CASE-0073" },

  "input": {
    "requested_service": { "procedure_code": "A0428", "code_system": "HCPCS" },
    "diagnosis_codes": [], "jurisdiction": null,
    "date_of_service": "2026-09-28",
    "patient": { "age": 60, "sex": "M", "synthetic": true },
    "clinical_note": "…"
  },

  "expected": {
    "policy_type": "REGULATION",
    "policy_id": "42 CFR 410.33",
    "policy_version": "2026-08-13",

    "applicability": {
      "state": "NONE_APPLICABLE",
      "reason": "NO_POLICY_LISTS_THE_PROCEDURE",
      "structured_facts": {
        "procedure_code_linked_to_policy": false,
        "code_system_stated": true,
        "date_of_service_stated": true,
        "jurisdiction_stated": false
      },
      "derivable_from_structured_input": true,
      "derivation": "(HCPCS A0428) does not appear in data/linkage/policy_code_links.yaml …"
    },

    "criterion_states": {}, "criterion_kinds": {},
    "policy_truth": "NO_APPLICABLE_POLICY",
    "recommendation": "NEEDS_INFO",
    "decision_rule": 1,
    "missing_information": [],
    "evidence_refs": {},
    "evidence_ground_truth": "SECTION_LEVEL. …chunk-level is NOT established…",
    "labelling": "derived by construction via app.decision.table.decide …"
  }
}
```

## The parts that carry weight

**`applicability` is re-derived, never trusted.**
`test_every_applicability_state_follows_from_the_structured_input` computes the state
from `input.requested_service` plus the committed linkage and compares. Reading the
case's own assertion would check that the file agrees with itself.

**`policy_truth` is an evaluation, or explicitly not one.** Where no policy governs
it reads `NO_APPLICABLE_POLICY` rather than a `PolicyTruth` member, so an
unevaluated policy cannot look evaluated.

**`evidence_refs` are `policy:version:ordinal`, never database UUIDs.** Chunk ids are
assigned at ingest; recording them would tie the dataset to one database and
inventing them would be fabricated ground truth. `evidence_ground_truth` states the
level is section-level and that chunk-level is **not** established — the third option
and the only correct one.

**`labelling` names the function.** Every recommendation is recomputed by the same
`decide()` the system runs (ADR-015), and
`test_recomputing_every_label_reproduces_the_dataset` re-runs all 156.

## What is deliberately absent

| absent | why |
|---|---|
| an outcome field in `input` | the system is handed `input` only; a leaked label makes an evaluation a measurement of its own answer key |
| chunk-level evidence ids | not established; see above |
| a clinical validation flag | none exists, and a `false` would invite a `true` later |
| engineered class balance | the distribution is inherited from gold_v1 case-for-case and a test asserts it |

## Non-covered codes

The eighteen not-applicable cases carry a procedure code the corpus does not link,
verified against NLM Clinical Tables for **existence and description only, never
coverage** (`data/linkage/noncovered_code_metadata.jsonl`,
`scripts/fetch_noncovered_codes.py`). Both halves are asserted: a code that does not
exist is not a fix, and a code that later acquires a link would silently make
eighteen labels wrong.

They live in a separate file because `scripts/fetch_code_metadata.py` regenerates
`code_metadata.jsonl` from the linkage and would delete anything unlinked. Two files,
two invariants:

    code_metadata.jsonl             every LINKED code exists
    noncovered_code_metadata.jsonl  these codes exist and are NOT linked

## Budget

**1 scoring, unspent.** Pre-registered for `phase16-evaluation-001`
([ADR-029](../adr/ADR-029-phase16-experiment-preregistration.md)). A second requires
its own ADR, in advance.
