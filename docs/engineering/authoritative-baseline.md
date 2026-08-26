# Authoritative baseline — 2026-08-26

Recomputed from the working tree at `6abfe58`+2, not carried forward from any earlier
report. Every number below was produced by running the command named beside it. This
supersedes the baseline stated in the preceding phase brief, which was stale in two
respects recorded in §1.

---

## 1. Git

| | |
|---|---|
| HEAD | `49d4c18` |
| branch | `main`, tree clean |
| `origin/main` | `a0f2859` — **one commit behind HEAD** |
| reflog | linear. No resets, amends, cherry-picks or rebases |

**Two corrections to the prior baseline.** It stated *nothing pushed* and *ten
unpushed commits*. Neither held: `origin/main` was at `a0f2859`, so all ten were
already pushed, and exactly one commit is unpushed now — the one made in this phase.

The single commit between `0fea8b9` and `a0f2859` touched 9 files — `.env.example`,
`Makefile`, `README.md`, `compose.yaml`, ADR-019, the roadmap, repository-structure,
system-architecture, evidence-and-claims. **No `app/` or `tests/` file changed**, so
no behaviour moved with it.

## 2. Deployment

The host port changed 8010 → **8015**; the container port did not.

| surface | value | consistent |
|---|---|---|
| `compose.yaml` | publishes `8015:8010` | ✔ |
| `deploy/docker/api.Dockerfile` | `EXPOSE 8010`, healthcheck 8010, uvicorn 8010 | ✔ — in-container |
| `settings.api_port` | default `8010` | ✔ — the bind, not the publish |
| Makefile, README, ADR-019, repository-structure | 8015 | ✔ — host-side |
| tests | **no test references any port** | ✔ |

Two surviving `8010` mentions are correct as written: `phase-1-implementation.md` is a
dated record of what was true then, and one roadmap line is annotated as historical.

## 3. Validation, recomputed

| | |
|---|---|
| full suite | **1358 passed**, 2 warnings |
| by marker | unit 638 · api 85 · security 660 · integration 79 · evaluation 516 |
| CI subset (`unit or api or security`) | 1054 passed, 304 deselected |
| ruff check / format | clean · 417 files formatted |
| mypy `app` | clean, 102 source files |
| `alembic check` | no new upgrade operations |
| `uv lock --check` | current |
| mutation harness | **47/47 caught** |

The CI subset and the full suite are the same suite under two denominators — the
subset excludes `integration` and `evaluation`. Both moved by 2 in this phase: the two
competence tests added in §5.

**One CI-equivalent failure found and fixed.** The *No compliance claims* guard would
have failed on HEAD, and had done since Phase 3 (`17434a6`) without being seen,
because nothing was pushed until recently. The test that *enforces* the rule holds
`"hipaa compliant",` in a tuple of claims that must not be made — a bare list entry,
carrying no prose for the grep's context filter to match on. Exempted by filename
exactly as `ci.yaml` already exempts itself; a file cannot ban a phrase without
quoting it. Verified in both directions: the guard passes, and still catches an
injected claim.

**A convention this exposed.** Two guards enforce this one rule and they accept
different framings. `test_no_fabricated_coverage_claim_in_phase_3_docs` is contextual
— it accepts `never`, `not`, `refus`, `forbid`, `prohibit`, `cannot`, `must not` and
more, anywhere in a six-line window. The CI grep is line-scoped and accepts only
`never write`, `refused`, `Refused`, `must not`. So a document framing a banned phrase
as *"forbidden"* satisfies the test and still fails CI. Both were left as they are —
widening the grep would loosen the outer net over every file to suit the two that are
exempt outright. **When quoting a banned phrase in `docs/`, frame it on the same line
with `must not`, `never write` or `refused`.**

**A second defect, in the record rather than the code.** `a0f2859` rewrote the
*evidence* column of a **Produced** claim in `docs/evidence-and-claims.md` from
`curl :8010/ready` to `curl :8015/ready`. The Phase 0 run that produced that evidence
used 8010; nothing was re-produced at 8015. Editing the evidence column to match a
later configuration makes the record describe a run that did not happen — the same
class of drift this repository's own rule forbids ("when a test's expectation changes
because the world changed, say so rather than silently editing the assertion"). The
row now carries the current command *and* states that the evidence predates the port
move.

**A vacuous test, caught before it was committed.** The competence API test in §5
first asserted only `status_code == 422`. It passed — but for the wrong reason: a
review action on a case still in `RECEIVED` is also a 422, so the assertion held with
the request model wide open. Confirmed by injection, then rewritten to assert the
pydantic `extra_forbidden` error on `competence` specifically, which only the closed
model can produce. Re-injected: it now fails as it should.

