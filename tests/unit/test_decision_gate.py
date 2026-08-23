"""A domain decision cannot be faked, defaulted, or reached in one step.

The risk is not that someone answers FOCUS-001 wrongly. It is that a later change
makes it *appear* answered — a default that reads as approval, a status that
advances when a pipeline runs, an "engineering acceptance" that quietly becomes the
decision. Every test here is a way of closing one of those routes.
"""

from __future__ import annotations

import inspect
from datetime import date

import pytest

from app.review.decision_gate import (
    DecisionGate,
    DecisionStatus,
    GateError,
    ReviewerIdentity,
)
from app.review.focus_impact import FocusOutcome, analyse_focus_001

pytestmark = [pytest.mark.unit, pytest.mark.security]

OPTIONS = tuple(outcome.value for outcome in FocusOutcome)
REVIEWER = ReviewerIdentity(reviewer_id="reviewer-1", qualification="coverage analyst")


def _gate() -> DecisionGate:
    return DecisionGate.pending(
        focus_id="FOCUS-001",
        question="Can C03 be adjudicated from this regulation alone?",
        policy_id="42 CFR 410.32",
        policy_version="2026-08-13",
        permitted_decisions=OPTIONS,
    )


def _submitted() -> DecisionGate:
    return _gate().submit(
        reviewer=REVIEWER,
        decision=FocusOutcome.NARROW_C03_TO_BASELINE.value,
        rationale="the floor is determinable and the escalation is out of scope",
        on=date(2026, 9, 1),
    )


# ---------------------------------------------------------------------------
# The default is unanswered
# ---------------------------------------------------------------------------


def test_a_new_gate_is_pending_and_blocks_production() -> None:
    gate = _gate()
    assert gate.status is DecisionStatus.PENDING
    assert not gate.is_resolved
    assert gate.blocks_production
    assert gate.reviewer is None
    assert gate.reviewer_decision is None


def test_there_is_no_constructor_that_yields_an_accepted_gate() -> None:
    """`pending()` is the only entry point, and its name says what it produces.

    A `DecisionGate.accepted(...)` classmethod would be one import away from a
    script that opens the gate by construction.
    """
    constructors = [
        name
        for name, member in inspect.getmembers(DecisionGate)
        if isinstance(inspect.getattr_static(DecisionGate, name, None), classmethod)
    ]
    assert constructors == ["pending"]


def test_only_accepted_resolves_the_gate() -> None:
    """Rejected is an answer and is not a resolution.

    It means the reviewer declined the framing, which leaves production exactly as
    blocked as it was.
    """
    for status in DecisionStatus:
        assert status.resolves_gate is (status is DecisionStatus.ACCEPTED)


def test_no_status_reads_as_provisional_progress() -> None:
    """No `ENGINEERING_ACCEPTED`, no `PROVISIONAL`, no `ASSUMED`.

    Each would be a state that reads as progress while meaning nobody qualified has
    answered — which is the whole thing the gate exists to prevent.
    """
    values = {status.value for status in DecisionStatus}
    assert not any(
        token in value
        for value in values
        for token in ("ENGINEERING", "PROVISIONAL", "ASSUMED", "AUTO")
    )


# ---------------------------------------------------------------------------
# Submission requires a real answer
# ---------------------------------------------------------------------------


def test_a_reviewer_must_name_themselves_and_their_standing() -> None:
    """A later reader must be able to weigh who answered, not just that someone did."""
    with pytest.raises(GateError, match="no identity"):
        ReviewerIdentity(reviewer_id="  ", qualification="coverage analyst")
    with pytest.raises(GateError, match="no qualification"):
        ReviewerIdentity(reviewer_id="reviewer-1", qualification="   ")


def test_a_decision_outside_the_option_set_is_refused() -> None:
    """The option set is closed so an answer cannot quietly change the question."""
    with pytest.raises(GateError, match="is not one of"):
        _gate().submit(
            reviewer=REVIEWER,
            decision="LOOKS_FINE",
            rationale="seems reasonable",
            on=date(2026, 9, 1),
        )


