# MEDAUTH AI

**Agentic Prior-Authorization & Medical-Necessity Decision Support System**

An evidence-grounded system that helps a human reviewer evaluate prior-authorization requests
against authoritative coverage-policy criteria — and that is structurally unable to make the
decision itself.

**Python 3.12+** · **Engineering-complete** · Evaluated exclusively on synthetic patient data

---

## Status

**Engineering-complete.** The system runs end to end: a case is submitted, policy is resolved by
date of service, evidence is retrieved inside the resolved versions, per-criterion verdicts are
adjudicated, code computes the recommendation, and a reviewer authenticated by a real identity
provider accepts, requests information or overrides it — with every step written to an append-only
audit trail.

**Two things are deliberately *not* claimed: no production deployment, and no evaluation result.**
The full status, with the evidence behind every line, is **[PROJECT-STATUS.md](PROJECT-STATUS.md)**.

**Reading it in five minutes:** [project summary](docs/portfolio/project-summary.md) — one page ·
[run the demo](docs/portfolio/demo-guide.md) · [evidence scorecard](docs/evidence/final-scorecard.md) ·
[architecture decisions](docs/architecture/README.md) · [security evidence](docs/security/security-summary.md) ·
[why the evaluation is blocked](docs/evaluation/r86-status.md)

| | |
|---|---|
| Application | 102 modules · 6 migrations · **1369 tests** · **47/47 mutations caught** |
| Decision records | 30 ADRs — [docs/adr/](docs/adr/) |
| Threat model | 27 threats — [docs/security/threat-model.md](docs/security/threat-model.md) |
| Identity | Real OIDC against Keycloak 26 — **non-production**; `verify_idp.py` 12/12 |
| Production shape | HTTPS + persistent IdP + clean image, E2E **45/45** — deployment **not performed** |
| Evaluation | **Blocked.** The 26-case run has never executed — see below |

### The one thing that is blocked, and why it is not a code defect

`R-86`: on the registered reproducer the model provider emits ~190 characters of JSON,
never closes the document, and pads whitespace to the completion ceiling — **6 of 12 trials, against
a 10% threshold.** Ruled out by measurement: the application, both directions of the gateway, output
budget, context length, the schema alone and the content alone. A *longer* prompt with the same
schema terminates cleanly.

The decoder is behind an external provider with no administrative surface, so **MEDAUTH cannot fix
it locally** — and the evaluation gate stays `BLOCKED` rather than being lowered to fit. `gold_v2`
remains unspent. That decision is the point: [docs/operations/r86-provider-escalation.md](docs/operations/r86-provider-escalation.md).

Every performance, accuracy and grounding figure remains **pending evidence**. No number appears
anywhere unless a committed report produces it — [docs/evidence-and-claims.md](docs/evidence-and-claims.md).

---

## 1. Problem

Prior authorization asks a reviewer to decide whether a requested procedure meets a payer's coverage
criteria for a specific patient. It requires reading a clinical narrative, finding the policy that
actually applies — the right payer, jurisdiction and version *as of the date of service* — and
checking each criterion against the record.

Automating it has a well-documented failure mode: systems that issue denials at scale, faster than
humans can meaningfully review, on grounds that are frequently procedural rather than clinical.

MEDAUTH is built so that failure mode is **structurally unreachable**, not merely discouraged.

## 2. Scope

| | |
|---|---|
| **Is** | Decision support. Produces a recommendation with its evidence for a qualified human reviewer. |
| **Is not** | An autonomous decision maker. No output of this system is a coverage determination. |
| Policy corpus | Publicly available **CMS Medicare Coverage Database** material — NCDs, LCDs, Billing & Coding Articles. Payer-agnostic by construction. |
| Patient data | **Synthetic only.** No real PHI. |
| Privacy | Designed with healthcare privacy and security considerations and evaluated exclusively using synthetic patient data. **No compliance claim is made.** |

## 3. The governing invariant

> **NO EVIDENCE → NO DECISION**

| Situation | Outcome |
|---|---|
| Insufficient clinical evidence | `NEEDS_INFO` |
| No applicable policy | `NEEDS_INFO` → human. **Never a denial.** |
| Unverifiable citation | `NO_DECISION` |
| Conflicting evidence | `HUMAN_REVIEW` |
| Abstention gate not cleared | `NEEDS_INFO` |
| Model call blocked or failed closed | `HUMAN_REVIEW` |
| Sufficient, verified evidence | `APPROVE_RECOMMENDED` / `DENY_RECOMMENDED` |

Every state is first-class, with its own rendering and its own audit row. None is an error path.

## 4. The structural idea

> **Models produce per-criterion verdicts. Code produces the decision.**
>
> The tokens `APPROVE_RECOMMENDED` and `DENY_RECOMMENDED` do not exist in any model output schema
> anywhere in this system.

The decision is a pure function — no I/O, no clock, no randomness — exhaustively testable as a truth
table with no model loaded and no network. The boundary is enforced by an AST test that parses
source rather than importing it, so a violation is caught even if the offending module never runs.

