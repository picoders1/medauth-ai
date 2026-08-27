# MEDAUTH AI

**Agentic Prior-Authorization & Medical-Necessity Decision Support**

An evidence-grounded system that helps a **human reviewer** evaluate prior-authorization requests
against authoritative CMS coverage-policy criteria — and that is *structurally unable* to make the
decision itself.

A case arrives. Code resolves which policy version governs it **as of the date of service**. A model
reads the clinical note and, separately, judges each policy criterion one call at a time. Every quote
it returns is verified character-for-character against the stored policy text. Then **code** — a pure
function with no model, no clock and no network — computes the recommendation and hands it to a
person, with the whole path written to an append-only audit trail.

**Python 3.12+** · Apache-2.0 · Evaluated exclusively on **synthetic** patient data · No PHI

---

## Status

| | |
|---|---|
| **Engineering** | **ENGINEERING-COMPLETE** — runs end to end |
| **Remote CI** | **VERIFIED PASS** — run `33097477139` on commit `4870ae3` |
| **Production shape** | **VERIFIED** — HTTPS edge, persistent IdP, clean image |
| **Production deployment** | **NOT PERFORMED** |
| **Evaluation (R-86)** | **BLOCKED** — external provider limitation, see below |
| **Clinical validation** | **NOT CLAIMED**, and none exists |

| | |
|---|---|
| Application | **102 modules** · 6 migrations · **1369 tests** · **47/47** safety mutations caught |
| Decision records | **30 ADRs** — [docs/adr/](docs/adr/) |
| Threat model | **27 threats** — [docs/security/threat-model.md](docs/security/threat-model.md) |
| Identity | Real OIDC against **Keycloak 26** (non-production); `verify_idp.py` **12/12** |
| End-to-end | **45/45** through the published port, incl. 19 negative auth cases |

**[PROJECT-STATUS.md](PROJECT-STATUS.md) is the single authoritative status document.** Where any
other document disagrees with it, that one is current.

### The one thing that is blocked

`R-86`: on the registered reproducer the model provider emits ~190 characters of JSON, never closes
the document, and pads whitespace to the completion ceiling — **6 of 12 trials against a 10%
threshold**. Ruled out by measurement: the application, both directions of the gateway, the output
budget, context length, the schema alone and the content alone. A *longer* prompt with the same
schema terminates cleanly.

The decoder sits behind an external provider with no administrative surface, so MEDAUTH **cannot fix
it locally** — and the evaluation gate stays `BLOCKED` rather than being lowered to fit. The
`gold_v2` scoring budget remains **unspent**.
See [docs/evaluation/r86-status.md](docs/evaluation/r86-status.md).

> **Every accuracy, grounding and performance figure is *pending evidence*.** No number appears
> anywhere in this repository unless a committed report under `eval/reports/` produces it —
> [docs/evidence-and-claims.md](docs/evidence-and-claims.md).

---

## What it does, in one screen

```
case  →  applicability  →  intake  →  retrieval  →  adjudication  →
         [SQL, 6 states]  [model]   [encoders]    [model, 1 call
                │                                  per criterion]
                │                                        ↓
     ┌──────────┴────────────────┬─────────────────────┬──────────────────┐
     ▼                           ▼                     ▼                  ▼
 date-of-service            citation guard      contradiction       policy logic
 version pinning            (span-verified,     analysis            (3-valued;
 (never "latest")            fail ⇒ NO_DECISION)                     declared, not
                                                                     assumed)
                                                        ↓
     ┌──────────────────┬────────────────────┬─────────────────────┐
     ▼                  ▼                    ▼                     ▼
 abstention gate    decision table      human review          append-only
 (rules now;        (pure code,         accept · override ·   audit
  thresholds         5 outcomes)        request-info          (every model
  uncalibrated)                                                call, replayable)
```

Two steps call a model. Everything that determines the outcome is code.

---

## Highlights, module by module

`app/` is 102 modules across 19 top-level packages. Each package owns one concern, and the boundaries between them
are enforced by an **AST-parsing test** that reads source rather than importing it — so a violation
is caught even in a module nobody runs.

