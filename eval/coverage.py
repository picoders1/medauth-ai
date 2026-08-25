"""Two denominators, never one. Parts E, F and H.

Phase 14 published "decision accuracy 6/26" for a run in which ten of those cases
never reached a model. That single figure answers two questions at once and gets both
wrong: as *operational* performance it understates nothing but explains nothing, and
as *decision quality* it is a measurement of an outage.

This module refuses to produce one number.

    OPERATIONAL COVERAGE    over every case attempted, provider failures INCLUDED
    DECISION QUALITY        over the cases that were actually assessed

**Neither may be presented as the other**, and `Coverage.headline` renders them
together so a reader cannot quote one without seeing the denominator of the other.

## Excluding a case from decision quality is not dropping it

Every case appears in the operational view, always. A case the provider never
answered has no verdict to score, and scoring it as wrong would attribute an outage
to the model's reasoning. It is *counted* in coverage, *named* in its disposition
bucket, and *absent* from the decision-quality denominator - and the three facts are
reported side by side so the arithmetic is checkable.

## Cost

There is none here. `cost_report` returns `COST_NOT_AVAILABLE` unless a price basis
is supplied by the caller, because this deployment records none. A per-token rate
guessed from a public price list would be a fabricated number about a model whose
identity is a deployment secret.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any

from eval.metrics.statistics import wilson_interval

__all__ = [
    "CaseDisposition",
    "Coverage",
    "cost_report",
    "coverage_report",
]


class CaseDisposition(StrEnum):
    """What became of one case. Exactly one applies, and `MODEL_WRONG` is not here.

    Part F's list, and the reason it is a list: Phase 14 collapsed all of these into
    a single "the model got it wrong" reading, and a provider outage became sixteen
    reasoning errors. A disposition says what *happened to the case*, never whether
    the answer was right - a case can be `ASSESSED` and completely wrong, and that
    is a decision-quality fact rather than a coverage one.
    """

    #: The chain ran and produced verdicts. **The only bucket whose cases enter the
    #: decision-quality denominator** - and being in it says nothing about accuracy.
    ASSESSED = "ASSESSED"

    #: The model path failed at the provider or the proxy. There was no answer to
    #: refuse. Counted in operational coverage; excluded from decision quality.
    PROVIDER_FAILURE = "PROVIDER_FAILURE"

    #: The case's own ground truth is unreachable from its input (R-97 shape). A
    #: defect in the dataset, not in the system, and attributing it to either the
    #: model or the provider would be wrong twice.
    DATASET_DEFECT = "DATASET_DEFECT"

    #: The system detected verdicts that disagree and declined. Behaved as designed.
    CONTRADICTION = "CONTRADICTION"

    #: Something inside MEDAUTH failed - a resolver fault, an unhandled state.
    #: **Ours.** Kept apart from PROVIDER_FAILURE so an outage cannot absorb a bug.
    SYSTEM_FAILURE = "SYSTEM_FAILURE"

    #: No evidence set could be produced. Distinct from a provider failure: the
    #: index, not the model path.
    RETRIEVAL_FAILURE = "RETRIEVAL_FAILURE"

    @property
    def enters_decision_quality(self) -> bool:
        """Only `ASSESSED`. Written as an identity test so a new bucket is excluded
        by default rather than admitted by omission."""
        return self is CaseDisposition.ASSESSED

    @property
    def attributable_to(self) -> str:
        """Whose defect this bucket represents. `NONE` where nothing failed."""
        return {
            CaseDisposition.ASSESSED: "NONE",
            CaseDisposition.PROVIDER_FAILURE: "PROVIDER_OR_FIREWALL",
            CaseDisposition.DATASET_DEFECT: "DATASET",
            CaseDisposition.CONTRADICTION: "NONE - behaved as designed",
            CaseDisposition.SYSTEM_FAILURE: "MEDAUTH",
            CaseDisposition.RETRIEVAL_FAILURE: "MEDAUTH",
        }[self]


#: What each disposition does to the evaluation. Declared as data so a seventh
#: bucket cannot be added without deciding both answers.
_IMPACT: dict[CaseDisposition, str] = {
    CaseDisposition.ASSESSED: "none - this is the measurable population",
    CaseDisposition.PROVIDER_FAILURE: (
        "reduces coverage AND biases decision quality: the lost cases are not a "
        "random subset when the failure correlates with case characteristics"
    ),
    CaseDisposition.DATASET_DEFECT: (
        "reduces the population the dataset can speak about; does not bias the "
        "system's measured behaviour"
    ),
    CaseDisposition.CONTRADICTION: "reduces coverage by design; no bias",
    CaseDisposition.SYSTEM_FAILURE: "reduces coverage and indicates an engineering defect",
    CaseDisposition.RETRIEVAL_FAILURE: "reduces coverage and indicates an index or scope defect",
}


@dataclass(frozen=True, slots=True)
class Coverage:
    """The two denominators and everything between them."""

    attempted: int
    dispositions: dict[str, int] = field(default_factory=dict)

    @property
    def assessed(self) -> int:
        return self.dispositions.get(CaseDisposition.ASSESSED.value, 0)

    @property
    def operational_coverage(self) -> float:
        """Assessed cases over EVERY case attempted. Failures included, always."""
        return self.assessed / self.attempted if self.attempted else 0.0

    @property
    def decision_quality_denominator(self) -> int:
        return self.assessed

    @property
    def headline(self) -> str:
        """Both numbers in one line, so neither can be quoted without the other."""
        return (
            f"operational coverage {self.assessed}/{self.attempted} = "
            f"{self.operational_coverage:.4f}; decision quality is measured over "
            f"{self.assessed} assessed case(s) and is NOT overall system accuracy"
        )


def _rate(successes: int, total: int) -> dict[str, Any]:
    interval = wilson_interval(successes, total)
    return {
        "value": round(interval.value, 4),
        "successes": successes,
        "total": total,
        "ci95": [round(interval.lower, 4), round(interval.upper, 4)],
    }


def coverage_report(
    cases: list[dict[str, Any]], *, disposition_key: str = "disposition"
) -> dict[str, Any]:
    """Both views, plus the per-bucket breakdown Part F requires.

    Every bucket reports count, rate, the stage it belongs to, its effect on
    coverage and its effect on validity. A bucket with a count and nothing else
    tells a reader that something happened and not what it cost.
    """
    attempted = len(cases)
    counts = Counter(
        str(c.get(disposition_key, CaseDisposition.SYSTEM_FAILURE.value)) for c in cases
    )
    coverage = Coverage(attempted=attempted, dispositions=dict(counts))

    breakdown: dict[str, Any] = {}
    for disposition in CaseDisposition:
        count = counts.get(disposition.value, 0)
        breakdown[disposition.value] = {
            "count": count,
            "rate": _rate(count, attempted),
            "attributable_to": disposition.attributable_to,
            "enters_decision_quality_denominator": disposition.enters_decision_quality,
            "impact": _IMPACT[disposition],
        }

    unknown = sorted(set(counts) - {d.value for d in CaseDisposition})
    return {
        "attempted": attempted,
        # THE OPERATIONAL VIEW. Provider failures are in this denominator, and there
        # is no variant of it from which they are removed.
        "operational": {
            "denominator": attempted,
            "assessed": coverage.assessed,
            "coverage": _rate(coverage.assessed, attempted),
            "note": (
                "Every attempted case is here, including the ones that never "
                "reached a model. This is what the system delivered."
            ),
        },
        # THE DECISION-QUALITY VIEW. A different denominator, stated as such.
        "decision_quality": {
            "denominator": coverage.decision_quality_denominator,
            "excluded": attempted - coverage.assessed,
            "note": (
                "Measured over ASSESSED cases only. **This is not overall system "
                "accuracy** and must never be reported as one. Excluded cases are "
                "counted above and named by bucket below; none is dropped."
            ),
        },
        "dispositions": breakdown,
        "unrecognised_dispositions": unknown,
        "headline": coverage.headline,
        "arithmetic": {
            "buckets_sum_to_attempted": sum(counts.values()) == attempted,
            "assessed_plus_excluded": coverage.assessed + (attempted - coverage.assessed),
        },
    }


def cost_report(
    *,
    prompt_tokens: int,
    completion_tokens: int,
    price_basis: dict[str, float] | None = None,
) -> dict[str, Any]:
    """Token counts always; a cost only if someone supplies a real price basis.

    Part H. This deployment records no price basis - the model behind the firewall
    is a deployment value and its rate card is not something MEDAUTH holds. A figure
    derived from a public list price for a model we cannot name would be a fabricated
    number wearing a unit.
    """
    if price_basis is None:
        return {
            "status": "COST_NOT_AVAILABLE",
            "prompt_tokens": prompt_tokens,
            "completion_tokens": completion_tokens,
            "total_tokens": prompt_tokens + completion_tokens,
            "cost": None,
            "why": (
                "No price basis is recorded for this deployment. MEDAUTH reaches the "
                "provider through the firewall and holds no provider credential, no "
                "billing account and no rate card; the model id itself is a "
                "deployment value held in .env. Estimating from a public price list "
                "would attribute a rate to a model this project cannot name."
            ),
            "what_would_change_it": (
                "A rate card supplied by whoever holds the provider account, keyed to "
                "the model digest recorded in the experiment manifest."
            ),
        }

    prompt_rate = float(price_basis.get("prompt_per_1k", 0.0))
    completion_rate = float(price_basis.get("completion_per_1k", 0.0))
    return {
        "status": "COMPUTED",
        "prompt_tokens": prompt_tokens,
        "completion_tokens": completion_tokens,
        "total_tokens": prompt_tokens + completion_tokens,
        "price_basis": dict(price_basis),
        "cost": round(
            prompt_tokens / 1000 * prompt_rate + completion_tokens / 1000 * completion_rate, 6
        ),
        "currency": str(price_basis.get("currency", "unspecified")),
        "note": "Computed from a supplied price basis, which is recorded above.",
    }