A prompt injection can flip a verdict. It cannot emit a decision, because there is no field to write
one into. See [ADR-010](docs/adr/ADR-010-deterministic-decision-engine.md).

## 5. Architecture

```
  Clinical case (synthetic)
        │
        ▼  INTAKE                    [model]  facts + source spans; no coverage vocabulary
        ▼  POLICY RESOLUTION  [deterministic]  code × jurisdiction × date of service → versions
        ▼  EVIDENCE RETRIEVAL  [local encoders] scoped to resolved versions only
        ▼  PER-CRITERION ADJUDICATION [model]  verdict + span-verified citations, one call each
        ▼  GUARDRAIL          [deterministic]  validate every citation; failure ⇒ NO_DECISION
        ▼  DECISION ENGINE       [pure code]   10-row table + abstention gate
        │
   APPROVE_REC · DENY_REC · NEEDS_INFO · HUMAN_REVIEW · NO_DECISION
        ▼  HUMAN REVIEW  →  APPEND-ONLY AUDIT TRAIL

  Every chat completion:  MEDAUTH → llm-firewall :8005/v1 → OpenAI-compatible provider
```

Two steps call a model. Three are deterministic. Details:
[docs/architecture/system-architecture.md](docs/architecture/system-architecture.md).

### Why policy resolution is separate from retrieval

Semantic search always returns *something*. For a knee-MRI case it returns a plausible,
well-written, confidently-citable imaging policy — possibly from the wrong jurisdiction, or a
version retired before the date of service. The system then reasons impeccably over the wrong
document and produces a fully-cited wrong answer.

**Citations do not catch this.** They are genuine; the quotes verify; the policy simply does not
apply. So applicability is decided by rules — procedure code, diagnosis codes, jurisdiction, date of
service — and semantic search runs only *inside* the resolved set.
[ADR-004](docs/adr/ADR-004-policy-resolution-and-temporal-versioning.md).

## 6. Citation contract

Every citation carries `chunk_id`, an exact `quote`, and claimed policy id, version, section and
page. The quote must be an exact normalized substring of the stored chunk; the claimed metadata must
match the chunk's own; the chunk must have been in that criterion's evidence set. `source_url`,
`effective_date` and `document_title` are **joined from the database, never accepted from the
model** — a URL cannot be fabricated because it is never requested.

**Any citation failing any check ⇒ `NO_DECISION`.** Not a warning, not a lowered score.
[ADR-009](docs/adr/ADR-009-evidence-and-citation-contract.md).

## 7. Abstention

Not a model-reported confidence — that is a token sequence, not a probability, and it is manipulable
by anything in the context. The gate reads **deterministic features**: criteria coverage, citation
validity rate, rerank margin, policy-resolution uniqueness, contradiction count, criteria-tree
review status.

Thresholds are calibrated on **dev only** (enforced at the library boundary, not by discipline) and
validated **once** on a frozen test split with a scoring budget. Denial carries a stricter threshold
than approval, because a wrong denial withholds care while a wrong approval costs money.
[ADR-011](docs/adr/ADR-011-abstention-and-calibration.md).

## 8. Security

Every model call traverses the sibling **LLM Firewall** project — but **MEDAUTH does not
rely on it for its primary threat.** The firewall's own committed evidence refuses the claim that it
protects RAG applications: indirect-injection recall **0.1423**, planted-content recall **0.0938**.
It classifies the *user's turn*; MEDAUTH's threat is content the user never wrote.

Containment is therefore structural and lives in MEDAUTH: fenced data delivery, closed output
schemas with no decision token, span-verified quotes, a decision computed by code, per-criterion
isolation, and corpus content hashing.

27 threats in [docs/security/threat-model.md](docs/security/threat-model.md), each becoming a test
in Phase 8. Integration boundary:
[docs/security/llm-firewall-integration.md](docs/security/llm-firewall-integration.md).

## 9. Evaluation methodology

Four layers measured separately, because they fail differently and are fixed differently: policy
resolution, retrieval, grounding, decision. Ground truth is **by construction** — cases are built
from a human-reviewed criteria tree and the label is computed by the same decision table the system
uses, so no model labels a case it will later adjudicate.

**Stated before any result exists:** with ~150 gold cases split dev/test, per-class denominators are
in the tens and 95% Wilson intervals span roughly ±10–15 pp. Differences smaller than that are not
detectable and will not be claimed.
[docs/evaluation/evaluation-strategy.md](docs/evaluation/evaluation-strategy.md).

## 10. Results

**None.** No evaluation has been run. This section will be populated only from committed reports
under `eval/reports/`, each carrying its dataset hash, split, denominators, intervals, model id and
git commit.

## 11. Limitations

Stated now, not after results.

1. **Constructed cases are cleaner than real clinical notes.** Any measured performance is an upper
   bound. The claim that it transfers to real documentation is **refused**, permanently.
2. **Small denominators.** ~25–40 cases per class bound what can be concluded.
3. **Criteria trees are model-extracted.** A systematic extraction error becomes a systematic
   adjudication error. Human review is the control; extraction accuracy is not claimed.
