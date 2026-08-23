# RAG Architecture

**Status:** **Implemented in Phase 1.** No real CMS document has been acquired - CMS is
unreachable from the development network (a geographic edge block, not a crawl policy;
see [phase-1-implementation.md](phase-1-implementation.md) section 6). The pipeline runs
against CMS-*shaped* fixtures, and real documents drop into `data/cms/` with no code change.
**Authoritative for:** ingestion, policy resolution, retrieval, reranking, citation generation,
policy versioning.

---

## 1. Pipeline

```
  CMS Medicare Coverage Database document  (NCD / LCD / Billing & Coding Article)
        │
   [1]  ▼  acquisition + provenance record       data/cms/registry.yaml
        │  content hash, licence, retrieval date, source URL
   [2]  ▼  document validation                   reject: empty, truncated, wrong type
        │
   [3]  ▼  parsing                               text + page boundaries preserved
        │
   [4]  ▼  structure detection                   headings → section tree
        │
   [5]  ▼  section-aware chunking                never across a section boundary
        │
   [6]  ▼  metadata enrichment                   policy id/version/section/page/dates/URL
        │
   [7]  ├─▶ RESOLUTION INDEX                     codes × jurisdiction × date  (deterministic)
        │
   [8]  ├─▶ CRITERIA TREE                        one-off structured extraction, human-reviewed
        │
   [9]  └─▶ EMBEDDINGS                           pgvector, scoped by policy_version_id
                    │
        ─────────── request time ───────────
                    │
  [10]  policy resolution   (SQL: codes + jurisdiction + date of service)
                    │
  [11]  vector search       scoped to resolved policy versions ONLY
                    │
  [12]  metadata + temporal filter
                    │
  [13]  cross-encoder rerank
                    │
  [14]  evidence set per criterion
                    │
  [15]  citation generation  (chunk_id + exact quote + full metadata)
```

Steps 1–9 are offline and idempotent. Steps 10–15 are the request path. Nothing in the request
path modifies the corpus.

---

## 2. The corpus

Initial corpus: publicly available **CMS Medicare Coverage Database** material — National Coverage
Determinations (NCDs), Local Coverage Determinations (LCDs), and the Billing & Coding Articles
attached to LCDs, which is where much of the operative code-level criteria actually live.

This is **CMS Medicare coverage policy**. It is not, and must never be described as, any
commercial payer's medical policy.

**The policy layer is payer-agnostic by construction.** Nothing above the `policy_documents` and
`policy_versions` tables knows the corpus is CMS. Swapping in another payer's corpus requires a
new loader that populates the same schema — the resolution index, criteria trees, retrieval,
adjudication, guardrail and decision engine are unchanged. This is the point of separating
resolution from retrieval: the applicability rules are data, not code.

### Licensing

CMS documents are US Government works. However, **CPT® codes and their descriptors, embedded in
these documents, are copyrighted by the American Medical Association.** Consequences, enforced by
`.gitignore` and by test:

- No CMS document is committed to this repository. The corpus is downloaded at ingest time.
- `data/cms/registry.yaml` **is** committed and records, per document: source URL, document type,
  policy id, retrieval date, content hash, licence note, and contamination risk relative to the
  evaluation corpus.
- Code *values* (e.g. `27447`) are stored and may appear in fixtures. CPT descriptor *text* is not
  redistributed in the repository.

See [ADR-003](../adr/ADR-003-policy-corpus.md).

---

## 3. Policy resolution — deterministic

This step decides **which policies apply**. It uses no embeddings and no model.

```sql
-- conceptual
SELECT pv.*
FROM policy_versions pv
JOIN policy_code_links pcl ON pcl.policy_version_id = pv.id
WHERE pcl.code = :procedure_code
  AND pcl.code_system = :code_system
  AND (pv.jurisdiction = :jurisdiction OR pv.scope = 'NATIONAL')
  AND pv.effective_date <= :date_of_service
  AND (pv.end_date IS NULL OR pv.end_date >= :date_of_service)
```

Outcomes:

| Result | Meaning | Routing |
|---|---|---|
| Exactly one version, or several that agree | Resolved | continue |
| Zero versions | No applicable policy | `NEEDS_INFO` — **never a denial** (see §3.2) |
| An NCD and an LCD both apply | NCD governs; LCD may add detail | continue, both recorded |
| Two LCDs with incompatible criteria | Genuine conflict | `HUMAN_REVIEW` |

### 3.1 Temporal correctness

Policy version selection is by **date of service**, never "latest". Retrieving a version that was
retired before the service occurred, or that took effect after it, is a silent correctness failure
of exactly the kind a fluent, well-cited answer will hide.

