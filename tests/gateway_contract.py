"""A transport that answers like a firewall, without one being there.

`FirewallGateway` is the only class in this repository that will ever open a socket
to a model provider. Testing it needs a firewall to respond - and needing a running
firewall to test the failure classification would mean the failure paths were never
tested, because nobody stands up a service in order to make it return 403.

`httpx.MockTransport` answers instead. `LlmClient` already accepts a `transport`
argument for exactly this, so the class under test is the real one, wired the real
way, reached through the real client. **Nothing here calls a provider and nothing
here needs a network.**

This module is inside the documented mypy scope, because it constructs the gateway
that domain code will depend on.
"""

from __future__ import annotations

import json
from typing import Any

import httpx

from app.llm.client import LlmClient
from app.llm.firewall_gateway import FirewallGateway
from app.llm.gateway import ModelRequest, ModelRole
from app.llm.schema_call import StructuredMode

__all__ = [
    "MODELS",
    "blocked_transport",
    "error_transport",
    "gateway_with",
    "json_transport",
    "request_for",
    "timeout_transport",
]

#: One model per role. Configuration, not a capability claim.
MODELS: dict[ModelRole, str] = {
    ModelRole.STRUCTURED_INTAKE: "csg-small",
    ModelRole.STRUCTURED_ADJUDICATION: "csg-small",
}


def _completion(payload: str, *, model: str = "csg-small") -> dict[str, Any]:
    """An OpenAI-shaped completion carrying `payload` as its content."""
    return {
        "id": "chatcmpl-fixture",
        "object": "chat.completion",
        "model": model,
        "choices": [
            {
                "index": 0,
                "message": {"role": "assistant", "content": payload},
                "finish_reason": "stop",
            }
        ],
        "usage": {"prompt_tokens": 11, "completion_tokens": 7, "total_tokens": 18},
    }


def json_transport(value: object, *, model: str = "csg-small") -> httpx.MockTransport:
    """Answers every call with `value` serialised as the structured payload."""

    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=_completion(json.dumps(value), model=model))

    return httpx.MockTransport(handler)


def raw_transport(payload: str) -> httpx.MockTransport:
    """Answers with an arbitrary string - malformed JSON, prose, an empty body."""

    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=_completion(payload))

    return httpx.MockTransport(handler)


def blocked_transport() -> httpx.MockTransport:
    """The firewall refusing the request. **Must never be retried.**"""

    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            403,
            json={"error": {"message": "request blocked by policy", "type": "blocked"}},
        )

    return httpx.MockTransport(handler)


def error_transport(status: int) -> httpx.MockTransport:
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(status, json={"error": {"message": f"upstream {status}"}})

    return httpx.MockTransport(handler)


def timeout_transport() -> httpx.MockTransport:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("read timed out", request=request)

    return httpx.MockTransport(handler)


def counting_transport(inner: httpx.MockTransport, counter: list[int]) -> httpx.MockTransport:
    """Wraps a transport and counts attempts, so a retry is observable.

    Counting rather than asserting: whether a 403 was retried is a fact about the
    number of requests, and reading it off a log message would be reading a sentence
    instead of counting calls.
    """

    def handler(request: httpx.Request) -> httpx.Response:
        counter.append(1)
        response = inner.handler(request)
        # `MockTransport.handler` is typed as possibly-async. Ours never is, and
        # asserting that is better than silencing it: a coroutine leaking through
        # here would be counted as a request and never awaited.
        assert isinstance(response, httpx.Response), "counting_transport wraps sync handlers only"
        return response

    return httpx.MockTransport(handler)


def gateway_with(
    transport: httpx.MockTransport,
    *,
    max_attempts: int = 3,
    mode: StructuredMode = StructuredMode.JSON_SCHEMA,
) -> FirewallGateway:
    """The real gateway, the real client, a fake wire."""
    client = LlmClient(
        base_url="http://firewall.invalid/v1",
        api_key="test-caller-key",
        model="csg-small",
        timeout_seconds=2.0,
        max_attempts=max_attempts,
        transport=transport,
    )
    return FirewallGateway(client=client, models=MODELS, mode=mode)


def request_for(
    role: ModelRole = ModelRole.STRUCTURED_ADJUDICATION,
    *,
    prompt_id: str = "adjudication.v1",
    instructions: str = "assess one criterion",
    evidence_block: str = "<<<MEDAUTH-DATA-8f2a>>> policy text <<<MEDAUTH-DATA-8f2a>>>",
) -> ModelRequest:
    return ModelRequest(
        role=role,
        prompt_id=prompt_id,
        instructions=instructions,
        evidence_block=evidence_block,
        schema_name="CriterionAssessment",
        schema={"type": "object"},
    )
