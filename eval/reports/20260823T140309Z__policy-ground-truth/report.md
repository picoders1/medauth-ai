# Policy Ground-Truth Report

Counted from the artefacts on disk. **No targets are stated.**

> **Authoritative policy, curated criteria, synthetic cases.** The policy text is
> real 42 CFR from the official eCFR API. The criteria are human transcriptions of
> that text, span-verified against it. The code linkage and the cases are curated
> and constructed respectively, and are authoritative for nothing.

## Corpus

| metric | value |
|---|---|
| authority | Office of the Federal Register (eCFR API) |
| policies | 5 |
| policy versions | 7 |

## Criteria

| metric | value |
|---|---|
| total | 33 |
| span-verified | 33 |
| **failed verifications** | **0** |
| with a numeric threshold | 3 |
| by type | {'EXCLUSION': 7, 'REQUIRED': 26} |

## Code linkage — HUMAN-CURATED, authoritative for nothing

| metric | value |
|---|---|
| HCPCS links | 14 |
| ICD-10-CM links | 2 |
| codes verified to exist (NLM) | 12 |
| by confidence | {'high': 10, 'low': 2, 'medium': 4} |

## Cases

| metric | value |
|---|---|
| total | 222 |
| gold (frozen) | 156 |
| development | 48 |
| validation | 18 |
| naming missing information | 60 |
| gold scorings spent | 0 |

**Decisions:** {'APPROVE_RECOMMENDED': 72, 'DENY_RECOMMENDED': 48, 'HUMAN_REVIEW': 18, 'NEEDS_INFO': 84}

**Categories:** {'BORDERLINE': 24, 'CLEARLY_FAILS': 36, 'CLEARLY_SATISFIES': 36, 'CONFLICTING_EVIDENCE': 18, 'EXCLUSION_PRESENT': 24, 'INSUFFICIENT_EVIDENCE': 24, 'MISSING_DOCUMENTATION': 36, 'POLICY_NOT_APPLICABLE': 24}

**Criterion states:** {'NOT_SATISFIED': 123, 'SATISFIED': 726, 'UNKNOWN': 108}

**Temporal:** {'CURRENT_POLICY': 148, 'HISTORICAL_POLICY': 74}

## Retrieval

23 queries, 23 criterion-linked, revisions ['2019-01-01', '2022-01-01', '2026-08-13'].

| encoder | reranker | recall@1 | recall@5 | MRR | p50 ms | n |
|---|---|---|---|---|---|---|
| `BAAI/bge-base-en-v1.5` | `none` | 0.7619 | 1.0000 | 0.8429 | 24.6 | 21 |
| `BAAI/bge-base-en-v1.5` | `BAAI/bge-reranker-base` | 0.5714 | 0.9524 | 0.7528 | 2612.16 | 21 |
| `BAAI/bge-base-en-v1.5` | `cross-encoder/ms-marco-MiniLM-L-6-v2` | 0.8095 | 1.0000 | 0.8825 | 529.98 | 21 |
| `BAAI/bge-small-en-v1.5` | `none` | 0.7143 | 1.0000 | 0.8349 | 14.74 | 21 |
| `BAAI/bge-small-en-v1.5` | `BAAI/bge-reranker-base` | 0.5714 | 0.9524 | 0.7528 | 2589.9 | 21 |
| `BAAI/bge-small-en-v1.5` | `cross-encoder/ms-marco-MiniLM-L-6-v2` | 0.8095 | 1.0000 | 0.8825 | 459.96 | 21 |

## Known exclusions — nothing is dropped silently

| item | excluded from | reason |
|---|---|---|
| 42 CFR 411.15 | case generation | EXCLUSION_OVERLAY - declares only exclusions and no required criteria, so it cannot support a standalone decision |
| 42 CFR 410.38 rev 2019-01-01 | criterion transcription | section restructured; 2026 criteria do not locate in it, and carrying a transcription across an amendment is refused |
| 42 CFR 410.43 | criterion transcription | too few headed paragraphs to anchor criteria reliably |

## Known limitations

- 42 CFR is regulation, not an NCD or LCD - a criterion here is not a coverage determination
- code linkage is a human-curated engineering artefact and is authoritative for nothing
- transcription completeness is unverified: nothing checks the right criteria were chosen
- no clinician has reviewed any criterion, case or label
- inter-annotator agreement is not measurable - one labeller, and it is a program
- clinical notes are constructed; measured performance is an upper bound
- MIMIC-IV-Note is NOT accessed and NOT available to this project
