# NCD Coverage Status Model

**A status exists only when something says so, and the record says which something.**

`app/coverage/status.py`.

---

## The gap this closes

Phase 5 built coverage *resolution* — which determination governs a date of service
— and stopped. Every governing NCD resolved to `UNKNOWN` because nothing recorded
what any determination establishes. Safe, and empty (OD-26, R-61).

Filling it is easy to do badly. A status could be derived from the title, from
procedure similarity, from code linkage, from a semantic match, from the absence of
exclusionary language, or from a model's reading of the prose. **Every one of those
is an unreviewed inference**, and a coverage conclusion is the last place one should
be allowed to hide.

## Four origins

| origin | means | authoritative | admissible |
|---|---|---|---|
| `SOURCE_STATED` | the determination's own text states it, quoted and located | **yes** | yes |
| `HUMAN_REVIEWED` | a qualified reviewer read it and recorded a judgement | no | yes, once `VERIFIED` |
| `ENGINEERING_DERIVED` | an engineer's reading | no | **no** |
| `UNKNOWN` | nobody has said anything | no | no |

**Only the source speaking for itself is authoritative.** A reviewer confirms a
reading of the source; they do not become the source. That is the same distinction
`LinkProvenance` draws for code linkage, and it exists for the same reason.

`ENGINEERING_DERIVED` is inadmissible **by construction** — `establishes` returns
`UNKNOWN` for it regardless of what `status` says. It exists to seed a review queue,
not to answer a coverage question.

## Evidence, or demotion

`determination_status()` demotes to `UNKNOWN`, with the reason recorded, in three
cases:

1. **A substantive status with no evidence.** `COVERED`, `NOT_COVERED` and
   `CONDITIONAL` are claims about what a document says; without a located quote
   there is nothing to check them against.
2. **`SOURCE_STATED` with no evidence.** The strongest available claim on the
   weakest available basis, and it reads as authoritative.
3. **`HUMAN_REVIEWED` with no reviewer identity and rationale.** An unsigned
   judgement is not a reviewed one.

Demotion rather than a raise, for the same reason as `PolicySemantics`: a malformed
record routes a case to a human instead of raising inside a decision path.

`CoverageEvidence` carries a section, a quote and character offsets, and
`locates_in()` checks the quote is genuinely where the record says — the same span
contract the criteria transcriptions live under (ADR-009). **A status whose evidence
cannot be located is not evidence, it is a summary.**

## What the API cannot be asked

`determination_status()` takes no `title`, no `code`, no `similarity`, no
`model_output`. A test asserts those parameters are absent, because the absence of an
API is easy to erode: the moment something accepts a title and returns a status, the
inference has been made.

## Current state

**19 NCD versions await status review. 0 have one.** Every acquired determination
establishes `UNKNOWN`, which is what the system reports — not a gap to be filled by
inference.

The review queue offers a candidate for 8 of 19, from a narrow phrase scan
(`is not covered`, `covered only when`). 11 get nothing, because they match no
unambiguous phrase or match conflicting ones. **A scan that always produces a
candidate is a classifier, not a starting point**, and a test asserts some
determinations come back empty.
