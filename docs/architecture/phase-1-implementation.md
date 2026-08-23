# Phase 1 — Implementation Assessment

**Written before any Phase 1 code**, as the phase requires. Records what the verified
Phase 0 foundation already provides, what must be extended, what is genuinely new, and
what Phase 1 depends on being true.

**Baseline:** commit `038d1b2`, working tree clean, 87 tests passing, ruff + mypy strict
clean, stack healthy on `:8010` with all four readiness checks green.

---

## 1. What Phase 0 already provides — reuse, do not rebuild

More of Phase 1 is already scaffolded than is obvious, because several Phase 0 types were
written with this phase in mind.

| Asset | Phase 1 use | Action |
|---|---|---|
| `app/core/normalize.py` | Chunk text hashing, and the span verification that turns a quote into a citation | **Reuse unchanged.** Already offset-preserving and confusable-folding |
| `app/core/ids.py` | `PolicyVersionId`, `ChunkId` are already defined `NewType`s | **Reuse unchanged** |
| `app/core/types.py` | `CodeSystem` (HCPCS/CPT/ICD10CM/ICD10PCS) and `ResolutionStatus` (RESOLVED / NONE_APPLICABLE / CONFLICTING) already exist | **Reuse unchanged** |
| `app/config/settings.py` | `embedding_model`, `reranker_model`, `embedding_device`, `retrieval_top_k`, `rerank_top_n` already present and validated | **Extend** (§2) |
| `config/decision-policy.yaml` | `retrieval.top_k`, `retrieval.rerank_top_n` already schema-validated | **Extend** (§2) |
| `app/database/engine.py` | `build_engine`, `session_scope` with commit/rollback | **Reuse unchanged** |
| `migrations/versions/0001` | pgvector **0.8.6** enabled and verified; `vector` type usable | **Reuse.** Phase 1 adds `0002` |
| `tests/unit/test_layer_boundaries.py` | `policy` and `retrieval` are already in `DOMAIN_PACKAGES` | **Reuse.** New code is governed automatically, with no test change |
| `app/observability/logging.py` | Sink-level redaction; `policy_text` and `text` are already in `CLINICAL_KEYS` | **Reuse unchanged** |
| `app/api/readiness.py` | Classified check pattern | **Extend** with a corpus check |
| `tests/conftest.py` | `repo_root`, `shipped_policy`, `dev_settings` | **Reuse** |

**Explicitly not used by Phase 1:** `app/llm/client.py` and `app/llm/schema_call.py`.
Retrieval runs on local encoders and makes no generative model call. The firewall exposes
no `/v1/embeddings`, and inspecting a corpus embedding request would serve no security
purpose (ADR-006, ADR-016). Phase 1 must not introduce a model call on the retrieval path.

---

## 2. What needs extension

| File | Extension | Why |
|---|---|---|
| `app/config/settings.py` | `embedding_dimension` (default 768), `embedding_batch_size`, `corpus_dir` | The vector column type is fixed at migration time; the dimension must be configuration the schema and the encoder agree on |
| `config/decision-policy.yaml` | `resolution:` block — whether an NCD outranks an LCD, and how a conflict is declared | Applicability rules are behaviour, so they belong in versioned policy, not in code constants |
| `app/api/readiness.py` | A `policy_corpus` check — advisory | An empty corpus means no case can resolve, which an operator should see before a case fails |
| `pyproject.toml` | Install the existing `retrieval` extra; add the CPU-only torch index | ~2.4 GB otherwise, for GPU wheels this project does not use |

No Phase 0 file is rewritten. No ADR is re-opened.

---

## 3. What is new

```
app/policy/
  models.py        SQLAlchemy ORM for the four corpus tables
  acquire.py       source adapters + registry provenance
  validate.py      reject empty / truncated / wrong-type loudly
  parse.py         text with page boundaries preserved
  structure.py     heading detection -> section tree
  chunk.py         section-aware; never crosses a boundary
  metadata.py      enrichment + content hashing
  resolve.py       THE DETERMINISTIC RESOLVER
app/retrieval/
  embed.py         local sentence-transformers, CPU default
  search.py        pgvector HNSW, scoped by policy_version_id
  rerank.py        cross-encoder over ANN candidates
  evidence.py      EvidenceChunk + citation objects
migrations/versions/0002_policy_corpus.py
scripts/ingest_cms.py, scripts/build_retrieval_evalset.py
data/cms/registry.yaml            (committed; the documents are not)
eval/datasets/retrieval/          (frozen, hashed, committed)
```

