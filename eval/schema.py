"""The library boundary between a frozen dataset and what may be done to it.

    from eval.schema import require_scoring_budget, require_tunable

    require_tunable(partition)                      # selection / calibration
    require_scoring_budget(GOLD_V2, experiment=...)  # scoring a hold-out

CLAUDE.md has named this module since Phase 0:

> Selection and threshold calibration use **dev only**, enforced at the library
> boundary: `eval/schema.py:require_tunable(split)` raises on a frozen split, and
> every calibration entry point calls it.

It did not exist. `R-23` (the frozen test split is re-scored until a number improves)
and `R-25` (thresholds are tuned on the test split) both recorded that boundary as
their mitigation, and both were in fact resting on discipline plus two inline checks
that had drifted apart:

- `scripts/score_retrieval_v4_baseline.py` compared `scorings_spent` against
  `scoring_budget` with `dataset.get("scoring_budget", 1)` - a **default of 1**, so a
  dataset that forgot to declare a budget silently acquired one.
- `scripts/phase16_prerun_gate.py` read the same field out of a gold manifest, whose
  shape is different, and reached the right answer by a second implementation.
- `scripts/evaluate_retrieval_v3.py` - the one script that actually **sweeps arms**,
  which is selection - checked neither, against a set whose budget is already spent.

Three call sites, two shapes, one of them absent. That is the state a boundary
exists to end. This is R-103.

## Refusal by absence

`TUNABLE_PARTITIONS` holds exactly one member. Everything else is refused because it
is **not in the set**, never by a branch naming it - the same technique that keeps
`RunMode.REPLAY` out of `PRODUCTION_MODES` and `GOLD_V1_REPLAY` out of
`PRODUCTION_ORIGINS`. A branch is somewhere to add an exception; an absence is not.
Adding a fourth partition therefore makes it frozen by default, which is the
direction an omission should fail in.

An unrecognised name raises rather than passing through. "We do not know what this
split is" is not permission to tune on it.

## These functions raise; they do not return a boolean

Same reason `OfficialEvaluationGate.require()` raises. The callers are scripts, and
the failure mode of forgetting to check a boolean is a scored hold-out. There is no
`force`, `skip`, `override` or `assume` parameter here and no environment read;
`tests/evaluation/test_schema_boundary.py` asserts both over this module's AST.

## What this boundary does NOT claim

It guards the entry points that call it. It is not a filesystem permission, and a
new script that reads `data/gold/cases/gold_v2.jsonl` directly still can. What it
removes is the accidental path and the divergent second implementation; the
deliberate path remains visible in `grep`, in the diff and in this module's call
graph. Overstating that would be the same defect this file exists to fix.
"""

from __future__ import annotations

import json
from enum import StrEnum
from pathlib import Path
from typing import Any

import yaml

REPO = Path(__file__).resolve().parents[1]

__all__ = [
    "TUNABLE_PARTITIONS",
    "FrozenSplitError",
    "Partition",
    "ScoringBudget",
    "ScoringBudgetExhausted",
    "budget_for",
    "require_scoring_budget",
    "require_tunable",
]


class Partition(StrEnum):
    """The partitions this repository actually holds, by their committed names.

    These are the values written into `data/synthetic/cases/*.jsonl` and
    `data/gold/cases/*.jsonl`, not an idealised vocabulary. A partition that is not
    here cannot be passed as one.
    """

    #: `data/synthetic/cases/development.jsonl`, 48 cases. The only tunable split.
    DEVELOPMENT = "development"

    #: `data/synthetic/cases/validation.jsonl`, 18 cases. Frozen: it exists to
    #: check a decision made on development, and a split used to make the decision
    #: cannot also check it.
    VALIDATION = "validation"

    #: `data/gold/cases/gold_v1.jsonl` and `gold_v2.jsonl`, 156 cases each. The
    #: hold-out, with a scoring budget.
    GOLD = "gold"

    #: `eval/datasets/retrieval*/questions.yaml`. Frozen and budgeted for the same
    #: reason: `retrieval_v3` proved arithmetically at n=31 that a set this size
    #: cannot separate arms, so a sweep over it produces a winner made of noise.
    RETRIEVAL_BENCHMARK = "retrieval_benchmark"


#: The partitions selection and calibration may read. **Exactly one.** Everything
#: else is refused by absence - see the module docstring.
TUNABLE_PARTITIONS: frozenset[Partition] = frozenset({Partition.DEVELOPMENT})


class FrozenSplitError(RuntimeError):
    """A frozen split was about to be used to choose something.

    Raised, not returned. Selecting a configuration, a threshold or a prompt on a
    frozen split converts a measurement into a fitted parameter, and the report that
    follows describes the fitting rather than the system.
    """


