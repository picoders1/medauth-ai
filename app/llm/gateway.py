"""The boundary a model call crosses. No call is made here.

    MEDAUTH  ──▶  ModelGateway  ──▶  LLM Firewall :8005/v1  ──▶  provider

This module defines the seam and nothing else. It exists now, before any agent, for
one reason: a direct model call added later "just to try it" is an architectural
shortcut that becomes load-bearing before anyone removes it. Declaring the interface
first makes the shortcut a visible violation rather than an expedient.

## What crosses the boundary

Only **schema-constrained chat completions**. Every call names a closed output
schema and the response is validated against it before it becomes a value. There is
no free-text path, and adding one would reopen the containment argument the whole
architecture rests on: a successful prompt injection cannot emit an approval when no
approval token exists in the schema being filled.

Embeddings do **not** cross it. The firewall exposes no `/v1/embeddings`, and
embedding a policy corpus through a security gateway would inspect nothing useful.
They run in-process (ADR-016).

## Failure semantics, and why they are asymmetric

    403  blocked by the firewall   -> HUMAN_REVIEW. **NEVER RETRIED.**
    503  detector unavailable      -> HUMAN_REVIEW (fail closed)
    timeout / unreachable          -> HUMAN_REVIEW
    400  unsupported feature       -> configuration error, surfaced at startup
    schema-invalid response        -> HUMAN_REVIEW after bounded repair attempts

A `403` is never retried because retrying a blocked request is an attempt to evade a
security control. Every failure routes toward the human and none toward a denial:
fail closed means fail toward a person, never toward a refusal of care.

## Credentials

MEDAUTH holds a revocable **caller** key for the firewall. The provider credential
lives in the firewall's environment. MEDAUTH therefore holds no model-provider
credential at all, and this interface has no field in which one could be passed.

## Model selection is a safety choice, not a quality claim

Phase 0 measured that the primary model supports `response_format: json_schema` at
5/5 schema-valid, while the long-context model rejects every grammar-constrained
mode and supports only `tool_choice: auto`. So structured adjudication prefers the
grammar-constrained path.

**That is a claim about output safety, not about reasoning quality.** No comparison
of clinical reasoning has been run, and none may be claimed. `ModelRole` records
what a call needs rather than naming a model, so the mapping stays in configuration
and a future measurement can change it without touching a call site.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Protocol, runtime_checkable

from pydantic import BaseModel

__all__ = [
    "GatewayFailure",
    "GatewayOutcome",
    "ModelGateway",
    "ModelRequest",
    "ModelResponse",
    "ModelRole",
]


class ModelRole(StrEnum):
    """What a call needs, rather than which model serves it.

    Kept abstract so the model behind a role is a configuration decision. A call
    site naming a model directly would make swapping one a code change across the
    codebase, and would encode a capability claim in a place nobody re-measures.
    """

    #: Per-criterion adjudication. Requires grammar-constrained structured output:
    #: the response is a closed schema with no case-level outcome member in it.
    STRUCTURED_ADJUDICATION = "STRUCTURED_ADJUDICATION"

    #: Extraction of clinical facts from a note. Also schema-constrained, and
    #: forbidden from referencing coverage, policy or any outcome.
    STRUCTURED_INTAKE = "STRUCTURED_INTAKE"


class GatewayOutcome(StrEnum):
    """What happened at the boundary. Never conflated with what the model said."""

    OK = "OK"
    #: The firewall refused the request. Routes to a human and is NEVER retried -
    #: retrying a blocked request is an attempt to evade a security control.
    BLOCKED = "BLOCKED"
    #: The firewall could not evaluate the request. Fail closed.
    DETECTOR_UNAVAILABLE = "DETECTOR_UNAVAILABLE"
    TIMEOUT = "TIMEOUT"
    UNREACHABLE = "UNREACHABLE"
    #: The response did not satisfy the closed schema after bounded repair.
    SCHEMA_INVALID = "SCHEMA_INVALID"
    #: The gateway rejected a feature (streaming, an unsupported mode). A
    #: configuration error, surfaced at startup rather than per request.
    UNSUPPORTED = "UNSUPPORTED"

    @property
    def is_retryable(self) -> bool:
        """Whether the caller may retry. `BLOCKED` never is."""
        return self in (GatewayOutcome.TIMEOUT, GatewayOutcome.UNREACHABLE)

    @property
    def routes_to_human(self) -> bool:
        """Every non-OK outcome does. None routes to a denial."""
        return self is not GatewayOutcome.OK


class GatewayFailure(Exception):
    """The boundary failed. Carries the outcome so a caller cannot lose it."""

    def __init__(self, outcome: GatewayOutcome, detail: str) -> None:
        super().__init__(f"{outcome.value}: {detail}")
        self.outcome = outcome
        self.detail = detail


@dataclass(frozen=True, slots=True)
class ModelRequest:
    """One schema-constrained call.

    There is no `stream` field and no free-text field. Both absences are the
    contract: streaming is refused by the firewall and every response here is a
    validated object, never prose to be parsed.

    `evidence_block` is separate from `instructions` deliberately. Retrieved policy
    text is DATA and is fenced and framed as non-instruction; it is never
    concatenated into a system prompt. Keeping them apart in the type means a caller
    cannot merge them by accident.
    """

    role: ModelRole
    prompt_id: str
    instructions: str
    evidence_block: str
    schema_name: str
    schema: dict[str, object]
    max_repair_attempts: int = 2
    #: Hard ceiling on generated tokens. **A safety control, not a cost control.**
    #:
    #: The 2026-08-25 live activation found intake calls burning 3 x 60s and
    #: returning nothing: `IntakeResult` has five unbounded arrays, and a
    #: grammar-constrained decoder filling them has no natural stopping point. The
    #: schema says the shape is legal, not that it is finite.
    #:
    #: An unbounded call does not fail fast - it ties up the request until the
    #: timeout, three times, and the case reaches a human far later than it should.
    max_output_tokens: int = 1024
    #: Passed to the firewall so it can distinguish user-authored text from
    #: retrieved content. Available, and NOT relied upon: the firewall's
    #: indirect-injection recall is 0.1423 and its provenance overlay ships
    #: uncalibrated (OD-3). Containment here is structural.
    provenance_hint: str = "retrieved-policy-text"

    def __post_init__(self) -> None:
        if not self.prompt_id.strip():
            raise ValueError("every model call names a versioned prompt id")
        if not self.schema:
            raise ValueError(f"{self.prompt_id}: a call with no schema is a free-text call")
        if self.max_output_tokens <= 0:
            raise ValueError(
                f"{self.prompt_id}: max_output_tokens must be positive; an unbounded "
                "structured call has no natural stopping point"
            )


@dataclass(frozen=True, slots=True)
class ModelResponse[M: BaseModel]:
    """A validated object, plus what it cost and how it was produced."""

    value: M
    outcome: GatewayOutcome
    model_id: str
    prompt_id: str
    attempts: int
    latency_ms: float
    prompt_tokens: int = 0
    completion_tokens: int = 0
    notes: tuple[str, ...] = field(default_factory=tuple)


@runtime_checkable
class ModelGateway(Protocol):
    """The single seam through which a model is reached.

    Implemented later. Declared now so that `app/adjudication` and `app/intake` can
    be written and tested against it, and so a direct `httpx` call in a domain
    package is a boundary violation rather than a shortcut nobody notices.
    """

    @property
    def model_for(self) -> dict[ModelRole, str]:
        """Which model serves each role. Configuration, not a capability claim."""
        ...

    async def call[M: BaseModel](
        self, request: ModelRequest, schema_model: type[M]
    ) -> ModelResponse[M]:
        """Make one schema-constrained call.

        Raises `GatewayFailure` on any non-OK outcome rather than returning a
        partial response, so a caller cannot mistake a blocked request for an empty
        answer. `GatewayOutcome.BLOCKED` must never be retried.
        """
        ...