The schema is already specified in
[data-architecture.md](data-architecture.md) §3.1 and is implemented verbatim:
`policy_documents`, `policy_versions`, `policy_code_links`, `policy_chunks`. Phase 1 does
not redesign it.

---

## 4. The architectural line Phase 1 must hold

> **Resolution decides *which policy applies*. Retrieval decides *which passage is
> relevant*. They are different mechanisms and must not merge.**

```
(procedure code, diagnosis codes, jurisdiction, as-of date)
        │   SQL over policy_code_links - no embeddings, no model, reproducible
        ▼
   applicable policy VERSIONS      0 -> NONE_APPLICABLE     conflicting -> CONFLICTING
        │
        ▼   semantic retrieval scoped INSIDE the resolved set only
   evidence chunks -> citations
```

Enforcement, so this cannot decay:

1. `resolve()` takes no embedding argument and imports no encoder. A unit test asserts
   `app/policy/resolve.py` imports neither `sentence_transformers` nor `app.retrieval`.
2. `search()` **requires** a non-empty `policy_version_ids` argument. There is no code path
   that searches the whole corpus — an empty resolved set raises rather than widening.
3. The temporal predicate used by retrieval is the *same function* used by resolution, not
   a re-implementation, so the two cannot drift.

That third point is the one most likely to be got wrong. A copy of the date filter in the
retrieval query is a defect waiting for a corpus refresh.

---

## 5. Assumptions Phase 1 depends on

| # | Assumption | Status | If false |
|---|---|---|---|
| A1 | pgvector supports the chosen dimension and cosine ops | **Verified** — 0.8.6, cosine distance exercised in Phase 0 | — |
| A2 | `bge-base-en-v1.5` emits 768 dimensions, matching the schema | Unverified until the encoder loads | Migration `0002` must use the measured dimension; a mismatch is a hard failure, never a silent truncation |
| A3 | CMS documents are obtainable in this environment | **FALSE — see §6** | Acquisition becomes a pluggable adapter; ingestion is validated on fixtures |
| A4 | CMS documents are templated enough for heading detection | Unverified | `structure.py` fails loudly on an unrecognised layout rather than flattening it |
| A5 | A superseded/current version pair is obtainable | Unverified | Construct a synthetic version pair, **labelled as synthetic**. The temporal logic must still be tested |
| A6 | CPU embedding is fast enough for a bounded corpus | Unverified | Measured, reported, not assumed |

---

## 6. Blocking finding: CMS is unreachable from this network

Measured, not assumed:

| Host | Result |
|---|---|
| `www.cms.gov` (incl. `/robots.txt`) | **403** |
| `data.cms.gov`, `pfs.data.cms.gov` | **403** |
| `www.medicare.gov` | **403** |
| `data.medicaid.gov`, `download.medicaid.gov` | **403** |
| `healthdata.gov` | 200 |
| `api.fda.gov` | 200 |

Two conclusions follow, and the first corrects an earlier reading of this as bot
mitigation.

**It is a geographic edge block, not a crawler policy.** `robots.txt` itself returns 403
from an Akamai edge (`errors.edgesuite.net`), while other US government properties answer
normally from the same host. There is no stated crawl restriction to respect or violate;
there is simply no route. A different user-agent, a retry policy or a headless browser
would all meet the same edge.

**The Medicare Coverage Database is not open data.** A search of all 20,470 datasets in
the HHS `healthdata.gov` catalog returns no NCD or LCD documents; the MCD is a separate
web application. All 778 CMS-published datasets in that catalog point back at the blocked
hosts. So there is no sanctioned programmatic route to the corpus from here either.

### Consequence for the design - an improvement, not a workaround

`acquire.py` is a **source adapter interface**:

