# NCD Data Model

What the CMS Coverage API provides, what is stored, and what is deliberately not
invented. Every property below was verified by live probe during Phase 5, not
assumed from documentation.

---

## The source record

`GET https://api.coverage.cms.gov/v1/data/ncd?ncdid=<id>[&ncdver=<n>]` returns
`{meta: {status, fields, children, next_token}, data: [record]}` with **19 fields**:

```
document_id · document_version · document_display_id · title · publication_number
effective_date · effective_end_date · implementation_date · qr_modifier_date
benefit_category · item_service_description · indications_limitations
cross_reference · transmittal_number · transmittal_url · revision_history
other_text · ama_statement · reasons_for_denial
```

**None of them is a procedure code.** Applicability comes from curated linkage in
`data/linkage/`, never from the document, and must never be presented as
CMS-supplied.

## Four source properties that shape the model

| observed | consequence |
|---|---|
| `effective_date` is prose in 14 of 24 sampled — *"This is a longstanding national coverage determination. The effective date of this version has not been posted."* | `TemporalStatus.UNDATED`; stored, indexed, **unreachable by date of service** |
| `effective_end_date` is identical across all versions of NCD 30.4 and *precedes* their effective dates | it is document-level retirement, **not** a version window |
| a non-existent version returns **200 with empty `data`**, not 404 | `VersionDataStatus.NO_VERSION_DATA`, never read as `END_OF_HISTORY` |
| content fields are **double-escaped** HTML (`&lt;p&gt;`) | unescaped and stripped at acquisition, never at retrieval |

## Stored representation

### `NcdVersion` (`app/coverage/ncd.py`)

Field names mirror the source. Nothing is invented: every value is copied, parsed
strictly, or derived with `window_derivation` recording that it was.

| field | note |
|---|---|
| `ncdid`, `version`, `display_id`, `title` | identity; `policy_id` is `"NCD 220.6.5"` |
| `effective_date` | `None` unless `temporal_status` is `DATED` |
| `effective_date_source` | **the raw published string, verbatim** |
| `temporal_status` | `DATED` · `UNDATED` · `AMBIGUOUS` |
| `end_date`, `window_derivation` | `POSTED` · `DERIVED_FROM_SEQUENCE` · `POSTED_RETIREMENT` |
| `benefit_category`, `item_service_description`, `indications_limitations`, `reasons_for_denial`, `cross_reference`, `revision_history`, `other_text` | text, HTML stripped |
| `ama_statement` | empty in all 24 sampled; a populated one **refuses the document** |
| `source_url`, `retrieved_at`, `content_sha256` | provenance |

### Schema (migration `0003_coverage_determinations`)

```sql
policy_versions.effective_date        -> NULLABLE
policy_versions.temporal_status       VARCHAR(16) NOT NULL DEFAULT 'DATED'
policy_versions.window_derivation     VARCHAR(24) NOT NULL DEFAULT 'POSTED'
policy_versions.effective_date_source TEXT        NOT NULL DEFAULT ''

CHECK ( (temporal_status = 'DATED'  AND effective_date IS NOT NULL)
     OR (temporal_status <> 'DATED' AND effective_date IS NULL AND end_date IS NULL) )

policy_documents.retirement_date_raw  TEXT NOT NULL DEFAULT ''
policy_documents CHECK document_type IN ('REGULATION','NCD','LCD','ARTICLE')
policy_code_links.link_provenance     VARCHAR(24) NOT NULL DEFAULT 'HUMAN_CURATED'
```

**Nullable but not weaker.** The CHECK ties nullability to the status, so a `DATED`
row still cannot have a NULL date and an undated row cannot carry an end date.
Existing regulation rows backfill as `DATED` through the default — no data
migration.

## What is deliberately not invented

**No sentinel date.** `date.min` would convert "we do not know when this took
effect" into "it has always been in effect" — the widest-applicability direction —
and would print `effective 0001-01-01` to a reviewer as though CMS had published
it. The dead `or date.min` fallback in `parse.py` was deleted in the same change; it
was unreachable, and it was one relaxed `required=` away from becoming live.

**No date scraped from prose.** `parse_cms_date` matches `^MM/DD/YYYY$` and nothing
else. A looser regex would eventually mine a date out of a sentence explaining that
no date exists.

**No coverage status inferred from the document.** `indications_limitations` is
prose. Classifying it `COVERED` or `NOT_COVERED` by keyword would be exactly the
unreviewed inference this project refuses everywhere else. A governing version with
no reviewer-recorded status resolves to `UNKNOWN`.

**No version history inferred from probing.** See
[ncd-temporal-resolution.md](ncd-temporal-resolution.md).

## Acquisition coverage — stated, not implied

This is **not** "the CMS NCD corpus". It is 11 determinations named in
`data/coverage/ncd_selection.yaml`, committed before any download:

| | |
|---|---|
| selected | 11 |
| acquired | **10** |
| refused | **1** (NCD 30.4 — retirement date precedes its own effective date) |
| unreachable | 0 |
| versions | 19 |
| temporally resolvable | **16 of 19** |

The refusal is evidence about the source, recorded in `registry.yaml` rather than
quietly filled. Documents are downloaded, never committed (ADR-003); the registry is
the committed record of their provenance.
