"""Error hierarchy.

Two deliberate properties:

* ``ConfigurationError`` is raised at startup and is never caught into a running
  degraded state. A misconfigured security boundary must fail loudly rather than
  serve traffic (ADR-017).
* ``UpstreamBlockedError`` is distinct from ``UpstreamFailureError`` because a
  block must **never** be retried - retrying a blocked request is an attempt to
  evade a security control (ADR-016). The type system makes the two impossible
  to conflate in a retry handler.
"""

from __future__ import annotations


class MedauthError(Exception):
    """Base for every error this application raises deliberately."""


class ConfigurationError(MedauthError):
    """Invalid configuration. Raised at startup; never recovered from."""


class LlmError(MedauthError):
    """Base for failures on the model path."""


class UpstreamBlockedError(LlmError):
    """The firewall refused the request (403).

    Carries the block category so it can be recorded in the audit trail. Never
    retried. Routes the case to HUMAN_REVIEW via row 4 of the decision table.
    """

    def __init__(self, category: str | None, request_id: str | None = None) -> None:
        self.category = category
        self.upstream_request_id = request_id
        super().__init__(f"blocked by security policy: {category or 'unspecified'}")


class UpstreamFailureError(LlmError):
    """The firewall or the provider failed (503, 5xx, timeout, unreachable).

    Retryable within the configured attempt ceiling; exhausting it routes the
    case to HUMAN_REVIEW. Fail closed means fail toward the human.
    """

    def __init__(self, detail: str, status_code: int | None = None) -> None:
        self.status_code = status_code
        super().__init__(detail)


class UpstreamRejectedError(LlmError):
    """The request itself is malformed or unsupported by the provider (4xx).

    Distinct from a failure: retrying will not help, and it indicates a defect in
    this application rather than a transient condition.
    """

    def __init__(self, detail: str, status_code: int | None = None) -> None:
        self.status_code = status_code
        super().__init__(detail)


class SchemaValidationError(LlmError):
    """Model output did not satisfy its closed schema after bounded repair.

    The affected criterion becomes INSUFFICIENT_EVIDENCE; the case is not
    abandoned.

    `finish_reason`, `body_chars` and `whitespace_fraction` describe the SHAPE of
    the last response - three numbers, no content. They are carried because
    "invalid after repair" covers two failures with different owners: a model that
    terminated and returned the wrong object, and a decoder that never terminated
    at all (R-86). Without the shape those are the same exception, and Phase 16's
    factorial found the second one being reported as the first.
    """

    def __init__(
        self,
        detail: str,
        attempts: int,
        *,
        finish_reason: str | None = None,
        body_chars: int = 0,
        whitespace_fraction: float = 0.0,
    ) -> None:
        self.attempts = attempts
        self.finish_reason = finish_reason
        self.body_chars = body_chars
        self.whitespace_fraction = whitespace_fraction
        super().__init__(detail)
