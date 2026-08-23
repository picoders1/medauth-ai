# ADR-024 — Fail-Closed Policy Semantics and a Separate Coverage Layer

**Status:** Accepted (2026-08-23)
**Amends:** ADR-010 (deterministic decision engine), ADR-023 (policy logic as data),
ADR-022 (coverage policy source). **Resolves:** R-59, OD-24.
**Opens:** OD-26, OD-27.

---

## Context

Two problems, one principle: **the absence of a fact must produce no decision, never
a default fact.**

**R-59.** ADR-023 gave policies a way to state their logic and `decide()` a rule
refusing a `REVIEW_REQUIRED` one. But `decide()` took `logic: PolicyLogic | None =
None` and, given `None`, built an assumed conjunction and executed it. A caller who
never consulted the logic inventory got a silent adjudication under a rule shape
nobody had established — for four of eight policy versions, ones the inventory
explicitly flags. The record stated a doubt the runtime did not act on.

**The missing layer.** ADR-022 decided to adopt NCDs and was never implemented. The
corpus was statutory regulation only, and a prior-authorization system reasons over
coverage determinations.

The two meet at one point: a real NCD arrives with no transcribed criteria, so it
lands on `NO_CRITERIA` and cannot adjudicate. **The fail-closed gate is what makes
ingesting a criteria-free coverage layer safe.** They had to land together, in that
order.

## Decisions

### 1. The `assumed_conjunction()` fallback is deleted, not defaulted

`semantics: PolicySemantics` is required and has no default. `assumed_conjunction()`
still exists — the inventory loader needs it to build a tree — but what it returns is
a bare `PolicyLogic`, and a bare `PolicyLogic` is no longer something `decide()`
accepts.

Deleting rather than defaulting is the substance. It converts the fix from *a
default someone can change back* into *a code path that must be re-added* — a
visible addition in a diff.

`decide()` remains total and never raises: omitting the argument is a `TypeError` at
call time, caught by `mypy --strict` and by every test. A signature error, not a
runtime failure on data.

### 2. Two failure causes, never collapsed

`POLICY_SEMANTICS_UNRESOLVED` (rule 12) means the **corpus** is unqualified, fixed by
OD-19 review. `POLICY_SEMANTICS_UNVERIFIED` (rule 13) means the **runtime** cannot
establish that what it holds is verified, fixed by fixing the caller.

Both route to `HUMAN_REVIEW`; both fire before any denial *and* before any approval.
Collapsing them would make a misconfigured deployment indistinguishable from an
honestly-unreviewed corpus, in the audit trail of all places.

### 3. The invariant is a construction rule, not a check

`PolicySemantics` is built only through classmethods, each **demoting** to
`POLICY_SEMANTICS_UNKNOWN` when an executable status arrives without both a matching
`PolicyLogic` and an `Attestation`. There is no validation anyone can forget to call:
the type cannot represent an unattested assumption. Demotion rather than a raise
keeps a misconfiguration routing to a human rather than raising inside adjudication.

### 4. Production and replay are separated by value, not by convention

gold_v1's labels were computed under an assumed conjunction. Reproducing them
requires asserting an assumption production refuses, so the assertion is *named*
(`eval/replay.py`), *stamped* (`GOLD_V1_REPLAY`) and *refused* on two independent
grounds — origin and digest. It lives outside `app/`, enforced by two AST rules.

The alternative considered and rejected was a `replay: bool` flag on `decide()`: a
boolean on the production entry point, defensible by nobody, and one character away
from reinstating R-59.

**Honest limit, recorded:** a determined in-process caller can defeat an in-process
check. The claim is narrower and true — the accidental path fails closed, and the
deliberate path is visible in the recommendation, the audit row and in grep.

### 5. An undated NCD is stored and never resolvable

The CMS Coverage API publishes prose where a date belongs in 14 of 24 records
sampled. Such a version is stored, indexed, provenance-preserved and **unreachable
by date of service**.