Every `policy_version` row carries `effective_date`, `end_date`, `revision_id` and
`superseded_by`. Retrieval filters on the same predicate as resolution, so a chunk from a
non-applicable version cannot enter an evidence set even if it is semantically the best match.

Dedicated tests, planned for Phase 1:

- a case whose date of service precedes the version's `effective_date` must not resolve to it;
- a case after `end_date` must resolve to the superseded version in force at that time, not the
  current one;
- a corpus refresh that introduces a new revision must not change the resolution of a case whose
  date of service is before the new `effective_date`;
- retrieval must never return a chunk whose `policy_version_id` is outside the resolved set.

### 3.2 Absence is not denial

Zero applicable NCD/LCD generally means contractor discretion or case-by-case adjudication, not
non-coverage. Row 1 of the decision table makes `NEEDS_INFO` unreachable-past, and the ordering is
asserted by test. See [system-architecture.md](system-architecture.md) §5.

---

## 4. Chunking, embedding, reranking

### 4.1 Chunking

Section-aware, never crossing a section boundary. Coverage policy is written so that the section
*is* the unit of meaning — "Indications", "Limitations", "Coverage Criteria", "Documentation
Requirements" — and a chunk spanning the boundary between Indications and Limitations can produce
a citation that is textually exact and semantically inverted. That is the worst available failure
mode: a verifiable citation supporting the opposite of what the policy says.

Each chunk stores: `policy_version_id`, `section_path`, `page_from`, `page_to`, `ordinal`,
`text`, `text_sha256`, `token_count`.

Oversized sections are split with overlap **within** the section, and every part inherits the same
`section_path` so the citation still names the correct section.

### 4.2 Embedding

Candidate default: `BAAI/bge-base-en-v1.5`. Runs locally in-process via `sentence-transformers`,
CPU by default. It does **not** traverse the firewall — the firewall exposes no `/v1/embeddings`,
and there is no security purpose served by inspecting a corpus embedding request.

The model is a **candidate, not a decision**. Phase 1 builds a retrieval evaluation set and
compares candidates on it. No claim about embedding quality is permitted before that artefact
exists. See [ADR-006](../adr/ADR-006-chunking-embedding-reranking.md) and
[evidence-and-claims.md](../evidence-and-claims.md).

The 4 GB GPU on the reference machine is adequate for a base-size encoder but is shared with
nothing else — no generative model runs locally, so there is no contention.

### 4.3 Reranking

Cross-encoder rerank over the ANN candidates, scoped to the resolved policy versions. Candidate
default `BAAI/bge-reranker-base`; again a candidate, evaluated in Phase 1.

Rerank matters more here than in general RAG because the candidate pool is small and homogeneous —
within one LCD, many sections are lexically similar and a bi-encoder separates them poorly. The
rerank score margin is also one of the deterministic features feeding the abstention gate.

---

## 5. The criteria tree (ingest-time)

Turning policy prose into a structured criteria tree is done **once per policy version**, offline,
persisted, versioned, and human-reviewable — not re-derived on every request.

```
CriteriaTree(policy_version_id)
  criteria: [
    Criterion {
      id, parent_id, kind: REQUIRED | EXCLUSION | INFORMATIONAL,
      logic: ALL_OF | ANY_OF | N_OF(n) | LEAF,
      text,                      # the criterion as stated
      source_chunk_ids: [...],   # provenance back into the policy
      section_path, page,
      mutually_exclusive_with: [criterion_id],
      review_status: DRAFT | HUMAN_REVIEWED,
      extracted_by: { model, prompt_version, extracted_at }
    }
  ]
```

Why ingest time rather than request time:

| | Request-time extraction | Ingest-time extraction |
|---|---|---|
| Consistency | Criteria differ between two runs of the same case | One canonical tree per version |
| Latency / cost | Paid per case | Paid once per policy version |
| Auditability | Criteria are a transient model output | Criteria are an inspectable, diffable artefact |
| Human oversight | Impossible in the loop | A reviewer can correct the tree once, for every future case |
| Evaluation | Ground truth cannot be pinned to criteria | Cases can be constructed *from* the tree (see below) |

The last row is load-bearing for evaluation: because the criteria tree exists as data before any
case is written, synthetic cases can be constructed to satisfy or violate specific criteria, which
gives ground-truth labels **by construction** rather than by a model's opinion. See
[ADR-007](../adr/ADR-007-ingest-time-criteria-extraction.md) and
[ADR-015](../adr/ADR-015-synthetic-case-construction.md).

Extraction is model-assisted, so the tree is `DRAFT` until a human marks it `HUMAN_REVIEWED`.
Whether `DRAFT` trees may be used to produce recommendations outside evaluation is an open
decision (OD-4).

---

## 6. The citation contract

A citation is only meaningful if it can be checked. Every citation must carry:

