# Reviewer UI

Two reviewer interfaces exist in this repository. This document says what each one is,
which is authoritative, and what has and has not been decided about them.

`app/api/reviewer_ui.py` has referenced this file since it was written. It did not exist
until the SPA correctness phase, which is itself the drift this section records.

---

## 1. The two interfaces

| | Server-rendered | React SPA |
|---|---|---|
| Location | `app/api/reviewer_ui.py`, `app/api/templates/case_detail.html` | `web/` |
| Route | `GET /ui/cases/{case_id}` | `/`, `/cases/new`, `/cases/:id`, `/settings` |
| Delivery | Jinja over the existing FastAPI app. No npm, no bundler, no CDN | Vite dev server; a static build under `web/dist` |
| Scope | One case, four actions | Submit, look up, review, connection settings |
| Status | **Authoritative reference behaviour** | **Brought into verified parity; not production-ready** |

### Why a server-rendered page exists at all

The roadmap named Next.js. **R-31** names its cost: an npm supply-chain surface in a
healthcare project. A page whose job is to render a queue, a case and four buttons does
not need a package manager, a bundler or a runtime framework, and adding a thousand
transitive dependencies to display server-owned data would pay R-31's price for none of
its benefit.

That reasoning has not been retracted. It is why the Jinja page is the reference and why
the SPA's own regression tests are written against Node's built-in test runner rather
than an installed framework.

---

## 2. Which is authoritative, and what that means

**The Jinja page is the reference implementation of the reviewer safety semantics.** Where
the two disagree about what a reviewer is shown, the Jinja page is right and the SPA is
the defect. It is the one the existing API tests exercise
(`tests/api/test_reviewer_workflow.py`), including the two load-bearing ones.

The SPA is **not** a second source of truth and was never reviewed as one. A frontend
audit found that it had drifted from the server contract in ways that could not be caught
from either side alone — it declared four case states the server cannot emit and lacked
five it does; it tested `available_actions` for `'OVERRIDE'`, a token the server has never
sent, which disabled override for every reviewer; and it attributed that refusal to a
permission the code had not consulted.

Those are repaired and pinned. The repair does not promote the SPA to authoritative.

---

## 3. What neither UI is allowed to do

Both interfaces are bound by the same three rules, and the tests enforce them on both.

**Neither decides anything.** Every action posts to the API, which re-authenticates,
re-authorises in the service layer and writes the audit event. A browser that skipped
either UI entirely reaches exactly the same refusals. `HumanReviewService.record` calls
`Principal.require()` for each permission an action needs, so the client-side gating
described below is an explanation offered in advance, never an enforcement point.

**Neither renders a recommendation as a decision.** The engine's draft and the human
disposition are separate blocks with separate headings, and the draft carries the words
"AI-generated recommendation — not a decision" every time it appears. Colour alone would
not survive a monochrome print-out of a case.

**Neither hides why a case is here.** The routing explanation is rendered *above* the
recommendation, not below it, because a reviewer needs to know what question they are
being asked before they see the proposed answer. That ordering is an anti-anchoring
measure and it is the reason **R-04** is on the register. The SPA's Recommendation tab was
ordered the other way round and now is not; both orderings are asserted by test.

---

## 4. State and authority are two gates, reported separately

The server refuses a review action for two independent reasons, and the API reports them
as two independent things:

| | Field | Source | Question it answers |
|---|---|---|---|
| State | `available_actions` | `app/case/review_view.py` | Is this case open for review at all? |
| Authority | `may_review`, `may_override`, `may_finalize` | `Principal.has()`, in the route | May *this* reviewer take this action? |

`available_actions` is **not** an authorization answer. It is identical for every
reviewer looking at the same case — a read-only principal sees all three tokens on a case
in `HUMAN_REVIEW`. A client holding only that field would have to infer authority, and the
only inference available is the wrong one.

The `may_*` flags mirror what `app/api/reviewer_ui.py` has always passed to the Jinja
template (`may_override`, `may_finalize`). Adding them to `ReviewCaseResponse` gave the
SPA the same facts through the same mechanism rather than inventing a second one.

The per-action permission table, from `app/case/review.py`:

| Action | Permissions required |
|---|---|
| `ACCEPT_RECOMMENDATION` | `REVIEW_CASE`, `FINALIZE_CASE` |
| `OVERRIDE_RECOMMENDATION` | `REVIEW_CASE`, `OVERRIDE_RECOMMENDATION`, `FINALIZE_CASE` |
| `REQUEST_INFORMATION` | `REVIEW_CASE` |

The asymmetry matters: returning a case to the submitter does not dispose of it, so
request-info needs no `FINALIZE_CASE`. A UI that gated all three identically would hide an
action a plain reviewer may take.

---

## 5. Submission is not execution

`POST /cases` accepts and persists a case. **It does not run the pipeline**, and no
run/execute endpoint exists. Binding a multi-second run to the HTTP request would make
intake availability depend on a provider defect that is explicitly not ours.