## 4. Authorization — set-based and cumulative

Read from `_PERMISSION_FOR_ROLE`, not from documentation:

| group | permissions |
|---|---|
| `medauth-readonly` | `READ_CASE` |
| `medauth-reviewer` | `READ_CASE`, `REVIEW_CASE`, `FINALIZE_CASE` |
| `medauth-senior-reviewer` | + `OVERRIDE_RECOMMENDATION` |
| any unknown group | **nothing** |

Per action, enforced in `app/case/review.py` — the service, not the route:

| action | requires |
|---|---|
| read a case | `READ_CASE` (`routes.py:367`, `reviewer_ui.py:70`) |
| accept | `REVIEW_CASE` + `FINALIZE_CASE` |
| override | `REVIEW_CASE` + `FINALIZE_CASE` + `OVERRIDE_RECOMMENDATION` |
| request-info | `REVIEW_CASE` only |

`REVIEW_CASE` is required for **every** review action and is not implied by
`FINALIZE_CASE`; the two are independent members of a set. `request-info` is the only
action `REVIEW_CASE` guards alone, which is why it is the action that proves the
requirement is live rather than masked.

Exercised, not asserted from the table:

```
principal                       accept   override   request-info
medauth-readonly                DENY     DENY       DENY
medauth-reviewer                allow    DENY       allow
medauth-senior-reviewer         allow    allow      allow
unknown-group                   DENY     DENY       DENY
SERVICE with EVERY permission   DENY     DENY       DENY
```

The last row is the one worth stating: a service principal holding **every**
permission in the enum is refused all three actions. `Principal.require()` checks
principal *type* before permissions, so the three `HUMAN_ONLY` permissions cannot be
exercised by a non-human whatever its grants say.

## 5. Identity, qualification, competence — separated structurally

| concept | what exists |
|---|---|
| identity | a validated OIDC subject — established |
| qualification | a sentence the reviewer typed — `SELF_ASSERTED` |
| competence | **nothing. Not modelled**, and no symbol named for it exists |

Verified as absences rather than as rules:

- neither `app/identity/principal.py` nor `authenticator.py` reads
  `stated_qualification` on any authorization path;
- `app/identity/qualification.py` does not export `Permission`, and holds no function
  from a qualification to one;
- `VERIFIED_BY_REGISTRY` is **unreachable** — an AST walk of every `return` in
  `verification_state()` yields only `NOT_STATED` and `SELF_ASSERTED`; the third name
  occurs solely in the docstring saying it is unreachable.

A reviewer stating *"Chief of Radiology, 30 years"* while holding `medauth-readonly`
is refused all three actions — two rows of §4's table are the same principal with the
same qualification and different grants.

**Competence had no executable guard, and now has two.** It was asserted in prose in
`hitl-workflow.md` §5 and nowhere else — the weakest position an absence can be in,
because absences rot silently. Added:

- `test_competence_is_not_modelled_anywhere_under_app` — walks the AST of every module
  under `app/` for any symbol named for competence. Written this way, like the
  repository's other absence guards, so a module nobody imports cannot escape it.
  Non-vacuity confirmed by injecting a `competence_score()` function: it fails.
- `test_competence_cannot_be_asserted_into_a_review` — a caller claiming competence in
  a review body gets `extra_forbidden`, not a tolerated field. There is nothing to
  ignore, which is stronger than a field that happens not to be read today.

## 6. R-86 — isolated, unchanged

| | |
|---|---|
| official evaluation gate | **BLOCKED** — production-shape failure 6/12 |
| reproducer manifest seal | intact (recomputed SHA-256 matches) |
| `gold_v1` | 2/2 spent — frozen |
| `gold_v2` | **0/1 — unspent** |
| `data/`, `eval/` | no diff against HEAD |
| `eval/reports/phase16-410-33/` | `AUTHORISATION.json`, `manifest.json` — no results |

Nothing in this phase read, spent or altered any evaluation asset. R-86's disposition
is unchanged: attributed `PROVIDER_SIDE`, blocked on evidence this repository cannot
produce.

## 7. What this baseline does not establish

- **No identity provider is selected, installed or integrated** (ADR-030). The OIDC
  adapter is implemented and tested against mocks; that is this repository's side of
  the boundary and is not the same claim.
- **No enterprise SSO is deployed.**
- **No verified credentials.** Every qualification is self-asserted.
- **No clinical validation**, and no evaluation result — the gate is `BLOCKED`.
