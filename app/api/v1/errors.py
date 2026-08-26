"""One place that decides which HTTP status a domain error deserves.

Routes do not choose status codes. A route that decided `409` for one invalid
transition and `422` for another would give callers a contract that depends on which
handler they hit, and the drift would be invisible until somebody wrote a client.

## Domain errors are not 500s

`MedauthError` subclasses each map to a status that says what went wrong. The default is
**500 only for errors this table does not know**, which is the honest meaning of "we did
not anticipate this" - and an unknown error never leaks its message, because a message
this table has not vetted may contain anything the runtime put in it.

## What is never in a response

No stack traces, no SQL, no provider identifiers, no clinical text. The `detail` of a
mapped error is its own message, which is written by us; the detail of an unmapped one
is a fixed string and the real error goes to the log with the request id attached.
"""

from __future__ import annotations

from typing import Any

from fastapi import Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from app.api.v1.security import NotAuthenticated
from app.case.lifecycle import InvalidTransition
from app.case.review import ReviewRejected
from app.case.service import CaseNotFound, NotAuthorised
from app.core.errors import (
    ConfigurationError,
    MedauthError,
    SchemaValidationError,
    UpstreamBlockedError,
    UpstreamFailureError,
    UpstreamRejectedError,
)

__all__ = ["ApiError", "http_status_for", "problem_response"]


class ApiError(BaseModel):
    """The stable error contract. Every failure has this shape."""

    error: str = Field(description="A stable machine-readable code.")
    detail: str = Field(description="Human-readable, and authored here - never a traceback.")
    request_id: str
    case_id: str | None = None


#: Ordered most specific first. `InvalidTransition` before `MedauthError`, or every
#: conflict would be swallowed by the base class.
_STATUS: tuple[tuple[type[BaseException], int, str], ...] = (
    (NotAuthenticated, 401, "not_authenticated"),
    (CaseNotFound, 404, "case_not_found"),
    (NotAuthorised, 403, "not_authorised"),
    (InvalidTransition, 409, "invalid_state_transition"),
    (ReviewRejected, 422, "review_rejected"),
    # A blocked request is a security decision, not a dependency outage, and it is
    # never retried (ADR: retrying a blocked request is an attempt to evade a control).
    (UpstreamBlockedError, 403, "blocked_by_firewall"),
    # 424: the dependency answered, and what it said was unusable. Distinguished from
    # 503 because a caller should not retry this one either.
    (SchemaValidationError, 424, "provider_schema_failure"),
    (UpstreamRejectedError, 424, "provider_rejected_request"),
    (UpstreamFailureError, 503, "provider_unavailable"),
    (ConfigurationError, 503, "misconfigured"),
)


def http_status_for(exc: BaseException) -> tuple[int, str]:
    """The status and code for a domain error. 500 only for what is not listed."""
    for kind, status, code in _STATUS:
        if isinstance(exc, kind):
            return status, code
    if isinstance(exc, MedauthError):
        # A domain error we have not classified. 422 rather than 500: it came from our
        # own vocabulary, so it is a request problem far more often than a bug, and a
        # blanket 500 here is how domain errors get lost.
        return 422, "domain_error"
    return 500, "internal_error"


def problem_response(
    request: Request, exc: BaseException, *, request_id: str, case_id: str | None = None
) -> JSONResponse:
    status, code = http_status_for(exc)
    # An unmapped error's message is not ours and is not shown. The real one is logged.
    detail = str(exc) if status != 500 else "An unexpected internal error occurred."
    body: dict[str, Any] = ApiError(
        error=code, detail=detail, request_id=request_id, case_id=case_id
    ).model_dump()
    return JSONResponse(
        status_code=status, content=body, headers={"x-medauth-request-id": request_id}
    )