Rejected: a **sentinel** date, which converts "we do not know when this took effect"
into "it has always been in effect" — the widest-applicability direction — and would
print a fabricated date to a reviewer. The dead `or date.min` in `parse.py` was
deleted in the same change.

Rejected: **rejecting at acquisition**, which deletes the evidence that the fact is
missing, and with a curated set of 11 would quietly turn "exclude the undated" into
"select the datable", biasing the sample without saying so.

### 6. Ends may be inferred; starts never are

Inferring an end narrows applicability; inferring a start widens it. A dated version
runs until the day before the next dated one, labelled `DERIVED_FROM_SEQUENCE` so a
reviewer is never shown an inferred date as a published one.

`effective_end_date` is never a version end. For NCD 30.4 it is identical across all
three versions and precedes their effective dates — document-level retirement, not a
window. It may close a window, never open one; where it precedes the newest start,
the document is **refused**.

### 7. Version history is never inferred from probing

A non-existent version returns **200 with empty data**, not 404. So enumeration
comes from `/ncd/other-versions`, and `VersionDataStatus.NO_VERSION_DATA` exists so
an empty response is never read as `END_OF_HISTORY`.

### 8. NCD code linkage is curated, and cannot be otherwise

The NCD record has **no procedure-code field** — 19 fields, none of them codes,
verified by probe. Linkage stays `HUMAN_CURATED`. Nothing may claim CMS supplies it.

### 9. Regulation and coverage never share a retrieval scope

`ResolutionResult.version_ids` is deleted. It flattened every resolved version into
one list, and one ANN query over both layers would rank a statutory chunk against a
coverage-determination chunk on cosine distance. `scope_for(document_type)`
partitions by each version's *actual* type, so a scope whose ids disagree with its
label is unconstructible.

### 10. Coverage status is not a recommendation

`COVERED · NOT_COVERED · CONDITIONAL · NOT_ESTABLISHED · NOT_APPLICABLE · UNKNOWN`.
No member names an outcome, and a test asserts it. Two conflations are refused
structurally: **absence of an NCD is `NOT_ESTABLISHED`, never `NOT_COVERED`**, and
satisfying a regulation is not coverage.

## Consequences

**Half the corpus is non-adjudicable.** Three of eight policy versions execute in
production; 78 of 156 gold cases and 111 of 222 synthetic cases are blocked. That is
the finding, not a bug: it was always true that nobody had read those policies.

**gold_v1 is byte-identical and no gold_v2 was created.** All 222 labels reproduce
through the replay path; regeneration was diffed and is byte-identical.

**Acquisition coverage is 10 of 11 selected NCDs**, 19 versions, 16 temporally
resolvable. One refusal, recorded. This is not "the CMS NCD corpus" and must never be
described as such.

**NCDs cannot adjudicate anything.** No criteria are transcribed from them, so they
are `NO_CRITERIA` and route to human review. They are corpus and evidence.

**Negative.** The evaluation runners still scope by version id without a type
partition (R-62). Coverage status has no reviewer-recorded values, so every governing
NCD resolves `UNKNOWN` (OD-26). Whether `REVIEW_REQUIRED` policies should be declared
or reviewed remains OD-19.

## Rejected alternatives, recorded

- **`replay: bool` on `decide()`** — see §4.
- **A fourth `PolicyTruth` member for UNKNOWN** — rule 5a returns before `evaluate()`
  runs, so it would require fabricating a `PolicyEvaluation`, inventing
  `unknown_criteria` for a policy never evaluated. Fabricated provenance in the exact
  field a reviewer checks.
- **Separate coverage tables** — they do not give scope separation (the caller would
  need a merge, and the merge is where crossing happens), and they force a second
  copy of `in_force_on()`, the precise defect `app/policy/temporal.py` exists to
  prevent.
- **Classifying NCD coverage status from `indications_limitations` prose** — the
  unreviewed inference this project refuses everywhere else.
