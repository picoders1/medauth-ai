"""The case state machine, and the one edge that must not exist.

`CaseState` was an enum before this phase - a vocabulary, not a machine. Any member
could follow any other. These tests are about the half that was missing.

The load-bearing one is
`test_a_recommendation_cannot_become_a_disposition_without_a_human`. It is this
project's central claim expressed as a graph property, so if the edge is ever added the
failure should read as a design change and not as a broken assertion.
"""

from __future__ import annotations

import pytest

from app.case.lifecycle import (
    TERMINAL_STATES,
    CaseState,
    InvalidTransition,
    allowed_next,
    is_terminal,
    require_transition,
)

pytestmark = pytest.mark.unit


def test_the_transition_table_is_total_over_the_enum() -> None:
    """A state added without an entry becomes a silent dead end. This is the check
    instead of that."""
    for state in CaseState:
        assert allowed_next(state) is not None, f"{state.value} has no entry"


def test_a_recommendation_cannot_become_a_disposition_without_a_human() -> None:
    """**The load-bearing test.**

    `RECOMMENDATION_READY -> FINALIZED` must not exist. This system produces
    recommendations for a human reviewer; an edge that let one finish on its own would
    make it a system that issues determinations, which is the thing every phase of this
    project has been built not to be.
    """
    assert CaseState.FINALIZED not in allowed_next(CaseState.RECOMMENDATION_READY)
    with pytest.raises(InvalidTransition):
        require_transition(CaseState.RECOMMENDATION_READY, CaseState.FINALIZED)
    # And the only route onward is through a person.
    assert CaseState.HUMAN_REVIEW in allowed_next(CaseState.RECOMMENDATION_READY)


def test_finalized_is_reachable_so_the_test_above_is_not_vacuous() -> None:
    """A machine where nothing could ever finalise would pass the assertion above and
    be useless."""
    assert CaseState.FINALIZED in allowed_next(CaseState.HUMAN_REVIEW)
    assert require_transition(CaseState.HUMAN_REVIEW, CaseState.FINALIZED) is CaseState.FINALIZED


@pytest.mark.parametrize("state", sorted(TERMINAL_STATES, key=lambda s: s.value))
def test_a_terminal_state_has_no_exit(state: CaseState) -> None:
    """A finalised case cannot be reopened by any code path. A reviewer who changes
    their mind files a new review event; the case does not travel backwards."""
    assert allowed_next(state) == frozenset()
    assert is_terminal(state)
    for target in CaseState:
        with pytest.raises(InvalidTransition):
            require_transition(state, target)


def test_failure_is_reachable_from_every_live_state() -> None:
    """A machine that could get stuck with no legal exit would be worked around by
    somebody writing the column directly, which is how state machines become
    decorative."""
    for state in CaseState:
        if is_terminal(state):
            continue
        assert CaseState.FAILED in allowed_next(state), f"{state.value} cannot fail"


def test_a_failed_case_is_never_a_clinical_outcome() -> None:
    """`FAILED` must not reach `FINALIZED`. A crashed run that could finalise would
    turn an outage into a disposition."""
    assert CaseState.FINALIZED not in allowed_next(CaseState.FAILED)


def test_an_illegal_transition_names_what_was_legal() -> None:
    """The error is read by whoever has to fix the caller."""
    with pytest.raises(InvalidTransition) as raised:
        require_transition(CaseState.RECEIVED, CaseState.FINALIZED)
    message = str(raised.value)
    assert "RECEIVED -> FINALIZED" in message
    assert "PROCESSING" in message, "the error does not say what would have been legal"


def test_a_legal_transition_returns_the_target() -> None:
    assert require_transition(CaseState.RECEIVED, CaseState.PROCESSING) is CaseState.PROCESSING
    assert require_transition(CaseState.PROCESSING, CaseState.NEEDS_INFO) is CaseState.NEEDS_INFO


def test_needs_info_can_return_to_processing() -> None:
    """A submitter answering the question puts the case back in the queue, rather than
    the case being stuck because someone asked for more."""
    assert CaseState.PROCESSING in allowed_next(CaseState.NEEDS_INFO)


def test_applicability_can_refuse_before_any_model_call() -> None:
    """`RECEIVED` reaches `NEEDS_INFO` and `HUMAN_REVIEW` directly: no applicable
    policy, conflicting policies, or not enough information to resolve one. None of
    those should cost a model call."""
    assert {CaseState.NEEDS_INFO, CaseState.HUMAN_REVIEW} <= allowed_next(CaseState.RECEIVED)
