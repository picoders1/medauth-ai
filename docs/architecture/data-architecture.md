# Data Architecture

**Status:** Implemented. Six migrations, head `0006_reviewer_identity`; the append-only audit is
enforced by trigger rather than by grant.
**Authoritative for:** the PostgreSQL schema, data classification, retention, and what is
deliberately not stored.

---

## 1. Storage decision

**PostgreSQL 16 + pgvector is the only datastore.** Relational data, vectors and the audit trail
live in one database. No separate vector database, no separate document store, no cache tier.

The corpus is small: CMS NCDs, LCDs and attached Billing & Coding Articles for a bounded set of
procedures produce chunks in the thousands to low tens of thousands. At that scale an HNSW index
in pgvector is comfortably adequate, and a dedicated vector database would add an operational
component, a second consistency domain, and a synchronisation problem — while solving nothing.

Decisive for this system specifically: **retrieval is scoped by a relational predicate.** Every
search is filtered to the policy versions that resolution selected, and to a date range. That is a
join, and it belongs where the joined data lives. Doing it in an external vector store means
either over-fetching and post-filtering, or duplicating policy metadata into the index and keeping
it in sync. Both are worse.

Full analysis, including the conditions that would justify revisiting:
[ADR-005](../adr/ADR-005-postgres-pgvector.md).

Host port **5435** (5432, 5433 and 5434 are occupied on the reference machine).

---

## 2. Data classification

| Class | Examples | Handling |
|---|---|---|
| **Public policy** | CMS document text, chunks, criteria trees | Freely stored and logged. Not committed to git (licensing, §1 of the RAG doc). |
| **Synthetic clinical** | Note text, extracted facts | Stored. **Never logged.** Never sent to third-party telemetry. |
| **Derived reasoning** | Verdicts, citations, guardrail results | Stored, audited, safe to log. |
| **Operational** | Latency, token counts, model ids, prompt versions | Stored, audited, logged, exported as metrics. |
| **Reviewer identity** | Subject id from the trusted proxy | Stored on audit rows. Never a free-text principal from a client header. |
| **Credentials** | Firewall caller key | Environment only, `SecretStr`. Never in the database, never in policy YAML, never logged. |

All patient data in this project is **synthetic**. The controls above exist because the
architecture must be correct for real deployment, not because the test data is sensitive.

---

## 3. Schema

### 3.1 Policy corpus

```
policy_documents
  id                  uuid pk
  policy_id           text          -- e.g. NCD 220.1, L34567, A56789
  document_type       text          -- NCD | LCD | ARTICLE
  title               text
  source_url          text
  contractor          text null     -- MAC, for LCDs
  first_seen_at       timestamptz
  UNIQUE (policy_id, document_type)

policy_versions
  id                  uuid pk
  document_id         uuid fk -> policy_documents
  revision_id         text
  scope               text          -- NATIONAL | JURISDICTIONAL
  jurisdiction        text null
  effective_date      date          NOT NULL
  end_date            date null                     -- null = currently in force
  superseded_by       uuid null fk -> policy_versions
  content_sha256      text          NOT NULL
  ingested_at         timestamptz
  UNIQUE (document_id, revision_id)
  CHECK (end_date IS NULL OR end_date >= effective_date)

policy_code_links                   -- THE RESOLUTION INDEX
  policy_version_id   uuid fk
  code                text          -- HCPCS/CPT or ICD-10
  code_system         text          -- HCPCS | CPT | ICD10CM | ICD10PCS
  link_type           text          -- COVERED_PROCEDURE | SUPPORTING_DIAGNOSIS | EXCLUDED
  PRIMARY KEY (policy_version_id, code, code_system, link_type)
  INDEX (code, code_system)         -- resolution reads this first

policy_chunks
  id                  uuid pk
  policy_version_id   uuid fk
  section_path        text          -- 'Indications and Limitations > Coverage Criteria'
  ordinal             int
  page_from           int
  page_to             int
  text                text
  text_sha256         text          -- tamper / drift detection
  token_count         int
  embedding           vector(768)
  INDEX hnsw (embedding vector_cosine_ops)
  INDEX (policy_version_id)         -- the scoping filter
```

`policy_code_links` is the whole of policy resolution. It is deliberately a plain table with a
plain index: applicability must be reproducible, explainable to a reviewer, and diffable when the
corpus is refreshed.

### 3.2 Criteria

```
criteria
  id                     uuid pk
  policy_version_id      uuid fk
  parent_id              uuid null fk -> criteria
  kind                   text     -- REQUIRED | EXCLUSION | INFORMATIONAL
  logic                  text     -- ALL_OF | ANY_OF | N_OF | LEAF
  n_required             int null -- for N_OF
  text                   text
  section_path           text
  page                   int null
  review_status          text     -- DRAFT | HUMAN_REVIEWED
  extracted_by_model     text
  extracted_by_prompt    text     -- prompt version id
  extracted_at           timestamptz
  reviewed_by            text null
  reviewed_at            timestamptz null

criteria_source_chunks   (criterion_id, chunk_id)      -- provenance
criteria_exclusivity     (criterion_id, excludes_criterion_id)
```

The criteria tree is versioned with the policy version, never edited in place. A corrected
criterion produces a new tree revision, so a case adjudicated against the old tree stays
reproducible.

### 3.3 Cases and outputs

