"""The model path fails closed, and closed means *toward the human*.

Every assertion here is about a security property rather than a convenience:

* a block is never retried, because retrying one is an attempt to evade a control;
* an exhausted failure raises rather than returning something a caller might
  mistake for a result;
* a caller cannot substitute the credential the client was constructed with;
* streaming cannot be turned on, because a streamed verdict cannot be validated.

Counting the requests matters as much as the exception type. A test that only
asserted ``UpstreamBlockedError`` would still pass if the client had quietly
retried three times first - and that retry is the thing being forbidden.
"""

from __future__ import annotations

import httpx
import pytest

from app.core.errors import (
    ConfigurationError,
    UpstreamBlockedError,
    UpstreamFailureError,
    UpstreamRejectedError,
)
from app.core.ids import RequestId
from app.llm.client import LlmClient

pytestmark = [pytest.mark.security, pytest.mark.unit]

BASE = "http://firewall.test/v1"


class CountingTransport(httpx.AsyncBaseTransport):
    """Records every request that reaches the wire."""

    def __init__(self, *responses: httpx.Response) -> None:
        self._responses = list(responses)
        self.requests: list[httpx.Request] = []

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        response = self._responses[min(len(self.requests) - 1, len(self._responses) - 1)]
        return httpx.Response(
            status_code=response.status_code,
            headers=response.headers,
            content=response.content,
            request=request,
        )

    @property
    def call_count(self) -> int:
        return len(self.requests)


def _client(transport: httpx.AsyncBaseTransport, **kw: object) -> LlmClient:
    params: dict[str, object] = {
        "base_url": BASE,
        "api_key": "caller-key",
        "model": "test-model",
        "max_attempts": 3,
        "timeout_seconds": 1.0,
    }
    params.update(kw)
    return LlmClient(transport=transport, **params)  # type: ignore[arg-type]


def _json(status: int, body: dict[str, object]) -> httpx.Response:
    return httpx.Response(status_code=status, json=body)


def _ok(content: str = '{"verdict":"SATISFIED"}') -> httpx.Response:
    return _json(
        200,
        {
            "model": "test-model",
            "choices": [{"message": {"content": content}, "finish_reason": "stop"}],
            "usage": {"prompt_tokens": 11, "completion_tokens": 7},
        },
    )


MESSAGES = [{"role": "user", "content": "criterion"}]


async def test_block_is_never_retried() -> None:
    """A 403 is terminal. One request reaches the wire - not two, not four."""
    transport = CountingTransport(
        _json(403, {"error": {"code": "prompt_injection", "request_id": "abc"}})
    )
    async with _client(transport) as client:
        with pytest.raises(UpstreamBlockedError) as caught:
            await client.chat(MESSAGES)

    assert transport.call_count == 1, (
        f"the client sent {transport.call_count} requests after a block. "
        "Retrying a blocked request is an attempt to evade a security control."
    )
    assert caught.value.category == "prompt_injection"
    assert caught.value.upstream_request_id == "abc"


async def test_upstream_failure_is_retried_then_raises() -> None:
    """503 is retryable, but exhaustion raises rather than returning a result."""
    transport = CountingTransport(_json(503, {"error": {"message": "detector_failure"}}))
    async with _client(transport, max_attempts=3) as client:
        with pytest.raises(UpstreamFailureError):
            await client.chat(MESSAGES)

    assert transport.call_count == 3, "the attempt ceiling was not honoured"


async def test_transient_failure_then_success() -> None:
    """A recovered call returns, and reports how many attempts it took."""
    transport = CountingTransport(_json(503, {"error": {}}), _ok())
    async with _client(transport) as client:
        result = await client.chat(MESSAGES)

    assert transport.call_count == 2
    assert result.attempts == 2
    assert result.usage.total == 18


async def test_client_error_is_not_retried() -> None:
    """A 400 means this application built a bad request. Retrying cannot help."""
    transport = CountingTransport(_json(400, {"error": {"message": "unsupported_feature"}}))
    async with _client(transport) as client:
        with pytest.raises(UpstreamRejectedError) as caught:
            await client.chat(MESSAGES)

    assert transport.call_count == 1
    assert caught.value.status_code == 400


async def test_streaming_cannot_be_enabled() -> None:
    """Rejected at construction, before any request can be built."""
    with pytest.raises(ConfigurationError, match="streaming"):
        _client(CountingTransport(_ok()), streaming_enabled=True)


async def test_every_request_declares_stream_false() -> None:
    """The firewall refuses streaming; the body must say so explicitly."""
    transport = CountingTransport(_ok())
    async with _client(transport) as client:
        await client.chat(MESSAGES)

    import json

    assert json.loads(transport.requests[0].content)["stream"] is False


async def test_caller_cannot_substitute_the_credential() -> None:
    """The key is bound at construction; ``chat()`` has nowhere to put a header.

    Asserted on the signature as well as the behaviour, so a refactor that adds a
    headers parameter fails here before it can leak one.
    """
    import inspect

    parameters = set(inspect.signature(LlmClient.chat).parameters)
    assert not parameters & {"headers", "authorization", "api_key", "auth"}, (
        f"LlmClient.chat exposes a credential-bearing parameter: {sorted(parameters)}"
    )

    transport = CountingTransport(_ok())
    async with _client(transport) as client:
        await client.chat(MESSAGES, request_id=RequestId("req-1"))

    sent = transport.requests[0].headers
    assert sent["authorization"] == "Bearer caller-key"
    assert sent["x-medauth-request-id"] == "req-1"


async def test_no_clinical_text_in_the_error_path(caplog: pytest.LogCaptureFixture) -> None:
    """An exhausted call must not put message content into a log record."""
    secret = "PATIENT-NOTE-DO-NOT-LOG"
    transport = CountingTransport(_json(503, {"error": {}}))
    async with _client(transport, max_attempts=2) as client:
        with pytest.raises(UpstreamFailureError):
            await client.chat([{"role": "user", "content": secret}])

    assert secret not in caplog.text
