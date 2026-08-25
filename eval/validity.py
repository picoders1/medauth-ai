"""Is an experiment interpretable as performance, or degraded by provider failure?

**Pre-registered in ADR-028, before the Phase-15 run existed.** The thresholds below
were fixed and committed with the manifest that names them; a rule chosen after
seeing results is a rule chosen because of them, and the whole point of this module
is that nobody gets to make that call by eye afterwards.

## Why a rule at all

Phase 14 reported decision accuracy 6/26 while 10 of those 26 cases never reached
adjudication - a provider defect (R-86) removed 38% of the sample, and the survivors
were not a random subset of it. The number was published with a paragraph of prose
saying so. Prose is the wrong mechanism: it can be softened, moved to a footnote, or
dropped by whoever quotes the figure next. A machine-checked status travels with the
artefact.

## What the rule decides, and what it does not

It decides whether decision-level metrics may be quoted **as evidence about the
system's reasoning**. It never decides whether an experiment ran, whether its safety
metrics hold, or whether a case may be excluded - no case may ever be excluded, and
`DEGRADED_BY_PROVIDER_FAILURE` is a label on the numbers, not a licence to drop the
rows that produced it.

Safety metrics stay interpretable under either status. "Did anything unsafe happen"
is answerable over the cases that ran; "how well does it reason" is not answerable
over a biased 62% of them.

## The direction is fixed in advance

Every condition can only **demote**. There is no evidence this rule can be shown
that turns `DEGRADED` into `VALID`, which is what stops it from being a knob.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field
from enum import StrEnum

__all__ = [
    "VALIDITY_RULE_ID",
    "ExperimentValidity",
    "ValidityFinding",
    "ValidityRule",
    "classify_validity",
]

#: Frozen into every manifest that uses it. A manifest naming a different id was run
#: under a different rule, and the two results are not comparable on this axis.
VALIDITY_RULE_ID = "provider-failure-validity.v1"


class ExperimentValidity(StrEnum):
    """Whether decision metrics may be read as performance."""

    #: Provider failure is low enough, and unbiased enough, that decision-level
    #: metrics describe the system rather than the outage.
    VALID_FOR_PERFORMANCE_ANALYSIS = "VALID_FOR_PERFORMANCE_ANALYSIS"

    #: The metrics are real, reported in full, and **not** interpretable as
    #: reasoning performance. Never a reason to exclude a case or to re-run.
    DEGRADED_BY_PROVIDER_FAILURE = "DEGRADED_BY_PROVIDER_FAILURE"


@dataclass(frozen=True, slots=True)
class ValidityRule:
    """The pre-registered thresholds. Values fixed in ADR-028, 2026-08-25.

    Justification for each is in the ADR rather than here, but the shape matters:
    three independent conditions, any one of which demotes, because provider failure
    can spoil an experiment three different ways and a single rate does not catch
    them all. A 5% failure rate that erases every expected approval is worse than a
    15% failure rate spread evenly.
    """

    #: Above this share of attempted cases, the survivors are too few to describe
    #: the corpus. 0.10 is the point at which a 26-case run loses three cases -
    #: enough to move a proportion by more than its own confidence interval.
    max_failure_rate: float = 0.10

    #: An expected-decision class every one of whose cases failed is a class the
    #: experiment cannot speak about at all, at any failure rate.
    demote_on_class_erasure: bool = True

    #: A category whose failure rate is at least this multiple of the overall rate,
    #: AND at least `concentration_floor`, is evidence the failures are not a random
    #: subset. Both conditions, because a 2x multiple on a 1% base rate is noise.
    concentration_multiple: float = 2.0
    concentration_floor: float = 0.50
    #: Categories smaller than this are exempt: one failure out of two is not a
    #: pattern, and treating it as one would demote almost every experiment.
    concentration_min_category_size: int = 3


@dataclass(frozen=True, slots=True)
class ValidityFinding:
    """The status, every condition that fired, and the numbers behind them."""

    status: ExperimentValidity
    rule_id: str
    attempted: int
    provider_failures: int
    failure_rate: float
    triggered: tuple[str, ...] = ()
    erased_classes: tuple[str, ...] = ()
    concentrated_categories: tuple[str, ...] = ()
    notes: tuple[str, ...] = field(default_factory=tuple)

    @property
    def interpretable_as_performance(self) -> bool:
        return self.status is ExperimentValidity.VALID_FOR_PERFORMANCE_ANALYSIS

    @property
    def headline(self) -> str:
        """One line a report cannot quote without the status attached."""
        share = f"{self.provider_failures}/{self.attempted} = {self.failure_rate:.4f}"
        return f"{self.status.value} (provider failure {share}, rule {self.rule_id})"


def classify_validity(
    cases: list[dict[str, object]],
    *,
    rule: ValidityRule | None = None,
    failed_key: str = "provider_failure",
    class_key: str = "expected_recommendation",
    category_key: str = "category",
) -> ValidityFinding:
    """Apply the pre-registered rule. Deterministic, and demote-only.

    `cases` is the per-case record of a completed run. Nothing is excluded, nothing
    is re-weighted, and the function has no access to any accuracy figure - it reads
    which cases the provider failed and how they are distributed, and nothing about
    whether the answers were right. A validity rule that could see the score would
    be a rule that could be satisfied by a good one.
    """
    rule = rule or ValidityRule()
    attempted = len(cases)
    if attempted == 0:
        return ValidityFinding(
            status=ExperimentValidity.DEGRADED_BY_PROVIDER_FAILURE,
            rule_id=VALIDITY_RULE_ID,
            attempted=0,
            provider_failures=0,
            failure_rate=0.0,
            triggered=("NO_CASES",),
            notes=("an experiment with no cases is not interpretable as anything",),
        )

    failed = [c for c in cases if bool(c.get(failed_key))]
    rate = len(failed) / attempted
    triggered: list[str] = []
    notes: list[str] = []

    if rate > rule.max_failure_rate:
        triggered.append("FAILURE_RATE")
        notes.append(
            f"provider failure {len(failed)}/{attempted} = {rate:.4f} exceeds the "
            f"pre-registered ceiling {rule.max_failure_rate:.2f}"
        )

    # Class erasure: an expected-decision class with no surviving case.
    by_class = Counter(str(c.get(class_key, "")) for c in cases)
    failed_by_class = Counter(str(c.get(class_key, "")) for c in failed)
    erased = tuple(sorted(k for k, n in by_class.items() if k and failed_by_class[k] == n))
    if erased and rule.demote_on_class_erasure:
        triggered.append("CLASS_ERASURE")
        notes.append(
            f"every case expecting {', '.join(erased)} was lost to provider failure; "
            "the experiment cannot speak about that class at any failure rate"
        )

    # Concentration: failures clustered in a category are not a random subset.
    by_category = Counter(str(c.get(category_key, "")) for c in cases)
    failed_by_category = Counter(str(c.get(category_key, "")) for c in failed)
    concentrated: list[str] = []
    for category, size in sorted(by_category.items()):
        if not category or size < rule.concentration_min_category_size:
            continue
        local = failed_by_category[category] / size
        if local >= rule.concentration_floor and (
            rate == 0 or local >= rate * rule.concentration_multiple
        ):
            concentrated.append(f"{category} ({failed_by_category[category]}/{size})")
    if concentrated:
        triggered.append("CONCENTRATION")
        notes.append(
            "provider failure is concentrated in " + ", ".join(concentrated) + "; the "
            "surviving cases are not a random subset of the corpus"
        )

    status = (
        ExperimentValidity.DEGRADED_BY_PROVIDER_FAILURE
        if triggered
        else ExperimentValidity.VALID_FOR_PERFORMANCE_ANALYSIS
    )
    if not triggered:
        notes.append(
            "no pre-registered condition fired. Decision metrics may be read as "
            "performance; this says nothing about clinical accuracy or validation."
        )
    return ValidityFinding(
        status=status,
        rule_id=VALIDITY_RULE_ID,
        attempted=attempted,
        provider_failures=len(failed),
        failure_rate=round(rate, 4),
        triggered=tuple(triggered),
        erased_classes=erased,
        concentrated_categories=tuple(concentrated),
        notes=tuple(notes),
    )
