# 42 CFR 410.32(b)(3) — Transcription and the Question It Leaves

**Status: `SOURCE_VERIFIED` / `QUALIFIED_REVIEW_PENDING`.**

Those are two different claims and this page keeps them apart. Phase 7 established
the first mechanically. Only a qualified reader can establish the second.

---

## What the source says

Retrieved from `data/cms/CFR-410_32-2026-08-13.md` — the eCFR document already in
the corpus, sha256 `d87f3242f432…`, source
`https://www.ecfr.gov/current/title-42/section-410.32`. No summary, no secondary
site, no model paraphrase.

> **(3) Levels of supervision.** Except where otherwise indicated, all diagnostic
> x-ray and other diagnostic tests subject to this provision and payable under the
> physician fee schedule **must be furnished under at least a general level of
> supervision** as defined in paragraph (b)(3)(i) of this section. In addition,
> **some of these tests also require either direct or personal supervision** as
> defined in paragraph (b)(3)(ii) or (iii)… When direct or personal supervision is
> required, supervision at the specified level is required throughout the
> performance of the test.

With definitions in `(i)` general, `(ii)` direct, `(iii)` personal, and an exception
in `(b)(4)` letting a certified RRA or RPA furnish under *direct* supervision where
*personal* would otherwise be required.

## What was transcribed

| criterion | type | text |
|---|---|---|
| **C07** | `REQUIRED` | *"must be furnished under at least a general level of supervision"* |
| **C08** | `EXCEPTION_CONDITION` | *"may be furnished under a direct level of physician supervision"* (the (b)(4) RRA/RPA route) |

Both span-verified. The gate was proven to reject all four corruption modes — wrong
text, wrong section, wrong version, and a **malformed record**, which it had not
caught before: an unknown key was silently ignored, so a typo in
`normalized_interpretation` would have emptied a hand-written field without trace.
The loader now refuses unknown keys.

**The definitions in (i)–(iii) were deliberately NOT transcribed.** Nothing can
satisfy or fail a definition. They are already chunked and retrievable within this
policy version, which is what makes them usable as evidence — which is what C03
actually needs them for.

## Why this does not close C03

C03 says a test must be furnished under **"the appropriate level of supervision"**.
(b)(3) supplies two of the three things needed to check that:

| | in the regulation? |
|---|---|
| the floor — at least general supervision | **yes** → C07 |
| what each level means | **yes** → (b)(3)(i)–(iii), retrievable |
| **which level applies to a given test** | **no** |

The last is set by the **physician fee schedule's supervision indicator**, published
separately from 42 CFR and absent from this corpus. No amount of transcribing this
regulation reaches it.

So the dependency moves from `UNRESOLVED` to
**`PARTIALLY_RESOLVABLE_FROM_SOURCE`** — and `permits_adjudication` returns `False`
for that, deliberately. Transcription is progress; it is not permission. Treating it
as permission would let engineering close a review question by doing engineering
work.

## The question a reviewer must answer

`data/review/focused_review.md`, item **FOCUS-001**. One question, four options:

- **`NARROW_C03_TO_BASELINE`** — restate C03 as the floor, which *is* determinable,
  and record the per-test level as out of scope
- **`SPLIT_C03`** — a baseline criterion plus a separate escalation criterion marked
  not determinable from this corpus
- **`LEAVE_C03_NOT_ADJUDICABLE`** — 410.32 stays inadmissible until that data exists
- **`OTHER`**

## A workflow gap this exposed

Transcribing (b)(3) reclassified it from `REQUIRES_HUMAN_REVIEW` to
`REPRESENTED_CRITERION`, which **removed it from the OD-19 queue while the
dependency it blocks remained open**. The question changed from *"should this be a
criterion?"* to *"does the criterion drawn from it make C03 adjudicable?"*, and that
second question had nowhere to live.

Transcription quietly retiring a review item is precisely the kind of progress that
leaves a gap where nobody looks. The focused review package exists to hold it, and
`test_the_focused_review_owns_the_b3_question` guards it.

## What is not claimed

- **Not** that C07 is the right criterion — that is the reviewer's call.
- **Not** that C03 is now adjudicable — the admissibility gate still refuses it.
- **Not** clinical correctness of any reading. `SOURCE_VERIFIED` is an engineering
  fact about where text sits, and nothing more.
