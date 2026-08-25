"""The concrete gateway's contract, proven without a provider.

Every test here drives the real `FirewallGateway` through the real `LlmClient` over
an `httpx.MockTransport`. **No network, no provider, no cost.** That matters for
more than convenience: the failure classification is the part of this class that
carries safety weight, and a failure path you can only test by standing up a
service is a failure path nobody tests.

What is NOT claimed by any test in this file: that a real model returns anything
useful. These prove the seam behaves, not that inference works.
"""

from __future__ import annotations

import asyncio

import pytest
from pydantic import BaseModel, Field

from app.contracts.slice import AssessmentState, CriterionAssessment
from app.llm.gateway import (
    GatewayFailure,
    GatewayOutcome,
    ModelGateway,
    ModelRole,
)
from tests.gateway_contract import (
    MODELS,
    blocked_transport,
    counting_transport,
    error_transport,
    gateway_with,
    json_transport,
    raw_transport,
    request_for,
    timeout_transport,
)

pytestmark = [pytest.mark.unit, pytest.mark.security]


class Tiny(BaseModel):
    """A minimal closed schema, so a test failure is about the gateway."""

    answer: str = Field(min_length=1)


VALID = {
    "criterion_id": "42_CFR_410_33_2026_08_13_C01",
    "assessment": "SATISFIED",
    "evidence_ids": ["E1"],
    "rationale_summary": "the order is written and from the treating physician",
    "uncertainty": None,
}


# ---------------------------------------------------------------------------
# Conformance
# ---------------------------------------------------------------------------


def test_the_gateway_satisfies_the_protocol() -> None:
    """The gap this closes: for a whole phase there was no implementation at all,
    and the only stand-in did not satisfy the contract it stood in for."""
    gateway = gateway_with(json_transport(VALID))
    assert isinstance(gateway, ModelGateway)
    assert hasattr(gateway, "model_for")


def test_a_role_with_no_model_is_a_startup_error_not_a_runtime_one() -> None:
    """Surfaced at construction. A role with no model would otherwise fail on the
    first case, which is the worst moment to discover a configuration mistake."""
    from app.llm.client import LlmClient
    from app.llm.firewall_gateway import FirewallGateway

    client = LlmClient(
        base_url="http://firewall.invalid/v1",
        api_key="k",
        model="m",
        transport=json_transport(VALID),
    )
    with pytest.raises(ValueError, match="no model configured"):
        FirewallGateway(client=client, models={ModelRole.STRUCTURED_INTAKE: "fixture-model"})


def test_model_selection_is_configuration_and_is_reported() -> None:
    gateway = gateway_with(json_transport(VALID))
    assert gateway.model_for == MODELS
    assert set(gateway.model_for) == set(ModelRole)


# ---------------------------------------------------------------------------
# The happy path
# ---------------------------------------------------------------------------


async def test_a_valid_structured_response_is_returned_validated() -> None:
    gateway = gateway_with(json_transport(VALID))
    response = await gateway.call(request_for(), CriterionAssessment)

    assert response.outcome is GatewayOutcome.OK
    assert isinstance(response.value, CriterionAssessment)
    assert response.value.assessment is AssessmentState.SATISFIED
    assert response.value.evidence_ids == ("E1",)


async def test_model_identity_and_cost_propagate() -> None:
    """An audit row that cannot name the model that produced it cannot be reproduced."""
    gateway = gateway_with(json_transport(VALID, model="fixture-model-2026"))
    response = await gateway.call(request_for(), CriterionAssessment)

    assert response.model_id == "fixture-model-2026"
    assert response.prompt_id == "adjudication.v1"
    assert response.prompt_tokens == 11
    assert response.completion_tokens == 7
    assert response.latency_ms >= 0