| Package | What it does | Why it is separate |
|---|---|---|
| **`core/`** | `CaseId`, `Verdict`, `Citation`, error types, `normalize()` (whitespace folding + Unicode confusables, offsets preserved), content hashing | Imports **nothing** from `app/`. The shared vocabulary every other layer speaks. |
| **`config/`** | `Settings` (env, `SecretStr`) and `policy.py` (`decision-policy.yaml` loader) | Two deliberately separate systems: secrets never appear in policy YAML — keys matching `*_key`/`*secret*`/`*token*`/`*password*` are **structurally rejected** at load. |
| **`contracts/`** | Closed, validated Pydantic shapes for every boundary in the execution path | Contract-only, no runtime. A contract found wrong after the fact is a rewrite; found early it is an edit. |
| **`policy/`** | Corpus acquisition, parsing, structure, chunking, **criteria extraction**, temporal versioning, applicability, provisions, transcription, validation | Criteria are built **at ingest, once per policy version, and human-reviewed** — never re-derived per request. That is what makes ground truth by construction possible. |
| **`coverage/`** | Which NCD version governs a date of service, and what it establishes | Produces **no recommendation**. Answers two narrow questions and stops. |
| **`retrieval/`** | Local bi-encoder embedding, pgvector ANN search, cross-encoder rerank, evidence assembly, scope enforcement | Runs **only inside** the already-resolved policy versions. Applies the same temporal predicate as resolution, so an out-of-scope chunk cannot enter an evidence set even when it is the best semantic match. |
| **`intake/`** | Model extraction of clinical facts with source spans | Emits facts, **no coverage vocabulary**. Cannot import `app/decision`; `Recommendation` is not importable here. |
| **`adjudication/`** | One model call per criterion; `evidence_block.py` is the *only* place retrieved policy text enters a prompt | Per-criterion isolation. Policy text is fenced and framed as **data**, never concatenated into a system prompt. |
| **`guardrail/`** | Span verification of every citation; contradiction analysis | `normalize(quote)` must be a substring of `normalize(chunk.text)`; claimed metadata must match the chunk's; the chunk must have been in that criterion's evidence set. Any failure ⇒ `NO_DECISION`. |
| **`decision/`** | The decision table, policy logic (3-valued), abstention, semantics | **Pure.** No I/O, no model, no database, no clock, no randomness. Exhaustively testable as a truth table with nothing loaded. |
| **`graph/`** | `SliceRunner` — the linear orchestrator, the only layer allowed to see every other one | Owns **all** routing. `intake` and `adjudication` cannot name a gateway outcome, so they let failures propagate and this classifies them. |
| **`case/`** | Case lifecycle: persistence, transitions, routing, review read model | **Not a second decision pipeline.** `SliceRunner` decides; this persists and routes around it. |
| **`review/`** | Criteria-tree review, versioning, migration, decision gate, impact analysis | A criteria tree that no human reviewed cannot reach production inference. |
| **`identity/`** | OIDC/JWT validation (RS256/ES256 via JWKS), dev adapter, API-key path, permissions | One protocol, three implementations. The principal is **type-checked before permissions** — a SERVICE principal holding every permission is still refused all three human actions. |
| **`audit/`** | The **single** writer to the append-only trail | Append-only is enforced by **trigger**, not by grant: PostgreSQL never restricts a table's owner, so grants alone were inert. |
| **`llm/`** | The one seam a model call crosses: gateway, firewall gateway, schema calls, failure taxonomy | MEDAUTH holds **no model-provider credential** — the firewall holds the upstream key, MEDAUTH holds a revocable caller key. |
| **`api/`** | FastAPI app, `/api/v1` routes, readiness, and a server-rendered reviewer view | The UI decides nothing: every action posts to the API, which re-authenticates, re-authorises in the **service layer** and writes the audit event. |
| **`observability/`** | structlog configuration with redaction **at the sink** | Redaction is not per call site — a new log line cannot forget it. |
| **`database/`** | Async engine and session factory | Schema is versioned by Alembic, never auto-created. |
| **`production_gate.py`** | The one gate: production inference is blocked unless every condition passes | No default mode. A default is a mode nobody chose, and it would have to be the one that skips the check. |

### Four design decisions that do most of the work

**Policy resolution is deterministic; retrieval is semantic.** Semantic search always returns
*something*. For a knee-MRI case it returns a plausible, well-written, confidently-citable imaging
policy — possibly from the wrong jurisdiction, or a version retired before the date of service. The
system then reasons impeccably over the wrong document. **Citations do not catch this**: they are
genuine, the quotes verify, the policy simply does not apply. So applicability is decided by rules —
procedure code, diagnosis codes, jurisdiction, date of service — and semantic search runs only
*inside* the resolved set. ([ADR-004](docs/adr/ADR-004-policy-resolution-and-temporal-versioning.md))

**No applicable policy is never a denial.** Absence of an NCD/LCD generally means contractor
discretion, not non-coverage. That row returns `NEEDS_INFO`, and a test asserts `DENY_RECOMMENDED`
is *unreachable* when resolution is empty.

**Missing evidence and evidenced failure are different rows**, and the missing-evidence row is
evaluated **first**. That ordering is what stops the system denying for missing paperwork — the most
common harm pattern in automated prior authorization. Reordering it is a clinical behaviour change
requiring an ADR amendment.

**Every citation is span-verified or the case stops.** `source_url`, `effective_date` and
`document_title` are joined from the database, **never accepted from the model** — a URL cannot be
fabricated because it is never requested. ([ADR-009](docs/adr/ADR-009-evidence-and-citation-contract.md))

---

## The governing invariant

> ### Models produce per-criterion verdicts. Code produces the decision.
>
> The tokens `APPROVE_RECOMMENDED` and `DENY_RECOMMENDED` exist in **no model output schema anywhere
> in this system**.

A prompt injection can flip a verdict. It **cannot** emit a decision, because there is no field to
write one into. Enforced by `tests/unit/test_layer_boundaries.py`:

1. `app/core` imports nothing from `app/`
2. `app/decision` imports only `app/core` — no I/O, model, database, clock or randomness
3. `app/adjudication` and `app/intake` cannot import `app/decision`
4. Domain packages cannot import `app/graph` or `app/api`
5. `langgraph` is importable only inside `app/graph`

