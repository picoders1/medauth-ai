# First Vertical-Slice Contract Fixtures

**Contract fixtures, not evaluation data.** They exercise the *shapes* at each
boundary of the future slice and require **no model inference**. Nothing here
produces or validates a clinical judgement.

## What they are built on

42 CFR 410.32 rev 2026-08-13 only — the one policy version whose criteria are
span-verified with complete citation provenance, and the one that becomes admissible
if FOCUS-001 clears.

They use criteria **C01, C02, C04** and deliberately avoid **C03**: its dependency
on the untranscribed (b)(3) is unresolved, so a fixture asserting a verdict on it
would encode an answer to the question a reviewer has not been asked yet.

They also avoid every `REVIEW_REQUIRED` policy, for the same reason.

## The eight scenarios

| fixture | exercises |
|---|---|
| `01-complete.json` | every required criterion satisfied with cited evidence |
| `02-missing-criterion.json` | one criterion with no evidence → `INSUFFICIENT_EVIDENCE` |
| `03-contradictory.json` | mappings that disagree → `CONTRADICTORY_EVIDENCE` |
| `04-invalid-citation.json` | a quote that does not appear in the chunk → `UNSUPPORTED_CITATION` |
| `05-retrieval-failure.json` | an empty evidence set → `RETRIEVAL_FAILURE` |
| `06-unresolved-policy.json` | a `REVIEW_REQUIRED` policy → `UNRESOLVED_POLICY_SEMANTICS` |
| `07-schema-failure.json` | a model return the closed schema rejects → `MODEL_SCHEMA_FAILURE` |
| `08-no-applicable-policy.json` | a code resolving to nothing → `NO_APPLICABLE_POLICY` |

## What they are not

**Not gold data.** They carry no expected clinical outcome, are not labelled, and
must never be scored or reported as accuracy.

**Not a substitute for gold_v1.** They test that the contract holds, not that the
system decides correctly.

Clinical notes are synthetic and deliberately thin — enough to carry a fact and its
span, and no more. **No real PHI, ever.**
