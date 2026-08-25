"""CASE-0073: valid citations must not rescue an inapplicable policy. R-93.

## What happened

Phase 14's frozen 26-case run produced, for CASE-0073:

    expected  NEEDS_INFO      (gold decision_rule 1 - no applicable policy)
    actual    DENY_RECOMMENDED
    citations 7 verified, 0 failures
    guardrail PASSED
    contradiction NO_CONTRADICTION

Every grounding metric passed that case. They had to: the quotes were real, they
came from chunks that were genuinely in the evidence set, and the metadata matched
the database. The system reasoned correctly, cited honestly, and applied a
regulation the case does not fall under - which ADR-004 names as the worst failure
available here, precisely because nothing downstream can see it.

The cause was one line. `SliceRunner.run()` passed
`ResolutionState(status=RESOLVED, version_count=1)` as a literal, because the runner
had been handed a `PolicyIdentity` at construction. Decision-table rows 1 and 2 -
the rows that refuse to decide when no policy applies or when several might - were
therefore unreachable from the live runtime for the whole of Phases 11 to 14. The
table had always been correct. Nothing ever asked it.

## What this file asserts

Not "the fix is present" - that would pass against a fix that is present and
bypassed. It reconstructs the Phase-14 conditions exactly: real chunks from the real
regulation, a model that returns evidenced `NOT_SATISFIED` verdicts, citations that
verify, no contradiction. Under Phase-14 code that combination denies. The only
thing changed is applicability, and the outcome must not be definitive.

`scripts/mutation_guard.py` carries the matching mutation (`applicability-stage-
removed`), so the claim that this test is load-bearing is checked rather than made.
"""

from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

from app.contracts.slice import AssessmentState, SliceInput
from app.core.types import CodeSystem, ResolutionStatus
from app.decision.abstention import AbstentionReason
from app.decision.models import DecisionRule, Outcome
from app.decision.semantics import Attestation, PolicySemantics, SemanticsOrigin
from app.graph.slice import RunMode, SliceRunner
from app.policy.applicability import ApplicabilityReason
from app.policy.logic_loader import load_policy_logic
from app.production_gate import ProductionGate
from tests.support_slice import (
    AS_OF,
    CRITERIA,
    IDENTITY,
    FakeGateway,
    FixtureApplicability,
    FixtureRetrieval,
    does_not_apply,
)

pytestmark = [pytest.mark.integration, pytest.mark.corpus]

REPO = Path(__file__).resolve().parents[2]
CONFIG_VERSION = "slice.v1"

#: CASE-0073's own structured input, transcribed from `data/gold/cases/gold_v1.jsonl`.
#: The note is not reproduced: it is synthetic, and it is also irrelevant - the whole
#: point is that applicability is decided from the structured request.
CASE_0073_CODE = "R0075"
CASE_0073_DATE = AS_OF


@pytest.fixture
def semantics() -> PolicySemantics:
    path = REPO / "data/policy_logic/42-CFR-410.33.yaml"
    known = frozenset(c.criterion_id for c in CRITERIA)
    return PolicySemantics.declared(
        policy_id="42 CFR 410.33",
        policy_version="2026-08-13",
        logic=load_policy_logic(path, known_criteria=known),
        attestation=Attestation(
            source=str(path.relative_to(REPO)),
            sha256=hashlib.sha256(path.read_bytes()).hexdigest(),
            origin=SemanticsOrigin.DECLARED_LOGIC_FILE,
        ),
    )


def gate() -> object:
    return ProductionGate(
        admissibility_report=REPO / "data/review/slice_admissibility.json",
        decision_records=(REPO / "data/review/focus_001_decision.json",),
    ).evaluate()


def denying_gateway() -> FakeGateway:
    """The model behaviour that produced the Phase-14 denial.

    Every requirement evidenced `NOT_SATISFIED`, each citing `E1` - the shape that
    reaches decision-table row 8. Nothing here is a failure mode; this is the model
    working, on a document that does not govern the case.
    """
    return FakeGateway(
        assessments={c.criterion_id: AssessmentState.NOT_SATISFIED for c in CRITERIA[:4]}
        | {CRITERIA[4].criterion_id: AssessmentState.NOT_SATISFIED},
        citations={c.criterion_id: ("E1",) for c in CRITERIA},
    )


