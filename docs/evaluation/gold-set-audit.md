# Gold-Set Audit (Part C)

**156 cases audited. 0 modified. All 156 classify as `REQUIRES_REVIEW`.**

Machine-readable: `data/gold/manifests/gold_v1.audit.json`

---

## 1. Result

| Status | Count |
|---|---|
| `VALID` | **0** |
| `REQUIRES_REVIEW` | **156** |
| `INVALID_FOR_GOLD` | 0 |

Evenly distributed — 26 per policy version across all six.

## 2. Why every case is `REQUIRES_REVIEW`

One reason, and it is structural rather than case-specific:

> Every policy version contains provisions marked `REQUIRES_HUMAN_REVIEW`, so the
> criterion set adjudicating every case is **not established as complete**.

A case is not wrong because of this. It means a case could satisfy every transcribed
criterion while failing a requirement nobody transcribed — 42 CFR
410.38 `(d)(1)(ii)(A)`, the prior-to-delivery timing rule, is a concrete example.

**`REQUIRES_REVIEW` is the correct status, not a pessimistic one.** Marking these
`VALID` would assert completeness that has not been established.

## 3. What was checked

| Check | Result |
|---|---|
| Every referenced criterion exists in the verified inventory | **PASS** — 0 unknown |
| Every requested code has a curated link to its policy | **PASS** |
| Non-`POLICY_NOT_APPLICABLE` cases reference ≥1 criterion | **PASS** |
| Policy version carries only reviewed provisions | **FAIL** — all 6 versions have provisions awaiting review |
| Requested code linked at better than `low` confidence | **PASS** for gold cases |

No case was found `INVALID_FOR_GOLD`: nothing references a nonexistent criterion, an
unlinked code, or a missing policy. The internal integrity is sound. What is
unestablished is the sufficiency of the rules the cases are judged against.

## 4. Cases resting on weak foundations

| Dependency | Cases affected | Handling |
|---|---|---|
| Incomplete criteria | **156 (all)** | `REQUIRES_REVIEW` |
| `INFERRED` code links (G0295, 410.61) | 0 in gold | The inferred links carry `low` confidence and no gold case uses one as its requested code |
| `EXCLUSION_OVERLAY` policy | 0 | 411.15 was excluded from case generation |
| Unsupported policy assumptions | 0 detected | — |

## 5. What was NOT done

**Nothing was changed.** No case deleted, relabelled, or corrected. The gold set
hash is unchanged and still matches its manifest.

Any correction ships as `gold_v2` with a recorded reason, per the
[review protocol](ground-truth-review-protocol.md). Editing in place would destroy
the record of every evaluation already run against v1 — and there is nothing to
correct yet, because no reviewer has found anything wrong.

## 6. Consequence

The gold set may be used for **regression testing** — does a change alter behaviour
on a fixed corpus — because that only needs the set to be stable, which it is.

It may **not** be used as evidence of decision quality, because that needs the
criterion set to be complete, which is unverified.
