"""Review versioning, gold impact, abstention states and the model gateway.

Four contracts that will carry the first AI vertical slice. Each is tested now,
before anything depends on it, because a contract discovered to be wrong after an
agent is built against it is a contract nobody changes.
"""

from __future__ import annotations

import inspect
from datetime import date

import pytest

from app.decision.abstention import (
    AbstentionReason,
    ScoredGate,
    abstention_for,
)
from app.decision.models import Outcome
from app.llm.gateway import (
    GatewayOutcome,
    ModelGateway,
    ModelRequest,
    ModelRole,
)
from app.review.impact import ImpactInputs, analyse_impact
from app.review.versioning import (
    ReviewDecision,
    ReviewImpact,
    ReviewScope,
    ReviewVersion,
    next_version,
)

pytestmark = pytest.mark.unit


def _decision(subject: str = "prov-1", **kwargs: object) -> ReviewDecision:
    base = {
        "scope": ReviewScope.PROVISION,
        "subject_id": subject,
        "decision": "REPRESENT_AS_CRITERION",
        "rationale": "states a condition a case can fail",
        "reviewer_id": "reviewer-1",
        "decided_on": date(2026, 8, 23),
    }
    return ReviewDecision(**{**base, **kwargs})  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# Review versioning
# ---------------------------------------------------------------------------


def test_an_unsigned_or_unreasoned_decision_is_refused() -> None:
    """A review nobody signed and nobody explained cannot be evaluated later.

    Which is what the record is for - a state change with no reasoning is a change,
    not a review.
    """
    for field in ("rationale", "reviewer_id", "decision", "subject_id"):
        with pytest.raises(ValueError, match=field):
            _decision(**{field: "   "})


def test_a_version_cannot_supersede_itself_or_a_later_one() -> None:
    """History runs one way. A version superseding a later one is a loop."""
    for supersedes in (2, 3):
        with pytest.raises(ValueError, match="earlier"):
            ReviewVersion(
                version=2,
                decisions=(_decision(),),
                impact=ReviewImpact(),
                recorded_on=date(2026, 8, 23),
                supersedes=supersedes,
                supersedes_reason="x",
            )


def test_superseding_without_a_reason_is_refused() -> None:
    """A correction with no reason is an unexplained divergence.

    Two versions disagreeing, with nothing saying why, is worse than one version
    being wrong - a later reader cannot tell which to believe.
    """
    with pytest.raises(ValueError, match="no recorded reason"):
        ReviewVersion(
            version=2,
            decisions=(_decision(),),
            impact=ReviewImpact(),
            recorded_on=date(2026, 8, 23),
            supersedes=1,
        )


def test_a_version_with_no_decisions_is_refused() -> None:
    with pytest.raises(ValueError, match="records no decisions"):
        ReviewVersion(version=1, decisions=(), impact=ReviewImpact(), recorded_on=date(2026, 8, 23))


def test_versions_accumulate_and_the_earlier_one_survives() -> None:
    """A correction is a new version beside the old one, never an edit.

    Overwriting `review_v1` would destroy the evidence of what was believed when
    every earlier report was written.
    """
    first = ReviewVersion(
        version=1,
        decisions=(_decision(),),
        impact=ReviewImpact(),
        recorded_on=date(2026, 8, 23),
    )
    second = ReviewVersion(
        version=2,
        decisions=(_decision(decision="NON_DECISION_RELEVANT"),),
        impact=ReviewImpact(),
        recorded_on=date(2026, 9, 1),
        supersedes=1,
        supersedes_reason="the provision was re-read alongside its parent paragraph",
    )
    history = (first, second)
    assert first.decisions[0].decision == "REPRESENT_AS_CRITERION"
    assert second.supersedes == 1
    assert next_version(history) == 3
    assert {v.label for v in history} == {"review_v1", "review_v2"}


def test_a_version_number_is_never_reused_after_a_gap() -> None:
    """Derived from the highest version, not the count.

    A reused number would make two different sets of decisions indistinguishable
    in a report.
    """
    sparse = (
        ReviewVersion(
            version=1,
            decisions=(_decision(),),
            impact=ReviewImpact(),
            recorded_on=date(2026, 8, 23),
        ),
        ReviewVersion(
            version=5,
            decisions=(_decision(),),
            impact=ReviewImpact(),
            recorded_on=date(2026, 9, 1),
        ),
    )
    assert next_version(sparse) == 6


def test_impact_flags_when_a_decision_would_force_a_new_frozen_dataset() -> None:
    """Forcing a gold_v2 must be visible before acting, not discovered after."""
    assert not ReviewImpact().touches_frozen_data
    assert not ReviewImpact(criteria=("c1",)).touches_frozen_data
    assert ReviewImpact(gold_cases=("CASE-0001",)).touches_frozen_data


# ---------------------------------------------------------------------------
# Gold impact analysis
# ---------------------------------------------------------------------------