def case() -> SliceInput:
    return SliceInput(
        case_id="CASE-0073",
        clinical_note=(
            "HISTORY OF PRESENT ILLNESS\nRequested service: unlisted procedure 99199.\n\n"
            "EXAMINATION\nHistory of chronic pain with prior conservative management."
        ),
        procedure_code=CASE_0073_CODE,
        code_system=CodeSystem.HCPCS,
        date_of_service=CASE_0073_DATE,
    )


def runner(gateway: FakeGateway, semantics: PolicySemantics, applicability: object) -> SliceRunner:
    return SliceRunner(
        gateway=gateway,
        retrieval=FixtureRetrieval(),  # type: ignore[arg-type]
        identity=IDENTITY,
        criteria=CRITERIA,
        semantics=semantics,
        decision_config_version=CONFIG_VERSION,
        gate=gate(),  # type: ignore[arg-type]
        mode=RunMode.PRODUCTION,
        applicability=applicability,  # type: ignore[arg-type]
    )


# ---------------------------------------------------------------------------
# The regression
# ---------------------------------------------------------------------------


async def test_an_inapplicable_policy_cannot_produce_a_denial(
    semantics: PolicySemantics,
) -> None:
    """THE Phase-15 regression. Everything is valid except the policy."""
    gateway = denying_gateway()
    outcome = await runner(gateway, semantics, FixtureApplicability(finding=does_not_apply())).run(
        case()
    )

    assert outcome.outcome is not Outcome.DENY_RECOMMENDED
    assert outcome.outcome is not Outcome.APPROVE_RECOMMENDED
    assert outcome.outcome in {Outcome.NEEDS_INFO, Outcome.HUMAN_REVIEW}
    assert outcome.recommendation.rule is DecisionRule.NO_APPLICABLE_POLICY
    assert outcome.abstention is not None
    assert outcome.abstention.reason is AbstentionReason.NO_APPLICABLE_POLICY


async def test_the_refusal_names_the_policy_reason_not_a_generic_one(
    semantics: PolicySemantics,
) -> None:
    """A reviewer must be told *why*, and the audit trail must carry it.

    Phase 14's trail could not distinguish an applicability that was checked from
    one that was assumed, because neither existed as an event.
    """
    outcome = await runner(
        denying_gateway(), semantics, FixtureApplicability(finding=does_not_apply())
    ).run(case())

    assert outcome.applicability is not None
    assert outcome.applicability.state is ResolutionStatus.NOT_APPLICABLE
    assert outcome.applicability.reason is ApplicabilityReason.NO_POLICY_LISTS_THE_PROCEDURE
    assert not outcome.resolved_applicability

    stages = [e.stage for e in outcome.audit]
    assert stages[0] == "applicability"
    resolved = next(e for e in outcome.audit if e.event == "slice.applicability.resolved")
    assert resolved.resolution_state == "NONE_APPLICABLE"
    assert resolved.resolution_reason == "NO_POLICY_LISTS_THE_PROCEDURE"


async def test_no_evidence_and_no_model_call_survive_an_inapplicable_policy(
    semantics: PolicySemantics,
) -> None:
    """A5's "never retrieve/adjudicate against that policy", asserted as behaviour.

    Not merely that the outcome is safe - that the stages which would have produced
    quotable material never ran. A refused case that still carries seven verified
    citations is a refused case somebody can quote out of context.
    """
    gateway = denying_gateway()
    retrieval = FixtureRetrieval()
    outcome = await SliceRunner(
        gateway=gateway,
        retrieval=retrieval,  # type: ignore[arg-type]
        identity=IDENTITY,
        criteria=CRITERIA,
        semantics=semantics,
        decision_config_version=CONFIG_VERSION,
        gate=gate(),  # type: ignore[arg-type]
        mode=RunMode.PRODUCTION,
        applicability=FixtureApplicability(finding=does_not_apply()),  # type: ignore[arg-type]
    ).run(case())

    assert gateway.calls == [], "a model was called for a policy that does not govern"
    assert retrieval.calls == [], "evidence was retrieved from an inapplicable policy"
    assert outcome.assessments == ()
    assert outcome.citations.verified == ()
    assert outcome.model_calls == 0
    assert outcome.tokens == {}


