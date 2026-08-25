# gold_v1 → gold_v2: the migration, case by case

**Report:** `data/review/gold_v2_migration.json` · **Builder:** `scripts/build_gold_v2.py`
**gold_v1 sha256:** `ca990b80…` — **byte-identical, and asserted before anything is written**

---

## What forced it

R-97. gold_v1's eighteen `POLICY_NOT_APPLICABLE` cases wrote their non-applicability
into the clinical narrative — *"Requested service: unlisted procedure 99199"* — while
their structured `requested_procedure.code` was `R0075`, a code the corpus genuinely
links to 42 CFR 410.33. Deterministic resolution reads the structured request,
correctly resolves, and the gold label of decision-rule 1 is unreachable.

Phase 15 made applicability real; the label became unreachable the same day.

## The audit — all 156, not just the broken

| classification | count |
|---|---|
| `UNCHANGED` | **138** |
| `REQUIRES_STRUCTURAL_FIX` | **18** |
| `REQUIRES_LABEL_REVIEW` | 0 |
| `INVALID_FOR_GOLD_V2` | 0 |

Every case is listed with its reason. A report showing only the edits would leave
*"and the other 138 were fine"* as an assertion nobody checked.

**Zero label disagreements.** Every one of the 156 recommendations and rules was
recomputed by `decide()` from gold_v1's own criterion states, under gold_v1's replay
semantics, and reproduced exactly. That is a real check on both artefacts: the
dataset and the decision table have not drifted apart across twelve phases.

## What changed, and what did not

| | gold_v1 | gold_v2 |
|---|---|---|
| cases | 156 | **156** — none excluded |
| `APPROVE / DENY / NEEDS_INFO / HUMAN_REVIEW` | 51 / 33 / 60 / 12 | **identical** |
| applicability | implied | **structured** — 138 `RESOLVED`, 18 `NONE_APPLICABLE` |
| not-applicable procedure code | `R0075` (covered) | a verified **non-covered** HCPCS code |
| clinical note | names `99199` in prose | names the structured code |

The label distribution is unchanged because **no label changed**. The eighteen cases
still expect `NEEDS_INFO` via rule 1; what changed is that the input can now produce
it.

## The fix is a code, not a parser

The tempting repair is to let the resolver read the narrative. It is refused:

- applicability would depend on prose, resolving differently for the same structured
  request depending on wording;
- it reintroduces the exact class of failure ADR-004 exists to prevent — a semantic
  resolver wearing a deterministic one's clothes.

## Per-case change records (B4)

One per case, including unchanged ones. Each carries the gold_v1 reference, the
gold_v2 reference, the affected policy and criteria, the changed fields, the values
before and after, and two explicit booleans — `decision_changed` and
`applicability_changed`. **No silent changes.**

## Partition

Inherited case-by-case, **not recomputed**. Recomputing would re-partition every case
and invalidate every committed report that names a gold_v1 split. The rule itself is
carried forward verbatim in the manifest.

## Reproducing

```bash
uv run python scripts/fetch_noncovered_codes.py --write   # verify the codes exist
uv run python scripts/build_gold_v2.py                    # audit only, writes nothing
uv run python scripts/build_gold_v2.py --write
```

The builder hashes gold_v1 against its manifest first and **refuses to run if they
disagree**. A migration that can run against a modified source is a migration that
can launder one.