def _inputs() -> ImpactInputs:
    return ImpactInputs(
        criteria={
            "C1": {"policy_id": "42 CFR 410.32", "policy_version": "v1"},
            "C2": {"policy_id": "42 CFR 410.32", "policy_version": "v1"},
        },
        provisions={
            "P1": {
                "policy_id": "42 CFR 410.32",
                "policy_version": "v1",
                "criterion_ids": ["C1"],
            },
            "P2": {"policy_id": "42 CFR 410.32", "policy_version": "v1", "criterion_ids": []},
        },
        dependencies={"C2": ("P2",)},
        gold_cases=(
            {
                "case_id": "G1",
                "expected": {
                    "policy_id": "42 CFR 410.32",
                    "policy_revision": "v1",
                    "criteria": [{"criterion_id": "C1"}],
                },
            },
            {
                "case_id": "G2",
                "expected": {
                    "policy_id": "42 CFR 410.32",
                    "policy_revision": "v1",
                    "criteria": [{"criterion_id": "C2"}],
                },
            },
        ),
        synthetic_cases=(),
    )


def test_impact_follows_a_recorded_dependency_to_the_cases() -> None:
    """P2 -> C2 -> G2. The chain a reviewer needs before ruling on P2."""
    impact = analyse_impact(ReviewScope.PROVISION, "P2", _inputs())
    assert impact.criteria == ("C2",)
    assert impact.gold_cases == ("G2",)
    assert impact.touches_frozen_data


def test_impact_follows_direct_representation_too() -> None:
    """P1 carries C1 directly - changing it changes what C1 means."""
    impact = analyse_impact(ReviewScope.PROVISION, "P1", _inputs())
    assert impact.criteria == ("C1",)
    assert impact.gold_cases == ("G1",)


def test_a_stale_reference_is_not_reported_as_no_impact() -> None:
    """They look identical in a summary and mean opposite things.

    "This decision affects nothing" and "this decision names something that does
    not exist" must not produce the same row.
    """
    impact = analyse_impact(ReviewScope.PROVISION, "does-not-exist", _inputs())
    assert impact.is_empty
    assert any("stale reference" in note for note in impact.notes)


def test_a_policy_scoped_decision_reaches_every_criterion_on_that_version() -> None:
    impact = analyse_impact(ReviewScope.POLICY_SEMANTICS, "REGULATION:42 CFR 410.32:v1", _inputs())
    assert set(impact.criteria) == {"C1", "C2"}
    assert set(impact.gold_cases) == {"G1", "G2"}


def test_impact_analysis_modifies_nothing() -> None:
    """It is a projection. gold_v1 is immutable and this must not touch it."""
    inputs = _inputs()
    before = (len(inputs.gold_cases), dict(inputs.criteria), dict(inputs.provisions))
    analyse_impact(ReviewScope.PROVISION, "P2", inputs)
    assert (len(inputs.gold_cases), inputs.criteria, inputs.provisions) == before


# ---------------------------------------------------------------------------
# Abstention
# ---------------------------------------------------------------------------


def test_no_abstention_reason_produces_an_approval_or_a_denial() -> None:
    """Abstention is by definition neither. The whole vocabulary must respect that."""
    for reason in AbstentionReason:
        record = abstention_for(reason)
        assert record.outcome not in (
            Outcome.APPROVE_RECOMMENDED,
            Outcome.DENY_RECOMMENDED,
        ), reason


def test_every_abstention_emits_an_audit_event() -> None:
    """An abstention that records nothing is invisible in the trail that exists to
    explain refusals."""
    events = set()
    for reason in AbstentionReason:
        record = abstention_for(reason)
        assert record.audit_event.startswith("abstention."), reason
        events.add(record.audit_event)
    assert len(events) == len(list(AbstentionReason)), "two reasons share an audit event"


def test_every_abstention_says_what_would_resolve_it() -> None:
    """An abstention with no remedy is an apology.

    The reviewer receiving it has to work out the next step from first principles,
    which is the opposite of what an abstention is for.
    """
    for reason in AbstentionReason:
        record = abstention_for(reason)
        assert record.remedy.strip()
        assert len(record.remedy.split()) >= 5, reason
    with pytest.raises(ValueError, match="no remedy"):
        abstention_for(AbstentionReason.RETRIEVAL_FAILURE, remedy="   ")


def test_the_scored_gate_is_uncalibrated_and_says_so() -> None:
    """ "There is no gate" and "the gate passed" are different claims.

    An audit row that cannot tell them apart lets an uncalibrated system read as a
    confident one. No threshold has been selected - that happens on the dev split
    under ADR-011/OD-8 - so every abstention records UNCALIBRATED explicitly.
    """
    for reason in AbstentionReason:
        record = abstention_for(reason)
        assert record.scored_gate is ScoredGate.UNCALIBRATED
        assert not record.is_scored


