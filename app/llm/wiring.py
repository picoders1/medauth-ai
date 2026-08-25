"""Build the live gateway from settings. The only place a real client is created.

Kept apart from `FirewallGateway` itself so the gateway stays constructible in a
test without touching settings or opening a socket, and so there is exactly one
place where "which model serves which role" is decided.

## Why roles are routed separately, on evidence

The 2026-08-25 capability probe against this deployment found the two configured
models support **inverted** structured-output modes:

| role | strict `json_schema` | `tool_call` | `json_object` |
|---|---|---|---|
| structured-output model | **5/5 schema-valid** | 502 | 5/5 returned, **0/5 schema-valid** |
| general `llm_model` | 502 | 5/5 schema-valid | 502 |

Two consequences, both measured rather than assumed:

**Structured roles must not use `llm_model`.** It rejects `json_schema` outright, so
a deployment that pointed adjudication at it would fail every call - loudly, which is
the good case, but only after the first clinical case rather than at startup.

**The grammar constraint is doing real work.** Same model, same prompt, `json_object`
instead of `json_schema`: five well-formed JSON responses, **zero** satisfying the
schema. Conformance here is structural - the decoder enforces it - not cooperative
compliance the validator happens to catch afterwards. That is the distinction ADR-008
exists to record, and it is now measured on the live path rather than inherited from
Phase 0.

**This says nothing about clinical reasoning.** It is a claim about a decoder.
"""

from __future__ import annotations

import httpx

from app.config.settings import Settings
from app.core.errors import ConfigurationError
from app.llm.client import LlmClient
from app.llm.firewall_gateway import FirewallGateway
from app.llm.gateway import ModelRole
from app.llm.schema_call import StructuredMode

__all__ = ["build_gateway", "structured_model_for"]


def structured_model_for(settings: Settings) -> str:
    """Which model serves the structured-output roles.

    Falls back to `llm_model` only when `llm_structured_model` is unset, and that
    fallback is a deployment statement - "one model does both here" - not a default
    anybody should rely on. On this deployment it is false, and the probe says so.
    """
    configured = settings.llm_structured_model.strip()
    if configured:
        return configured
    fallback = settings.llm_model.strip()
    if not fallback:
        raise ConfigurationError(
            "neither llm_structured_model nor llm_model is set; a gateway with no "
            "model would fail on the first case rather than at startup"
        )
    return fallback


def build_gateway(
    settings: Settings,
    *,
    transport: httpx.AsyncBaseTransport | None = None,
    mode: StructuredMode = StructuredMode.JSON_SCHEMA,
) -> FirewallGateway:
    """The live gateway, pointed at the firewall.

    `transport` exists for contract tests; production passes nothing and gets a real
    connection. The caller key comes from settings and is bound inside `LlmClient`,
    which has nowhere to put a substitute - MEDAUTH holds a revocable caller key and
    never a provider credential.
    """
    structured = structured_model_for(settings)
    client = LlmClient(
        base_url=settings.llm_base_url,
        api_key=settings.llm_api_key.get_secret_value(),
        model=structured,
        timeout_seconds=settings.llm_timeout_seconds,
        max_attempts=settings.llm_max_attempts,
        streaming_enabled=settings.llm_streaming_enabled,
        transport=transport,
    )
    return FirewallGateway(
        client=client,
        models=dict.fromkeys(ModelRole, structured),
        mode=mode,
    )