4. **Injection containment is unmeasured** until Phase 8. Layers exist by design; no containment
   claim is made before the report exists.
5. **No Kubernetes cluster run.** Manifests are authored and statically validated with
   `kubeconform`. "Runs on Kubernetes" is a refused claim.
6. **No self-hosted vLLM.** The reference machine has 4 GB VRAM. vLLM is a documented target, not a
   validated one.
7. **No reviewer pilot.** Override rate, human/AI agreement and review-time claims are refused.
8. **Corpus is bounded** to 5–8 procedures initially, limiting generality.
9. **No penetration test.**

## 12. Repository

```
app/        intake · policy · retrieval · adjudication · guardrail · decision · audit · llm · graph
config/     decision-policy.yaml — thresholds are configuration, versioned and audited
eval/       harness; datasets/ frozen + hashed + committed; reports/ the source of every number
tests/      unit · integration · security · evaluation
ui/         Next.js reviewer console
deploy/     docker · k8s
docs/       architecture · adr · evaluation · security · runbooks
```

[docs/architecture/repository-structure.md](docs/architecture/repository-structure.md)

| Service | Port |
|---|---|
| API | 8015 |
| PostgreSQL + pgvector | 5435 |
| Reviewer console | 3100 |
| llm-firewall (consumed) | 8005 |

## 13. Getting started

### The test suite

```bash
uv sync --all-groups --all-extras
docker compose up -d postgres       # 38 api/security tests reach a real database
docker exec medauth-postgres-1 psql -U medauth -d medauth -c 'CREATE DATABASE medauth_test'
MEDAUTH_DATABASE_URL="postgresql+asyncpg://medauth:medauth@localhost:5435/medauth_test"   uv run alembic upgrade head

uv run pytest -q                          # 1369 passed
uv run python scripts/mutation_guard.py   # 47/47 mutations caught
```

**No API key and no network egress are required**, and no model is ever called — tests that would
call one are marked and skipped. A database *is* required: the reviewer workflow, the append-only
audit triggers and the case lifecycle are verified against real PostgreSQL rather than a fake, and
the schema comes from the migrations so the triggers are the ones a deployment gets.

With nothing running at all, `uv run pytest -m "unit or evaluation"` is green (1160 passed) and the
rest fail on connection rather than skipping — deliberately, because a database a runner can start
in seconds is not the kind of missing dependency that should quietly reduce coverage.

### The full demonstration — a real identity provider, end to end

Roughly ten minutes, entirely local, no cloud account. **It does not touch the blocked evaluation
gate or `gold_v2`, and it needs no model calls.**

```bash
# 1. non-production identity provider (a SEPARATE compose file, on purpose:
#    `docker compose up` must never start an IdP by accident)
docker compose -f compose.idp.yaml up -d
set -a; . ./.env; . ./.env.idp; set +a
bash scripts/bootstrap_nonprod_idp.sh        # realm, 3 groups, 4 fixture identities

# 2. prove the provider satisfies the contract, before trusting anything
uv run python scripts/verify_idp.py --issuer "$MEDAUTH_OIDC_ISSUER" --audience medauth-api

# 3. the application
docker compose up -d --build
uv run alembic upgrade head

# 4. the whole path: real tokens → authorization matrix → HITL → audit → 19 negative cases
uv run python scripts/verify_idp_container_e2e.py
```

What that last command demonstrates, in order: a real RS256 token authenticates through the
published port; `readonly` may read and nothing else; `reviewer` may accept and request information
but **not** override; `senior-reviewer` may override; an authenticated user in no group can do
nothing. Then it opens a case and shows the review read model — **the routing explanation renders
above the AI recommendation**, which is labelled a draft and kept in a different field from the
human disposition. It accepts one case, requests information on another, overrides a third, and
shows the original AI draft surviving the disagreement. It reads the audit back: the provider's
`sub` with its issuer, and `UPDATE`/`DELETE` refused by trigger. Finally it runs 19 negative
authentication cases, all returning one identical `401`.

### The production-shaped stack, and the safe smoke suite

```bash
bash scripts/make_local_tls.sh                        # an isolated local CA
docker compose -f compose.prod-shape.yaml up -d --build
uv run python scripts/production_smoke.py --api-url https://api.medauth.localhost:8444     --issuer "$MEDAUTH_OIDC_ISSUER" --audience medauth-api
```

Keycloak in production mode on persistent PostgreSQL, HTTPS with real certificate verification. The
smoke suite runs in **safe mode** by default — ten of its twelve checks are reads or denials, and it
writes **nothing**. The two that finalise a case run only against a case you designate with
`--smoke-case-id`, because a smoke test that quietly finalises a case has corrupted the append-only
record it was checking.

## 14. Engineering conventions

- **No fabricated numbers.** Every figure traces to a committed report, or it is not written.
- **Negative results are first-class.** A failed experiment honestly reported is the expected
  output.
- **Frozen corpora are never edited.** Extend by adding a version.
- **`docs/` is the source of truth.** Code contradicting it is a bug in one of the two.
- **Commits are manual.**
