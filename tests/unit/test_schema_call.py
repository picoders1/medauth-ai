"""Structured output: schema hardening, validation, and bounded repair."""

from __future__ import annotations

import json

import httpx
import pytest
from pydantic import BaseModel, ConfigDict

from app.core.errors import SchemaValidationError, UpstreamBlockedError
from app.core.types import Verdict
from app.llm.client import LlmClient
from app.llm.schema_call import StructuredMode, harden_schema, structured_call

pytestmark = pytest.mark.unit


class Citation(BaseModel):
    model_config = ConfigDict(extra="forbid")
    chunk_id: str
    quote: str


class Sample(BaseModel):
    """Shaped like a real per-criterion verdict, including a nested model."""

    model_config = ConfigDict(extra="forbid")
    criterion_id: str
    verdict: Verdict
    citations: list[Citation]


class ScriptedTransport(httpx.AsyncBaseTransport):
    def __init__(self, *payloads: str) -> None:
        self._payloads = list(payloads)
        self.count = 0
        self.bodies: list[dict[str, object]] = []

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        self.bodies.append(json.loads(request.content))
        payload = self._payloads[min(self.count, len(self._payloads) - 1)]
        self.count += 1
        return httpx.Response(
            200,
            json={
                "model": "test-model",
                "choices": [{"message": {"content": payload}, "finish_reason": "stop"}],
                "usage": {"prompt_tokens": 5, "completion_tokens": 3},
            },
            request=request,
        )


def _client(transport: httpx.AsyncBaseTransport) -> LlmClient:
    return LlmClient(
        base_url="http://firewall.test/v1", api_key="k", model="test-model", transport=transport
    )


VALID = json.dumps(
    {"criterion_id": "c1", "verdict": "SATISFIED", "citations": [{"chunk_id": "ch1", "quote": "q"}]}
)
MESSAGES = [{"role": "user", "content": "adjudicate"}]


# --------------------------------------------------------------- schema shape
def test_harden_schema_closes_every_object() -> None:
    """Closed means closed: no object may accept an unlisted field."""
    hardened = harden_schema(Sample.model_json_schema())

    assert hardened["additionalProperties"] is False
    assert set(hardened["required"]) == {"criterion_id", "verdict", "citations"}
    nested = hardened["properties"]["citations"]["items"]
    assert nested["additionalProperties"] is False, "nested $ref was not inlined and closed"
    assert set(nested["required"]) == {"chunk_id", "quote"}


def test_harden_schema_leaves_no_references() -> None:
    """Grammar-constrained decoders commonly reject ``$ref``/``$defs``."""
    rendered = json.dumps(harden_schema(Sample.model_json_schema()))
    assert "$ref" not in rendered and "$defs" not in rendered


def test_hardened_schema_still_carries_the_closed_enum() -> None:
    """The containment property must survive hardening."""
    enum = harden_schema(Sample.model_json_schema())["properties"]["verdict"]["enum"]
    assert set(enum) == {v.value for v in Verdict}
    assert not {"APPROVE_RECOMMENDED", "DENY_RECOMMENDED"} & set(enum)


# ------------------------------------------------------------------ behaviour
async def test_valid_first_response_needs_no_repair() -> None:
    transport = ScriptedTransport(VALID)
    async with _client(transport) as client:
        result = await structured_call(client, MESSAGES, Sample)

    assert transport.count == 1
    assert result.repairs == 0
    assert result.value.verdict is Verdict.SATISFIED
    assert result.usage.total == 8


async def test_invalid_output_is_repaired_and_counted() -> None:
    """A repair is recorded, because the repair rate is a reported metric."""
    transport = ScriptedTransport('{"criterion_id": "c1"}', VALID)
    async with _client(transport) as client:
        result = await structured_call(client, MESSAGES, Sample, max_repair_attempts=2)

    assert transport.count == 2
    assert result.repairs == 1
    assert result.value.criterion_id == "c1"


async def test_repair_feedback_carries_no_clinical_text() -> None:
    """The retry turn states the validation error and nothing about the patient."""
    secret = "PATIENT-NOTE-DO-NOT-ECHO"
    transport = ScriptedTransport("not json at all", VALID)
    async with _client(transport) as client:
        await structured_call(
            client, [{"role": "user", "content": secret}], Sample, max_repair_attempts=1
        )

    repair_turn = transport.bodies[1]["messages"][-1]["content"]  # type: ignore[index]
    assert "schema" in repair_turn
    assert secret not in repair_turn


async def test_exhausted_repair_raises() -> None:
    """A criterion that will not validate becomes INSUFFICIENT_EVIDENCE upstream."""
    transport = ScriptedTransport('{"wrong": true}')
    async with _client(transport) as client:
        with pytest.raises(SchemaValidationError) as caught:
            await structured_call(client, MESSAGES, Sample, max_repair_attempts=2)

    assert transport.count == 3, "repair budget was not spent exactly"
    assert caught.value.attempts == 3


async def test_a_block_is_never_repaired() -> None:
    """UpstreamBlockedError propagates untouched - a block is not a schema problem."""

    class Blocking(httpx.AsyncBaseTransport):
        count = 0

        async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
            type(self).count += 1
            return httpx.Response(
                403, json={"error": {"code": "prompt_injection"}}, request=request
            )

    transport = Blocking()
    async with _client(transport) as client:
        with pytest.raises(UpstreamBlockedError):
            await structured_call(client, MESSAGES, Sample, max_repair_attempts=2)

    assert Blocking.count == 1, "a block was retried or repaired"


# ----------------------------------------------------------------- wire shape
@pytest.mark.parametrize(
    ("mode", "expect_key"),
    [
        (StructuredMode.JSON_SCHEMA, "response_format"),
        (StructuredMode.TOOL_CALL, "tools"),
        (StructuredMode.JSON_OBJECT, "response_format"),
    ],
)
async def test_each_mode_sends_its_own_request_shape(mode: StructuredMode, expect_key: str) -> None:
    transport = ScriptedTransport(VALID)
    async with _client(transport) as client:
        await structured_call(client, MESSAGES, Sample, mode=mode)

    assert expect_key in transport.bodies[0]


async def test_tool_mode_does_not_force_the_function() -> None:
    """Forcing a call requires grammar-constrained decoding, which some serving
    stacks reject with a 400. ``auto`` keeps the mode usable there."""
    transport = ScriptedTransport(VALID)
    async with _client(transport) as client:
        await structured_call(client, MESSAGES, Sample, mode=StructuredMode.TOOL_CALL)

    assert transport.bodies[0]["tool_choice"] == "auto"


async def test_tool_call_arguments_are_read_from_the_tool_call() -> None:
    class ToolTransport(httpx.AsyncBaseTransport):
        async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
            return httpx.Response(
                200,
                json={
                    "model": "test-model",
                    "choices": [
                        {
                            "message": {
                                "content": "",
                                "tool_calls": [
                                    {"function": {"name": "Sample", "arguments": VALID}}
                                ],
                            },
                            "finish_reason": "tool_calls",
                        }
                    ],
                    "usage": {},
                },
                request=request,
            )

    async with _client(ToolTransport()) as client:
        result = await structured_call(client, MESSAGES, Sample, mode=StructuredMode.TOOL_CALL)

    assert result.value.verdict is Verdict.SATISFIED
