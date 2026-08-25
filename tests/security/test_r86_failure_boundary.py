"""R-86 is bounded, and it fails toward the human. Part C2.

R-86 is a provider/decoder defect: grammar-constrained decoding guarantees the output
*shape* and not that the output *terminates*, so a decoder can satisfy the schema
forever with whitespace. It is **not fixed**, it is not fixable in this repository,
and the Phase-15 investigation found it is input-length dependent - which means the
cases most likely to hit it are the long ones, not a random third.

What this repository owes, and all it owes, is a boundary:

    R-86 → bounded by a token ceiling and a timeout → HUMAN_REVIEW → never a
    recommendation.

Two of those are configuration and two are behaviour, and this file asserts both
kinds. The configuration half matters because the tempting response to a truncation
is to raise the ceiling - which converts a bounded failure back into a 180-second
hang, and buys nothing, because a decoder that pads to 1536 pads to 4000.
"""

from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

from app.adjudication.assess import ASSESSMENT_PROMPT_ID
from app.config.settings import Settings
from app.contracts.slice import SliceInput
from app.core.types import CodeSystem
from app.decision.abstention import AbstentionReason
from app.decision.models import DecisionRule, Outcome
from app.decision.semantics import Attestation, PolicySemantics, SemanticsOrigin
from app.graph.slice import RunMode, SliceRunner
from app.llm.gateway import GatewayOutcome
from app.policy.logic_loader import load_policy_logic
from app.production_gate import ProductionGate
from tests.support_slice import (
    AS_OF,
    CRITERIA,
    IDENTITY,
    NOTE,
    FakeGateway,
    FixtureApplicability,
    FixtureRetrieval,
)

pytestmark = [pytest.mark.security, pytest.mark.corpus]

REPO = Path(__file__).resolve().parents[2]
CONFIG_VERSION = "slice.v1"
DEFINITIVE = {Outcome.APPROVE_RECOMMENDED, Outcome.DENY_RECOMMENDED}

#: The ceilings as of Phase 12, and they must not be raised to chase completion.
#: Intake is higher because it fills five arrays; adjudication answers one question.
EXPECTED_CEILINGS = {"intake": 1536, "adjudication": 512}


@pytest.fixture
def semantics() -> PolicySemantics:
    path = REPO / "data/policy_logic/42-CFR-410.33.yaml"
    return PolicySemantics.declared(
        policy_id="42 CFR 410.33",
        policy_version="2026-08-13",
        logic=load_policy_logic(path, known_criteria=frozenset(c.criterion_id for c in CRITERIA)),
        attestation=Attestation(
            source=str(path.relative_to(REPO)),
            sha256=hashlib.sha256(path.read_bytes()).hexdigest(),
            origin=SemanticsOrigin.DECLARED_LOGIC_FILE,
        ),
    )


def runner(gateway: FakeGateway, semantics: PolicySemantics) -> SliceRunner:
    return SliceRunner(
        gateway=gateway,
        retrieval=FixtureRetrieval(),  # type: ignore[arg-type]
        identity=IDENTITY,
        criteria=CRITERIA,
        semantics=semantics,
        decision_config_version=CONFIG_VERSION,
        gate=ProductionGate(
            admissibility_report=REPO / "data/review/slice_admissibility.json",
            decision_records=(REPO / "data/review/focus_001_decision.json",),
        ).evaluate(),
        mode=RunMode.PRODUCTION,
        applicability=FixtureApplicability(),  # type: ignore[arg-type]
    )


def case() -> SliceInput:
    return SliceInput(
        case_id="CASE-R86",
        clinical_note=NOTE,
        procedure_code="R0075",
        code_system=CodeSystem.HCPCS,
        date_of_service=AS_OF,
    )


# ---------------------------------------------------------------------------
# The boundary is configured
# ---------------------------------------------------------------------------


def test_the_token_ceilings_are_still_bounded_and_unraised() -> None:
    """The ceiling is what turns a 180-second hang into a truncation.

    Asserted as exact values, not as "is not None". "Bounded" at 32768 is
    unbounded in every sense that matters here, and raising a ceiling is precisely
    the change somebody makes when a truncation looks like the problem.
    """
    intake_source = (REPO / "app/intake/extract.py").read_text(encoding="utf-8")
    assess_source = (REPO / "app/adjudication/assess.py").read_text(encoding="utf-8")

    assert f"max_output_tokens={EXPECTED_CEILINGS['intake']}" in intake_source
    assert f"max_output_tokens={EXPECTED_CEILINGS['adjudication']}" in assess_source


def test_the_request_timeout_is_bounded() -> None:
    """A ceiling alone is not enough: a slow pad still consumes the timeout."""
    settings = Settings(llm_api_key="test-key")  # type: ignore[arg-type]
    assert 0 < settings.llm_timeout_seconds <= 120
    assert 1 <= settings.llm_max_attempts <= 3


