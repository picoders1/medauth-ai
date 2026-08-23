# Focused Review — the next decision

**1 question at priority 1.** Answering it is what stands between `REGULATION:42 CFR 410.32:2026-08-13` and an admissible first AI vertical slice.

Priority 2 holds 4 supporting provisions. Priority 3 is the existing OD-19 queue of 244 provisions, unchanged and not urgent for this decision.

Machine-readable: `data/review/focused_review.jsonl`. Decision fields are empty and nothing in the pipeline fills them.

## FOCUS-001 — priority 1

**42 CFR 410.32 (b)(3)** (version 2026-08-13, section *Paragraph (b)*, page 1)

> Levels of supervision. Except where otherwise indicated, all diagnostic x-ray and other diagnostic tests subject to this provision and payable under the physician fee schedule must be furnished under at least a general level of supervision as defined in paragraph (b)(3)(i) of this section. In addition, some of these tests also require either direct or personal supervision as defined in paragraph (

*Why this is asked:* This is the single decision standing between 42 CFR 410.32 and an admissible first AI vertical slice. Every other admissibility condition for that policy passes. Phase 7 transcribed (b)(3) and span-verified it as criterion C07 (the baseline: at least general supervision), so the question is no longer whether the provision should be transcribed - it is whether that transcription makes C03 adjudicable.

**Question**

Criterion C03 says a test must be furnished under 'the appropriate level of supervision'. (b)(3) sets a floor of at least general supervision and says some tests require direct or personal instead - but WHICH tests is set by the physician fee schedule's supervision indicator, which is not in 42 CFR and is not in this corpus.

Can C03 be adjudicated from this regulation alone?

**Options**

- `NARROW_C03_TO_BASELINE - restate C03 as the floor (at least general supervision), which IS determinable from the regulation, and record that the per-test level is out of scope`
- `SPLIT_C03 - keep a baseline criterion and add a separate criterion for the escalation, marked not determinable from this corpus`
- `LEAVE_C03_NOT_ADJUDICABLE - the criterion as written needs data this corpus does not have; 410.32 stays inadmissible until that data exists`
- `OTHER - state the reading in the rationale`

*C07, transcribed in Phase 7 from this provision:* must be furnished under at least a general level of supervision

*What is NOT in the regulation:* Which supervision level applies to a specific test. That is the physician fee schedule supervision indicator, published separately from 42 CFR and absent from this corpus.

## FOCUS-b3i — priority 2

**42 CFR 410.32 (b)(3)(i)** (version 2026-08-13, section *Paragraph (b)*, page 1)

> General supervision means the procedure is furnished under the physician's overall direction and control, but the physician's presence is not required during the performance of the procedure. Under general supervision, the training of the nonphysician personnel who actually perform the diagnostic procedure and the maintenance of the necessary equipment and supplies are the continuing responsibilit

*Why this is asked:* Directly required by C03: this provision is the definition of general supervision. It is retrievable as evidence today; the question is whether it also needs to be a criterion.

**Question**

Is this a condition a case can satisfy or fail, or is it definitional context that belongs in an evidence set but not in the criteria tree?

**Options**

- `REPRESENT_AS_CRITERION`
- `EVIDENCE_ONLY - definitional; nothing can satisfy or fail it`
- `MERGE_WITH_EXISTING_CRITERION`
- `REQUIRES_POLICY_INTERPRETATION`

## FOCUS-b3ii — priority 2

**42 CFR 410.32 (b)(3)(ii)** (version 2026-08-13, section *Paragraph (b)*, page 1)

> Direct supervision in the office setting means that the physician (or other supervising practitioner) must be present in the office suite and immediately available to furnish assistance and direction throughout the performance of the service. It does not mean that the physician (or other supervising practitioner) must be present in the room when the service is performed. The presence of the physic

*Why this is asked:* Directly required by C03: this provision is the definition of direct supervision. It is retrievable as evidence today; the question is whether it also needs to be a criterion.

**Question**

Is this a condition a case can satisfy or fail, or is it definitional context that belongs in an evidence set but not in the criteria tree?

**Options**

- `REPRESENT_AS_CRITERION`
- `EVIDENCE_ONLY - definitional; nothing can satisfy or fail it`
- `MERGE_WITH_EXISTING_CRITERION`
- `REQUIRES_POLICY_INTERPRETATION`

## FOCUS-b3iii — priority 2

**42 CFR 410.32 (b)(3)(iii)** (version 2026-08-13, section *Paragraph (b)*, page 1)

> Personal supervision means a physician must be in attendance in the room during the performance of the procedure.

*Why this is asked:* Directly required by C03: this provision is the definition of personal supervision. It is retrievable as evidence today; the question is whether it also needs to be a criterion.

**Question**

Is this a condition a case can satisfy or fail, or is it definitional context that belongs in an evidence set but not in the criteria tree?

**Options**

- `REPRESENT_AS_CRITERION`
- `EVIDENCE_ONLY - definitional; nothing can satisfy or fail it`
- `MERGE_WITH_EXISTING_CRITERION`
- `REQUIRES_POLICY_INTERPRETATION`

## FOCUS-b4 — priority 2

**42 CFR 410.32 (b)(4)** (version 2026-08-13, section *Paragraph (b)*, page 1)

> Supervision requirement for RRA or RPA. Diagnostic tests that are performed by a registered radiologist assistant (RRA) who is certified and registered by the American Registry of Radiologic Technologists or a radiology practitioner assistant (RPA) who is certified by the Certification Board for Radiology Practitioner Assistants, and that would otherwise require a personal level of supervision as 

*Why this is asked:* Directly required by C03: this provision is the exception permitting direct in place of personal for RRA/RPA. It is retrievable as evidence today; the question is whether it also needs to be a criterion.

**Question**

Is this a condition a case can satisfy or fail, or is it definitional context that belongs in an evidence set but not in the criteria tree?

**Options**

- `REPRESENT_AS_CRITERION`
- `EVIDENCE_ONLY - definitional; nothing can satisfy or fail it`
- `MERGE_WITH_EXISTING_CRITERION`
- `REQUIRES_POLICY_INTERPRETATION`