```
cases
  id                  uuid pk
  request_id          text unique
  case_ref            text          -- synthetic case identifier
  note_text           text          -- synthetic clinical note
  note_sha256         text
  requested_code      text
  requested_code_system text
  jurisdiction        text
  date_of_service     date
  submitted_at        timestamptz
  corpus_snapshot_id  uuid          -- which corpus state adjudicated this

intake_facts
  id                  uuid pk
  case_id             uuid fk
  kind                text          -- DIAGNOSIS | PROCEDURE | FINDING | MEDICATION | HISTORY
  text                text
  span_start          int
  span_end            int
  code                text null
  code_system         text null

case_policy_resolution
  case_id             uuid fk
  policy_version_id   uuid fk
  resolution_status   text          -- RESOLVED | CONFLICTING
  matched_code        text
  matched_link_type   text

criterion_verdicts
  id                  uuid pk
  case_id             uuid fk
  criterion_id        uuid fk
  verdict             text          -- SATISFIED | NOT_SATISFIED
                                    -- | INSUFFICIENT_EVIDENCE | NOT_APPLICABLE
  reasoning           text
  missing_evidence    jsonb
  model               text
  prompt_version      text
  attempt_count       int
  latency_ms          int
  prompt_tokens       int
  completion_tokens   int

verdict_citations
  id                  uuid pk
  verdict_id          uuid fk
  chunk_id            uuid fk
  quote               text
  claimed_section     text
  claimed_page        int
  validation_status   text          -- VALID | SPAN_MISMATCH | UNKNOWN_CHUNK
                                    -- | METADATA_MISMATCH | OUT_OF_EVIDENCE_SET

verdict_fact_links   (verdict_id, fact_id)

recommendations
  id                     uuid pk
  case_id                uuid fk unique
  outcome                text   -- APPROVE_RECOMMENDED | DENY_RECOMMENDED
                                -- | NEEDS_INFO | HUMAN_REVIEW | NO_DECISION
  decision_rule_matched  int    -- which row of the decision table fired
  abstained              bool
  abstention_reason      text null
  gate_features          jsonb  -- the deterministic features, for calibration analysis
  decision_config_version text  -- which config/decision-policy.yaml produced this
  created_at             timestamptz
```

`decision_rule_matched` and `gate_features` exist so that a recommendation can be *explained*
rather than merely reported, and so that threshold recalibration can be run over historical cases
without re-running any model.

### 3.4 Human review and audit

```
human_reviews
  id                  uuid pk
  case_id             uuid fk
  reviewer_subject    text          -- derived from trusted proxy, never client-supplied
  decision            text          -- APPROVED | DENIED | INFO_REQUESTED
  agreed_with_system  bool
  override_reason     text null     -- REQUIRED when agreed_with_system = false
  reviewed_at         timestamptz
  review_duration_ms  int
  CHECK (agreed_with_system OR override_reason IS NOT NULL)

audit_events                        -- APPEND ONLY
  id                  bigserial pk
  case_id             uuid
  request_id          text
  event_type          text
  step                text          -- intake | resolve | retrieve | adjudicate
                                    -- | guardrail | finalize | human_review
  payload             jsonb         -- structured; no clinical free text (§4)
  model               text null
  model_version       text null
  prompt_version      text null
  agent_version       text null
  corpus_snapshot_id  uuid null
  decision_config_version text null
  actor               text null
  created_at          timestamptz default now()
  INDEX (case_id, created_at)
```

The database role used by the application is granted `INSERT` and `SELECT` on `audit_events` and
**not** `UPDATE` or `DELETE`. Retention runs under a separate role. There is no code path in
`app/` that updates or deletes an audit row, and a test asserts the grant.

---

## 4. What is deliberately not stored, and where

| Not stored | Where instead / why |
|---|---|
| Clinical free text in `audit_events.payload` | Payloads carry fact **ids**, chunk **ids** and spans. The text is joined from `cases`/`policy_chunks` when a reviewer opens the case. An audit trail that duplicates the note multiplies the exposure surface for no gain. |
| Prompts and completions | Never persisted. Prompt *version ids* and token *counts* are. Matches the firewall's posture, where no audit column can hold a prompt. |
| Model-provider credentials | MEDAUTH holds none — the firewall holds the upstream key. |
| Raw reviewer identity headers | Only the derived subject. |
| Clinical text in logs or OTel spans | `MEDAUTH_CLINICAL_TEXT_LOGGING=off`, enforced at the structlog sink rather than per call site. Span attributes carry ids and counts. |

Presidio was considered for de-identification and is **not** adopted in the initial system. All
data here is synthetic, so Presidio would detect nothing real while adding spaCy, a model download
and a startup cost; the firewall already applies regex PII redaction on the model path. It is
recorded as an open decision for a real-data deployment (OD-6), not shipped as a compliance
gesture.

---

## 5. Retention

Retention deletes by **age and nothing else** — the only predicate is `created_at`. There is no
filter by outcome, reviewer, policy or case. A purge that can be aimed at particular rows is a
mechanism for erasing the record of a specific recommendation; this constraint is asserted against
the compiled SQL, following the firewall's ADR-030.

Off by default (`MEDAUTH_RETENTION_ENABLED=false`); deletion is irreversible and an upgrade must
not start removing an operator's trail. Deletion is batched, because the database command timeout
would otherwise cause one unbounded `DELETE` to time out, roll back, and delete nothing while
appearing enabled.

---

## 6. Corpus snapshots and reproducibility

`corpus_snapshot_id` on every case pins the corpus state that adjudicated it. Combined with
`policy_version_id`, chunk `text_sha256`, `prompt_version`, `model`, `agent_version` and
`decision_config_version`, a recommendation is reproducible: the deterministic half exactly, and
the model half to the extent the provider is deterministic.

This is what makes an audit trail defensible rather than decorative — the question a reviewer will
eventually face is not "what did the system say" but "why did it say that, against what text, under
which rules". Every element of that answer is a column.