| Adapter | Behaviour |
|---|---|
| `LocalDirectorySource` | Reads documents an operator placed in `data/cms/`. The default, and the only one exercised in tests |
| `HttpSource` | Fetches from a registered URL. Present, disabled by default, for environments where the source is reachable |

Provenance is recorded identically either way - source, retrieval date, content hash,
licence note, contamination risk, and a `synthetic` flag - so `registry.yaml` is the record
of what was ingested regardless of what fetched it.

Phase 1 therefore proceeds on **CMS-shaped fixtures**, faithful to real NCD, LCD and
Billing & Coding Article structure. This is not a stand-in awaiting the real thing: CI has
no CMS access and never will, so network-free fixtures are a permanent requirement that
the real corpus sits alongside. Real documents dropped into `data/cms/` later need **zero
code change**.

Fixtures carry code *values* only. No AMA CPT descriptor text is reproduced (ADR-003), and
`registry.yaml` marks them `synthetic: true` so every report derived from them states that
limitation rather than implying real-corpus results.

## 7. Risks specific to this phase

| ID | Risk | Handling |
|---|---|---|
| P1-a | Embedding dimension mismatch between encoder and column | Ingest asserts the measured dimension against the schema and refuses to write on mismatch |
| P1-b | Chunk crosses a section boundary, producing a citation that verifies while inverting the policy's meaning | The boundary rule is a unit test over generated section trees, not a code comment (ADR-006) |
| P1-c | Retrieval date filter drifts from resolution's | Both call one shared predicate builder; a test asserts they produce identical SQL for the same inputs |
| P1-d | Retrieval eval set authored from the same chunking that produced the chunks (circular) | Questions authored from the **policy text before chunking**; answer chunks human-selected |
| P1-e | Corpus too small for meaningful retrieval metrics | Denominator stated in the report; no extrapolation |
| P1-f | `torch` pulls GPU wheels (~2.4 GB) that this project does not use | Pin the CPU-only index |

---

## 8. Definition of done

- [x] Migration `0002` creates the four tables verbatim from data-architecture section 3.1
- [x] `resolve()` is deterministic, embedding-free, and explains *why* a version applied
- [x] **Four mandatory temporal tests pass** (ADR-004), each shown to fail on an injected bug
- [x] `search()` cannot be called without a resolved version set (`EmptyScopeError`)
- [x] Chunker never crosses a section boundary, asserted at every chunk size
- [x] Citations carry every ADR-009 field, with derived fields joined and never accepted
- [x] Retrieval eval set frozen and hashed; 2 encoders x 3 rerank options compared
- [x] A committed report under `eval/reports/` - resolution accuracy reported **separately**
- [x] `docs/` updated in the same change; ADR-003 and ADR-006 amended
- [x] ruff, mypy strict, and the full suite clean

## 9. What Phase 1 found

Four defects were found by building, three of them in work this phase produced. They are
listed because the finding is the useful part, not the fix.

| Finding | Why it mattered |
|---|---|
| **The scoping tests were vacuous** (R-36) | Version scoping and the temporal predicate are redundant on the happy path, so the first suite passed with *either* filter deleted. Both are now tested where each alone is load-bearing, and both injections fail. |
| **Wrapped prose reads as a heading** (R-34) | A thirteen-word wrapped sentence satisfies every lexical heading test. The section tree filled with body text. Local headings now require structural evidence. |
| **Unpunctuated sections could not be split** (R-35) | Enumerations and code tables have no sentence boundary, so they produced a chunk wider than the encoder context - silently truncated at embedding time. |
| **Boundary rule 1 was too strict** (Phase 0 defect) | `app.core` was forbidden from importing *anything* under `app/`, including its own modules. Phase 0 never noticed because core had no internal imports. |

And one gap that is recorded rather than closed:

**Billing & Coding Articles are unreachable by resolution** (OD-15, R-37). An Article
declares no covered procedure, so no request resolves to it, and the diagnosis codes it
carries cannot be retrieved. Found while authoring the retrieval set - question q012 asks
exactly that. It is excluded from the denominator with its reason stated, not dropped.
