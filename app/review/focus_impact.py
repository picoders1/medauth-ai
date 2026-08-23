"""What each possible answer to FOCUS-001 would cost, computed before it is given.

A reviewer asked to rule on C03 is being asked to make a decision whose consequences
run through a frozen dataset, an admissibility gate and every downstream phase. They
should be able to see those consequences *before* deciding, not discover them
afterwards - and they should see them for every option, not only the one someone
expects them to pick.

**This does not recommend an answer.** Each outcome is modelled on its own terms and
the table is presented flat. Some options cost more than others; that is a fact
about the options, not an argument for the cheap one. Choosing the cheapest reading
of a regulation because it needs no gold_v2 would be exactly the wrong reason.

Pure and deterministic: the corpora arrive already loaded, nothing is read from
disk, and the same inputs always produce the same table.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any

__all__ = [
    "FocusOutcome",
    "OutcomeImpact",
    "analyse_focus_001",
]


class FocusOutcome(StrEnum):
    """The permitted answers to FOCUS-001. A closed set, so an answer cannot
    quietly change the question it was asked."""

    #: Restate C03 as the floor - "at least general supervision" - which IS
    #: determinable from the regulation, and record the per-test level as out of
    #: scope for this corpus.
    NARROW_C03_TO_BASELINE = "NARROW_C03_TO_BASELINE"

    #: Keep a baseline criterion and add a separate escalation criterion, marked
    #: not determinable from this corpus.
    SPLIT_C03 = "SPLIT_C03"

    #: The criterion as written needs data this corpus does not have. 410.32 stays
    #: inadmissible.
    LEAVE_C03_NOT_ADJUDICABLE = "LEAVE_C03_NOT_ADJUDICABLE"

    #: The reviewer's reading is none of the above and is stated in the rationale.
    #: Its impact cannot be precomputed, and saying so is more honest than
    #: modelling a placeholder.
    OTHER = "OTHER"


@dataclass(frozen=True, slots=True)
class OutcomeImpact:
    """The consequences of one answer. Every field is derived, none asserted."""

    outcome: FocusOutcome
    c03_state: str
    criteria_changed: tuple[str, ...] = ()
    criteria_added: tuple[str, ...] = ()
    gold_cases_affected: tuple[str, ...] = ()
    policy_admissible_after: bool = False
    gold_v2_required: bool = False
    evidence_changes: tuple[str, ...] = ()
    evaluation_impact: tuple[str, ...] = ()
    unblocks: tuple[str, ...] = ()
    still_blocked_by: tuple[str, ...] = ()
    notes: tuple[str, ...] = field(default_factory=tuple)

    @property
    def gold_cases_affected_count(self) -> int:
        return len(self.gold_cases_affected)


def _cases_referencing(cases: tuple[dict[str, Any], ...], criterion_id: str) -> tuple[str, ...]:
    return tuple(
        sorted(
            case["case_id"]
            for case in cases
            if any(entry["criterion_id"] == criterion_id for entry in case["expected"]["criteria"])
        )
    )


def _cases_on_version(
    cases: tuple[dict[str, Any], ...], policy_id: str, policy_version: str
) -> tuple[str, ...]:
    return tuple(
        sorted(
            case["case_id"]
            for case in cases
            if case["expected"]["policy_id"] == policy_id
            and case["expected"]["policy_revision"] == policy_version
        )
    )


def analyse_focus_001(
    *,
    gold_cases: tuple[dict[str, Any], ...],
    synthetic_cases: tuple[dict[str, Any], ...],
    other_blockers: tuple[str, ...],
    c03_id: str = "42_CFR_410_32_2026_08_13_C03",
    policy_id: str = "42 CFR 410.32",
    policy_version: str = "2026-08-13",
) -> tuple[OutcomeImpact, ...]:
    """The four-way impact table.

    `other_blockers` is what would STILL block 42 CFR 410.32 after this decision -
    read from the admissibility gate, not assumed empty. If the gate ever grows a
    condition this policy also fails, that appears here rather than being discovered
    when the slice is attempted.
    """
    referencing_c03 = _cases_referencing(gold_cases, c03_id)
    on_version = _cases_on_version(gold_cases, policy_id, policy_version)
    synthetic_c03 = _cases_referencing(synthetic_cases, c03_id)

    # A decision that changes what C03 MEANS invalidates the labels of cases that
    # were labelled against the old C03. That is what forces a new frozen version;
    # a decision that changes nothing forces nothing.
    changing = (
        f"{len(referencing_c03)} gold and {len(synthetic_c03)} synthetic case(s) were "
        "labelled against C03 as it is written; a decision that changes what C03 means "
        "makes those labels a record of a criterion that no longer exists in that form"
    )

    impacts: list[OutcomeImpact] = []

    # ------------------------------------------------- NARROW_C03_TO_BASELINE
    impacts.append(
        OutcomeImpact(
            outcome=FocusOutcome.NARROW_C03_TO_BASELINE,
            c03_state=(
                "C03 is restated as the floor already transcribed in C07 (at least "
                "general supervision). The per-test level is recorded as out of scope "
                "for this corpus."
            ),
            criteria_changed=(c03_id,),
            gold_cases_affected=referencing_c03,
            policy_admissible_after=not other_blockers,
            gold_v2_required=bool(referencing_c03),
            evidence_changes=(
                "C03's evidence set narrows to the (b)(3) baseline sentence, which is "
                "in the corpus and retrievable",
                "the (b)(3)(i)-(iii) definitions remain retrievable as context",
            ),
            evaluation_impact=(
                "any retrieval query targeting C03 now targets a narrower criterion; "
                "the query text is unchanged but what counts as the right answer is not",
            ),
            unblocks=("42 CFR 410.32 becomes admissible for the first AI vertical slice",)
            if not other_blockers
            else (),
            still_blocked_by=other_blockers,
            notes=(
                changing,
                "REDUCES what the system checks: a test requiring direct or personal "
                "supervision would pass a criterion that only tests the floor. Whether "
                "that under-checking is acceptable is precisely the reviewer's call, "
                "and it is not an engineering trade-off.",
            ),
        )
    )

    # ------------------------------------------------------------- SPLIT_C03
    escalation = f"{c03_id}_ESCALATION"
    impacts.append(
        OutcomeImpact(
            outcome=FocusOutcome.SPLIT_C03,
            c03_state=(
                "C03 becomes two criteria: the baseline (adjudicable) and the "
                "escalation to direct or personal supervision (not determinable from "
                "this corpus, and marked so)."
            ),
            criteria_changed=(c03_id,),
            criteria_added=(escalation,),
            gold_cases_affected=referencing_c03,
            # The escalation criterion is itself not determinable, so it carries the
            # dependency forward. Splitting relocates the blocker; it does not remove
            # it, unless the escalation half is excluded from adjudication.
            policy_admissible_after=False,
            gold_v2_required=bool(referencing_c03),
            evidence_changes=(
                "the baseline half draws on the (b)(3) floor sentence",
                "the escalation half has NO evidence in this corpus - the physician "
                "fee schedule supervision indicator is not part of 42 CFR",
            ),
            evaluation_impact=(
                "criterion count rises; every case referencing C03 needs a state for "
                "both halves, so a gold_v2 is a regeneration rather than a relabelling",
            ),
            unblocks=(),
            still_blocked_by=(
                *other_blockers,
                "the escalation criterion is not determinable from this corpus, so it "
                "inherits the dependency unless a further decision excludes it from "
                "adjudication",
            ),
            notes=(
                changing,
                "PRESERVES what the system checks and relocates the blocker rather "
                "than removing it. More honest about the gap and more work, and it "
                "does not by itself make 410.32 admissible.",
            ),
        )
    )

    # ------------------------------------------- LEAVE_C03_NOT_ADJUDICABLE
    impacts.append(
        OutcomeImpact(
            outcome=FocusOutcome.LEAVE_C03_NOT_ADJUDICABLE,
            c03_state="C03 is unchanged and remains not independently adjudicable.",
            gold_cases_affected=(),
            policy_admissible_after=False,
            gold_v2_required=False,
            evidence_changes=(),
            evaluation_impact=(
                "none. Every dataset, label and committed report stays exactly as it is",
            ),
            unblocks=(),
            still_blocked_by=(
                *other_blockers,
                "C03's dependency on 42 CFR 410.32(b)(3) remains unresolved",
            ),
            notes=(
                "Costs nothing and unblocks nothing. 42 CFR 410.32 stays inadmissible "
                f"and all {len(on_version)} gold cases on it stay non-adjudicable.",
                "A legitimate answer, not a refusal to answer: it says the criterion "
                "as written needs data this corpus does not have, which may simply be "
                "true.",
            ),
        )
    )

    # ------------------------------------------------------------------ OTHER
    impacts.append(
        OutcomeImpact(
            outcome=FocusOutcome.OTHER,
            c03_state="Determined by the reviewer's stated reading.",
            gold_cases_affected=(),
            policy_admissible_after=False,
            gold_v2_required=False,
            evidence_changes=(),
            evaluation_impact=(),
            unblocks=(),
            still_blocked_by=("the impact cannot be computed until the reading is stated",),
            notes=(
                "Deliberately NOT modelled. Precomputing an impact for an unstated "
                "reading would mean inventing the reading, and the placeholder would "
                "then be mistaken for an analysis. This row exists to record that the "
                "option is open and its consequences are unknown.",
            ),
        )
    )

    return tuple(impacts)