Plus a schema test: no model output schema contains an approval or denial member.

### The five outcomes

Every outcome is a **first-class terminal state** with its own rendering and its own audit row. None
is an error path.

| Situation | Outcome |
|---|---|
| No applicable policy | `NEEDS_INFO` → human. **Never a denial.** |
| Conflicting policies | `HUMAN_REVIEW` |
| Unverifiable citation | `NO_DECISION` |
| Model path failed / blocked | `HUMAN_REVIEW` |
| Contradictory verdicts | `HUMAN_REVIEW` |
| Insufficient evidence (open question) | `NEEDS_INFO` |
| Evidenced non-satisfaction | `DENY_RECOMMENDED` |
| Exclusion satisfied | `DENY_RECOMMENDED` |
| Sufficient, verified evidence | `APPROVE_RECOMMENDED` |

---

## Architecture

```
                        Clinical case (synthetic)
                                   │
                                   ▼
              ┌────────────────────────────────────────────┐
              │  APPLICABILITY / RESOLUTION   deterministic │  SQL over policy_code_links:
              │  six states; only RESOLVED continues       │  code × dx × jurisdiction × DOS
              └────────────────────┬───────────────────────┘
                                   │
                                   ▼
              ┌────────────────────────────────────────────┐
              │  INTAKE                            [model] │  facts + source spans
              │  no coverage vocabulary                    │  prompt: intake.v2
              └────────────────────┬───────────────────────┘
                                   │
                                   ▼
              ┌────────────────────────────────────────────┐
              │  EVIDENCE RETRIEVAL        [local encoders]│  bi-encoder → pgvector ANN (top_k 40)
              │  scoped to resolved versions ONLY          │  → cross-encoder rerank (top_n 8)
              └────────────────────┬───────────────────────┘
                                   │
                                   ▼
              ┌────────────────────────────────────────────┐
              │  PER-CRITERION ADJUDICATION        [model] │  one call per criterion, ≤4 parallel
              │  verdict + citations, isolated             │  prompt: adjudication.v1
              └────────────────────┬───────────────────────┘
                                   │
                                   ▼
              ┌────────────────────────────────────────────┐
              │  GUARDRAILS                  deterministic │  span verification · metadata match
              │  any citation failure ⇒ NO_DECISION        │  · evidence-set membership
              └────────────────────┬───────────────────────┘
                                   │
                                   ▼
              ┌────────────────────────────────────────────┐
              │  POLICY LOGIC + DECISION TABLE  [pure code]│  3-valued logic, then the table
              │  + ABSTENTION GATE                         │  rows 1-6 before any denial
              └────────────────────┬───────────────────────┘
                                   │
      ┌──────────┬─────────────────┼─────────────────┬──────────────┐
      ▼          ▼                 ▼                 ▼              ▼
 APPROVE_REC  DENY_REC        NEEDS_INFO       HUMAN_REVIEW    NO_DECISION
      └──────────┴─────────────────┼─────────────────┴──────────────┘
                                   ▼
                    HUMAN REVIEW  (accept · override · request-info)
                                   ▼
                         APPEND-ONLY AUDIT TRAIL

  Every chat completion:  MEDAUTH → llm-firewall :8005/v1 → OpenAI-compatible provider
  MEDAUTH holds a revocable CALLER key. The firewall holds the provider key.
```

### Identity and authorization

```
User → HTTPS (terminated at a reverse proxy; the app holds no certificate)
     → Keycloak 26 (non-production) → OIDC token, RS256
     → MEDAUTH: discovery → JWKS → signature/issuer/audience/expiry/nbf/subject
     → validated Principal   (TYPE checked BEFORE permissions)
     → permission set        (three permissions, cumulative)
     → service-layer authorization   (in the service, not the route)
     → case / HITL service → review decision → append-only audit (trigger-enforced)
```

**Two separations the design exists to protect:**

- **AI recommendation ≠ human decision.** Distinct fields. `human_disposition` is `None` until a
  person acts, and an override **preserves** the original draft rather than replacing it.
- **Historical evidence ≠ fresh retrieval.** A reviewer sees the evidence the original run used,
  read from its audit trail. Re-running retrieval would show today's corpus for yesterday's decision
  — and the failure would be invisible, because the citations would still verify.

---

## Tech stack