async def test_the_same_case_denies_when_the_policy_does_apply(
    semantics: PolicySemantics,
) -> None:
    """**Non-vacuity.** Without this, the regression above proves nothing.

    Identical criteria, identical model output, identical evidence - and a resolving
    applicability port. If this did not deny, the test above would be passing
    because the fixture cannot reach a denial at all rather than because
    applicability stopped it.
    """
    gateway = denying_gateway()
    outcome = await runner(gateway, semantics, FixtureApplicability()).run(case())

    assert outcome.outcome is Outcome.DENY_RECOMMENDED
    assert outcome.recommendation.rule in {
        DecisionRule.REQUIRED_NOT_SATISFIED,
        DecisionRule.EXCLUSION_SATISFIED,
    }
    assert outcome.citations.passed
    assert len(outcome.citations.verified) >= 1, (
        "the control's denial must be evidenced, or it is not the Phase-14 shape"
    )
    assert gateway.calls, "the model must have been called, or nothing was adjudicated"


async def test_citations_verify_in_the_denying_control(semantics: PolicySemantics) -> None:
    """The control's citations are real, which is what made Phase 14 dangerous.

    Stated separately so the file records the uncomfortable part explicitly: this is
    not a case of a model hallucinating. Grounding was perfect. Applicability was
    absent.
    """
    outcome = await runner(denying_gateway(), semantics, FixtureApplicability()).run(case())
    assert outcome.citations.passed
    assert outcome.citations.failures == ()


@pytest.mark.parametrize(
    ("state", "reason"),
    [
        (ResolutionStatus.NOT_APPLICABLE, ApplicabilityReason.NO_POLICY_LISTS_THE_PROCEDURE),
        (ResolutionStatus.MULTIPLE_CANDIDATES, ApplicabilityReason.SEVERAL_POLICIES_COULD_GOVERN),
        (
            ResolutionStatus.TEMPORALLY_UNRESOLVED,
            ApplicabilityReason.NO_VERSION_IN_FORCE_ON_THAT_DATE,
        ),
        (ResolutionStatus.INSUFFICIENT_INFORMATION, ApplicabilityReason.NO_PROCEDURE_CODE),
        (ResolutionStatus.RESOLUTION_ERROR, ApplicabilityReason.RESOLVER_FAILED),
    ],
    ids=lambda v: getattr(v, "value", str(v)),
)
async def test_no_refusing_state_reaches_a_definitive_decision(
    state: ResolutionStatus, reason: ApplicabilityReason, semantics: PolicySemantics
) -> None:
    """Every non-RESOLVED state, against the model output that otherwise denies."""
    from app.policy.applicability import ApplicabilityFinding

    finding = ApplicabilityFinding(state=state, reason=reason, designated=IDENTITY)
    gateway = denying_gateway()
    outcome = await runner(gateway, semantics, FixtureApplicability(finding=finding)).run(case())

    assert outcome.outcome not in {Outcome.APPROVE_RECOMMENDED, Outcome.DENY_RECOMMENDED}
    assert gateway.calls == []


async def test_a_port_that_raises_fails_toward_the_human(semantics: PolicySemantics) -> None:
    """The port contract says it must not raise. One that does is still contained.

    Classified as `RESOLUTION_ERROR` rather than allowed to reach the slice's
    generic handler, where it would be reported as a retrieval failure and diagnosed
    against the wrong subsystem for a week.
    """
    gateway = denying_gateway()
    port = FixtureApplicability(raises=ConnectionError("resolver unreachable"))
    outcome = await runner(gateway, semantics, port).run(case())

    assert outcome.outcome is Outcome.HUMAN_REVIEW
    assert outcome.recommendation.rule is DecisionRule.POLICY_RESOLUTION_ERROR
    assert outcome.applicability is not None
    assert outcome.applicability.reason is ApplicabilityReason.RESOLVER_FAILED
    assert gateway.calls == []