| Field | Source | Checked how |
|---|---|---|
| `chunk_id` | model | exists, and was in this criterion's evidence set |
| `quote` | model | exact normalized substring of `chunk.text` |
| `policy_id` | model | matches the chunk's stored value |
| `policy_version` | model | matches the chunk's stored value |
| `document_title` | derived | joined from `policy_versions` |
| `section_path` | model | matches the chunk's stored value |
| `page` | model | within `[chunk.page_from, chunk.page_to]` |
| `effective_date` | derived | joined from `policy_versions` |
| `source_url` | derived | joined from `policy_documents` |

Fields marked *derived* are never accepted from the model — they are joined from the database at
validation time. A model cannot fabricate a source URL because it is never asked for one.

**Any citation that fails any check ⇒ `NO_DECISION` for the case.** Not a warning, not a lowered
confidence. See [ADR-009](../adr/ADR-009-evidence-and-citation-contract.md).

Normalization for span matching folds whitespace runs and Unicode confusables, using the same
approach as the firewall's `core/normalize.py` (its ADR-010). This matters in both directions: a
quote cosmetically altered to smuggle in different meaning must fail, while a quote that differs
only in whitespace from a PDF extraction must pass.

---

## 7. Corpus versioning and refresh

Ingesting a revised policy **adds a version**; it never edits one. A case adjudicated last month
remains reproducible because its `policy_version_id` still resolves to the text that was used.

`data/cms/registry.yaml` records the content hash of every acquired document. A refresh that
changes a hash creates a new `policy_version`; a refresh that does not change any hash is a no-op.
Chunk `text_sha256` values make corpus tampering detectable after the fact — an audit row's
citation can be re-validated against the chunk it named, and a hash mismatch is a poisoning signal
rather than a silent behaviour change (threat T-06 in the
[threat model](../security/threat-model.md)).

---

## 8. Retrieval evaluation

Retrieval is evaluated independently of decision quality, and at a much larger denominator —
per-criterion retrieval judgements rather than per-case labels. Planned metrics: recall@k,
nDCG@k, and *policy-resolution accuracy* (did the deterministic step select the version a human
says applies).

Policy-resolution accuracy is reported separately from semantic retrieval quality because they
fail differently and are fixed differently: resolution errors are rule or data defects, retrieval
errors are ranking defects. Details in
[evaluation-strategy.md](../evaluation/evaluation-strategy.md).

No retrieval metric may be stated until its report artefact exists.

---

## 9. Implementation notes (Phase 1)

Where the built pipeline goes beyond what this document specified, and why.

### Acquisition is an adapter, not a fetcher

`app/policy/acquire.py` exposes `LocalDirectorySource` (the default) and `HttpSource`
(present, opt-in). Provenance is recorded identically either way, including a
`synthetic` flag that travels into every report derived from the corpus. CI has no CMS
access and never will, so network-free ingestion is a permanent requirement rather than
a temporary accommodation.

### Structure detection needs structural evidence, not lexical

The first implementation matched headings lexically - short, title-cased, unpunctuated -
and filled the section tree with body text, because **a wrapped prose line satisfies
every one of those tests**. "Total knee arthroplasty is considered reasonable and
necessary when" is thirteen words, capitalised, and unpunctuated only because the line
wrapped.

Canonical CMS headings are now matched exactly and need no further evidence. A
document-local heading additionally requires a preceding blank line and following
content. Recorded as R-34.

### Chunking has a last-resort word split

ADR-006 specified splitting oversized sections at sentence boundaries. Policy documents
contain enumerations and code tables with no terminal punctuation at all, and such a
section produced a single chunk wider than the encoder's context - silently truncated at
embedding time, where the loss reads as a retrieval-quality problem. `chunk.py` now falls
back to word boundaries, never mid-word, only when no sentence boundary exists. Recorded
as R-35.

### Retrieval re-applies the temporal predicate

`search_chunks` filters on `in_force_on(as_of)` even though resolution has already
applied it. That is deliberate defence in depth against a caller supplying a scope from
somewhere other than `resolve()` - a cache, or a hand-built list. The two call **one
shared function**, never two copies, and a test asserts the identity.

The redundancy has a testing consequence worth stating: a test that exercises only the
happy path passes with *either* filter deleted, and the first version of the scoping
suite did exactly that. Each filter is now tested on the path where it alone is
load-bearing (R-36).

### Known gap: Billing & Coding Articles are unreachable by resolution

An Article declares no covered procedure of its own, so no request resolves to it from a
procedure code, and its content - notably the diagnosis codes that support medical
necessity - cannot be retrieved. Recorded as **OD-15** and excluded from the retrieval
denominator with the reason stated, rather than dropped.
