"""The case lifecycle, as a machine that refuses illegal moves.

`CaseState` already existed as an enum. An enum is a vocabulary, not a machine: any
member could follow any other, so "FINALIZED, then back to RUNNING" was expressible and
nothing objected. This module is the missing half.

## Transitions are a table, not a chain of `if`s

`_ALLOWED` maps each state to the states that may follow it. A branch is somewhere to
add an exception to; a table is checked for totality by a test, and a state added to the
enum without an entry here fails that test rather than silently becoming a dead end.

## The two properties worth stating

**Terminal means terminal.** `FINALIZED` and `FAILED` have empty successor sets, so a
finalised case cannot be reopened by any code path. A reviewer who changes their mind
files a new review event; the case does not travel backwards.

**A recommendation is not a disposition.** `RECOMMENDATION_READY` cannot reach
`FINALIZED` directly - it must pass through `HUMAN_REVIEW`. That is the architecture's
central claim expressed as a graph property: this system produces recommendations for a
human, and there is no edge that lets one become an outcome on its own.

## Failure is always reachable

Every non-terminal state may go to `FAILED`. A machine that could get stuck with no legal
exit would eventually be worked around by a caller writing the column directly, which
is how state machines become decorative.
"""

from __future__ import annotations

from enum import StrEnum

from app.core.errors import MedauthError

__all__ = [
    "TERMINAL_STATES",
    "CaseState",
    "InvalidTransition",
    "allowed_next",
    "is_terminal",
    "require_transition",
]


class CaseState(StrEnum):
    """Where a case is.

    Deliberately fewer states than the brief's example list. `VALIDATING` and
    `APPLICABILITY_PENDING` are moments inside a single synchronous call, not states a
    case can be observed in or recovered from; modelling them would produce rows nobody
    can ever see and transitions nobody can ever exercise. What survives is what a
    reader of the table can actually find a case sitting in.
    """

    #: Accepted and persisted. Nothing has run.
    RECEIVED = "RECEIVED"
    #: The pipeline is executing. A case found here after a crash is recoverable.
    PROCESSING = "PROCESSING"
    #: Applicability resolved and the engine decided. **Not a disposition.**
    RECOMMENDATION_READY = "RECOMMENDATION_READY"
    #: The submitter can close this: a question was asked of them.
    NEEDS_INFO = "NEEDS_INFO"
    #: Routed to a person - abstention, provider failure, or a denial draft.
    HUMAN_REVIEW = "HUMAN_REVIEW"
    #: A named reviewer acted. Terminal.
    FINALIZED = "FINALIZED"
    #: The run could not complete. Terminal, and never a clinical outcome.
    FAILED = "FAILED"


#: No successors. Reachable, and then nothing.
TERMINAL_STATES: frozenset[CaseState] = frozenset({CaseState.FINALIZED, CaseState.FAILED})


#: Every state's legal successors. Total over `CaseState`, asserted by test.
_ALLOWED: dict[CaseState, frozenset[CaseState]] = {
    CaseState.RECEIVED: frozenset(
        {
            CaseState.PROCESSING,
            # Applicability refused before any model call: no policy, conflicting
            # policies, or not enough information to resolve one.
            CaseState.NEEDS_INFO,
            CaseState.HUMAN_REVIEW,
            CaseState.FAILED,
        }
    ),
    CaseState.PROCESSING: frozenset(
        {
            CaseState.RECOMMENDATION_READY,
            CaseState.NEEDS_INFO,
            CaseState.HUMAN_REVIEW,
            CaseState.FAILED,
        }
    ),
    # **No edge to FINALIZED.** A recommendation becomes a disposition only by passing
    # through a person. This is the invariant the whole architecture rests on, and it
    # is a graph property here rather than a rule somebody remembers.
    CaseState.RECOMMENDATION_READY: frozenset({CaseState.HUMAN_REVIEW, CaseState.FAILED}),
    # A submitter answering the question puts the case back in the queue.
    CaseState.NEEDS_INFO: frozenset(
        {CaseState.PROCESSING, CaseState.HUMAN_REVIEW, CaseState.FAILED}
    ),
    CaseState.HUMAN_REVIEW: frozenset(
        {CaseState.FINALIZED, CaseState.NEEDS_INFO, CaseState.FAILED}
    ),
    CaseState.FINALIZED: frozenset(),
    CaseState.FAILED: frozenset(),
}


class InvalidTransition(MedauthError):
    """An illegal state change was attempted.

    A `MedauthError` so the API's existing handler maps it, and the route does not need
    to know that a 409 is the right answer - `app/api/v1/errors.py` decides that once.
    """

    def __init__(self, current: CaseState, requested: CaseState) -> None:
        self.current = current
        self.requested = requested
        legal = ", ".join(sorted(s.value for s in _ALLOWED[current])) or "none (terminal)"
        super().__init__(
            f"{current.value} -> {requested.value} is not a legal case transition; "
            f"legal from {current.value}: {legal}"
        )


def allowed_next(state: CaseState) -> frozenset[CaseState]:
    """The states that may legally follow `state`."""
    return _ALLOWED[state]


def is_terminal(state: CaseState) -> bool:
    return state in TERMINAL_STATES


def require_transition(current: CaseState, requested: CaseState) -> CaseState:
    """Return `requested`, or raise. **The only supported way to change state.**

    Raises rather than returning a boolean, for the reason `require()` does elsewhere in
    this repository: a boolean is something a caller forgets, and the caller here is a
    service writing a row.
    """
    if requested not in _ALLOWED[current]:
        raise InvalidTransition(current, requested)
    return requested