async def test_instructions_and_evidence_are_sent_as_separate_turns() -> None:
    """The separation the whole containment argument rests on, checked at the wire.

    Every layer above keeps `instructions` and `evidence_block` apart. This is the
    last place it could be lost, and a transport that concatenated them would undo
    all of it silently.
    """
    seen: list[dict[str, object]] = []

    import httpx

    def handler(request: httpx.Request) -> httpx.Response:
        import json as _json

        seen.append(_json.loads(request.content))
        return json_transport(VALID).handler(request)  # type: ignore[attr-defined,no-any-return]

    gateway = gateway_with(httpx.MockTransport(handler))
    await gateway.call(
        request_for(instructions="INSTRUCTION-MARKER", evidence_block="EVIDENCE-MARKER"),
        CriterionAssessment,
    )

    messages = seen[0]["messages"]
    assert isinstance(messages, list)
    by_role = {m["role"]: m["content"] for m in messages}

    # The property, stated as it actually is: the half WE author is in the system
    # role, and retrieved text is in the user role. Different roles, not merely
    # different turns.
    #
    # This test previously asserted two separate `user` turns. The live path refused
    # that shape - the upstream requires strict role alternation - and the fix moved
    # the trusted half into `system`, which is a stronger separation rather than a
    # weaker one. The expectation changed because the deployment did.
    assert "INSTRUCTION-MARKER" in by_role["system"]
    assert "EVIDENCE-MARKER" in by_role["user"]

    # The rule that must never bend: retrieved text does not enter the system turn.
    assert "EVIDENCE-MARKER" not in by_role["system"]
    # And instructions are not smuggled into the untrusted turn either, where they
    # would sit inside the fence and read as data quoting itself.
    assert "INSTRUCTION-MARKER" not in by_role["user"]


