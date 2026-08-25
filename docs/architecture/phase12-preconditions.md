# Phase 12 Preconditions

**Phase 12 is real-model activation.** Everything below was closed before it, because
each is something that gets harder to fix once inference is in the loop.

An independent audit on 2026-08-25 returned **E — MULTIPLE_BLOCKERS**. This records
what it found and what closed it.

---

## What the audit found, and what it cost to miss

| | finding | status |
|---|---|---|
| **P0-1** | CI aborted at collection on any clean checkout | closed |
| **P0-2** | the production gate lived in one script | closed |
| **P1-1** | no concrete `ModelGateway` existed | closed |
| **P1-2** | `FakeGateway` did not satisfy the protocol | closed |
| **P1-3** | tests were outside the mypy scope | closed |
| **P1-4** | mutation evidence was manual and unrepeatable | closed |
| **P2** | roadmap, CLAUDE.md and the claims ledger were stale | closed |

### P0-1 — the suite was green on one machine

`data/cms/*.md` is deliberately uncommitted (AMA-copyright descriptors, ADR-003).
`tests/support_slice.py` read it **at module import**, so collection raised
`FileNotFoundError` and the whole run aborted. 824 tests passed here and zero ran
anywhere else.

Fixed by making the fixture corpus lazy, adding a `corpus` marker, and skipping with
a reason that names the missing files and the command that gets them. **No substitute
corpus.** A test that verified a quote against text CMS never published would pass
while checking nothing, which is worse than skipping.

```
clean checkout:  542 passed, 53 skipped, 0 failed
corpus present:  853 passed
```

### P0-2 — the gate was advice, not a gate

`ProductionGate` was consulted only by `scripts/run_first_slice.py`. Anyone
constructing a `SliceRunner` directly got no check — which is precisely the
"conditional on a caller remembering" that the gate exists to eliminate.

Now enforced in `SliceRunner.__init__`: at **construction**, so a blocked runner
cannot be built, held, and invoked later against a gate that was READY when it was
made. `gate` has no default, a truthy stand-in is a `TypeError`, and a gate READY for
a *different* policy is refused.

Removing an unreachable redundant check was part of this. It was `# pragma: no
cover` and it masked the mutation that removed the real one — **redundancy that hides
a regression is worse than none.**

### P1-1/2/3 — the seam had no implementation and the double had drifted

`app/llm/firewall_gateway.py` implements the protocol and does one thing: turn
transport facts into `GatewayOutcome` values. No business logic — what a blocked call
means for a case is decided in `app/graph/slice.py`, because that is a decision about
the case.

`FakeGateway` had the wrong parameter name and no `model_for`, so
`isinstance(FakeGateway(), ModelGateway)` was `False` for a whole phase. It worked
only because callers passed positionally. Both are now checked statically, under a
documented mypy scope covering the boundary doubles.

### P1-4 — and what automating it immediately found

`scripts/mutation_guard.py`: 11 named mutations, applied, tested, reverted, with the
working tree verified unchanged. Two things surfaced on the first run that a manual
pass had not:

**A dead mutation.** Adding 403 to `_RETRYABLE` changed nothing — the terminal 403
branch runs before that set is consulted. Mutating dead code proves nothing, and the
harness reported SURVIVED until the anchor was corrected.

**A genuinely undefended rule.** Removing the `REVIEW_REQUIRED` branch from `decide()`
still produced `HUMAN_REVIEW`, so the safety outcome held — but the rule silently
became **13** instead of **12**, and nothing noticed. Those are different diagnoses:
12 is a corpus problem fixed by OD-19 review, 13 is a wiring problem fixed by fixing
the caller. Collapsed, a misconfigured deployment is indistinguishable from an
honestly unreviewed corpus. A test now pins the distinction.

---

## The Phase 12 gate

| | |
|---|---|
| CI passes from a clean checkout | ✅ |
| corpus tests visibly classified | ✅ 53 skips, each with a reason |
| gate enforced in `SliceRunner` | ✅ |
| direct construction cannot bypass | ✅ 4 mutations caught |
| concrete `ModelGateway` | ✅ routes through the firewall |
| `FakeGateway` conforms | ✅ `isinstance` True, statically checked |
| gateway contract tests | ✅ 19, over `MockTransport` |
| mutation harness in CI | ✅ 11/11 |
| invariants preserved | ✅ boundaries 12/12, security 260 |
| gold_v1 unchanged | ✅ `ca990b80…` |
| FOCUS-001 accepted | ✅ `LEAVE_C03_NOT_ADJUDICABLE` |
| retrieval benchmark | ✅ still `NOT_READY` |
| **a model has been called** | ❌ **never, in any phase** |

## What Phase 12 must not assume

`FirewallGateway` is contract-tested against `httpx.MockTransport`. That proves the
**seam** behaves: a 403 classifies and is attempted once, a 503 fails closed, a
malformed payload becomes `SCHEMA_INVALID` rather than a guess.

It proves **nothing** about a real provider. `MODEL_REASONING_QUALITY_NOT_YET_EVALUATED`
stands, and the first thing Phase 12 should do is discover which of these
classifications a real firewall actually exercises.