def test_a_decision_with_no_rationale_is_refused() -> None:
    with pytest.raises(GateError, match="no rationale"):
        _gate().submit(
            reviewer=REVIEWER,
            decision=FocusOutcome.SPLIT_C03.value,
            rationale="   ",
            on=date(2026, 9, 1),
        )


def test_a_hand_built_answered_gate_without_a_reviewer_is_refused() -> None:
    """The transitions are not the only route to a value; construction is too."""
    with pytest.raises(GateError, match="no reviewer"):
        DecisionGate(
            focus_id="FOCUS-001",
            question="q",
            policy_id="p",
            policy_version="v",
            permitted_decisions=OPTIONS,
            status=DecisionStatus.ACCEPTED,
            reviewer_decision=FocusOutcome.SPLIT_C03.value,
            reviewer_rationale="because",
            accepted_by="someone",
        )


def test_a_hand_built_accepted_gate_with_nobody_accepting_is_refused() -> None:
    with pytest.raises(GateError, match="nobody recorded as accepting"):
        DecisionGate(
            focus_id="FOCUS-001",
            question="q",
            policy_id="p",
            policy_version="v",
            permitted_decisions=OPTIONS,
            status=DecisionStatus.ACCEPTED,
            reviewer=REVIEWER,
            reviewer_decision=FocusOutcome.SPLIT_C03.value,
            reviewer_rationale="because",
        )


# ---------------------------------------------------------------------------
# One step cannot open the gate
# ---------------------------------------------------------------------------


def test_submission_does_not_resolve_the_gate() -> None:
    """The load-bearing separation.

    A single forged or mistaken call produces `SUBMITTED`, which unblocks nothing.
    Reaching an admissible state needs a second, separately-attributed act.
    """
    submitted = _submitted()
    assert submitted.status is DecisionStatus.SUBMITTED
    assert not submitted.is_resolved
    assert submitted.blocks_production


def test_acceptance_requires_naming_who_accepted() -> None:
    with pytest.raises(GateError, match="nobody recorded"):
        _submitted().accept(accepted_by="  ")


def test_acceptance_resolves_and_is_the_only_thing_that_does() -> None:
    """The positive control. If nothing could ever open the gate, the refusals
    above would prove nothing about a working mechanism."""
    accepted = _submitted().accept(accepted_by="maintainer")
    assert accepted.status is DecisionStatus.ACCEPTED
    assert accepted.is_resolved
    assert not accepted.blocks_production
    assert accepted.reviewer_decision == FocusOutcome.NARROW_C03_TO_BASELINE.value


def test_a_rejected_decision_leaves_the_gate_shut() -> None:
    rejected = _submitted().reject(reason="the reading does not follow from the text")
    assert rejected.status is DecisionStatus.REJECTED
    assert not rejected.is_resolved
    assert rejected.blocks_production
    # The answer is kept, not erased.
    assert rejected.reviewer_decision == FocusOutcome.NARROW_C03_TO_BASELINE.value


@pytest.mark.parametrize("method", ["accept", "reject"])
def test_a_pending_gate_cannot_be_accepted_or_rejected_directly(method: str) -> None:
    """Skipping submission would be a one-step route to an admissible state."""
    kwargs = {"accepted_by": "x"} if method == "accept" else {"reason": "x"}
    with pytest.raises(GateError, match="only a SUBMITTED"):
        getattr(_gate(), method)(**kwargs)


def test_a_decided_gate_cannot_be_resubmitted_over() -> None:
    """A new answer supersedes the old one rather than overwriting it."""
    with pytest.raises(GateError, match="cannot submit against"):
        _submitted().submit(
            reviewer=REVIEWER,
            decision=FocusOutcome.SPLIT_C03.value,
            rationale="changed my mind",
            on=date(2026, 9, 2),
        )


def test_superseding_requires_a_reason() -> None:
    with pytest.raises(GateError, match="no recorded reason"):
        _submitted().supersede(reason="  ")


# ---------------------------------------------------------------------------
# The four-way impact model
# ---------------------------------------------------------------------------