| Layer | Technology | Version | Why |
|---|---|---|---|
| Language | Python | `>=3.12` | `StrEnum`, native generics, structural typing |
| API | FastAPI | `>=0.115,<1.0` | ASGI, async-first, OpenAPI from types |
| Server | Uvicorn (standard) | `>=0.30,<1.0` | ASGI server |
| Types / schemas | Pydantic | `>=2.9,<3.0` | Domain types and **closed** output schemas |
| Settings | pydantic-settings | `>=2.5,<3.0` | Env config with `SecretStr` |
| Database | PostgreSQL + **pgvector** | `pg16` | Relational filters and vector search in **one query** |
| ORM | SQLAlchemy (asyncio) | `>=2.0.35,<3.0` | Corpus, cases, audit |
| Driver | asyncpg | `>=0.29,<1.0` | Async PostgreSQL |
| Migrations | Alembic | `>=1.13,<2.0` | Schema versioned, never auto-created |
| HTTP client | httpx | `>=0.27,<1.0` | Pooled async client → llm-firewall |
| Identity | PyJWT `[crypto]` | `>=2.9` | RS256/ES256 verification via JWKS |
| Identity provider | Keycloak | `26.0` | Non-production OIDC issuer |
| Templating | Jinja2 | `>=3.1,<4.0` | Server-rendered reviewer view — no npm, no bundler |
| Logging | structlog | `>=24.4,<26.0` | Redaction **at the sink** |
| Metrics | prometheus-client | `>=0.21,<1.0` | `/metrics` exposition |
| Config | PyYAML | `>=6.0,<7.0` | Decision policy + overlays |
| **Extra:** `retrieval` | sentence-transformers · torch (**CPU**) | `>=3.0` · `>=2.4` | `BAAI/bge-base-en-v1.5` encoder, `BAAI/bge-reranker-base` cross-encoder |
| **Extra:** `eval` | pandas · scikit-learn | `>=2.2` · `>=1.5` | Evaluation harness |
| **Extra:** `otel` | OpenTelemetry SDK + OTLP | `>=1.27` | Opt-in tracing |
| Packaging | **uv** + PEP 621 + hatchling | `0.5.x` | Poetry is **not** supported |
| Quality | ruff · mypy (strict) · pytest | — | `E,F,I,B,S,ASYNC,UP,C4,RUF`; `mypy app` strict |
| Runtime | Docker Compose | — | API, pgvector; the firewall is *consumed*, not started |

> GPU torch wheels are ~2.4 GB and this project never uses them — encoders run on **CPU** and no
> generative model is served locally. A dedicated CPU-only index is pinned in `pyproject.toml`.

---

## Prerequisites

