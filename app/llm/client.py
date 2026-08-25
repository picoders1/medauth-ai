"""OpenAI-compatible client, pointed at the LLM Firewall.

MEDAUTH speaks the OpenAI HTTP contract and points at the firewall, never at a
provider. The abstraction is ``base_url`` - the firewall *is* the OpenAI API, so
wrapping it in a bespoke gateway interface would convert a standard contract into
a private one and buy portability the protocol already provides (ADR-016).

Three behaviours here are security properties, not conveniences:

* **A 403 is never retried.** Retrying a blocked request is an attempt to evade a
  security control. It raises :class:`UpstreamBlockedError`, which the retry loop
  has no branch for - the distinction is carried by the type system rather than
  by a flag someone can flip.
* **Fail closed means fail toward the human.** Every exhausted failure path ends
  in an exception that routes the case to HUMAN_REVIEW. A security or transport
  failure must never be able to manufacture a clinical outcome in either
  direction.
* **Streaming is rejected before a request is built.** The firewall refuses it
  (400) and a partially-streamed verdict has no meaning when every call must be
  schema-validated.

No message content is ever logged. Structured events carry counts, durations and
identifiers only (ADR-018).
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from types import TracebackType
from typing import Any, Self

import httpx
import structlog

from app.core.errors import (
    ConfigurationError,
    UpstreamBlockedError,
    UpstreamFailureError,
    UpstreamRejectedError,
)
from app.core.ids import RequestId

__all__ = ["ChatResponse", "LlmClient", "TokenUsage"]

log = structlog.get_logger(__name__)

#: Statuses worth another attempt. 403 is deliberately absent and must stay so.
_RETRYABLE = frozenset({408, 425, 429, 500, 502, 503, 504})


@dataclass(frozen=True, slots=True)
class TokenUsage:
    prompt_tokens: int = 0
    completion_tokens: int = 0

    @property
    def total(self) -> int:
        return self.prompt_tokens + self.completion_tokens


@dataclass(frozen=True, slots=True)
class ChatResponse:
    """One completion, reduced to what this application uses."""

    content: str | None
    tool_arguments: str | None
    model: str
    usage: TokenUsage
    finish_reason: str | None
    attempts: int
    latency_ms: float

    @property
    def payload(self) -> str | None:
        """The structured payload, wherever the provider put it.

        Grammar-constrained ``json_schema`` returns it as content; tool calling
        returns it as function arguments. Callers should not care which.
        """
        return self.tool_arguments if self.tool_arguments is not None else self.content


class LlmClient:
    """Pooled async client for the firewall's ``/v1/chat/completions``."""

    def __init__(
        self,
        *,
        base_url: str,
        api_key: str,
        model: str,
        timeout_seconds: float = 60.0,
        max_attempts: int = 3,
        streaming_enabled: bool = False,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        if streaming_enabled:
            raise ConfigurationError(
                "streaming is not supported: the firewall refuses it (400) and a "
                "partially-streamed verdict cannot be schema-validated (ADR-016)"
            )
        self._model = model
        self._max_attempts = max_attempts
        # The credential is bound at construction. `chat()` has nowhere to put an
        # Authorization header, so a caller cannot substitute one.
        self._client = httpx.AsyncClient(
            base_url=base_url,
            timeout=httpx.Timeout(timeout_seconds),
            headers={
                "authorization": f"Bearer {api_key}",
                "content-type": "application/json",
            },
            transport=transport,
        )

    @property
    def model(self) -> str:
        return self._model

    async def __aenter__(self) -> Self:
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        await self.aclose()

    async def aclose(self) -> None:
        await self._client.aclose()

    async def chat(
        self,
        messages: list[dict[str, Any]],
        *,
        request_id: RequestId | None = None,
        model: str | None = None,
        temperature: float = 0.0,
        max_tokens: int | None = None,
        response_format: dict[str, Any] | None = None,
        tools: list[dict[str, Any]] | None = None,
        tool_choice: str | dict[str, Any] | None = None,
    ) -> ChatResponse:
        """Send one completion request. Never streams.

        Raises:
            UpstreamBlockedError: the firewall refused the request (403). Not retried.
            UpstreamRejectedError: the request is malformed or unsupported (other 4xx).
            UpstreamFailureError: transport or upstream failure after the attempt ceiling.
        """
        body: dict[str, Any] = {
            "model": model or self._model,
            "messages": messages,
            "temperature": temperature,
            "stream": False,
        }
        if max_tokens is not None:
            body["max_tokens"] = max_tokens
        if response_format is not None:
            body["response_format"] = response_format
        if tools is not None:
            body["tools"] = tools
        if tool_choice is not None:
            body["tool_choice"] = tool_choice

        headers = {"x-medauth-request-id": str(request_id)} if request_id else None
        started = asyncio.get_running_loop().time()
        last_detail = "no attempt was made"
        last_status: int | None = None

        for attempt in range(1, self._max_attempts + 1):
            try:
                response = await self._client.post("/chat/completions", json=body, headers=headers)
            except httpx.TimeoutException as exc:
                last_detail = f"timeout after {exc.__class__.__name__}"
            except httpx.HTTPError as exc:
                last_detail = f"transport error: {type(exc).__name__}"
            else:
                status = response.status_code

                if status == 403:
                    # Terminal by design. There is no retry branch below this.
                    raise UpstreamBlockedError(
                        category=_error_field(response, "code"),
                        request_id=_error_field(response, "request_id"),
                    )

                if status == 200:
                    elapsed = (asyncio.get_running_loop().time() - started) * 1000
                    return _parse(response, attempts=attempt, latency_ms=elapsed)

                if status not in _RETRYABLE:
                    raise UpstreamRejectedError(
                        f"upstream rejected the request ({status}): "
                        f"{_error_field(response, 'message') or 'no detail'}",
                        status_code=status,
                    )

                last_detail = f"upstream returned {status}"
                last_status = status
                await asyncio.sleep(_backoff(attempt, response))
                continue

            if attempt < self._max_attempts:
                await asyncio.sleep(_backoff(attempt, None))

        log.warning(
            "llm_call_exhausted",
            attempts=self._max_attempts,
            detail=last_detail,
            request_id=str(request_id) if request_id else None,
        )
        # The last status is carried, not dropped. `UpstreamFailureError` has always
        # had the field; the exhausted path never filled it, so the Phase-16 failure
        # taxonomy could not tell a 429 from a 502 after retries were spent - both
        # arrived as an unclassifiable "model path failed" string.
        raise UpstreamFailureError(
            f"model path failed after {self._max_attempts} attempts: {last_detail}",
            status_code=last_status,
        )


def _backoff(attempt: int, response: httpx.Response | None) -> float:
    """Exponential backoff, capped, honouring ``Retry-After`` when offered."""
    if response is not None:
        header = response.headers.get("retry-after")
        if header:
            try:
                requested = float(header)
            except ValueError:
                pass
            else:
                return min(requested, 30.0)
    return min(0.25 * (2.0 ** (attempt - 1)), 8.0)


def _error_field(response: httpx.Response, field: str) -> str | None:
    """Read one field from an OpenAI-shaped error envelope, tolerating anything."""
    try:
        error = response.json().get("error")
    except ValueError:
        return None
    if not isinstance(error, dict):
        return None
    value = error.get(field)
    return str(value) if value is not None else None


def _parse(response: httpx.Response, *, attempts: int, latency_ms: float) -> ChatResponse:
    try:
        body = response.json()
        choice = body["choices"][0]
        message = choice["message"]
    except (ValueError, KeyError, IndexError) as exc:
        raise UpstreamFailureError(f"malformed completion response: {exc}") from exc

    tool_arguments: str | None = None
    calls = message.get("tool_calls")
    if isinstance(calls, list) and calls:
        function = calls[0].get("function", {})
        arguments = function.get("arguments")
        if isinstance(arguments, str):
            tool_arguments = arguments

    usage = body.get("usage") or {}
    return ChatResponse(
        content=message.get("content"),
        tool_arguments=tool_arguments,
        model=str(body.get("model", "")),
        usage=TokenUsage(
            prompt_tokens=int(usage.get("prompt_tokens", 0) or 0),
            completion_tokens=int(usage.get("completion_tokens", 0) or 0),
        ),
        finish_reason=choice.get("finish_reason"),
        attempts=attempts,
        latency_ms=round(latency_ms, 2),
    )
