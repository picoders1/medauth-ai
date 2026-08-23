"""Structured logging with redaction enforced at the sink.

Redaction lives in a processor rather than at each call site, because call-site
discipline fails predictably: the leak arrives in a log line added months later by
someone who never read this module. A sink-level rule is safe by default for code
that does not yet exist (ADR-018, threat T-14).

``clinical_text_logging`` is ``off`` by default and ``full`` is refused in
production by :class:`~app.config.settings.Settings` - in code, not by convention.
"""

from __future__ import annotations

import logging
import sys
from typing import Any

import structlog

from app.config.settings import ClinicalTextLogging, Settings

__all__ = ["CLINICAL_KEYS", "configure_logging", "redact_clinical_text"]

#: Event keys that may carry clinical narrative, policy prose, prompts or model
#: output. Redacted unless clinical text logging is explicitly enabled.
CLINICAL_KEYS = frozenset(
    {
        "clinical_text",
        "completion",
        "content",
        "evidence",
        "fact_text",
        "messages",
        "note",
        "note_text",
        "payload",
        "policy_text",
        "prompt",
        "quote",
        "rationale",
        "reasoning",
        "response",
        "text",
    }
)

_REDACTED = "[redacted]"


def redact_clinical_text(
    mode: ClinicalTextLogging,
) -> Any:
    """Build a structlog processor that removes clinical text from every event."""

    def processor(_logger: Any, _method: str, event: dict[str, Any]) -> dict[str, Any]:
        if mode is ClinicalTextLogging.FULL:
            return event
        for key in list(event):
            if key.lower() in CLINICAL_KEYS:
                value = event[key]
                if mode is ClinicalTextLogging.HASHED and isinstance(value, str):
                    # A stable fingerprint supports correlation without content.
                    import hashlib

                    event[key] = "sha256:" + hashlib.sha256(value.encode()).hexdigest()[:16]
                else:
                    event[key] = _REDACTED
        return event

    return processor


def configure_logging(settings: Settings) -> None:
    """Install the process-wide logging configuration. Idempotent."""
    logging.basicConfig(
        format="%(message)s",
        stream=sys.stdout,
        level=getattr(logging, settings.log_level.upper(), logging.INFO),
        force=True,
    )
    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            structlog.processors.add_log_level,
            structlog.processors.TimeStamper(fmt="iso", utc=True),
            # Redaction runs LAST among the enrichers, so nothing added above it
            # can smuggle clinical text past the check.
            redact_clinical_text(settings.clinical_text_logging),
            structlog.processors.StackInfoRenderer(),
            structlog.processors.format_exc_info,
            structlog.processors.JSONRenderer(),
        ],
        wrapper_class=structlog.make_filtering_bound_logger(
            getattr(logging, settings.log_level.upper(), logging.INFO)
        ),
        logger_factory=structlog.PrintLoggerFactory(),
        cache_logger_on_first_use=True,
    )
