"""If a reviewed provision changes, what else changes?

gold_v1 is immutable. That protects the record and it also means a reviewer working
the OD-19 queue has no way to see, before deciding, how far a decision reaches. This
answers that question and changes nothing.

The chain it walks:

    provision  ──cited_by──▶  criterion  ──referenced_by──▶  case
                                   │
                                   └──belongs_to──▶  policy version  ──▶  cases

A provision reaches a criterion two ways, and they are not equally strong:

**A recorded dependency.** The criterion invokes a rule this provision contains
(R-51). Changing the provision changes what the criterion means, so every case
referencing that criterion is affected.

**Shared policy version.** The provision sits in a policy a criterion was drawn
from. Ruling `REPRESENT_AS_CRITERION` on it adds a criterion to that policy, which
changes what a *complete* adjudication of any case on that version requires - even
though no existing criterion changed.

The second is weaker and is reported separately. Merging them would make every
decision look like it invalidated half the corpus.

Pure: no I/O. The corpora arrive already loaded.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from app.review.versioning import ReviewImpact, ReviewScope

__all__ = ["ImpactInputs", "analyse_impact"]


@dataclass(frozen=True, slots=True)
class ImpactInputs:
    """Everything needed to trace a decision's reach, supplied by the caller."""

    #: criterion_id -> its record from the criteria inventory
    criteria: dict[str, dict[str, Any]]
    #: provision_id -> its row from the coverage matrix
    provisions: dict[str, dict[str, Any]]
    #: criterion_id -> provision_ids it cannot be evaluated without
    dependencies: dict[str, tuple[str, ...]]
    #: case records, each with `case_id` and `expected`
    gold_cases: tuple[dict[str, Any], ...]
    synthetic_cases: tuple[dict[str, Any], ...]


def _cases_referencing(
    cases: tuple[dict[str, Any], ...], criterion_ids: frozenset[str]
) -> tuple[str, ...]:
    return tuple(
        sorted(
            case["case_id"]
            for case in cases
            if any(entry["criterion_id"] in criterion_ids for entry in case["expected"]["criteria"])
        )
    )


def _cases_on_versions(
    cases: tuple[dict[str, Any], ...], versions: frozenset[tuple[str, str]]
) -> tuple[str, ...]:
    return tuple(
        sorted(
            case["case_id"]
            for case in cases
            if (case["expected"]["policy_id"], case["expected"]["policy_revision"]) in versions
        )
    )


def analyse_impact(scope: ReviewScope, subject_id: str, inputs: ImpactInputs) -> ReviewImpact:
    """What acting on this decision would touch. **Nothing is modified.**

    A subject the corpora do not know is not an empty impact - it is a stale
    reference, and it is reported as a note rather than as "nothing is affected".
    Those look identical in a summary and mean opposite things.
    """
    notes: list[str] = []
    criteria: set[str] = set()
    versions: set[tuple[str, str]] = set()

    if scope is ReviewScope.PROVISION:
        provision = inputs.provisions.get(subject_id)
        if provision is None:
            return ReviewImpact(
                notes=(
                    f"provision {subject_id!r} is not in the coverage matrix; this is a "
                    "stale reference, not an absence of impact",
                )
            )
        versions.add((provision["policy_id"], provision["policy_version"]))
        criteria |= {
            criterion_id
            for criterion_id, provisions in inputs.dependencies.items()
            if subject_id in provisions
        }
        # Criteria already drawn from this provision - ruling on it changes them.
        criteria |= set(provision.get("criterion_ids") or ())
        if not criteria:
            notes.append(
                "no criterion depends on this provision. Ruling REPRESENT_AS_CRITERION "
                "would ADD one, which changes what a complete adjudication of this "
                "policy version requires without changing any existing criterion."
            )

    elif scope is ReviewScope.CRITERION:
        criterion = inputs.criteria.get(subject_id)
        if criterion is None:
            return ReviewImpact(
                notes=(f"criterion {subject_id!r} is not in the inventory; stale reference",)
            )
        criteria.add(subject_id)
        versions.add((criterion["policy_id"], criterion["policy_version"]))

    elif scope in (
        ReviewScope.POLICY_SEMANTICS,
        ReviewScope.COVERAGE_STATUS,
        ReviewScope.CODE_LINKAGE,
    ):
        # The subject is a policy identity string, `TYPE:policy id:version`.
        parts = subject_id.split(":")
        if len(parts) < 3:
            return ReviewImpact(
                notes=(f"{subject_id!r} is not a policy identity; stale reference",)
            )
        versions.add((":".join(parts[1:-1]), parts[-1]))
        criteria |= {
            criterion_id
            for criterion_id, record in inputs.criteria.items()
            if (record["policy_id"], record["policy_version"]) in versions
        }

    frozen_criteria = frozenset(criteria)
    frozen_versions = frozenset(versions)

    directly_affected_gold = _cases_referencing(inputs.gold_cases, frozen_criteria)
    on_version_gold = _cases_on_versions(inputs.gold_cases, frozen_versions)
    if scope is ReviewScope.PROVISION and not frozen_criteria and on_version_gold:
        notes.append(
            f"{len(on_version_gold)} gold case(s) sit on this policy version and would "
            "need re-examining if a new criterion were added, though none references a "
            "criterion that changes"
        )

    return ReviewImpact(
        criteria=tuple(sorted(frozen_criteria)),
        policy_versions=tuple(f"{p}:{v}" for p, v in sorted(frozen_versions)),
        gold_cases=directly_affected_gold,
        synthetic_cases=_cases_referencing(inputs.synthetic_cases, frozen_criteria),
        evaluation_reports=(
            ("eval/reports/** (any report scored against affected cases)",)
            if directly_affected_gold
            else ()
        ),
        notes=tuple(notes),
    )