class ScoringBudgetExhausted(RuntimeError):
    """A hold-out was about to be scored more times than was declared in advance.

    The budget is not a formality. Re-scoring until a number improves is how an
    evaluation becomes fiction, and the difference between "we measured once" and
    "we measured until it looked right" is invisible in the final report unless
    something counts.
    """


def require_tunable(split: str | Partition) -> Partition:
    """Raise unless `split` may be used for selection or calibration.

    The **only** supported way to ask. Call it before reading a dataset for any
    purpose that ends in a choice: an encoder, a reranker, `top_k`, an abstention
    threshold, a prompt variant, a chunking rule.

    An unknown name raises `FrozenSplitError` rather than being treated as a new
    tunable partition - see the module docstring on failing in the safe direction.
    """
    try:
        partition = Partition(str(split))
    except ValueError:
        raise FrozenSplitError(
            f"{split!r} is not a partition this repository holds "
            f"({', '.join(sorted(p.value for p in Partition))}). An unrecognised "
            "split is not a tunable one: 'we do not know what this is' is not "
            "permission to fit a parameter to it."
        ) from None

    if partition not in TUNABLE_PARTITIONS:
        raise FrozenSplitError(
            f"{partition.value} is frozen and may not be used for selection or "
            f"calibration. Tunable: {', '.join(sorted(p.value for p in TUNABLE_PARTITIONS))}. "
            "Measure on a frozen split; choose on development. A threshold chosen "
            "here would be reported as a result and would be a fitted parameter."
        )
    return partition


class ScoringBudget:
    """One hold-out's declared scoring allowance, read from its own manifest.

    Two committed shapes exist and neither is going to be rewritten - a gold
    manifest nests the budget under `scoring_budget`, a retrieval questions file
    carries `scoring_budget`/`scorings_spent` at the top level. Both are read here so
    that no caller has to know which it holds, which is exactly the knowledge that
    let the two inline implementations drift.

    There is **no default allowance.** A dataset that declares no budget has not been
    granted one; the previous inline check defaulted to `1` and would have handed a
    free scoring to any set that forgot to say.
    """

    __slots__ = ("allowed", "dataset", "spent")

    def __init__(self, dataset: Path, allowed: int, spent: int) -> None:
        self.dataset = dataset
        self.allowed = allowed
        self.spent = spent

    @property
    def remaining(self) -> int:
        return max(0, self.allowed - self.spent)

    @property
    def permits_scoring(self) -> bool:
        return self.spent < self.allowed

    def as_dict(self) -> dict[str, Any]:
        return {
            "dataset": str(self.dataset.relative_to(REPO)),
            "allowed_scorings": self.allowed,
            "scorings_spent": self.spent,
            "remaining": self.remaining,
            "permits_scoring": self.permits_scoring,
        }


def budget_for(dataset: Path) -> ScoringBudget:
    """Read a dataset's declared budget. Never raises on an exhausted one.

    Separated from `require_scoring_budget` so a gate can *report* a spent budget
    without a traceback, which is what `scripts/phase16_prerun_gate.py` needs.
    """
    if not dataset.is_file():
        raise ScoringBudgetExhausted(
            f"{dataset} does not exist, so it declares no scoring allowance. A "
            "dataset that cannot be found has not granted one."
        )

    if dataset.suffix in {".yaml", ".yml"}:
        raw = yaml.safe_load(dataset.read_text(encoding="utf-8")) or {}
    else:
        raw = json.loads(dataset.read_text(encoding="utf-8"))

    block = raw.get("scoring_budget")
    if isinstance(block, dict):  # a gold manifest
        allowed = block.get("allowed_scorings")
        spent = block.get("scorings_spent", 0)
    else:  # a retrieval questions file
        allowed = block
        spent = raw.get("scorings_spent", 0)

    if allowed is None:
        raise ScoringBudgetExhausted(
            f"{dataset.name} declares no scoring allowance. There is no default: an "
            "undeclared budget is zero, not one. Declare it in the manifest, in an "
            "ADR, before the run."
        )
    return ScoringBudget(dataset, int(allowed), int(spent))


def require_scoring_budget(dataset: Path, *, experiment: str) -> ScoringBudget:
    """Raise unless `dataset` may be scored once more.

    Call it before the first case runs, not after - a run that scores a hold-out and
    discovers afterwards that the budget was spent has already spent it.
    """
    budget = budget_for(dataset)
    if not budget.permits_scoring:
        raise ScoringBudgetExhausted(
            f"{experiment}: {dataset.name}'s scoring budget is spent "
            f"({budget.spent}/{budget.allowed}). A further scoring must be declared "
            "in an ADR **in advance**, with the reason it is a different system "
            "under test rather than the same one re-drawn."
        )
    return budget