A submitted case therefore sits in `RECEIVED` with no recommendation and no available
actions, indefinitely, by design. Both UIs must say so. The SPA previously navigated
straight from the submit form to a detail page showing nothing, with no explanation, so a
deliberate architecture read as a broken console.

Neither UI may add a pipeline trigger to look complete. That would be a new feature
smuggled in as a bug fix, and `test_the_console_invents_no_execution_endpoint` refuses it.

---

## 6. Running the SPA

There is **no UI service in `compose.yaml`**. The SPA is a development-time process:

```bash
cd web
npm install
npm run dev          # Vite dev server on :3100, proxying /api and /ui to :8015
```

The Vite dev server proxies `/api` and `/ui` to `http://localhost:8015`, so the browser
talks to the API same-origin and the CORS configuration is not exercised on this path.
`MEDAUTH_UI_ORIGIN` (default `http://localhost:3100`) governs the cross-origin case.

```bash
npm run build        # tsc -b, then a static bundle in web/dist
npm run typecheck    # tsc -b
npm run lint         # oxlint
npm test             # node --test, Node's built-in runner
```

`npm test` installs nothing. Node 22 strips TypeScript natively and ships `node:test`, so
the regression suite runs with zero test-framework dependencies — R-31 again.

Credentials are entered in Settings and held **in memory only** — `web/src` calls no
browser-storage API, and a reload discards them. MEDAUTH holds no model-provider
credential; the caller API key is revocable and the reviewer bearer token is the human's
own. See §8 for what that change does and does not achieve.

---

## 7. Where the SPA's guarantees are tested

The SPA's contract is checked from three directions, because no one of them is sufficient:

| Test | Asserts |
|---|---|
| `tests/api/test_spa_review_contract.py` | What the **server** emits: every lifecycle state, the exact action tokens, the permission flags against what the service enforces, the submit contract, the error envelope |
| `tests/unit/test_spa_contract_conformance.py` | That the **TypeScript matches the Python** — it reads both `web/src/**` and the server enums |
| `web/src/**/*.test.ts` | The **gating truth table**, lifecycle presentation totality, and error-envelope parsing |

The middle one is the load-bearing addition. A Python test sees the real enum and not the
console's copy of it; a TypeScript test sees the copy and not the enum, so it agrees with
whatever the frontend author typed. That is precisely how the original defect survived,
and how an attempt at these tests came to assert `available_actions: ['ACCEPT',
'OVERRIDE']` and pass against a broken UI. Frontend fixtures cannot validate a vocabulary
they invent.

---

## 8. What has NOT been decided

**Whether both interfaces survive.** This is open. The correctness phase deliberately did
not settle it: retiring the Jinja page would remove the reference the SPA was measured
against, and retiring the SPA would discard work that now passes that measurement. The
decision needs its own record, and should account for R-31, for who the reviewer console
is actually for, and for the fact that only the Jinja page has ever been reviewed as a
safety surface. **Neither is deprecated.**

**Whether the SPA is production-ready.** It is not, and nothing here claims otherwise. It
builds, type-checks, passes lint and passes its regression suite. That is a statement
about the code, not about operational readiness, and no deployment artefact for it exists.

**Where credentials should live — the persistence half is now settled.** The SPA used to
write the caller API key and the reviewer bearer token to `localStorage`. Both are
secrets, and of different kinds: the API key is long-lived, reusable and carries no
expiry, and the bearer token is what the audit attributes an accept, an override or a
request-info to. `localStorage` is script-readable, survives a browser restart and expires
nothing, so a single XSS anywhere in the console — including via a dependency — took a
long-lived backend credential and a reviewer identity together.

They are now held in memory for the life of the page. `web/src/lib/auth.ts` is the only
file that names a storage API at all, and only to *delete* the key the previous build
wrote, so a secret already sitting in a reviewer's browser is cleared on next load rather
than left there. `test_no_console_source_persists_anything_to_the_browser` asserts the rule
over the whole tree, since a property of "the console persists nothing" is not established
by a test that reads one module.

`sessionStorage` was rejected as a middle ground: equally script-readable, so it would
trade the same exposure for less inconvenience while reading, in a diff, like a fix.

**What is still open is the XSS half.** In-memory credentials do not become unreadable to
injected script — anything running in the page reaches React state too. The claim made is
the narrow one: the secrets no longer outlive the tab. The full answer is an httpOnly
`SameSite` session cookie set by the server, which needs a session endpoint, CSRF
protection and server-side session state that MEDAUTH does not have. That is a backend
decision and is not half-built in the console.

The cost taken deliberately: a reload empties the fields and the reviewer re-enters them.

**Whether a validation error should carry a correlation id.** Domain errors carry
`request_id` in the body; FastAPI's default `RequestValidationError` handler produces a
422 with neither a `request_id` field nor the `x-medauth-request-id` header. The console
degrades correctly — it renders the field-level messages and omits the id line — but a
reviewer cannot quote an id for a rejected submission.