def test_the_mitigation_is_labelled_as_a_mitigation() -> None:
    """The compact-output sentence is a prompt-level patch for a decoder defect.

    Asserted so that a future reader cannot mistake it for a formatting preference
    and delete it, and cannot mistake it for a fix and close R-86.
    """
    source = (REPO / "app/llm/firewall_gateway.py").read_text(encoding="utf-8")
    assert "R-86" in source
    assert "PROMPT-LEVEL MITIGATION FOR A DECODER-LEVEL DEFECT" in source


def test_r86_is_not_recorded_as_fixed() -> None:
    """The escalation must keep refusing the claim, whatever a run happens to show.

    The Phase-15 investigation makes this stricter, not weaker: a short-prompt arm
    that terminates is now known to prove nothing.
    """
    doc = (REPO / "docs/escalations/R-86-unbounded-whitespace.md").read_text(encoding="utf-8")
    normalised = " ".join(doc.lower().split())
    assert "contained, not eliminated" in normalised
    assert "must cite a change in the decoder" in normalised
    assert "input-length dependent" in normalised or "length dependent" in normalised


# ---------------------------------------------------------------------------
# The boundary holds, as behaviour
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "outcome",
    [
        GatewayOutcome.SCHEMA_INVALID,
        GatewayOutcome.TIMEOUT,
        GatewayOutcome.UNREACHABLE,
        GatewayOutcome.BLOCKED,
        GatewayOutcome.DETECTOR_UNAVAILABLE,
        GatewayOutcome.UNSUPPORTED,
    ],
    ids=lambda o: o.value,
)
async def test_an_intake_failure_never_becomes_a_recommendation(
    outcome: GatewayOutcome, semantics: PolicySemantics
) -> None:
    """Every gateway outcome, at intake. R-86 arrives as `SCHEMA_INVALID`."""
    result = await runner(FakeGateway(fail_intake=outcome), semantics).run(case())

    assert result.outcome is Outcome.HUMAN_REVIEW
    assert result.outcome not in DEFINITIVE
    assert result.recommendation.rule is DecisionRule.MODEL_PATH_FAILED
    assert result.abstention is not None
    assert result.abstention.reason is AbstentionReason.MODEL_SCHEMA_FAILURE
    assert result.assessments == ()


@pytest.mark.parametrize(
    "outcome",
    [GatewayOutcome.SCHEMA_INVALID, GatewayOutcome.TIMEOUT, GatewayOutcome.BLOCKED],
    ids=lambda o: o.value,
)
async def test_an_assessment_failure_never_becomes_a_recommendation(
    outcome: GatewayOutcome, semantics: PolicySemantics
) -> None:
    """The other place R-86 can land: mid-adjudication, after intake succeeded.

    A partially-assessed case is the tempting one to salvage - four criteria came
    back, one did not - and salvaging it would let a decision rest on whichever
    criteria happened to survive a provider defect.
    """
    result = await runner(FakeGateway(fail_assessment=outcome), semantics).run(case())

    assert result.outcome is Outcome.HUMAN_REVIEW
    assert result.recommendation.rule is DecisionRule.MODEL_PATH_FAILED
    assert result.outcome not in DEFINITIVE


async def test_a_blocked_request_is_never_retried_into_a_recommendation(
    semantics: PolicySemantics,
) -> None:
    """403 is a security control, not a transient error.

    Retrying it is an attempt to evade the control, and the remedy text says so -
    checked here as well as in the gateway tests, because this is the file a reader
    consults about what a failure may become.
    """
    result = await runner(FakeGateway(fail_intake=GatewayOutcome.BLOCKED), semantics).run(case())

    assert result.abstention is not None
    assert "never retried" in result.abstention.remedy
    assert result.outcome is Outcome.HUMAN_REVIEW


async def test_the_same_case_reaches_a_recommendation_when_the_model_answers(
    semantics: PolicySemantics,
) -> None:
    """**Non-vacuity.** Without it, every test above passes on a chain that never decides."""
    from app.contracts.slice import AssessmentState

    gateway = FakeGateway(
        assessments={c.criterion_id: AssessmentState.SATISFIED for c in CRITERIA[:4]}
        | {CRITERIA[4].criterion_id: AssessmentState.NOT_SATISFIED}
    )
    result = await runner(gateway, semantics).run(case())

    assert result.outcome is Outcome.APPROVE_RECOMMENDED
    assert result.model_calls == 1 + len(CRITERIA)


async def test_a_failed_case_reports_what_it_spent(semantics: PolicySemantics) -> None:
    """An abstention that spent tokens and one that spent none are different facts.

    R-86 costs three attempts before it abstains. A bare zero in the report would
    make a provider outage look free, and the cost of the defect is part of the case
    for escalating it.
    """
    result = await runner(FakeGateway(fail_intake=GatewayOutcome.SCHEMA_INVALID), semantics).run(
        case()
    )
    assert result.model_calls == 1, "the attempt must be counted even though it produced nothing"
    assert "applicability" in result.timings_ms
    assert "intake" in result.timings_ms


def test_the_adjudication_prompt_is_versioned() -> None:
    """Editing a template in place breaks audit reproducibility (a repository rule).

    Relevant here because the R-86 mitigation lives in a prompt: a future attempt to
    strengthen it must increment the version rather than edit the text.
    """
    assert ASSESSMENT_PROMPT_ID == "adjudication.v1"
