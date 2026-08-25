"""The six-state applicability machine, as a truth table. R-93.

Every state is reachable here with no database, no model and no container, because
`classify()` takes counts and identities rather than a session. That split is the
whole reason this file can exist: Phase 14's applicability logic was one literal -
`ResolutionState(RESOLVED, 1)` - and a literal has no states to test.

The ten fixtures the Phase-15 brief requires are named individually rather than
parametrised into one loop. A parametrised sweep would report "10 passed" whether it
covered ten distinct situations or the same one ten times, and the point of the list
is that each situation is *different*.
"""

from __future__ import annotations

from datetime import date

import pytest

from app.core.identity import PolicyIdentity, PolicyType
from app.core.types import CodeSystem, ResolutionStatus
from app.decision.abstention import AbstentionReason, abstention_for
from app.decision.models import Outcome
from app.decision.table import _ROUTE_FOR_RESOLUTION
from app.graph.slice import _ABSTENTION_FOR_RESOLUTION
from app.policy.applicability import (
    ApplicabilityFinding,
    ApplicabilityReason,
    ApplicabilityRequest,
    CandidateCensus,
    classify,
    designated_without_resolution,
)

pytestmark = pytest.mark.unit

DESIGNATED = PolicyIdentity(
    policy_type=PolicyType.REGULATION, policy_id="42 CFR 410.33", version="2026-08-13"
)
OTHER_VERSION = PolicyIdentity(
    policy_type=PolicyType.REGULATION, policy_id="42 CFR 410.33", version="2022-01-01"
)
OTHER_POLICY = PolicyIdentity(
    policy_type=PolicyType.REGULATION, policy_id="42 CFR 410.32", version="2026-08-13"
)
AN_NCD = PolicyIdentity(policy_type=PolicyType.NCD, policy_id="NCD 220.1", version="4")

AS_OF = date(2026, 9, 28)


def request(
    code: str = "R0075",
    system: CodeSystem | None = CodeSystem.HCPCS,
    as_of: date | None = AS_OF,
    jurisdiction: str | None = None,
) -> ApplicabilityRequest:
    return ApplicabilityRequest(
        procedure_code=code, code_system=system, as_of=as_of, jurisdiction=jurisdiction
    )


# ---------------------------------------------------------------------------
# The ten fixtures the phase requires
# ---------------------------------------------------------------------------


def test_1_exactly_one_applicable_policy() -> None:
    """The only path to a model call. Everything else abstains."""
    finding = classify(
        request(),
        designated=DESIGNATED,
        applicable=(DESIGNATED,),
        census=CandidateCensus(total=1, in_force=1, in_jurisdiction=1),
    )
    assert finding.state is ResolutionStatus.RESOLVED
    assert finding.reason is ApplicabilityReason.DESIGNATED_POLICY_APPLIES
    assert finding.selected == DESIGNATED
    assert finding.version_count == 1
    assert finding.permits_adjudication


def test_2_no_applicable_policy() -> None:
    """Nothing lists the code. **NEEDS_INFO, never a denial** (ADR-004)."""
    finding = classify(request(code="99199"), designated=DESIGNATED, census=CandidateCensus())
    assert finding.state is ResolutionStatus.NOT_APPLICABLE
    assert finding.state is ResolutionStatus.NONE_APPLICABLE  # the same member
    assert finding.reason is ApplicabilityReason.NO_POLICY_LISTS_THE_PROCEDURE
    assert finding.selected is None
    assert not finding.permits_adjudication


def test_3_multiple_candidate_policies() -> None:
    """Two distinct policies apply. Which governs is a judgement, not a ranking."""
    finding = classify(
        request(),
        designated=DESIGNATED,
        applicable=(DESIGNATED, OTHER_POLICY),
        census=CandidateCensus(total=2, in_force=2, in_jurisdiction=2),
    )
    assert finding.state is ResolutionStatus.MULTIPLE_CANDIDATES
    assert finding.reason is ApplicabilityReason.SEVERAL_POLICIES_COULD_GOVERN
    assert finding.selected is None, "a state that cannot choose must not name a choice"


def test_4_wrong_policy_version() -> None:
    """Resolution selected a different revision of the same policy.

    The runtime holds criteria, a criteria tree and declared logic for ONE version.
    Adjudicating a case against a revision that was not in force when the service
    happened is the temporal failure ADR-004 exists to stop - and it is silent,
    because every citation still verifies against the document it came from.
    """
    finding = classify(
        request(),
        designated=DESIGNATED,
        applicable=(OTHER_VERSION,),
        census=CandidateCensus(total=2, in_force=1, in_jurisdiction=2),
    )
    assert finding.state is ResolutionStatus.RESOLUTION_ERROR
    assert finding.reason is ApplicabilityReason.RESOLVED_VERSION_IS_NOT_THE_DESIGNATED_ONE
    assert not finding.permits_adjudication


