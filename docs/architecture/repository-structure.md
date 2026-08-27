# Repository Structure

**Status:** Built. The layout below exists — 102 modules under `app/`, 6 migrations, 62 test
modules. It was written as a target and is now a description.

---

## 1. Tree

```
medauth-ai/
│
├── app/                          application code
│   ├── api/                      FastAPI routes, readiness contract, error envelope
│   ├── core/                     domain types, ids, normalization, errors  (imports nothing from app/)
│   ├── intake/                   clinical extraction        [model]
│   ├── policy/                   corpus model, ingest, criteria trees, RESOLUTION
│   ├── retrieval/                embedding, pgvector search, reranking     [local encoders]
│   ├── adjudication/             per-criterion verdicts     [model]
│   ├── guardrail/                citation + evidence validation            [deterministic]
│   ├── decision/                 pure decision engine + abstention gate    [pure]
│   ├── audit/                    append-only trail
│   ├── llm/                      OpenAI-compatible client → llm-firewall
│   ├── graph/                    LangGraph wiring ONLY — no domain logic
│   ├── database/                 SQLAlchemy async session, engine
│   └── observability/            structlog, OTel, Prometheus
│
├── config/                       decision-policy.yaml, environments/
├── migrations/                   Alembic; schema is versioned, never auto-created
│
├── data/                         INPUTS — gitignored
│   ├── cms/                      downloaded corpus  (+ registry.yaml, committed)
│   └── synthea/                  generated records
│
├── eval/                         evaluation harness
│   ├── datasets/                 FROZEN, hashed, COMMITTED gold corpora
│   ├── metrics/                  classification, calibration, grounding
│   ├── runners/                  decision, retrieval, grounding, abstention
│   └── reports/                  committed run artefacts — the source of every number
│
├── tests/
│   ├── unit/                     pure logic, no I/O
│   ├── integration/              needs PostgreSQL and/or the firewall
│   ├── security/                 injection, poisoning, leakage, boundaries
│   └── evaluation/               harness guards; no model loads
│
├── ui/                           Next.js reviewer console
├── deploy/
│   ├── docker/
│   └── k8s/                      authored + statically validated; see ADR-019
├── scripts/                      ingest, generate cases, calibrate, purge
├── docs/                         architecture/ adr/ evaluation/ security/ runbooks/
├── .github/workflows/
│
├── pyproject.toml                PEP 621, uv
├── Makefile
├── compose.yaml                  development
├── compose.prod.yaml             reference production topology (standalone)
├── README.md
├── .env.example
└── .gitignore
```

---

## 2. Divergences from the original proposal, and why

| Proposed | Here | Reason |
|---|---|---|
| `app/agents/` | `app/intake/`, `app/policy/`, `app/retrieval/`, `app/adjudication/`, `app/guardrail/` + `app/graph/` | "Agent" is an orchestration concept, not a domain boundary. Naming packages after what they *do* means each step is an ordinary async function, unit-testable without constructing a graph, and LangGraph stays replaceable. See [ADR-002](../adr/ADR-002-agent-orchestration.md). |
| `app/decision/` doing validation and decision | `app/guardrail/` + `app/decision/` | Validation does I/O (it reads chunks); the decision must be pure. Merging them would make the decision function untestable as a truth table. |
| `data/gold/` | `eval/datasets/` | Frozen corpora are evaluation artefacts: hashed, committed, scoring-budgeted. `data/` holds only gitignored inputs. Mirrors the sibling project. |
| — | `config/` | Thresholds are configuration, not code, and changing one changes clinical behaviour. Separating settings (env) from policy (YAML) follows the firewall's ADR-011. |
| — | `migrations/` | Schema versioned by Alembic, never auto-created. |
| `app/services/` | dropped | A generic bucket that accretes anything not obviously placed elsewhere. Every candidate belonged in a named package. |
| `docs/runbooks/` populated now | deferred to Phase 8 | A runbook for a system that cannot yet run is fiction. |

Kept from the proposal without change: `app/api/`, `app/core/`, `app/audit/`, `eval/`, `tests/`
with its four categories, `ui/`, `deploy/docker` + `deploy/k8s`, `scripts/`, `docs/` with its five
subdirectories, and the root files.

---

## 3. Dependency direction

```
   app/api ─────────┐
   app/graph ───────┤          orchestration (thin)
                    ▼
   intake · policy · retrieval · adjudication          domain
                    │
                    ▼
   guardrail ──▶ decision                              pure
                    │
                    ▼
   audit · database · observability · llm              infrastructure
                    │
                    ▼
                 core                                  types only
```

Enforced by `tests/unit/test_layer_boundaries.py`, which parses the AST rather than importing, so a
violation is caught even if the module never runs:

1. `app/core` imports nothing from `app/`.
2. `app/decision` imports only `app/core`; no I/O, no model, no database.
3. `app/adjudication` and `app/intake` cannot import `app/decision`; `Recommendation` is not
   importable inside them.
4. Domain packages cannot import `app/graph` or `app/api`.
5. `langgraph` is importable only inside `app/graph`.

These five rules are the structural expression of *models produce verdicts; code produces the
decision*. Without rules 2, 3 and 5 the invariant is a convention, and conventions decay.

---

## 4. Ports

Chosen to avoid everything bound on the reference machine (3000, 5000, 5433, 5434, 5678, 8005,
8006, 8010, 8080–8082, 8089, 9001, 9004, 9005, 9091).

**8010 was the API port until 2026-08-26** and is now on that avoided list: the port was reclaimed
for another application on the reference machine, so the API publishes on **8015** instead. Only the
published port moved - the container still binds 8010 internally (ADR-019).

| Service | Port |
|---|---|
| MEDAUTH API | **8015** |
| PostgreSQL + pgvector | **5435** |
| Next.js reviewer console | **3100** |
| Prometheus (optional overlay) | **9092** |
| Langfuse (optional overlay) | **3200** |
| llm-firewall (existing, consumed not deployed) | 8005 |

---

## 5. Toolchain

Matched to the sibling project so both repositories are operated the same way.

| Concern | Choice |
|---|---|
| Packaging | `uv`, PEP 621; lockfile checked in CI |
| Lint / format | `ruff` (line length 100, `E,F,I,B,S,ASYNC,UP,C4,RUF`) |
| Types | `mypy --strict` over `app/` |
| Tests | `pytest`, `--strict-markers`, markers `unit`, `api`, `security`, `integration`, `evaluation` |
| Migrations | `alembic` |
| Logging | `structlog`, redaction at the sink |
| Metrics | `prometheus-client` |
| Security scanning | `trivy`, `gitleaks`, `pip-audit` |
| UI | Next.js (`ui/`), built in its own container |

Heavy dependencies live in optional extras so the default image does not carry them:
`retrieval` (sentence-transformers, torch), `eval` (pandas, scikit-learn), `otel`.

---

## 6. Conventions

- **`docs/` is the source of truth.** Code contradicting it is a bug in one of the two.
- **No fabricated numbers.** Every figure traces to a committed report in `eval/reports/`, or it is
  not written. [evidence-and-claims.md](../evidence-and-claims.md) is the ledger.
- **Frozen corpora are never edited.** Extend by adding a version that reproduces the split rule
  byte-for-byte.
- **Negative results are first-class.** A failed experiment honestly reported is the expected
  output.
- **Commits are manual.** Changes are staged and the command handed over; nothing commits or
  pushes on its own.
