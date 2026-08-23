# Data Foundation Quality Report

Counted from the artefacts on disk. **No targets are stated**, because a target
here would invite shaping the dataset to meet it.

> **The corpus is CMS-SHAPED, not CMS.** CMS is unreachable from this network
> (a geographic edge block, not a crawl policy). Every artefact below carries
> `provenance: synthetic`, and the first link of the credibility chain -
> AUTHORITATIVE POLICY - is therefore **unfilled**. What is verified here is the
> machinery, not the authority of the data it operates on.

## Provenance

| | |
|---|---|
| generated_at | `2026-08-23T12:14:22+00:00` |
| corpus | `tests/fixtures/cms` |
| corpus_kind | `synthetic` |
| criteria_sha256 | `21f8c961197d55e5` |
| cases_sha256 | `afba41c65cc64fe2` |
| gold_sha256 | `48fc67f00b38dc20` |
| gold_set_version | `1` |
| retrieval_set_version | `2` |

## Corpus

| metric | value |
|---|---|
| documents acquired | 6 |
| extraction success | 6/6 (100.0%) |
| documents rejected | 0 |
| distinct policy versions | 6 |
| sections detected | 25 |
| chunks produced | 24 |

No document was rejected or quarantined.

## Criteria provenance

| metric | value |
|---|---|
| criteria in inventory | 27 |
| with a verified source span | 27/27 (100.0%) |
| with a source page | 27/27 (100.0%) |
| linked to retrievable chunks | 27/27 (100.0%) |
| duplicate criterion ids | 0 |

Every criterion was **span-verified against the section it declares**. A
declaration whose text could not be located there is rejected at parse time,
not stored with weaker provenance.

## Cases

| metric | value |
|---|---|
| cases generated | 210 |
| duplicate case ids | 0 |
| dangling criterion references | 0 |
| cases with a policy link | 210/210 (100.0%) |
| labels recomputable from criterion states | verified by test |

### Category distribution (all cases)

| category | n |
|---|---|
| BORDERLINE | 20 |
| CLEARLY_FAILS | 35 |
| CLEARLY_SATISFIES | 35 |
| CONFLICTING_EVIDENCE | 15 |
| EXCLUSION_PRESENT | 25 |
| INSUFFICIENT_EVIDENCE | 20 |
| MISSING_DOCUMENTATION | 35 |
| POLICY_NOT_APPLICABLE | 25 |

### Decision distribution (all cases)

| decision | n |
|---|---|
| APPROVE_RECOMMENDED | 55 |
| DENY_RECOMMENDED | 60 |
| HUMAN_REVIEW | 15 |
| NEEDS_INFO | 80 |

### Criterion-state distribution

| state | all cases | gold |
|---|---|---|
| NOT_SATISFIED | 417 | 302 |
| SATISFIED | 491 | 360 |
| UNKNOWN | 91 | 67 |

### Missing-information distribution

| | all cases | gold |
|---|---|---|
| cases naming missing information | 55 | 40 |
| expected NEEDS_INFO | 80 | 60 |

## Partitions

| partition | n | may be used for |
|---|---|---|
| development | 40 | prompt, retrieval, threshold and model selection |
| validation | 15 | intermediate checks within a phase |
| gold | 155 | **nothing but a budgeted final scoring** |

Disjointness and completeness are asserted by test. Gold scorings spent: **0** of 1.

## Retrieval evaluation set

| metric | value |
|---|---|
| queries | 21 |
| linked to a criterion | 20/21 (95.2%) |
| criteria with at least one query | 20/27 (74.1%) |
| excluded, with stated reason | 1 |

## What this report does NOT establish

- **Not that the policies are authoritative.** They are CMS-shaped documents
  written for this project. Every downstream artefact inherits that.
- **Not label quality in a clinical sense.** Labels are computed from criterion
  states by `decide()`. They are consistent by construction, not expert judgement.
- **Not that measured performance will transfer.** Constructed cases state each
  fact once, unambiguously, where a reader expects it. Real submissions do not.
- **Not inter-annotator agreement.** One labeller, and that labeller is a program.
  Agreement was not measured because there is nothing to measure it between.