async def test_the_system_turn_frames_data_as_non_instruction() -> None:
    import json as _json

    import httpx

    seen: list[dict[str, object]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(_json.loads(request.content))
        return json_transport(VALID).handler(request)  # type: ignore[attr-defined,no-any-return]

    await gateway_with(httpx.MockTransport(handler)).call(request_for(), CriterionAssessment)
    system = next(m for m in seen[0]["messages"] if m["role"] == "system")  # type: ignore[union-attr]
    assert "DATA, never" in system["content"]


# ---------------------------------------------------------------------------
# Failure classification
# ---------------------------------------------------------------------------


async def test_a_firewall_block_is_classified_and_never_retried() -> None:
    """The security-critical one.

    Asserted by COUNTING REQUESTS, not by reading a log line. Retrying a request the
    firewall refused is an attempt to evade a security control, and the client's
    retry set deliberately excludes 403.
    """
    attempts: list[int] = []
    gateway = gateway_with(counting_transport(blocked_transport(), attempts), max_attempts=3)

    with pytest.raises(GatewayFailure) as caught:
        await gateway.call(request_for(), CriterionAssessment)

    assert caught.value.outcome is GatewayOutcome.BLOCKED
    assert not caught.value.outcome.is_retryable
    assert len(attempts) == 1, f"a blocked request was attempted {len(attempts)} times"


async def test_a_detector_outage_fails_closed() -> None:
    gateway = gateway_with(error_transport(503), max_attempts=1)
    with pytest.raises(GatewayFailure) as caught:
        await gateway.call(request_for(), CriterionAssessment)
    assert caught.value.outcome is GatewayOutcome.DETECTOR_UNAVAILABLE


async def test_a_timeout_is_classified_as_retryable() -> None:
    gateway = gateway_with(timeout_transport(), max_attempts=1)
    with pytest.raises(GatewayFailure) as caught:
        await gateway.call(request_for(), CriterionAssessment)
    assert caught.value.outcome in (GatewayOutcome.TIMEOUT, GatewayOutcome.UNREACHABLE)
    assert caught.value.outcome.is_retryable


async def test_a_client_rejection_is_a_configuration_error() -> None:
    """400 means the gateway asked for something the firewall refuses - streaming, an
    unsupported mode. Not retryable, because trying again asks the same thing."""
    gateway = gateway_with(error_transport(400), max_attempts=1)
    with pytest.raises(GatewayFailure) as caught:
        await gateway.call(request_for(), CriterionAssessment)
    assert caught.value.outcome is GatewayOutcome.UNSUPPORTED
    assert not caught.value.outcome.is_retryable


async def test_a_malformed_response_becomes_a_schema_failure_not_a_guess() -> None:
    gateway = gateway_with(raw_transport("this is prose, not JSON"), max_attempts=1)
    with pytest.raises(GatewayFailure) as caught:
        await gateway.call(request_for(), CriterionAssessment)
    assert caught.value.outcome is GatewayOutcome.SCHEMA_INVALID


async def test_a_response_violating_the_closed_schema_is_refused() -> None:
    """`PROBABLY_SATISFIED` is exactly the hedge a model reaches for. It is refused,
    not coerced to the nearest legal state."""
    gateway = gateway_with(
        json_transport({**VALID, "assessment": "PROBABLY_SATISFIED"}), max_attempts=1
    )
    with pytest.raises(GatewayFailure) as caught:
        await gateway.call(request_for(), CriterionAssessment)
    assert caught.value.outcome is GatewayOutcome.SCHEMA_INVALID


async def test_an_empty_payload_is_a_failure_not_an_empty_answer() -> None:
    """A caller must not be able to mistake a refused call for a model that said
    nothing. `GatewayFailure` carries the outcome so it cannot be lost."""
    gateway = gateway_with(raw_transport(""), max_attempts=1)
    with pytest.raises(GatewayFailure):
        await gateway.call(request_for(), CriterionAssessment)


@pytest.mark.parametrize("status", [500, 502, 504])
async def test_upstream_failures_route_to_a_retryable_outcome(status: int) -> None:
    gateway = gateway_with(error_transport(status), max_attempts=1)
    with pytest.raises(GatewayFailure) as caught:
        await gateway.call(request_for(), CriterionAssessment)
    assert caught.value.outcome.routes_to_human


def test_every_non_ok_outcome_routes_to_a_human_and_none_to_a_denial() -> None:
    """Over the whole enum, not just the ones exercised above."""
    for outcome in GatewayOutcome:
        if outcome is GatewayOutcome.OK:
            continue
        assert outcome.routes_to_human
    assert not GatewayOutcome.BLOCKED.is_retryable


def test_a_structured_request_has_a_token_ceiling() -> None:
    """R-86. An unbounded structured call has no natural stopping point.

    Live activation found intake calls burning 3 x 60 s and returning nothing: JSON
    permits arbitrary whitespace between tokens, so a grammar-constrained decoder can
    satisfy the schema forever without closing the document. 2000 tokens, 98.6% of
    them whitespace.

    The ceiling does not fix that - it converts a hang into a truncation - but a hang
    is strictly worse: it holds the request for the full timeout, three times, before
    the case reaches a human.
    """
    from app.llm.gateway import ModelRequest

    assert request_for().max_output_tokens > 0
    with pytest.raises(ValueError, match="no natural stopping point"):
        ModelRequest(
            role=ModelRole.STRUCTURED_ADJUDICATION,
            prompt_id="p",
            instructions="i",
            evidence_block="e",
            schema_name="S",
            schema={"type": "object"},
            max_output_tokens=0,
        )


def test_the_ceiling_reaches_the_wire() -> None:
    """A ceiling the transport ignores is a comment."""
    import json as _json

    import httpx

    seen: list[dict[str, object]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(_json.loads(request.content))
        return json_transport(VALID).handler(request)  # type: ignore[attr-defined,no-any-return]

    from app.llm.gateway import ModelRequest

    req = ModelRequest(
        role=ModelRole.STRUCTURED_ADJUDICATION,
        prompt_id="adjudication.v1",
        instructions="i",
        evidence_block="e",
        schema_name="CriterionAssessment",
        schema={"type": "object"},
        max_output_tokens=321,
    )
    asyncio.run(gateway_with(httpx.MockTransport(handler)).call(req, CriterionAssessment))
    assert seen[0]["max_tokens"] == 321


def test_the_compact_output_instruction_is_present() -> None:
    """R-86's mitigation, pinned so it is not tidied away as verbosity.

    It reads like a formatting preference and is not one: without it, 0/3 intake
    calls terminated; with it, 3/3. It belongs in the system turn, where the model
    sees it before any data.
    """
    from app.llm.firewall_gateway import _SYSTEM

    assert "single line" in _SYSTEM
    assert "no indentation" in _SYSTEM


def test_the_gateway_holds_no_provider_credential() -> None:
    """MEDAUTH holds a revocable caller key; the provider credential lives in the
    firewall's environment. The gateway has no field for one."""
    import inspect

    from app.llm.firewall_gateway import FirewallGateway

    fields = set(inspect.signature(FirewallGateway).parameters)
    assert not fields & {"api_key", "provider_key", "token", "secret", "authorization"}