| Required | Notes |
|---|---|
| **Python 3.12+** | |
| **[uv](https://docs.astral.sh/uv/)** | The only supported installer. Poetry is not supported. |
| **Docker + Docker Compose** | PostgreSQL/pgvector, the API image, the IdP |
| **PostgreSQL client** (`psql`) | Creating the test database |

| Optional | Needed for |
|---|---|
| **[llm-firewall](https://github.com/picoders1/llm-firewall)** at `:8005` | Live model calls only. **Not needed for the test suite.** |
| Restricted CFR corpus | `corpus`-marked tests. Acquire with `uv run python scripts/acquire_ecfr.py`. |

**No API key and no network egress are required to run the tests**, and no model is ever called —
tests that would call one are marked and skipped.

> **The restricted CFR corpus is not in this repository.** Embedded CPT® descriptors are
> AMA-copyrighted and are not redistributed here. Code *values* are fine; descriptor *text* is not.
> `data/cms/registry.yaml` records provenance and **is** committed; the documents are not.

---

## Installation

```bash
git clone https://github.com/picoders1/medauth-ai.git
cd medauth-ai

uv sync --all-groups --all-extras     # everything, incl. torch (CPU) for retrieval
# or: uv sync --all-groups            # skip the ~2 GB retrieval extra

cp .env.example .env                  # then edit; see Configuration below
```

Start the database and apply migrations:

```bash
docker compose up -d postgres
uv run alembic upgrade head
```

For the test suite, create the separate test database:

```bash
docker exec medauth-postgres-1 psql -U medauth -d medauth -c 'CREATE DATABASE medauth_test'

MEDAUTH_DATABASE_URL="postgresql+asyncpg://medauth:medauth@localhost:5435/medauth_test" \
  uv run alembic upgrade head
```

---

## Running

### The stack

```bash
docker compose up -d --build     # or: make up
uv run alembic upgrade head
curl localhost:8015/ready        # or: make ready
```

`/ready` reports four checks — configuration, decision policy, database, and the firewall
(advisory). A container that lost its security configuration never has traffic routed to it.

### Make targets

| Target | Does |
|---|---|
| `make install` | `uv sync --all-groups` |
| `make fmt` | `ruff format` + `ruff check --fix` |
| `make lint` | `ruff check` + `ruff format --check` (blocking in CI) |
| `make type` | `mypy app` strict, plus the boundary-protocol test doubles |
| `make test` | Fast suite: `unit or api or security` |
| `make test-all` | Everything, including integration |
| `make check` | What CI runs: lint + type + test |
| `make up` / `make down` | Start / stop the stack |
| `make migrate` | `alembic upgrade head` |
| `make ready` | Readiness report |
| `make mutations` | Break each safety rule on purpose; every one must make a test fail |
| `make probe` | Record model capabilities → `eval/reports/` |

### The full demonstration — a real identity provider, end to end

Roughly ten minutes, entirely local, no cloud account. **It needs no model calls and does not touch
the blocked evaluation gate or `gold_v2`.**

```bash
# 1. non-production IdP — a SEPARATE compose file, on purpose:
#    `docker compose up` must never start an identity provider by accident
docker compose -f compose.idp.yaml up -d
set -a; . ./.env; . ./.env.idp; set +a
bash scripts/bootstrap_nonprod_idp.sh      # realm, 3 groups, 4 fixture identities

# 2. prove the provider satisfies the contract, before trusting anything
uv run python scripts/verify_idp.py --issuer "$MEDAUTH_OIDC_ISSUER" --audience medauth-api

# 3. the application
docker compose up -d --build && uv run alembic upgrade head

# 4. the whole path: real tokens → authorization matrix → HITL → audit → 19 negative cases
uv run python scripts/verify_idp_container_e2e.py
```

That last command demonstrates, in order: a real RS256 token authenticating through the published
port; `readonly` may read and nothing else; `reviewer` may accept and request information but **not**
override; `senior-reviewer` may override; an authenticated user in no group can do nothing. It then
opens a case and shows the review read model — **the routing explanation renders above the AI
recommendation**, which is labelled a draft and kept in a different field from the human disposition.
It accepts one case, requests information on another, overrides a third, and shows the original AI
draft surviving the disagreement. It reads the audit back: the provider's `sub` with its issuer, and
`UPDATE`/`DELETE` refused by trigger. Finally it runs 19 negative authentication cases, all returning
**one identical `401`**.

### The production-shaped stack

```bash
bash scripts/make_local_tls.sh                       # an isolated local CA
docker compose -f compose.prod-shape.yaml up -d --build

uv run python scripts/production_smoke.py \
  --api-url https://api.medauth.localhost:8444 \
  --issuer "$MEDAUTH_OIDC_ISSUER" --audience medauth-api
```

Keycloak in production mode on persistent PostgreSQL, HTTPS with real certificate verification. The
smoke suite runs in **safe mode** by default — ten of its twelve checks are reads or denials and it
writes **nothing**. The two that finalise a case run only against a case you designate with
`--smoke-case-id`, because a smoke test that quietly finalises a case has corrupted the append-only
record it was checking.

---

## Configuration

Two deliberately separate systems ([ADR-017](docs/adr/ADR-017-configuration-model.md)):

| System | Location | Holds |
|---|---|---|
| **Settings** | `.env` / environment, prefix `MEDAUTH_` | Secrets and deployment values |
| **Policy** | `config/decision-policy.yaml` | Thresholds, actions, gates — **clinical behaviour** |

Secrets never appear in policy YAML: any key matching `*_key`, `*secret*`, `*token*` or `*password*`
**fails the load**. Copy `.env.example` (placeholders only) to `.env`.

### Key settings

| Variable | Default | Notes |
|---|---|---|
| `MEDAUTH_ENVIRONMENT` | `development` | `production` refuses to start if any security boundary is disabled |
| `MEDAUTH_LLM_BASE_URL` | `http://localhost:8005/v1` | Points at the **firewall**, never at a provider |
| `MEDAUTH_LLM_API_KEY` | — | Firewall **caller** key, not a provider key |
| `MEDAUTH_LLM_FAIL_CLOSED` | `true` | Fail toward the human, never toward a denial |
| `MEDAUTH_LLM_STREAMING_ENABLED` | `false` | `stream=True` is rejected in code |
| `MEDAUTH_DATABASE_URL` | `…@localhost:5435/medauth` | |
| `MEDAUTH_EMBEDDING_MODEL` | `BAAI/bge-base-en-v1.5` | Local, CPU |
| `MEDAUTH_RERANKER_MODEL` | `BAAI/bge-reranker-base` | Local cross-encoder |
| `MEDAUTH_RETRIEVAL_TOP_K` | `40` | ANN candidates within resolved versions |
| `MEDAUTH_RERANK_TOP_N` | `8` | Cross-encoder survivors per criterion |
| `MEDAUTH_CLINICAL_TEXT_LOGGING` | `off` | |
| `MEDAUTH_AUDIT_REQUIRED` | `true` | |
| `MEDAUTH_AUTH_MODE` | `development` | `oidc` for a real identity provider |
| `MEDAUTH_OIDC_ISSUER` / `_AUDIENCE` | — | Discovery on by default |
| `MEDAUTH_TRUSTED_PROXIES` | `127.0.0.1/32` | `0.0.0.0/0` is **refused at startup** |
| `MEDAUTH_API_PORT` | `8010` | The port bound **inside** the container — see Ports |

### Decision policy

```yaml
abstention_rules:                     # hard constraints, evaluated before anything is scored
  require_unique_resolution: true     # exactly one applicable policy version
  require_all_citations_valid: true
  max_contradictions: 0
  min_criteria_coverage: 1.0

abstention_thresholds:
  approve: null                       # NOT YET CALIBRATED — null means the scored stage is
  deny:    null                       # inert and the RULE stage alone gates

retrieval:      { top_k: 40, rerank_top_n: 8 }
adjudication:   { max_concurrency: 4, max_repair_attempts: 2, max_criteria_per_case: 64 }
```

> Writing a plausible threshold here before calibration would be a **fabricated metric with clinical
> consequences**. The nulls are deliberate.

The decision **table** is *not* configuration. It lives in `app/decision/table.py` with a truth-table
suite, because a deployment must not be able to reorder the missing-evidence and evidenced-failure
rows — turning missing paperwork into a denial — without a code review.

Every recommendation records `decision_config_version`, so which rules were in force for a given case
is an **auditable fact** rather than a reconstruction.

---

## Pipeline stages

| # | Stage | Kind | What it produces | Failure route |
|---|---|---|---|---|
| 1 | **Applicability** | SQL, deterministic | One of six resolution states; only `RESOLVED` continues | `NEEDS_INFO` (none) · `HUMAN_REVIEW` (conflicting) |
| 2 | **Intake** | **model** | Clinical facts + source spans. No coverage vocabulary | `HUMAN_REVIEW` |
| 3 | **Retrieval** | local encoders | Evidence chunks, scoped to resolved versions | — |
| 4 | **Mapping** | code | Criterion → evidence set | — |
| 5 | **Assessment** | **model** | Per-criterion verdict + citations, one call each | `HUMAN_REVIEW` |
| 6 | **Citations** | code | Span verification of every quote | `NO_DECISION` |
| 7 | **Contradiction** | code | Contradiction report | `HUMAN_REVIEW` |
| 8 | **Policy logic** | pure | What the *policy* concludes (3-valued) | `HUMAN_REVIEW` if unresolved |
| 9 | **Abstention** | code | Whether to decide at all | `NEEDS_INFO` |
| 10 | **Decision** | pure | One of five outcomes + rule | — |
| 11 | **Audit** | code | Append-only event rows | — |

**Two layers, kept apart.** Policy logic says what the *regulation* concludes; the decision table
says what to *recommend*. "The conditions are met" and "approve" are different claims — the second
also weighs evidence quality, guardrail state and open questions — and a system that conflates them
cannot say which of the two it got wrong.

**Row order is the safety design.** Rows 1–6 are all evaluated before any denial is reachable, and
the open-question row precedes evidenced failure. That is the difference between "the note does not
say" and "the note says otherwise". Three-valued logic alone would not preserve it: a decisive FALSE
is logically decisive whatever else is unknown. Holding the case anyway is a **safety choice of this
system**, made where it can be read and tested.

---

## Orchestration — and why this is *not* a multi-agent system

`app/graph/slice.py` holds `SliceRunner`: **one case, one pass, one policy version.**

```
Not implemented here, deliberately:
  no LangGraph · no agent loop · no retry policy beyond the gateway's own
```

**LangGraph is not implemented and is not in progress.** `langgraph` is importable only inside
`app/graph` — a boundary held open for a future that has not arrived — and that package currently
contains the linear slice runner and no graph. Multi-agent orchestration is listed **NOT STARTED** in
[the roadmap](docs/architecture/implementation-roadmap.md), and this README does not claim it.

That is a design position, not a gap left by accident:

- **A fixed pipeline is auditable.** Every case takes the same path in the same order, so "why did
  this case get this outcome" is answerable from the audit trail without replaying a planner's
  reasoning.
- **An agent that chooses its own steps can choose to skip one.** The steps here include span
  verification and the applicability check. Neither is optional, so neither is a decision to delegate.
- **Per-criterion isolation is the containment boundary.** Criteria are adjudicated in separate
  calls that cannot see each other — up to 4 concurrently. A shared agent scratchpad would reconnect
  them and hand an injection a channel between criteria.

**What the orchestrator does own:** all routing. `app/intake` and `app/adjudication` cannot even
*name* a gateway outcome — the enum member carries a token the layer-boundary test refuses in those
packages — so they let failures propagate and the runner classifies them. What a blocked call means
for a case is a decision about the *case*, not about the call.

**A lesson recorded in the code.** Until Phase 15 the runner was *handed* a policy identity and
passed `ResolutionState(RESOLVED)` as a literal, which made the two rows that refuse to decide when
no policy applies unreachable from the runtime. A case was adjudicated against a policy that did not
govern it and produced `DENY_RECOMMENDED` backed by **seven citations that all verified** — every
grounding metric passed it. The table had always refused that; nothing ever asked it. Applicability
now runs **first**.

---

## Security

**Retrieved policy text is DATA, never instruction.** It enters a prompt only through
`app/adjudication/evidence_block.py`, fenced and explicitly framed. It is never concatenated into a
system prompt. No prompt is ever assembled from note text, policy text or reviewer input.

**The firewall does not protect this system's main attack surface — and this project does not claim
it does.** The firewall's own committed evidence refuses that claim: indirect-injection recall
**0.1423**, planted-content recall **0.0938**. It classifies the *user's turn*; the threat here is
content the user never wrote. Containment is **structural** — closed schemas with no decision token,
span-verified quotes, code-computed decisions, per-criterion isolation, corpus content hashing — and
holds whether or not an injection is detected.

**A `403` from the firewall is never retried.** Retrying a blocked request is an attempt to evade a
security control. It routes to `HUMAN_REVIEW`, as does `503`, a timeout, and unreachability. *Fail
closed means fail toward the human, never toward a denial.*

Other invariants:

- **MEDAUTH holds no model-provider credential.** The firewall holds the upstream key; MEDAUTH holds
  a revocable caller key.
- **No clinical text in logs, spans, metric labels or audit payloads.** Redaction is enforced at the
  structlog sink, not per call site. Audit payloads carry fact ids, chunk ids and spans; text is
  joined for display.
- **The audit trail is append-only**, enforced by trigger. Retention deletes by `created_at` and by
  nothing else — a purge that can be aimed at particular rows is a mechanism for erasing the record
  of a specific recommendation.
- **Model identity is hashed in audit rows** (`sha256:…`), so a concrete model id — a deployment
  value — never reaches the artefact that gets exported.

27 threats in [docs/security/threat-model.md](docs/security/threat-model.md) ·
[evidence summary](docs/security/security-summary.md) ·
[firewall integration](docs/security/llm-firewall-integration.md)

---

## Testing

```bash
uv run pytest -q                          # 1369 tests
uv run pytest -m "unit or api or security"   # 1065 — the fast suite CI runs
uv run pytest -m "unit or evaluation"        # 1160 — green with nothing running
uv run python scripts/mutation_guard.py      # 47/47 safety mutations caught
```

| Marker | Meaning |
|---|---|
| `unit` | Pure logic, no I/O |
| `api` | Exercises the ASGI app in-process |
| `security` | Containment, fail-closed, leakage, boundaries |
| `integration` | Requires PostgreSQL and/or the firewall |
| `evaluation` | Evaluation harness; **no model calls** |
| `corpus` | Needs the restricted CFR documents; **skips with a reason** when absent |

**A database is required for 38 of them** — the reviewer workflow, the append-only audit triggers and
the case lifecycle are verified against real PostgreSQL rather than a fake, and the schema comes from
the migrations so the triggers are the ones a deployment gets. Those 38 deliberately **fail on
connection rather than skipping**: a database a runner can start in seconds is not the kind of
missing dependency that should quietly remove 38 security tests from CI.

**The mutation guard** breaks each safety rule on purpose and requires a test to fail. Where the
restricted corpus is present it reports **47/47 caught**; in CI, which cannot hold that corpus, it
reports **37 caught, 10 not verified** and names them — it does not credit a mutation whose catching
test could not run.

CI additionally enforces a fresh lockfile, strict typing, that no credential-shaped literal is
committed, that no outcome token appears in a verdict-only package, and that **no compliance claim**
is present anywhere in the tree.

---

## Evaluation

`eval/` is a **pre-registration regime**, not a scratch area.

- **No fabricated metrics, ever.** Every number in any document must come from a committed report
  under `eval/reports/` carrying its dataset hash, split, denominators, git commit and machine
  metadata.
- **ADRs from 011 onward are pre-registered protocols** — hypotheses, success criteria (with
  denominators, interval method and *direction*) and failure modes fixed **before** execution.
  Criteria are never retuned after seeing results.
- **Ground truth is by construction.** A case's label comes from its criteria-satisfaction pattern
  via the **same `decide()`** the system uses — never from a model's opinion. A model labelling cases
  it will later adjudicate measures self-consistency and reports it as accuracy.
- **Frozen corpora are versioned, never edited.** Hashes are pinned in `registry.yaml` and in tests.
- **Hold-outs have a scoring budget**, enforced at the library boundary: `require_tunable(split)`
  raises on a frozen split, and every calibration entry point calls it. Selection and threshold
  calibration use **dev only**.
- **Denial precision is always reported separately**, with its own denominator and interval.
- **Negative results are first-class.** If abstention reduces coverage without reducing unsafe
  decisions, that is the finding — commit it and leave the claim refused.

Statistical conventions: **Wilson** intervals for single rates, **exact McNemar** for paired
same-corpus comparisons.

**Stated before any result exists:** with ~150 gold cases split dev/test, per-class denominators are
in the tens and 95% Wilson intervals span roughly ±10–15 pp. Differences smaller than that are not
detectable and will not be claimed.

### Results

**None.** No evaluation has been run — the gate is blocked on R-86 above. This section will be
populated only from committed reports, each carrying its dataset hash, split, denominators,
intervals, model id and git commit.

---

## Limitations

Stated now, not after results.

1. **Constructed cases are cleaner than real clinical notes.** Any measured performance is an upper
   bound. The claim that it transfers to real documentation is **refused, permanently**.
2. **Small denominators.** ~25–40 cases per class bound what can be concluded.
3. **Criteria trees are model-extracted.** A systematic extraction error becomes a systematic
   adjudication error. Human review is the control; extraction accuracy is not claimed.
4. **Injection containment is unmeasured.** The layers exist by design; no containment claim is made
   before a report exists.
5. **No self-hosted vLLM.** The reference machine has 4 GB VRAM. vLLM is a documented target, not a
   validated one.
6. **No reviewer pilot.** Override rate, human/AI agreement and review-time claims are refused.
7. **Corpus is bounded** to a small number of procedures, limiting generality.
8. **No penetration test.**
9. **No production deployment**, and no enterprise SSO deployment.

### Scope

| | |
|---|---|
| **Is** | Decision support. Produces a **recommendation with its evidence** for a qualified human reviewer. |
| **Is not** | An autonomous decision maker. No output of this system is a coverage determination. |
| Policy corpus | Publicly available **CMS Medicare Coverage Database** material — NCDs, LCDs, Billing & Coding Articles. CMS policy is **not** any commercial payer's medical policy. |
| Patient data | **Synthetic only.** No real PHI. |
| Privacy | Designed with healthcare privacy and security considerations and evaluated exclusively using synthetic patient data. **No compliance claim is made.** |

---

## Repository layout

```
app/          19 packages, 102 modules — the application
  core/         shared types; imports nothing from app/
  decision/     the pure decision engine
  policy/       corpus, criteria, temporal versioning
  retrieval/    encoders, pgvector search, rerank
  intake/ adjudication/ guardrail/    the model-facing layers
  graph/        the linear slice runner (no LangGraph)
  case/ review/ identity/ audit/      lifecycle, HITL, identity, audit
  llm/          the single model seam
  api/          FastAPI app + server-rendered reviewer view
config/       decision-policy.yaml — thresholds are configuration, versioned and audited
prompts/      versioned prompt files: intake.v1, intake.v2, adjudication.v1
migrations/   6 Alembic revisions; the schema a deployment actually gets
eval/         harness · datasets/ frozen + hashed · reports/ the source of every number
tests/        unit · api · security · integration · evaluation · corpus
scripts/      63 operational, ingest, evaluation and verification scripts
deploy/       docker/ · nginx-prod-shape.conf · local-tls/
docs/         architecture · adr (30) · evaluation · security · operations · portfolio
```

Prompts are **versioned files with ids**. Editing a template in place without incrementing the
version breaks audit reproducibility and is a defect.

### Ports

| Service | Port | Notes |
|---|---|---|
| **MEDAUTH API** | **8015** | Published on the host. The **container** binds `8010`; `compose.yaml` maps `8015:8010` |
| PostgreSQL + pgvector | 5435 | |
| llm-firewall | 8005 | **Consumed**, never started by this stack |
| Non-production IdP (Keycloak) | 8090 | `compose.idp.yaml` only — a separate file, on purpose |
| Production-shape HTTPS edge | 8444 | `compose.prod-shape.yaml` (Keycloak 8443, PostgreSQL 5436) |
| Reviewer UI origin | 3100 | CORS origin setting; the reviewer view itself is served by the API at `/ui/cases/{id}` |

Ports avoid everything bound on the reference machine. `8010` is on that avoided list — it was
reclaimed for another application on 2026-08-26 ([ADR-019](docs/adr/ADR-019-deployment.md) amendment).

### API surface

```
POST   /api/v1/cases                        create
GET    /api/v1/cases/{id}                   read
GET    /api/v1/cases/{id}/status            lifecycle state
GET    /api/v1/cases/{id}/recommendation    the AI draft — never a decision
GET    /api/v1/cases/{id}/evidence          the evidence that run used
GET    /api/v1/cases/{id}/review            reviewer read model
POST   /api/v1/cases/{id}/review/accept          reviewer +
POST   /api/v1/cases/{id}/review/request-info    reviewer +
POST   /api/v1/cases/{id}/review/override        senior-reviewer only
GET    /api/v1/cases/{id}/audit             append-only trail
GET    /health  ·  /ready  ·  /metrics
GET    /ui/cases/{id}                       server-rendered reviewer view
```

A nonexistent case and another integrator's case are **indistinguishable** — both `404`.

---

## Documentation

`docs/` is the source of truth. Code contradicting it is a bug in one of the two. Start at
[docs/README.md](docs/README.md).

| Document | What it is |
|---|---|
| [PROJECT-STATUS.md](PROJECT-STATUS.md) | **The authoritative status.** Where anything disagrees, this is current |
| [docs/architecture/](docs/architecture/) | How the system works |
| [docs/adr/](docs/adr/) | 30 decision records — why, with alternatives and consequences |
| [docs/evidence-and-claims.md](docs/evidence-and-claims.md) | What may and may not be said, and the claims this project **refuses** |
| [docs/risk-register.md](docs/risk-register.md) · [docs/open-decisions.md](docs/open-decisions.md) | An item leaves either list only with the artefact that resolved it |
| [docs/security/threat-model.md](docs/security/threat-model.md) | 27 threats |
| [docs/portfolio/project-summary.md](docs/portfolio/project-summary.md) | One page · [demo guide](docs/portfolio/demo-guide.md) |

---

## Engineering conventions

- **No fabricated numbers.** Every figure traces to a committed report, or it is not written.
- **Negative results are first-class.** A failed experiment honestly reported is the expected output.
- **Frozen corpora are never edited.** Extend by adding a version that reproduces the split rule
  byte-for-byte.
- **Documentation ships in the same change as the code.** Drift is a defect, not a chore.
- **Tests must not be vacuous** — assert the input actually reaches the branch under test. A
  "borderline" sample scoring 0.0000 proves nothing about a threshold.
- **Prompts are versioned files with ids.** Editing a template in place is a defect.
- **Model weights and downloaded corpora never enter the app tree or git.**
- **Commits are manual.**

## License

Apache-2.0.

**CPT® is a registered trademark of the American Medical Association.** No CMS document and no CPT®
descriptor text is redistributed in this repository.
