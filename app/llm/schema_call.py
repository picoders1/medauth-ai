"""The one place model output becomes typed data.

Closed schemas are how the governing invariant is enforced: a model shaping its
output here has no field in which to write an approval, because the token does
not exist in the schema (ADR-010). That guarantee is only as strong as the
mechanism producing it, so this module is explicit about which mechanism is in
use and how often it needed help.

Three modes, in descending order of strength:

``JSON_SCHEMA``
    Grammar-constrained decoding. The *decoder* enforces the schema, so
    conformance is structural rather than cooperative. Preferred wherever the
    served model supports it.
``TOOL_CALL``
    The model emits function arguments. Conformance is learned behaviour, not
    enforced, so validation and repair do real work here.
``JSON_OBJECT``
    Guarantees only that the output parses as JSON - **not** that it matches our
    schema. Weakest, and measured as such.

Which modes a deployment's model supports is an observation, not an assumption:
``scripts/probe_model_capabilities.py`` records it, and ADR-008 cites that report.

``repairs`` is returned on every result and is reported as a first-class metric.
A rising repair rate means the containment is doing more work than it should, and
that is a safety signal rather than an efficiency one.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from enum import StrEnum
from typing import Any

import structlog
from pydantic import BaseModel, ValidationError

from app.core.errors import SchemaValidationError
from app.core.ids import RequestId
from app.llm.client import ChatResponse, LlmClient, TokenUsage

__all__ = ["StructuredMode", "StructuredResult", "structured_call"]

log = structlog.get_logger(__name__)


class StructuredMode(StrEnum):
    JSON_SCHEMA = "json_schema"
    TOOL_CALL = "tool_call"
    JSON_OBJECT = "json_object"


@dataclass(frozen=True, slots=True)
class StructuredResult[M: BaseModel]:
    """A validated object plus what it cost to obtain."""

    value: M
    mode: StructuredMode
    repairs: int
    attempts: int
    usage: TokenUsage
    latency_ms: float
    model: str


def harden_schema(schema: dict[str, Any], defs: dict[str, Any] | None = None) -> dict[str, Any]:
    """Rewrite a Pydantic JSON schema into the strict subset providers accept.

    Two transformations, both required by grammar-constrained decoding:
    ``$ref``/``$defs`` are inlined (many servers reject references), and every
    object gets ``additionalProperties: false`` with all of its properties listed
    as required. The second is what makes the schema *closed* - without it a
    model may add fields, which is precisely the hole this design must not have.
    """
    defs = defs if defs is not None else schema.get("$defs", {})
    node = {k: v for k, v in schema.items() if k != "$defs"}

    ref = node.pop("$ref", None)
    if isinstance(ref, str) and ref.startswith("#/$defs/"):
        target = defs.get(ref.removeprefix("#/$defs/"), {})
        node = {**harden_schema(dict(target), defs), **node}

    for key in ("items", "additionalItems", "contains"):
        if isinstance(node.get(key), dict):
            node[key] = harden_schema(node[key], defs)

    for key in ("anyOf", "oneOf", "allOf", "prefixItems"):
        if isinstance(node.get(key), list):
            node[key] = [harden_schema(m, defs) if isinstance(m, dict) else m for m in node[key]]

    properties = node.get("properties")
    if isinstance(properties, dict):
        node["properties"] = {k: harden_schema(v, defs) for k, v in properties.items()}
        node["required"] = list(node["properties"])
        node["additionalProperties"] = False

    return node


def _request_kwargs(mode: StructuredMode, name: str, schema: dict[str, Any]) -> dict[str, Any]:
    if mode is StructuredMode.JSON_SCHEMA:
        return {
            "response_format": {
                "type": "json_schema",
                "json_schema": {"name": name, "strict": True, "schema": schema},
            }
        }
    if mode is StructuredMode.TOOL_CALL:
        return {
            "tools": [{"type": "function", "function": {"name": name, "parameters": schema}}],
            # Deliberately "auto", not a forced function. Forcing a call requires
            # grammar-constrained decoding, which some serving stacks (e.g. those
            # using speculative decoding) reject outright with a 400.
            "tool_choice": "auto",
        }
    return {"response_format": {"type": "json_object"}}


def _extract[M: BaseModel](response: ChatResponse, schema_model: type[M]) -> M:
    payload = response.payload
    if payload is None or not payload.strip():
        raise ValueError("model returned no payload")
    return schema_model.model_validate_json(payload)


async def structured_call[M: BaseModel](
    client: LlmClient,
    messages: list[dict[str, Any]],
    schema_model: type[M],
    *,
    mode: StructuredMode = StructuredMode.JSON_SCHEMA,
    request_id: RequestId | None = None,
    model: str | None = None,
    max_repair_attempts: int = 2,
    max_tokens: int | None = None,
    temperature: float = 0.0,
) -> StructuredResult[M]:
    """Call the model and return a validated instance of ``schema_model``.

    On a validation failure the error is fed back and the call is retried, up to
    ``max_repair_attempts``. Exhausting them raises
    :class:`~app.core.errors.SchemaValidationError`; the caller turns that into
    ``INSUFFICIENT_EVIDENCE`` for one criterion rather than abandoning the case.

    :class:`~app.core.errors.UpstreamBlockedError` propagates untouched. A block
    is never repaired, retried, or worked around.
    """
    name = schema_model.__name__
    schema = harden_schema(schema_model.model_json_schema())
    kwargs = _request_kwargs(mode, name, schema)

    conversation = list(messages)
    prompt_tokens = completion_tokens = 0
    total_latency = 0.0
    attempts = 0
    last_error = "no attempt was made"

    for repair in range(max_repair_attempts + 1):
        response = await client.chat(
            conversation,
            request_id=request_id,
            model=model,
            temperature=temperature,
            max_tokens=max_tokens,
            **kwargs,
        )
        attempts += response.attempts
        prompt_tokens += response.usage.prompt_tokens
        completion_tokens += response.usage.completion_tokens
        total_latency += response.latency_ms

        try:
            value = _extract(response, schema_model)
        except (ValidationError, ValueError, json.JSONDecodeError) as exc:
            last_error = str(exc)
            if repair == max_repair_attempts:
                break
            log.info(
                "structured_output_repair",
                schema=name,
                mode=mode.value,
                repair_attempt=repair + 1,
                request_id=str(request_id) if request_id else None,
            )
            # Feed back only the validation error - never the clinical content.
            conversation = [
                *messages,
                {"role": "assistant", "content": response.payload or ""},
                {
                    "role": "user",
                    "content": (
                        "That output did not satisfy the required schema. "
                        f"Validation error: {last_error}\n"
                        "Return only a JSON object matching the schema exactly."
                    ),
                },
            ]
            continue

        return StructuredResult(
            value=value,
            mode=mode,
            repairs=repair,
            attempts=attempts,
            usage=TokenUsage(prompt_tokens, completion_tokens),
            latency_ms=round(total_latency, 2),
            model=response.model,
        )

    raise SchemaValidationError(
        f"{name} did not validate after {max_repair_attempts} repair attempt(s): {last_error}",
        attempts=attempts,
    )