def test_5_future_policy_version() -> None:
    """The corpus holds the policy; no version was in force on the date of service.

    Reported as `TEMPORALLY_UNRESOLVED` rather than as "no policy applies", and the
    difference is not cosmetic: one says the request is uncovered, the other says
    the system cannot place it in a window. A reviewer's next action differs.
    """
    finding = classify(
        request(as_of=date(2020, 1, 1)),
        designated=DESIGNATED,
        applicable=(),
        census=CandidateCensus(total=2, in_force=0, in_jurisdiction=2),
    )
    assert finding.state is ResolutionStatus.TEMPORALLY_UNRESOLVED
    assert finding.reason is ApplicabilityReason.NO_VERSION_IN_FORCE_ON_THAT_DATE


def test_6_historical_valid_policy() -> None:
    """A superseded revision that WAS in force on the date of service resolves.

    Version selection is by date of service, never "latest". A runtime designated
    for the historical revision and handed a historical date must proceed - refusing
    would make every retrospective review unresolvable.
    """
    finding = classify(
        request(as_of=date(2023, 6, 1)),
        designated=OTHER_VERSION,
        applicable=(OTHER_VERSION,),
        census=CandidateCensus(total=2, in_force=1, in_jurisdiction=2),
    )
    assert finding.state is ResolutionStatus.RESOLVED
    assert finding.selected == OTHER_VERSION


def test_7_insufficient_procedure_information() -> None:
    """No procedure code. Applicability has nothing to key on, so it asks."""
    finding = classify(request(code="   "), designated=DESIGNATED)
    assert finding.state is ResolutionStatus.INSUFFICIENT_INFORMATION
    assert finding.reason is ApplicabilityReason.NO_PROCEDURE_CODE
    assert abstention_for(_ABSTENTION_FOR_RESOLUTION[finding.state]).outcome is Outcome.NEEDS_INFO


def test_8_ambiguous_procedure() -> None:
    """A bare code with no code system names different procedures in different systems.

    Guessing a system would pick a policy by coincidence, and the coincidence would
    be invisible downstream - the resolved policy is real, its text is real, and
    nothing later in the chain knows the question was ambiguous.
    """
    finding = classify(request(system=None), designated=DESIGNATED)
    assert finding.state is ResolutionStatus.INSUFFICIENT_INFORMATION
    assert finding.reason is ApplicabilityReason.CODE_SYSTEM_NOT_STATED


def test_9_policy_type_mismatch() -> None:
    """An NCD governs; this runtime adjudicates a regulation.

    Separate from "wrong version" because the layers of authority are different
    claims: a regulation states statutory conditions of payment, an NCD makes a
    national coverage determination, and one does not stand in for the other.
    """
    finding = classify(
        request(),
        designated=DESIGNATED,
        applicable=(AN_NCD,),
        census=CandidateCensus(total=1, in_force=1, in_jurisdiction=1),
    )
    assert finding.state is ResolutionStatus.RESOLUTION_ERROR
    assert finding.reason is ApplicabilityReason.RESOLVED_POLICY_TYPE_DIFFERS


def test_10_jurisdiction_mismatch() -> None:
    """Policies list the code and none reaches this jurisdiction.

    Still `NOT_APPLICABLE` - absence of a local determination is contractor
    discretion - but with a reason that says which absence it is.
    """
    finding = classify(
        request(jurisdiction="J-K"),
        designated=DESIGNATED,
        applicable=(),
        census=CandidateCensus(total=3, in_force=3, in_jurisdiction=0),
    )
    assert finding.state is ResolutionStatus.NOT_APPLICABLE
    assert finding.reason is ApplicabilityReason.NO_POLICY_IN_THIS_JURISDICTION


# ---------------------------------------------------------------------------
# The remaining states, and the properties that hold across all of them
# ---------------------------------------------------------------------------


def test_no_date_of_service_cannot_apply_any_version_window() -> None:
    finding = classify(request(as_of=None), designated=DESIGNATED)
    assert finding.state is ResolutionStatus.INSUFFICIENT_INFORMATION
    assert finding.reason is ApplicabilityReason.NO_DATE_OF_SERVICE


def test_a_resolver_failure_is_not_reported_as_a_coverage_answer() -> None:
    """ "The database was down" must never reach a reviewer as "nothing covers this"."""
    finding = classify(request(), designated=DESIGNATED, error="ConnectionError: refused")
    assert finding.state is ResolutionStatus.RESOLUTION_ERROR
    assert finding.reason is ApplicabilityReason.RESOLVER_FAILED
    assert "ConnectionError" in finding.notes[0]


def test_overlapping_corpus_versions_are_a_conflict_not_a_choice() -> None:
    finding = classify(
        request(),
        designated=DESIGNATED,
        applicable=(DESIGNATED,),
        census=CandidateCensus(total=2, in_force=2, in_jurisdiction=2),
        conflicts=("Corpus defect: overlapping in-force versions",),
    )
    assert finding.state is ResolutionStatus.MULTIPLE_CANDIDATES
    assert finding.reason is ApplicabilityReason.CORPUS_VERSIONS_OVERLAP


