# FOCUS-001 — Reviewer Packet

**One question. It requires a qualified reader of coverage regulation, and there is
no engineering answer to it.**

Nothing in this packet recommends an outcome. The options are listed in the order
they appear in the decision record, and their consequences are stated so you can see
what each costs — not so that the cheapest one looks best. **Choosing the cheapest
reading of a regulation because it needs no gold_v2 would be the wrong reason.**

Machine-readable: `data/review/focus_001_decision.json`.

---

## 1. The question

> Criterion C03 says a test must be furnished under 'the appropriate level of supervision'. (b)(3) sets a floor of at least general supervision and says some tests require direct or personal instead - but WHICH tests is set by the physician fee schedule's supervision indicator, which is not in 42 CFR and is not in this corpus.
> 
> Can C03 be adjudicated from this regulation alone?

## 2. The authoritative source

42 CFR 410.32(b)(3), from `data/cms/CFR-410_32-2026-08-13.md`
(sha256 `d87f3242f432…`, eCFR, revision 2026-08-13).

> (3) Levels of supervision. Except where otherwise indicated, all diagnostic x-ray and other diagnostic tests subject to this provision and payable under the physician fee schedule must be furnished under at least a general level of supervision as defined in paragraph (b)(3)(i) of this section. In addition, some of these tests also require either direct or personal supervision as defined in paragraph (b)(3)(ii) or (iii) of this section, respectively. When direct or personal supervision is required, supervision at the specified level is required throughout the performance of the test.

## 3. Criterion C03, as currently written

| | |
|---|---|
| id | `42_CFR_410_32_2026_08_13_C03` |
| type | REQUIRED |
| authoritative text | *"must be furnished under the appropriate level of supervision"* |
| section | Paragraph (b) |

> General, direct or personal supervision as designated for the test. Services furnished without it are not reasonable and necessary.

## 4. Criterion C07 — the supervision floor (transcribed in Phase 7)

| | |
|---|---|
| id | `42_CFR_410_32_2026_08_13_C07` |
| type | REQUIRED |
| authoritative text | *"must be furnished under at least a general level of supervision"* |

> Every diagnostic test subject to this provision and payable under the physician fee schedule must be furnished under at least general supervision, as defined in 42 CFR 410.32(b)(3)(i). This is the FLOOR, not the applicable level: some tests require direct or personal supervision instead, and which tests those are is determined by the physician fee schedule's supervision indicator, which is not part of this regulation.

## 5. Criterion C08 — the (b)(4) exception

| | |
|---|---|
| id | `42_CFR_410_32_2026_08_13_C08` |
| type | EXCEPTION_CONDITION |
| authoritative text | *"may be furnished under a direct level of physician supervision"* |

> (4) Supervision requirement for RRA or RPA. Diagnostic tests that are performed by a registered radiologist assistant (RRA) who is certified and registered by the American Registry of Radiologic Technologists or a radiology practitioner assistant (RPA) who is certified by the Certification Board for Radiology Practitioner Assistants, and that would otherwise require a personal level of supervision as specified in paragraph (b)(3) of this section, may be furnished under a direct level of physician supervision to the extent permitted by state law and state scope of practice regulations.
> 
> Portable x-ray services
> 
> (c) Portable x-ray services. Portable x-ray services furnished in a place of resid

## 6. The three supervision levels, as defined

**General — (b)(3)(i)**

> (i) General supervision means the procedure is furnished under the physician's overall direction and control, but the physician's presence is not required during the performance of the procedure. Under general supervision, the training of the nonphysician personnel who actually perform the diagnostic procedure and the maintenance of the necessary equipment and supplies are the continuing responsibility of the physician.

**Direct — (b)(3)(ii)**

> (ii) Direct supervision in the office setting means that the physician (or other supervising practitioner) must be present in the office suite and immediately available to furnish assistance and direction throughout the performance of the service. It does not mean that the physician (or other supervising practitioner) must be present in the room when the service is performed. The presence of the physician (or other practitioner) required for direct supervision may include virtual presence through audio/video real-time communications technology (excluding audio-only) for services without a 010 or 090 global surgery indicator.

**Personal — (b)(3)(iii)**

> (iii) Personal supervision means a physician must be in attendance in the room during the performance of the procedure.

## 7. What is missing, and why it cannot be supplied by engineering

(b)(3) sets a floor and says *"some of these tests also require either direct or
personal supervision"*. **It does not say which tests.**

That is set by the **physician fee schedule supervision indicator**, published
separately from 42 CFR. It is not in this corpus, and it is not in the regulation at
any depth — so no amount of further transcription reaches it.

This is why C03's dependency is recorded as `PARTIALLY_RESOLVABLE_FROM_SOURCE`
rather than resolved, and why the question is yours rather than ours.

## 8. What is affected

| | |
|---|---|
| gold_v1 cases referencing C03 | **23** of 156 |
| policy version | `42 CFR 410.32` rev 2026-08-13 |
| other conditions blocking this policy | none — this decision is the only one |

gold_v1 is frozen and **will not be modified** by any answer. Where a decision would
invalidate labels, a `gold_v2` is prepared as a separate, deliberate act.

## 9. The options

- `NARROW_C03_TO_BASELINE` — C03 is restated as the floor already transcribed in C07 (at least general supervision). The per-test level is recorded as out of scope for this corpus.
- `SPLIT_C03` — C03 becomes two criteria: the baseline (adjudicable) and the escalation to direct or personal supervision (not determinable from this corpus, and marked so).
- `LEAVE_C03_NOT_ADJUDICABLE` — C03 is unchanged and remains not independently adjudicable.
- `OTHER` — Determined by the reviewer's stated reading.

## 10. Consequences

| outcome | 410.32 admissible after | gold_v2 required | gold cases affected |
|---|---|---|---|
| `NARROW_C03_TO_BASELINE` | yes | yes | 23 |
| `SPLIT_C03` | no | yes | 23 |
| `LEAVE_C03_NOT_ADJUDICABLE` | no | no | 0 |
| `OTHER` | no | no | 0 |

Detail for each, including what it changes about the evidence set and what it leaves
blocked, is in [FOCUS-001-impact.md](FOCUS-001-impact.md).

---

## Recording your answer

`data/review/focus_001_decision.json`. Required: `reviewer_identity`,
`reviewer_qualification`, `reviewer_decision` (one of the four), and
`reviewer_rationale`.

Submission sets the status to `SUBMITTED`, **not** `ACCEPTED` — acceptance is a
separate act naming who accepted it, so that no single step opens the gate. Until a
decision is `ACCEPTED`, production stays blocked and the admissibility gate keeps
reporting `BLOCKED`.

**If none of the four options fits, use `OTHER` and state the reading.** Its impact
is deliberately not precomputed: modelling an unstated reading would mean inventing
one, and the placeholder would then be mistaken for an analysis.