GOLD = (
    {
        "case_id": "G1",
        "expected": {
            "policy_id": "42 CFR 410.32",
            "policy_revision": "2026-08-13",
            "criteria": [{"criterion_id": "42_CFR_410_32_2026_08_13_C03"}],
        },
    },
    {
        "case_id": "G2",
        "expected": {
            "policy_id": "42 CFR 410.32",
            "policy_revision": "2026-08-13",
            "criteria": [{"criterion_id": "42_CFR_410_32_2026_08_13_C01"}],
        },
    },
)


def _impacts(other_blockers: tuple[str, ...] = ()) -> dict[str, object]:
    return {
        impact.outcome: impact
        for impact in analyse_focus_001(
            gold_cases=GOLD, synthetic_cases=(), other_blockers=other_blockers
        )
    }


def test_every_permitted_outcome_is_modelled() -> None:
    assert set(_impacts()) == set(FocusOutcome)


def test_the_impact_model_is_deterministic() -> None:
    """Same inputs, same table. A reviewer must be able to re-derive it."""
    first = analyse_focus_001(gold_cases=GOLD, synthetic_cases=(), other_blockers=())
    second = analyse_focus_001(gold_cases=GOLD, synthetic_cases=(), other_blockers=())
    assert first == second


def test_only_outcomes_that_change_c03_force_a_new_frozen_dataset() -> None:
    """A decision that changes nothing invalidates nothing."""
    impacts = _impacts()
    assert impacts[FocusOutcome.NARROW_C03_TO_BASELINE].gold_v2_required
    assert impacts[FocusOutcome.SPLIT_C03].gold_v2_required
    assert not impacts[FocusOutcome.LEAVE_C03_NOT_ADJUDICABLE].gold_v2_required
    assert not impacts[FocusOutcome.OTHER].gold_v2_required


def test_only_cases_referencing_c03_are_reported_as_affected() -> None:
    """G2 sits on the same policy and does not reference C03. Reporting it would
    overstate the blast radius, which is how a reviewer talks themselves out of the
    more expensive reading."""
    impact = _impacts()[FocusOutcome.NARROW_C03_TO_BASELINE]
    assert impact.gold_cases_affected == ("G1",)
    assert impact.gold_cases_affected_count == 1


def test_splitting_relocates_the_blocker_rather_than_removing_it() -> None:
    """The escalation half is still not determinable from this corpus.

    Reporting SPLIT_C03 as admissible would be the analysis telling the reviewer
    something false about the option that preserves the most checking.
    """
    impact = _impacts()[FocusOutcome.SPLIT_C03]
    assert not impact.policy_admissible_after
    assert any("inherits the dependency" in reason for reason in impact.still_blocked_by)


def test_other_blockers_propagate_into_every_outcome() -> None:
    """If the gate grows a condition this policy also fails, it shows up here.

    Otherwise a reviewer answers FOCUS-001, expects admissibility, and discovers a
    second blocker at the moment the slice is attempted.
    """
    impacts = _impacts(other_blockers=("citation_provenance_complete",))
    narrowed = impacts[FocusOutcome.NARROW_C03_TO_BASELINE]
    assert not narrowed.policy_admissible_after
    assert "citation_provenance_complete" in narrowed.still_blocked_by
    assert narrowed.unblocks == ()


def test_the_other_outcome_is_not_modelled_and_says_so() -> None:
    """Precomputing an impact for an unstated reading would mean inventing one."""
    impact = _impacts()[FocusOutcome.OTHER]
    assert not impact.policy_admissible_after
    assert any("NOT modelled" in note for note in impact.notes)
    assert any("cannot be computed" in reason for reason in impact.still_blocked_by)


def test_the_model_states_costs_without_recommending() -> None:
    """Each outcome carries what it gives up as well as what it buys.

    An impact table that listed only benefits would be an argument dressed as an
    analysis - and the cheapest option here is also the one that checks least.
    """
    impacts = _impacts()
    narrowed = impacts[FocusOutcome.NARROW_C03_TO_BASELINE]
    assert any("REDUCES what the system checks" in note for note in narrowed.notes)
    split = impacts[FocusOutcome.SPLIT_C03]
    assert any("PRESERVES what the system checks" in note for note in split.notes)
    left = impacts[FocusOutcome.LEAVE_C03_NOT_ADJUDICABLE]
    assert any("legitimate answer" in note for note in left.notes)