def test_a_conflict_outranks_an_otherwise_clean_resolution() -> None:
    """Non-vacuity for the test above.

    Its `applicable` tuple holds exactly the designated policy, so without the
    conflict it would resolve. That is what makes it evidence that the conflict
    check fires rather than evidence that something else refused first.
    """
    finding = classify(
        request(),
        designated=DESIGNATED,
        applicable=(DESIGNATED,),
        census=CandidateCensus(total=2, in_force=2, in_jurisdiction=2),
    )
    assert finding.state is ResolutionStatus.RESOLVED


def test_only_resolved_permits_adjudication() -> None:
    """Over the whole state space, not over the members somebody listed."""
    for state in ResolutionStatus:
        assert state.permits_adjudication is (state is ResolutionStatus.RESOLVED)


def test_a_resolved_finding_cannot_name_a_policy_it_was_not_wired_for() -> None:
    """The invariant is enforced at construction, so it cannot be forgotten."""
    with pytest.raises(ValueError, match="R-93"):
        ApplicabilityFinding(
            state=ResolutionStatus.RESOLVED,
            reason=ApplicabilityReason.DESIGNATED_POLICY_APPLIES,
            designated=DESIGNATED,
            selected=OTHER_POLICY,
        )


def test_a_resolved_finding_must_name_what_it_resolved_to() -> None:
    with pytest.raises(ValueError, match="RESOLVED with no selected version"):
        ApplicabilityFinding(
            state=ResolutionStatus.RESOLVED,
            reason=ApplicabilityReason.DESIGNATED_POLICY_APPLIES,
            designated=DESIGNATED,
        )


def test_a_census_subset_cannot_exceed_its_total() -> None:
    """A filter counting more rows than the unfiltered query is not a filter."""
    with pytest.raises(ValueError, match="exceed the total"):
        CandidateCensus(total=1, in_force=2, in_jurisdiction=0)


# ---------------------------------------------------------------------------
# Routing: total, and never toward a denial
# ---------------------------------------------------------------------------


def test_every_resolution_status_is_routed() -> None:
    """A seventh state must fail loudly rather than fall through to adjudication.

    Two mappings, checked together: the decision table's row lookup and the slice's
    abstention lookup. Both must cover every non-RESOLVED member, and neither may
    cover RESOLVED - a route for RESOLVED would mean the admitting state also had a
    refusal defined for it, and whichever was consulted first would win.
    """
    refusing = {s for s in ResolutionStatus if s is not ResolutionStatus.RESOLVED}
    assert set(_ROUTE_FOR_RESOLUTION) == refusing
    assert set(_ABSTENTION_FOR_RESOLUTION) == refusing


def test_no_resolution_route_can_produce_an_approval_or_a_denial() -> None:
    """The safety property of the whole block, asserted over the mapping."""
    definitive = {Outcome.APPROVE_RECOMMENDED, Outcome.DENY_RECOMMENDED}
    for state, (outcome, _rule) in _ROUTE_FOR_RESOLUTION.items():
        assert outcome not in definitive, f"{state.value} routes to {outcome.value}"
    for state, reason in _ABSTENTION_FOR_RESOLUTION.items():
        assert abstention_for(reason).outcome not in definitive, (
            f"{state.value} abstains into {reason.value}, which is definitive"
        )


def test_the_two_mappings_agree_on_the_outcome() -> None:
    """The table and the abstention record must not disagree about the same case.

    They are computed independently - one by `decide()`, one by `abstention_for()` -
    and the slice reports both. Two authorities that agree today and drift tomorrow
    is how an audit row ends up contradicting the recommendation it explains.
    """
    for state, (outcome, rule) in _ROUTE_FOR_RESOLUTION.items():
        record = abstention_for(_ABSTENTION_FOR_RESOLUTION[state])
        assert record.outcome is outcome, f"{state.value}: {record.outcome} != {outcome}"
        assert record.rule is rule, f"{state.value}: {record.rule} != {rule}"


def test_absence_of_a_policy_is_never_a_denial() -> None:
    """Stated on its own because it is the single most harmful thing to get wrong.

    Absence of an NCD or LCD generally means contractor discretion. A system that
    learned to read it as non-coverage would deny people for the corpus's gaps.
    """
    outcome, rule = _ROUTE_FOR_RESOLUTION[ResolutionStatus.NOT_APPLICABLE]
    assert outcome is Outcome.NEEDS_INFO
    assert int(rule) == 1
    assert (
        _ABSTENTION_FOR_RESOLUTION[ResolutionStatus.NOT_APPLICABLE]
        is AbstentionReason.NO_APPLICABLE_POLICY
    )


# ---------------------------------------------------------------------------
# Replay
# ---------------------------------------------------------------------------


def test_a_replay_finding_is_distinguishable_from_a_resolution() -> None:
    """Both carry RESOLVED. Only one of them resolved anything.

    A report that grouped them would present "we designated this policy" as "we
    established this policy governs", which is the Phase-14 claim exactly.
    """
    replay = designated_without_resolution(DESIGNATED)
    assert replay.state is ResolutionStatus.RESOLVED
    assert replay.reason is ApplicabilityReason.DESIGNATED_WITHOUT_RESOLUTION
    assert replay.reason is not ApplicabilityReason.DESIGNATED_POLICY_APPLIES
    assert "no applicability resolution was performed" in replay.notes[0]
