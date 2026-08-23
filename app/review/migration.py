"""Planning a gold_v2 without creating one, and without touching gold_v1.

A reviewer's answer to FOCUS-001 may invalidate labels. Acting on that is a
regeneration, and regenerations are where frozen data quietly stops being frozen:
the tempting move is to fix the affected cases in place, because only 23 of 156
change and editing 23 rows looks smaller than rebuilding a dataset.

It is not smaller. gold_v1 is the record of what was measured; editing it makes
every committed report describe a set that no longer exists. So this module plans
the migration and **creates nothing**. It has no write path at all - not to
gold_v1, not to gold_v2, not to a manifest. `plan_migration` returns a description.

The planner supports all four outcomes rather than the expected one. Modelling only
the likely answer is how the unlikely answer becomes the expensive surprise.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from app.review.focus_impact import FocusOutcome

__all__ = [
    "CaseMigration",
    "MigrationPlan",
    "plan_migration",
]


@dataclass(frozen=True, slots=True)
class CaseMigration:
    """What one case would need. A description, never an instruction executed here."""

    case_id: str
    reason: str
    criteria_removed: tuple[str, ...] = ()
    criteria_added: tuple[str, ...] = ()
    expected_decision_may_change: bool = False


@dataclass(frozen=True, slots=True)
class MigrationPlan:
    """Everything a gold_v2 would require, and everything it must not touch."""

    outcome: FocusOutcome
    required: bool
    from_version: str
    to_version: str | None
    cases_total: int = 0
    cases_migrated: tuple[CaseMigration, ...] = ()
    criteria_changed: tuple[str, ...] = ()
    criteria_added: tuple[str, ...] = ()
    policy_semantics_changed: tuple[str, ...] = ()
    evidence_changes: tuple[str, ...] = ()
    evaluation_changes: tuple[str, ...] = ()
    #: Artefacts the migration must leave untouched. Enumerated so the guarantee is
    #: checkable rather than a promise in a docstring.
    must_not_modify: tuple[str, ...] = ()
    steps: tuple[str, ...] = ()
    notes: tuple[str, ...] = field(default_factory=tuple)

    @property
    def cases_unchanged(self) -> int:
        return self.cases_total - len(self.cases_migrated)

    @property
    def is_additive(self) -> bool:
        """A migration is additive when it creates a new version and edits none.

        `to_version` differing from `from_version` is necessary and not sufficient;
        the `must_not_modify` list is what says the old one survives.
        """
        return (
            not self.required
            or (self.to_version is not None and self.to_version != self.from_version)
        ) and bool(self.must_not_modify or not self.required)

    @property
    def summary(self) -> str:
        if not self.required:
            return f"{self.outcome.value}: no migration required"
        return (
            f"{self.outcome.value}: {self.from_version} -> {self.to_version}, "
            f"{len(self.cases_migrated)} of {self.cases_total} case(s) migrated, "
            f"{self.cases_unchanged} carried forward unchanged"
        )


#: Artefacts a migration may never write to. gold_v1 and its manifest are obvious;
#: the reports and prior manifests matter just as much, because a report describing
#: a dataset that has since changed is worse than no report - it reads as evidence.
IMMUTABLE = (
    "data/gold/cases/gold_v1.jsonl",
    "data/gold/manifests/gold_v1.manifest.json",
    "data/synthetic/cases/cases.jsonl",
    "eval/reports/**",
    "eval/datasets/retrieval/questions.yaml",
    "eval/datasets/retrieval_v2/questions.yaml",
)


def _affected(cases: tuple[dict[str, Any], ...], criterion_id: str) -> tuple[dict[str, Any], ...]:
    return tuple(
        case
        for case in cases
        if any(entry["criterion_id"] == criterion_id for entry in case["expected"]["criteria"])
    )


def plan_migration(
    outcome: FocusOutcome,
    *,
    gold_cases: tuple[dict[str, Any], ...],
    c03_id: str = "42_CFR_410_32_2026_08_13_C03",
    from_version: str = "gold_v1",
) -> MigrationPlan:
    """What a gold_v2 would require under one outcome. **Creates nothing.**

    Every outcome is modelled, including the two that require no migration. A
    planner that returned nothing for those would make "no plan" and "not yet
    planned" indistinguishable.
    """
    affected = _affected(gold_cases, c03_id)
    common_steps = (
        "1. Record the accepted FOCUS-001 decision and its reviewer attribution.",
        "2. Update the transcription for 42 CFR 410.32 and re-run the span gate; "
        "it must pass with zero failures before anything downstream runs.",
        "3. Regenerate cases from data/synthetic/cases/cases.jsonl through the SAME "
        "pipeline, into gold_v2. Never hand-edit a case.",
        "4. Reproduce the split rule byte-for-byte: stratify by (policy, revision, "
        "category); order within a stratum by int(sha256(case_id)[:8], 16); take "
        "DEV_FRACTION=0.18 and VALIDATION_FRACTION=0.10 as exact counts.",
        "5. Write gold_v2.manifest.json with supersedes_reason naming the FOCUS-001 "
        "decision, and reset the scoring budget - budget is per version.",
        "6. Leave gold_v1 in place. Reports keep pointing at the version they scored.",
    )

    if outcome is FocusOutcome.LEAVE_C03_NOT_ADJUDICABLE:
        return MigrationPlan(
            outcome=outcome,
            required=False,
            from_version=from_version,
            to_version=None,
            cases_total=len(gold_cases),
            must_not_modify=IMMUTABLE,
            notes=(
                "C03 is unchanged, so no label was computed against a criterion that "
                "no longer exists in that form. Nothing migrates.",
                "42 CFR 410.32 stays inadmissible and every case on it stays "
                "non-adjudicable. Costing nothing is not the same as achieving "
                "nothing - it is a legitimate answer that leaves the corpus honest.",
            ),
        )

    if outcome is FocusOutcome.OTHER:
        return MigrationPlan(
            outcome=outcome,
            required=False,
            from_version=from_version,
            to_version=None,
            cases_total=len(gold_cases),
            must_not_modify=IMMUTABLE,
            notes=(
                "The reading is not stated, so the migration cannot be planned. "
                "Producing a placeholder plan would mean inventing the reading, and "
                "the placeholder would then be mistaken for preparation.",
                "Re-run this planner once the reviewer's reading is recorded.",
            ),
        )

    if outcome is FocusOutcome.NARROW_C03_TO_BASELINE:
        migrations = tuple(
            CaseMigration(
                case_id=case["case_id"],
                reason=(
                    "references C03, which is restated as the supervision floor; the "
                    "criterion the label was computed against no longer exists in "
                    "that form"
                ),
                expected_decision_may_change=True,
            )
            for case in affected
        )
        return MigrationPlan(
            outcome=outcome,
            required=bool(migrations),
            from_version=from_version,
            to_version="gold_v2",
            cases_total=len(gold_cases),
            cases_migrated=migrations,
            criteria_changed=(c03_id,),
            policy_semantics_changed=("42 CFR 410.32:2026-08-13",),
            evidence_changes=(
                "C03's evidence set narrows to the (b)(3) baseline sentence",
                "the (b)(3)(i)-(iii) definitions remain retrievable as context, not "
                "as the criterion's own evidence",
            ),
            evaluation_changes=(
                "retrieval queries targeting C03 now target a narrower criterion: the "
                "query text is unchanged and what counts as the right answer is not",
                "any report scored against the affected cases describes gold_v1 and "
                "must keep saying so",
            ),
            must_not_modify=IMMUTABLE,
            steps=common_steps,
            notes=(
                f"{len(migrations)} of {len(gold_cases)} case(s) migrate; the rest "
                "carry forward byte-for-byte.",
                "A narrowed C03 checks LESS than the criterion it replaces. That is "
                "the reviewer's call and it is not reversed by the migration.",
            ),
        )

    # SPLIT_C03
    escalation = f"{c03_id}_ESCALATION"
    migrations = tuple(
        CaseMigration(
            case_id=case["case_id"],
            reason=(
                "references C03, which becomes two criteria; every case needs a state "
                "for both halves, so this is a regeneration rather than a relabelling"
            ),
            criteria_added=(escalation,),
            expected_decision_may_change=True,
        )
        for case in affected
    )
    return MigrationPlan(
        outcome=FocusOutcome.SPLIT_C03,
        required=bool(migrations),
        from_version=from_version,
        to_version="gold_v2",
        cases_total=len(gold_cases),
        cases_migrated=migrations,
        criteria_changed=(c03_id,),
        criteria_added=(escalation,),
        policy_semantics_changed=("42 CFR 410.32:2026-08-13",),
        evidence_changes=(
            "the baseline half draws on the (b)(3) floor sentence",
            "the escalation half has NO evidence in this corpus; the physician fee "
            "schedule supervision indicator is not part of 42 CFR",
        ),
        evaluation_changes=(
            "criterion count rises, so every affected case needs a state for a "
            "criterion that did not exist when it was generated",
            "the escalation criterion inherits C03's dependency, so 410.32 does not "
            "become admissible by this migration alone",
        ),
        must_not_modify=IMMUTABLE,
        steps=(
            *common_steps,
            "7. Record that the escalation criterion is not determinable from this "
            "corpus, so the admissibility gate keeps refusing 410.32 until a further "
            "decision excludes it from adjudication.",
        ),
        notes=(
            f"{len(migrations)} of {len(gold_cases)} case(s) migrate.",
            "Costs a gold_v2 AND does not unblock the policy. Splitting relocates the "
            "blocker rather than removing it - which is the honest reading of a gap "
            "the regulation genuinely leaves.",
        ),
    )