# ---------------------------------------------------------------------------
# The mode boundary (A3)
# ---------------------------------------------------------------------------


async def test_production_without_a_resolver_cannot_be_constructed(
    semantics: PolicySemantics,
) -> None:
    """A PRODUCTION runner with no port *is* the Phase-14 runtime.

    Refused at construction rather than per case: a per-case refusal is 26
    abstentions in a report, which reads as a hard corpus rather than as a defect.
    """
    gateway = FakeGateway()
    with pytest.raises(ValueError, match="requires an ApplicabilityPort"):
        SliceRunner(
            gateway=gateway,
            retrieval=FixtureRetrieval(),  # type: ignore[arg-type]
            identity=IDENTITY,
            criteria=CRITERIA,
            semantics=semantics,
            decision_config_version=CONFIG_VERSION,
            gate=gate(),  # type: ignore[arg-type]
            mode=RunMode.PRODUCTION,
        )
    assert gateway.calls == []


async def test_the_mode_has_no_default(semantics: PolicySemantics) -> None:
    """Omitting it is a TypeError. A default mode is a mode nobody chose."""
    with pytest.raises(TypeError):
        SliceRunner(  # type: ignore[call-arg]
            gateway=FakeGateway(),
            retrieval=FixtureRetrieval(),  # type: ignore[arg-type]
            identity=IDENTITY,
            criteria=CRITERIA,
            semantics=semantics,
            decision_config_version=CONFIG_VERSION,
            gate=gate(),  # type: ignore[arg-type]
        )


async def test_replay_is_admitted_and_stamped(semantics: PolicySemantics) -> None:
    """REPLAY runs without a resolver, and every artefact says which mode it was.

    A historical replay reproduces gold_v1's labels, which were computed against a
    designated policy before this stage existed. Admitting it is correct; letting it
    be *mistaken* for a resolution is not, so the finding carries a different reason
    and `resolved_applicability` is False even though the state is RESOLVED.
    """
    outcome = await SliceRunner(
        gateway=denying_gateway(),
        retrieval=FixtureRetrieval(),  # type: ignore[arg-type]
        identity=IDENTITY,
        criteria=CRITERIA,
        semantics=semantics,
        decision_config_version=CONFIG_VERSION,
        gate=gate(),  # type: ignore[arg-type]
        mode=RunMode.REPLAY,
    ).run(case())

    assert outcome.mode is RunMode.REPLAY
    assert outcome.applicability is not None
    assert outcome.applicability.reason is ApplicabilityReason.DESIGNATED_WITHOUT_RESOLUTION
    assert not outcome.resolved_applicability
    # It adjudicates - that is the point of a replay - and it is labelled.
    assert outcome.outcome is Outcome.DENY_RECOMMENDED


async def test_replay_does_not_consult_a_port_even_when_one_is_supplied(
    semantics: PolicySemantics,
) -> None:
    """Otherwise a replay's reproduction would be conditional on today's corpus."""
    port = FixtureApplicability()
    outcome = await SliceRunner(
        gateway=denying_gateway(),
        retrieval=FixtureRetrieval(),  # type: ignore[arg-type]
        identity=IDENTITY,
        criteria=CRITERIA,
        semantics=semantics,
        decision_config_version=CONFIG_VERSION,
        gate=gate(),  # type: ignore[arg-type]
        mode=RunMode.REPLAY,
        applicability=port,  # type: ignore[arg-type]
    ).run(case())

    assert port.requests == []
    assert outcome.applicability is not None
    assert outcome.applicability.reason is ApplicabilityReason.DESIGNATED_WITHOUT_RESOLUTION
