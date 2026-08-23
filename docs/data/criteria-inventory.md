# Criteria Inventory

**33 criteria across 7 policy versions, every one span-verified against
authoritative 42 CFR text.**

Machine-readable: `data/criteria/inventory.jsonl`.
Verification record: `data/criteria/verification.json`.

---

## 1. How a criterion comes to exist

```
eCFR API  ->  acquired document (verbatim, never edited)
                     |
                     v
          human transcribes criteria into data/criteria/transcriptions/
                     |
                     v
          scripts/verify_criteria.py  --  SPAN VERIFICATION GATE
                     |
              pass  |  fail -> pipeline stops, nothing written
                     v
          data/criteria/inventory.jsonl
```

**No model extracts criteria.** A person reads the regulation and transcribes what
it requires. The gate then checks that the transcribed wording actually occurs in
the section it cites, using the same normalizer that verifies citations at runtime.

That division is the point. Transcription is a human judgement about *which*
requirements matter; verification is a mechanical check that the transcription did
not drift from the text. Neither substitutes for the other.

---

## 2. What every criterion carries

| Field | Source | Meaning |
|---|---|---|
| `criterion_id` | derived | `42_CFR_410_38_2026_08_13_C01` - stable, never free text |
| `policy_id`, `policy_version` | document | The exact revision it was verified against |
| `criterion_type` | curated | REQUIRED, EXCLUSION or INFORMATIONAL |
| `fact_key` | curated | The clinical fact a case varies to exercise it |
| **`authoritative_text`** | **regulation** | **Verbatim. Span-verified. What a citation quotes.** |
| `normalized_interpretation` | curated | A plain reading, for reviewers. **Never replaces the above** |
| `applicability` | curated | When the criterion bears on a request at all |
| `source_section`, `source_page`, `source_span` | verified | Where it was located, to the character |
| `source_chunk_refs` | derived | Which retrievable chunks cover it |
| `comparator`, `threshold`, `unit` | curated | Machine-checkable shape, where the criterion has one |
| `source_url`, `document_sha256` | acquisition | The document as fetched |
| `curator`, `curator_role`, `curated_at` | curated | Who made the claim, and what they are not |

`authoritative_text` and `normalized_interpretation` are separate fields and a test
asserts they differ. If the interpretation ever stood in for the regulation, the
interpretation would quietly become the policy.

---

## 3. Coverage

| Policy | Revision | Required | Exclusion | Total | Role |
|---|---|---|---|---|---|
| 42 CFR 410.32 | 2026-08-13 | 4 | 0 | 4 | PRIMARY |
| 42 CFR 410.33 | 2026-08-13 | 4 | 1 | 5 | PRIMARY |
| 42 CFR 410.38 | 2022-01-01 | 4 | 1 | 5 | PRIMARY |
| 42 CFR 410.38 | 2026-08-13 | 4 | 1 | 5 | PRIMARY |
| 42 CFR 410.61 | 2019-01-01 | 5 | 0 | 5 | PRIMARY |
| 42 CFR 410.61 | 2026-08-13 | 5 | 0 | 5 | PRIMARY |
| 42 CFR 411.15 | 2026-08-13 | 0 | 4 | 4 | **EXCLUSION_OVERLAY** |

Criterion kinds represented: documentation content, documentation timing, ordering
authority, clinical purpose, supervision level, personnel qualification, numeric
thresholds, setting conditions, and categorical exclusions.

---

## 4. Two findings worth carrying forward

### A transcription does not survive a revision automatically

42 CFR 410.38's criteria were transcribed against the 2026-08-13 text. Verified
against earlier revisions:

| Revision | Result |
|---|---|
| 2022-01-01 | **verifies** - the cited spans are unchanged |
| 2019-01-01 | **REFUSED** - the section was restructured; the spans do not exist |

The 2019 revision therefore has **no** transcription. That is the correct outcome:
carrying criteria across an amendment without re-verifying would silently
misattribute requirements to a text that never contained them. Each revision that
does verify is published as its own transcription file, re-verified, and the fact
recorded in its notes.

### A real policy can be authoritative and still not decidable

42 CFR 411.15 declares only exclusions and no required criteria. Generating
standalone cases against it drove every case to the decision table's totality guard
(row 10) - the table correctly reporting that it cannot classify a request with no
requirements to satisfy.

It is marked `EXCLUSION_OVERLAY`. Its criteria remain in the inventory and
retrievable; it is simply not a basis for a decision on its own.

---

## 5. What this inventory does **not** establish

- **Not completeness.** These are the criteria one non-clinician judged material. A
  regulation contains more requirements than are transcribed here, and nothing
  checks that the important ones were chosen.
- **Not clinical correctness.** Span verification proves the transcription is
  faithful to the text. It says nothing about whether the interpretation matches how
  the requirement is applied in practice.
- **Not coverage authority.** 42 CFR is regulation - the layer above NCDs and LCDs.
  A criterion here is not a coverage determination.
- **Not reviewed by a clinician.** No clinician has seen any criterion.

---

## 6. Regenerating

```bash
uv run python scripts/acquire_ecfr.py --as-of 2026-08-13 --sections 410.32 410.38
uv run python scripts/verify_criteria.py     # gate; fails loudly, repairs nothing
```

The gate never re-anchors a span or accepts a near match. A failure means the
regulation was amended or the transcription is wrong, and both need a person.
