# ADR-025 — Policy Identity, Coverage Substantiation, and the Slice Admissibility Test

**Status:** Accepted (2026-08-23)
**Amends:** ADR-004 (policy resolution), ADR-022 (coverage policy source),
ADR-024 (fail-closed semantics). **Resolves:** R-62. **Advances:** OD-26, OD-27.
**Opens:** OD-28.

---

## Context

Phase 5 left three things unfinished, and they turned out to share a shape.

**R-62.** The evaluation runners scoped retrieval by version id alone. That was an
instance of a wider problem: policy *type* was metadata everywhere except the
database's unique constraint, so `(policy_id, version)` — the key used by the
linkage YAML, the criteria inventory and the gold cases — could not tell a
regulation from a coverage determination.

**OD-26.** Every acquired NCD resolved to `UNKNOWN` because nothing recorded what
any determination establishes. The layer was safe and empty.

**OD-27.** NCDs have no procedure-code field, so they were unreachable by
resolution.

Each is a case of the same question: *on whose authority is this true?* Identity
answers "which thing is this"; coverage status and code linkage answer "who says
so". Getting either wrong produces the same failure — a claim that reads as
established and is not.

## Decisions

### 1. Policy type participates in identity

`PolicyIdentity(policy_type, policy_id, version)` in `app/core/identity.py`, with
type as the **first** component so a partial key cannot match a full one. There is
no constructor that omits it.

A `policy_id` must carry a type-consistent prefix (`42 CFR `, `NCD `, `L`, `A`),
enforced rather than assumed, so a bare id in a log line or a citation says which
layer of authority it names. `infer()` recovers the type from the prefix for
artefacts that predate this, and **refuses an unprefixed id rather than guessing**.

`PolicyType` lives in `app.core` because identity is domain vocabulary and
`app.decision` may not import `app.policy`. `DocumentType` is an alias — the same
object, not a parallel enum that could drift.

### 2. Three levels of link authority, and review as a separate axis

`SOURCE_STATED` (authoritative) · `HUMAN_CURATED` (admissible, not authoritative) ·
`ENGINEERING_INFERRED` (**refused by production resolution**).

`admissible_in_production` and `is_authoritative` answer different questions.
Refusing `HUMAN_CURATED` as well would leave the corpus with no resolvable link at
all — disabling the system rather than making it safer. Admitting
`ENGINEERING_INFERRED` would let applicability rest on similarity, which ADR-004
exists to prevent.

`LinkReviewStatus` is its own column: verifying a curated link confirms a reading, it
does not make the reviewer the source.

### 3. Coverage status is recorded with evidence, never derived

`StatusOrigin`: `SOURCE_STATED` · `HUMAN_REVIEWED` · `ENGINEERING_DERIVED` ·
`UNKNOWN`. Only the first is authoritative; the third is **inadmissible as a
coverage conclusion by construction** — `establishes` returns `UNKNOWN` for it
whatever `status` says.

`determination_status()` demotes to `UNKNOWN` when a substantive status has no
located evidence, when `SOURCE_STATED` carries no quote, or when `HUMAN_REVIEWED`
carries no signature. The function takes no `title`, `code`, `similarity` or
`model_output`, and a test asserts their absence: the moment something accepts a
title and returns a status, the inference has been made.

### 4. Admissibility is a re-runnable test, not a written verdict

`scripts/assess_slice_admissibility.py` checks seven conditions against committed
artefacts and reports the conjunction. A readiness claim in a document goes stale
silently; a script re-run after a reviewer closes a blocker changes its answer
without anyone editing prose.

### 5. Review decisions are versioned; history is never mutated

`review_v1`, `review_v2`, … A version may supersede only an earlier one and only with
a recorded reason. Every decision is signed and reasoned. Nothing *applies* a
decision — `app/review/impact.py` exists so the size of that work is visible before
anyone starts.

### 6. Abstention states exist; thresholds do not

Eight structural reasons, each carrying a remedy. `ScoredGate` is `UNCALIBRATED` and
records it explicitly: "there is no gate" and "the gate passed" are different claims,
and an audit row that cannot tell them apart would let an uncalibrated system read as
a confident one.

### 7. The model gateway is declared before it is needed

`app/llm/gateway.py`. Schema-constrained calls only; no `stream` field, no free-text
field, evidence separate from instructions. A `403` is never retried. Roles, not
model names — Phase 0's finding is a claim about **output safety, not reasoning
quality**.

## Consequences

**A false negative was found and fixed, and it cost coverage.** The logic inventory
matched `any of the following` but not `one of the following` — the commonest way a
regulation writes a disjunction. 42 CFR 410.61(b) scanned clean because of it and was
classified `ASSUMED_CONJUNCTION` on that basis. Found by reading the regulation, not
by the scan.

| | before | after |
|---|---|---|
| adjudicable policy versions | 3 of 8 | **1 of 8** |
| adjudicable gold cases | 78 of 156 | **26 of 156** |

The corpus did not get worse; the record of it got more accurate.

**No slice is admissible.** The nearest, `REGULATION:42 CFR 410.32:2026-08-13`, fails
exactly one condition: C03 depends on the untranscribed `(b)(3)` (R-51). That is the
single blocker, and it reaches 23 of 156 gold cases.

**The coverage layer remains substantively empty.** 19 NCD versions await status
review; none is recorded. That is by design — inferring one is the thing being
refused — and it means the layer establishes nothing yet.

**Negative.** `ENGINEERING_INFERRED` links no longer resolve, so 42 CFR 410.61 is
unreachable in production; the retrieval sets were authored against those links and
would need `admit_engineering_inferred_links` set explicitly to re-run (OD-28).

## Rejected alternatives, recorded

- **Deriving coverage status from `indications_limitations` prose.** The unreviewed
  inference this project refuses everywhere else, applied to the layer where it
  would do the most damage.
- **A `policy_type` field that is merely required.** Required is not the same as
  *part of the key*: a required field can still be ignored by a dict that keys on
  something else, which is exactly what R-62 was.
- **Declaring 42 CFR 410.61's logic to manufacture an admissible slice.** Its
  disjunctions are over practitioner types that are not transcribed as criteria, so
  declaring it would mean either referencing criteria that do not exist or asserting
  a conjunction the text does not support.
- **Refusing `HUMAN_CURATED` links.** Safer-sounding and actually disabling: the
  corpus would resolve nothing at all.