def test_the_structural_states_the_brief_requires_all_exist() -> None:
    """Phase 9 note: `NO_APPLICABLE_POLICY` was added.

    It is an abstention with a different character from the rest - absence of a
    determination generally means contractor discretion, not a system failure - and
    it was missing while every other structural refusal had a name. States may be
    ADDED here; one may never quietly disappear, which is why this asserts an exact
    set rather than a subset.

    **Phase 15 note: four applicability states were added**, and the expectation
    below changed because the world did. Until Phase 15 the runtime asserted that
    its designated policy applied, so the only applicability abstention it could
    ever produce was the one gold-set generation used. Resolving applicability for
    real makes five outcomes reachable, and the four new ones are named here rather
    than folded into `NO_APPLICABLE_POLICY` - "no policy governs this" and "several
    might" and "the resolver was unreachable" are different sentences to put in
    front of a reviewer (R-93).
    """
    required = {
        "NO_APPLICABLE_POLICY",
        "INSUFFICIENT_EVIDENCE",
        "UNSUPPORTED_CITATION",
        "UNRESOLVED_POLICY_SEMANTICS",
        "UNRESOLVED_POLICY_DEPENDENCY",
        "UNRESOLVED_COVERAGE",
        "MODEL_SCHEMA_FAILURE",
        "RETRIEVAL_FAILURE",
        "CONTRADICTORY_EVIDENCE",
        # Phase 15 (R-93).
        "MULTIPLE_CANDIDATE_POLICIES",
        "POLICY_TEMPORALLY_UNRESOLVED",
        "INSUFFICIENT_APPLICABILITY_INFORMATION",
        "POLICY_RESOLUTION_ERROR",
        # Phase 16 (R-86). Splits "the model answered badly" from "there was no
        # answer": same routing, different owner, different remedy.
        "PROVIDER_LIMITATION",
    }
    assert {reason.value for reason in AbstentionReason} == required


def test_only_an_unverifiable_citation_yields_no_decision() -> None:
    """No evidence, no decision - and everything else routes to a person."""
    no_decision = [r for r in AbstentionReason if abstention_for(r).outcome is Outcome.NO_DECISION]
    assert no_decision == [AbstentionReason.UNSUPPORTED_CITATION]


# ---------------------------------------------------------------------------
# Model gateway
# ---------------------------------------------------------------------------


def test_a_blocked_request_is_never_retryable() -> None:
    """Retrying a blocked request is an attempt to evade a security control."""
    assert not GatewayOutcome.BLOCKED.is_retryable
    assert not GatewayOutcome.DETECTOR_UNAVAILABLE.is_retryable
    assert GatewayOutcome.TIMEOUT.is_retryable


def test_every_failure_routes_to_a_human_and_none_to_a_denial() -> None:
    """Fail closed means fail toward a person, never toward a refusal of care."""
    for outcome in GatewayOutcome:
        assert outcome.routes_to_human is (outcome is not GatewayOutcome.OK)


def test_the_request_has_no_streaming_and_no_free_text_field() -> None:
    """Both absences are the contract.

    Streaming is refused by the firewall, and every response is a validated object
    rather than prose to be parsed. A free-text field would reopen the containment
    argument the architecture rests on.
    """
    fields = set(ModelRequest.__dataclass_fields__)
    assert not fields & {"stream", "streaming", "text", "raw_prompt", "completion"}
    assert {"schema", "schema_name", "prompt_id"} <= fields


def test_evidence_is_a_separate_field_from_instructions() -> None:
    """Retrieved policy text is DATA and is never concatenated into a prompt.

    Keeping them apart in the type means a caller cannot merge them by accident.
    """
    fields = set(ModelRequest.__dataclass_fields__)
    assert {"instructions", "evidence_block"} <= fields


def test_a_call_without_a_schema_or_a_prompt_id_is_refused() -> None:
    """A call with no schema is a free-text call by another name."""
    with pytest.raises(ValueError, match="no schema"):
        ModelRequest(
            role=ModelRole.STRUCTURED_ADJUDICATION,
            prompt_id="adjudication.v1",
            instructions="x",
            evidence_block="y",
            schema_name="s",
            schema={},
        )
    with pytest.raises(ValueError, match="versioned prompt id"):
        ModelRequest(
            role=ModelRole.STRUCTURED_ADJUDICATION,
            prompt_id="  ",
            instructions="x",
            evidence_block="y",
            schema_name="s",
            schema={"type": "object"},
        )


def test_the_gateway_names_roles_rather_than_models() -> None:
    """So a model choice stays configuration and is not encoded at call sites.

    Naming a model in a call site would also encode a capability claim in a place
    nobody re-measures.
    """
    assert {r.value for r in ModelRole} == {
        "STRUCTURED_ADJUDICATION",
        "STRUCTURED_INTAKE",
    }
    assert "call" in dir(ModelGateway)
    assert inspect.isclass(ModelGateway)
