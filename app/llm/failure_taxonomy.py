"""What went wrong at the model boundary, in enough detail to escalate. Part A1.

`GatewayOutcome` is the **routing** vocabulary: seven members, every one of which
sends the case to a human. That is the correct size for routing - a case does not
need to know whether it was a 502 or a 504 - and it is far too coarse for a
reliability report. Phase 14 published "MODEL_ASSESSMENT: 16" and a provider outage
read as sixteen reasoning errors.

This module is the **diagnostic** vocabulary. Same transport facts, finer grain, and
a separate question: *whose problem is this?*

## The rule that makes the taxonomy honest

> **A bad answer is not a provider failure. A broken response path is.**

`classify_provider_failure` takes transport facts only - an exception, a status code,
a response body's shape. It cannot see whether the answer was right, and there is no
parameter through which it could. A taxonomy that could see accuracy would drift into
explaining away wrong answers as infrastructure, which is the direction that flatters.

The inverse also holds and matters more: a model that returns a well-formed, schema
-valid, completely incorrect verdict produces `NONE` here. That is not the boundary's
failure, and calling it one would hide a reasoning defect inside an outage.

## Attribution is usually indeterminate, and says so

MEDAUTH reaches the provider only through the firewall and holds no provider
credential. For most failures the two are **not distinguishable from here** - a 502
could be the provider refusing or the proxy failing to reach it. `INDETERMINATE` is
the honest answer and is the default; naming a layer without evidence is how an
escalation gets closed against the wrong team.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from app.core.errors import (
    LlmError,
    SchemaValidationError,
    UpstreamBlockedError,
    UpstreamFailureError,
    UpstreamRejectedError,
)

__all__ = [
    "FailureAttribution",
    "ProviderFailure",
    "ProviderFailureKind",
    "ResponseShape",
    "classify_provider_failure",
]


class ProviderFailureKind(StrEnum):
    """One reason a request did not produce a usable response.

    Ten failure members plus `NONE`. The list is closed and every member is
    reachable from a transport fact; a category that could only be assigned by
    judgement would be assigned inconsistently and would then be aggregated.
    """

    #: The response path worked. **Says nothing about whether the answer was right.**
    NONE = "NONE"

    #: The request exceeded the client timeout, on every attempt.
    TIMEOUT = "TIMEOUT"

    #: 4xx other than 403 and 429. The request was rejected as malformed or
    #: unsupported - which is usually OUR defect, not the provider's.
    UPSTREAM_CLIENT_ERROR = "UPSTREAM_CLIENT_ERROR"

    #: 403 from the firewall. **Not a reliability failure**: a security control
    #: doing its job. Counted separately so an outage rate cannot be inflated by
    #: the firewall working correctly, and never retried.
    UPSTREAM_BLOCKED = "UPSTREAM_BLOCKED"

    #: 5xx other than 503-as-detector-unavailable. The far side failed.
    UPSTREAM_SERVER_ERROR = "UPSTREAM_SERVER_ERROR"

    #: 429, or an explicit rate-limit signal. Separated from 5xx because the
    #: remediation is ours (pace the calls) rather than theirs.
    RATE_LIMITED = "RATE_LIMITED"

    #: The firewall could not evaluate the request and failed closed (503).
    #: Attributable to the proxy layer specifically, which is rare enough to be
    #: worth keeping distinct.
    PROXY_TRANSFORMATION = "PROXY_TRANSFORMATION"

    #: HTTP 200 with a body that is not usable JSON at all - truncated, empty, or
    #: not an object. The response path returned something; it was not a response.
    MALFORMED_RESPONSE = "MALFORMED_RESPONSE"

    #: The body parses and does not satisfy the closed schema after bounded repair.
    #: **This is where R-86 lands**: grammar-constrained decoding guarantees the
    #: output shape and not that the output terminates, so a decoder can satisfy
    #: the schema forever with whitespace and hit the ceiling mid-document.
    SCHEMA_GRAMMAR_FAILURE = "SCHEMA_GRAMMAR_FAILURE"

    #: The socket never opened, or died. No status code exists.
    CONNECTION_FAILURE = "CONNECTION_FAILURE"

    #: Reached the boundary and matched nothing above. Deliberately last and
    #: deliberately not empty: an unclassified failure must be visible as
    #: unclassified rather than folded into the nearest neighbour.
    UNKNOWN_PROVIDER_FAILURE = "UNKNOWN_PROVIDER_FAILURE"

    @property
    def is_failure(self) -> bool:
        return self is not ProviderFailureKind.NONE

    @property
    def counts_toward_provider_reliability(self) -> bool:
        """Whether this belongs in a provider-failure rate.

        `UPSTREAM_BLOCKED` does not: the firewall refusing a request is a control
        operating correctly, and counting it as an outage would make a security
        system look like an availability problem. `UPSTREAM_CLIENT_ERROR` does not
        either - a 400 means we sent something wrong.
        """
        return self.is_failure and self not in (
            ProviderFailureKind.UPSTREAM_BLOCKED,
            ProviderFailureKind.UPSTREAM_CLIENT_ERROR,
        )


class FailureAttribution(StrEnum):
    """Whose defect this is, as far as the evidence reaches.

    `INDETERMINATE` is the default and the commonest answer, because MEDAUTH sees
    one hop. Guessing between the provider and the proxy is how an escalation is
    closed against the wrong owner and reopened a month later.
    """

    #: Ours. A malformed request, an unsupported feature, a pacing problem.
    MEDAUTH = "MEDAUTH"
    #: The firewall specifically - it answered, about itself.
    FIREWALL = "FIREWALL"
    #: The provider specifically. **Rarely assignable from here**, and never by
    #: inference from a symptom.
    PROVIDER = "PROVIDER"
    #: Provider or firewall; the interface cannot separate them.
    INDETERMINATE = "INDETERMINATE"
    #: No failure to attribute.
    NONE = "NONE"


#: Who owns each kind. Declared as data so a new kind cannot be added without
#: deciding who it belongs to - and so that the many `INDETERMINATE` entries are
#: visible as a deliberate refusal to guess rather than as an oversight.
_ATTRIBUTION: dict[ProviderFailureKind, FailureAttribution] = {
    ProviderFailureKind.NONE: FailureAttribution.NONE,
    # We sent it, we own it.
    ProviderFailureKind.UPSTREAM_CLIENT_ERROR: FailureAttribution.MEDAUTH,
    ProviderFailureKind.RATE_LIMITED: FailureAttribution.MEDAUTH,
    # The firewall answered about itself.
    ProviderFailureKind.UPSTREAM_BLOCKED: FailureAttribution.FIREWALL,
    ProviderFailureKind.PROXY_TRANSFORMATION: FailureAttribution.FIREWALL,
    # Everything else is one hop away and stays unassigned. R-86 in particular:
    # a decoder that pads and a proxy that pads are indistinguishable from here,
    # and the escalation asks the owner rather than answering for them.
    ProviderFailureKind.TIMEOUT: FailureAttribution.INDETERMINATE,
    ProviderFailureKind.UPSTREAM_SERVER_ERROR: FailureAttribution.INDETERMINATE,
    ProviderFailureKind.MALFORMED_RESPONSE: FailureAttribution.INDETERMINATE,
    ProviderFailureKind.SCHEMA_GRAMMAR_FAILURE: FailureAttribution.INDETERMINATE,
    ProviderFailureKind.CONNECTION_FAILURE: FailureAttribution.INDETERMINATE,
    ProviderFailureKind.UNKNOWN_PROVIDER_FAILURE: FailureAttribution.INDETERMINATE,
}


@dataclass(frozen=True, slots=True)
class ResponseShape:
    """What a 200 response body looked like. **No content, only shape.**

    Every field is a count, a fraction or a flag. There is no field a clinical note,
    a policy quote or a model rationale could be put in, which is what makes a
    reliability report safe to export.
    """

    #: `stop`, `length`, `content_filter`, or absent.
    finish_reason: str | None = None
    #: Characters in the structured payload, whatever the provider called it.
    body_chars: int = 0
    #: Share of the payload that is whitespace. The R-86 signature.
    whitespace_fraction: float = 0.0
    parsed_as_json: bool = False
    satisfied_schema: bool = False
    prompt_tokens: int = 0
    completion_tokens: int = 0

    @property
    def looks_like_whitespace_runaway(self) -> bool:
        """R-86's fingerprint: hit the ceiling, and mostly whitespace.

        Both conditions. Whitespace alone is normal in pretty-printed JSON, and
        hitting the ceiling alone is an ordinary truncation of a long answer.
        """
        return self.finish_reason == "length" and self.whitespace_fraction >= 0.5


@dataclass(frozen=True, slots=True)
class ProviderFailure:
    """One classified failure, with what it does and does not license."""

    kind: ProviderFailureKind
    attribution: FailureAttribution
    #: HTTP status where one was seen. `None` means no response arrived.
    status_code: int | None = None
    #: A short, non-clinical description. Exception types and status codes only.
    detail: str = ""
    shape: ResponseShape | None = None
    #: True where the shape matches R-86 specifically, rather than schema failure
    #: in general. A schema failure that terminated cleanly is a different defect.
    is_r86_signature: bool = False

    @property
    def is_failure(self) -> bool:
        return self.kind.is_failure

    @property
    def counts_toward_provider_reliability(self) -> bool:
        return self.kind.counts_toward_provider_reliability


def _status_kind(status: int) -> ProviderFailureKind:
    """HTTP status to kind. The only place this mapping exists."""
    if status == 403:
        return ProviderFailureKind.UPSTREAM_BLOCKED
    if status == 429:
        return ProviderFailureKind.RATE_LIMITED
    if status == 503:
        return ProviderFailureKind.PROXY_TRANSFORMATION
    if 500 <= status < 600:
        return ProviderFailureKind.UPSTREAM_SERVER_ERROR
    if 400 <= status < 500:
        return ProviderFailureKind.UPSTREAM_CLIENT_ERROR
    return ProviderFailureKind.UNKNOWN_PROVIDER_FAILURE


def classify_provider_failure(
    error: BaseException | None,
    *,
    status_code: int | None = None,
    shape: ResponseShape | None = None,
) -> ProviderFailure:
    """Transport facts to a failure record. Pure, total, and accuracy-blind.

    There is **no parameter for whether the answer was correct**, and adding one
    would be the defect this module exists to prevent. A model that returns a
    schema-valid, well-formed, entirely wrong verdict classifies as `NONE`.

    Ordered most-specific first, for the same reason `_classify` is: a block must
    never be reclassified into something retryable by a later branch matching on a
    substring.
    """
    if error is None:
        # Success at the boundary. A schema-invalid body would have raised, so a
        # shape that says otherwise is a caller bug rather than a provider failure.
        return ProviderFailure(
            kind=ProviderFailureKind.NONE,
            attribution=FailureAttribution.NONE,
            status_code=status_code,
            shape=shape,
        )

    name = type(error).__name__
    kind: ProviderFailureKind

    if isinstance(error, UpstreamBlockedError):
        kind = ProviderFailureKind.UPSTREAM_BLOCKED
    elif isinstance(error, SchemaValidationError):
        # Every repair attempt was spent and the body still did not validate. R-86
        # arrives here; so does a genuinely malformed response, and `shape` is what
        # separates them.
        #
        # **The runaway test comes FIRST, and the first version of this function had
        # it second.** That ordering hid R-86 from its own taxonomy: a decoder that
        # pads to the ceiling never closes the document, so the body does not parse,
        # so an "unparseable => MALFORMED_RESPONSE" branch swallowed every
        # occurrence. `r86-factorial-001` reported five textbook runaways -
        # finish_reason=length, 1536 completion tokens, 92% whitespace - as
        # MALFORMED_RESPONSE with `is_r86_signature: False`.
        #
        # Found by running the experiment; the instrument was the defect. A
        # genuinely malformed response is one that TERMINATED and returned garbage,
        # which is a different failure with a different owner.
        if shape is not None and shape.looks_like_whitespace_runaway:
            kind = ProviderFailureKind.SCHEMA_GRAMMAR_FAILURE
        elif shape is not None and not shape.parsed_as_json:
            kind = ProviderFailureKind.MALFORMED_RESPONSE
        else:
            kind = ProviderFailureKind.SCHEMA_GRAMMAR_FAILURE
    elif isinstance(error, UpstreamRejectedError):
        kind = _status_kind(error.status_code or status_code or 400)
    elif isinstance(error, UpstreamFailureError):
        detail = str(error).lower()
        status = error.status_code or status_code
        if "timeout" in detail or "timed out" in detail:
            kind = ProviderFailureKind.TIMEOUT
        elif "transport error" in detail or "connect" in detail:
            kind = ProviderFailureKind.CONNECTION_FAILURE
        elif status is not None:
            kind = _status_kind(status)
        else:
            kind = ProviderFailureKind.UNKNOWN_PROVIDER_FAILURE
    elif isinstance(error, TimeoutError):
        kind = ProviderFailureKind.TIMEOUT
    elif isinstance(error, ConnectionError | OSError):
        kind = ProviderFailureKind.CONNECTION_FAILURE
    elif isinstance(error, LlmError):
        kind = ProviderFailureKind.UNKNOWN_PROVIDER_FAILURE
    elif status_code is not None:
        kind = _status_kind(status_code)
    else:
        kind = ProviderFailureKind.UNKNOWN_PROVIDER_FAILURE

    return ProviderFailure(
        kind=kind,
        attribution=_ATTRIBUTION[kind],
        status_code=status_code if status_code is not None else getattr(error, "status_code", None),
        # Exception TYPE, never its message: an upstream message can echo request
        # content back, and this record is exported.
        detail=name,
        shape=shape,
        is_r86_signature=bool(
            kind is ProviderFailureKind.SCHEMA_GRAMMAR_FAILURE
            and shape is not None
            and shape.looks_like_whitespace_runaway
        ),
    )
