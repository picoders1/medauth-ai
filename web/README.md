# MEDAUTH reviewer console

A React SPA over `/api/v1`. See
[docs/architecture/reviewer-ui.md](../docs/architecture/reviewer-ui.md) for what this is,
what the server-rendered reviewer page at `/ui/cases/{id}` is, which of the two is
authoritative, and what has deliberately not been decided about them.

**This console is not production-ready**, and building successfully is not a claim that it
is. No deployment artefact for it exists and `compose.yaml` defines no UI service.

## Running it

```bash
npm install
npm run dev          # Vite on :3100, proxying /api and /ui to the API on :8015
```

The API must be running (`docker compose up -d --build`, then `uv run alembic upgrade
head`). The dev server proxies same-origin, so the browser never makes a cross-origin
request on this path.

Open Settings first. Two credentials, deliberately separate (OD-43):

- **Caller API key** (`x-api-key`) — the integrating *system*. Decides which cases are
  visible. Required for every request.
- **Reviewer bearer token** (`Authorization: Bearer`) — the authenticated *person*.
  Required only for the review view and the three review actions.

An API key can never stand in for a person.

**Both are held in memory for the life of the page and are written nowhere.** A reload,
a Clear, or closing the tab discards them and you enter them again — that re-entry is the
intended cost, not a rough edge. An earlier build persisted both to `localStorage`, where
any script on the origin can read them and where they survive a browser restart; §8 of the
architecture document records what that fixed and what it did not.

## Commands

```bash
npm run build        # tsc -b, then a static bundle in dist/
npm run typecheck    # tsc -b
npm run lint         # oxlint
npm test             # node --test 'src/**/*.test.ts'
```

`npm test` installs nothing. Node 22 strips TypeScript natively and ships `node:test`, so
the regression suite runs with **zero test-framework dependencies**. That is deliberate:
**R-31** names the npm supply-chain surface as a risk in this project, and a truth table
does not justify paying it.

One lint warning is accepted: `react(set-state-in-effect)` in `pages/CaseDetail.tsx`,
where the effect loads a case from the API and setting state is the point of it. The two
in `lib/auth.ts` and `pages/Settings.tsx` went away with the credential change — the
effects existed to rehydrate from storage and to mirror it.

## What the console must not do

It decides nothing. Every action posts to the API, which re-authenticates, re-authorises
in the service layer and writes the audit event; a browser that skipped this UI reaches
exactly the same refusals. It never renders the engine's draft as a decision, and it never
shows the draft above the reason the case was routed to a person (R-04).

Two gates are read from the server and never inferred here: `available_actions` says what
the case's **state** permits, and `may_review` / `may_override` / `may_finalize` say what
**this reviewer** may do. They are different questions and the UI must not collapse them.

## Layout

```
src/
  api/client.ts        typed client for /api/v1; two identities, one error envelope
  lib/auth.ts          the two credentials, in memory only - never persisted
  lib/types.ts         mirrors of server vocabularies - see the conformance test below
  lib/lifecycle.ts     the case-state presentation table, total over CaseState
  lib/actions.ts       action gating: state gate ∧ authority gate, both server-reported
  components/          status and outcome chips
  pages/               Dashboard, NewCase, CaseDetail (+ Review/Recommendation tabs), Settings
```

## Tests

`src/**/*.test.ts` covers the gating truth table, lifecycle totality and error parsing.

It cannot cover whether the vocabularies in `lib/types.ts` match the server — a frontend
fixture only asserts what the frontend author typed, which is how the original drift
survived. That half lives in Python and reads both sources:

- `tests/unit/test_spa_contract_conformance.py` — the TypeScript against the server enums
- `tests/api/test_spa_review_contract.py` — what the server actually emits

Change a vocabulary on either side and the Python tests fail. Run them with
`uv run pytest -m "unit or api"` from the repository root.
