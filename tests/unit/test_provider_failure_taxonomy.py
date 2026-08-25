"""The provider-failure taxonomy, and the one rule that makes it honest. Part A1/K.

    A bad answer is not a provider failure. A broken response path is.

Everything here defends that sentence from both directions, because it can fail
either way and the two failures look nothing alike:

- **inward**: a wrong-but-well-formed answer classified as infrastructure would
  launder a reasoning defect into an outage;
- **outward**: an outage classified as a model error is what Phase 14 published,
  where ten cases that never reached a model appeared as sixteen reasoning errors.
"""

from __future__ import annotations

import pytest

from app.core.errors import (
    SchemaValidationError,
    UpstreamBlockedError,
    UpstreamFailureError,
    UpstreamRejectedError,
)
from app.llm.failure_taxonomy import (
    FailureAttribution,
    ProviderFailureKind,
    ResponseShape,
    classify_provider_failure,
)

pytestmark = pytest.mark.unit


def runaway(whitespace: float = 0.92) -> ResponseShape:
    """R-86's fingerprint: hit the ceiling, mostly whitespace, never closed."""
    return ResponseShape(
        finish_reason="length",
        body_chars=2389,
        whitespace_fraction=whitespace,
        parsed_as_json=False,
        satisfied_schema=False,
        completion_tokens=1536,
    )


def terminated_garbage() -> ResponseShape:
    """Stopped cleanly and returned something unusable. A different defect."""
    return ResponseShape(
        finish_reason="stop",
        body_chars=40,
        whitespace_fraction=0.05,
        parsed_as_json=False,
        satisfied_schema=False,
        completion_tokens=12,
    )


# ---------------------------------------------------------------------------
# The governing rule
# ---------------------------------------------------------------------------


def test_a_successful_call_is_never_a_provider_failure() -> None:
    """Including one whose answer was completely wrong.

    There is no parameter through which correctness could reach this function, and
    that is the design. This asserts the consequence.
    """
    shape = ResponseShape(
        finish_reason="stop",
        body_chars=120,
        whitespace_fraction=0.09,
        parsed_as_json=True,
        satisfied_schema=True,
        completion_tokens=48,
    )
    failure = classify_provider_failure(None, status_code=200, shape=shape)
    assert failure.kind is ProviderFailureKind.NONE
    assert failure.attribution is FailureAttribution.NONE
    assert not failure.is_failure


def test_the_classifier_takes_no_accuracy_argument() -> None:
    """Structural, over the signature. A rule that could see the score would be
    a rule a good score could satisfy."""
    import inspect

    parameters = set(inspect.signature(classify_provider_failure).parameters)
    assert parameters == {"error", "status_code", "shape"}
    for forbidden in ("correct", "accuracy", "expected", "gold", "label"):
        assert not any(forbidden in p for p in parameters)


# ---------------------------------------------------------------------------
# Each kind, from a transport fact
# ---------------------------------------------------------------------------


def test_a_timeout_is_a_timeout() -> None:
    failure = classify_provider_failure(
        UpstreamFailureError("model path failed after 3 attempts: timeout after ReadTimeout")
    )
    assert failure.kind is ProviderFailureKind.TIMEOUT
    assert failure.attribution is FailureAttribution.INDETERMINATE


def test_a_firewall_block_is_not_a_reliability_failure() -> None:
    """403 is a security control operating correctly.

    Counting it as an outage would make the firewall look like an availability
    problem every time it does its job - and would give anyone reading the
    reliability number a reason to want it switched off.
    """
    failure = classify_provider_failure(UpstreamBlockedError(category="prompt_injection"))
    assert failure.kind is ProviderFailureKind.UPSTREAM_BLOCKED
    assert failure.attribution is FailureAttribution.FIREWALL
    assert failure.is_failure
    assert not failure.counts_toward_provider_reliability


def test_our_own_bad_request_is_not_the_providers_fault() -> None:
    failure = classify_provider_failure(
        UpstreamRejectedError("upstream rejected the request (400)", status_code=400)
    )
    assert failure.kind is ProviderFailureKind.UPSTREAM_CLIENT_ERROR
    assert failure.attribution is FailureAttribution.MEDAUTH
    assert not failure.counts_toward_provider_reliability


def test_rate_limiting_is_ours_to_pace() -> None:
    failure = classify_provider_failure(UpstreamRejectedError("too many requests", status_code=429))
    assert failure.kind is ProviderFailureKind.RATE_LIMITED
    assert failure.attribution is FailureAttribution.MEDAUTH


def test_a_5xx_after_retries_keeps_its_status() -> None:
    """The exhausted path used to drop the status and arrive unclassifiable.

    `UpstreamFailureError` has always had the field; `LlmClient` never filled it, so
    a 429 and a 502 both reached this function as the same string. Fixed in Phase 16
    and asserted here because the fix is invisible from the outside.
    """
    failure = classify_provider_failure(
        UpstreamFailureError(
            "model path failed after 3 attempts: upstream returned 502", status_code=502
        )
    )
    assert failure.kind is ProviderFailureKind.UPSTREAM_SERVER_ERROR
    assert failure.status_code == 502


def test_a_detector_failure_is_attributed_to_the_proxy() -> None:
    failure = classify_provider_failure(
        UpstreamRejectedError("detector unavailable", status_code=503)
    )
    assert failure.kind is ProviderFailureKind.PROXY_TRANSFORMATION
    assert failure.attribution is FailureAttribution.FIREWALL


def test_a_dead_socket_is_a_connection_failure() -> None:
    failure = classify_provider_failure(ConnectionError("connection reset"))
    assert failure.kind is ProviderFailureKind.CONNECTION_FAILURE


def test_an_unrecognised_failure_is_visible_as_unrecognised() -> None:
    """Never folded into the nearest neighbour.

    A category that absorbs the unknown makes an unclassified failure look
    diagnosed, and nobody goes looking for it again.
    """
    failure = classify_provider_failure(RuntimeError("something nobody anticipated"))
    assert failure.kind is ProviderFailureKind.UNKNOWN_PROVIDER_FAILURE
    assert failure.attribution is FailureAttribution.INDETERMINATE


# ---------------------------------------------------------------------------
# R-86 specifically - and the bug the experiment found
# ---------------------------------------------------------------------------


def test_a_whitespace_runaway_is_a_grammar_failure_not_a_malformed_response() -> None:
    """The Phase-16 instrument defect, pinned.

    The first version of this classifier tested "did the body parse?" before "is
    this a runaway?". A decoder that pads to the ceiling never closes its document
    and therefore never parses - so every R-86 occurrence was reported as
    MALFORMED_RESPONSE with `is_r86_signature: False`. `r86-factorial-001` produced
    five textbook runaways and the taxonomy hid all five.
    """
    failure = classify_provider_failure(
        SchemaValidationError("did not validate", attempts=3), status_code=200, shape=runaway()
    )
    assert failure.kind is ProviderFailureKind.SCHEMA_GRAMMAR_FAILURE
    assert failure.is_r86_signature
    assert failure.counts_toward_provider_reliability


def test_a_terminated_garbage_response_is_malformed_not_r86() -> None:
    """Non-vacuity for the test above: the other branch must still be reachable.

    Same exception, same unparseable body. The only difference is that this one
    STOPPED - and a response that stopped and returned garbage is a different defect
    with a different owner from one that never stopped at all.
    """
    failure = classify_provider_failure(
        SchemaValidationError("did not validate", attempts=3),
        status_code=200,
        shape=terminated_garbage(),
    )
    assert failure.kind is ProviderFailureKind.MALFORMED_RESPONSE
    assert not failure.is_r86_signature


def test_both_conditions_are_required_for_the_r86_signature() -> None:
    """Whitespace alone is normal in pretty-printed JSON; a ceiling alone is a
    long answer truncated. Only together are they the runaway."""
    assert not ResponseShape(
        finish_reason="stop", whitespace_fraction=0.95
    ).looks_like_whitespace_runaway
    assert not ResponseShape(
        finish_reason="length", whitespace_fraction=0.10
    ).looks_like_whitespace_runaway
    assert ResponseShape(
        finish_reason="length", whitespace_fraction=0.55
    ).looks_like_whitespace_runaway


def test_a_schema_failure_that_parsed_is_still_a_grammar_failure() -> None:
    """Well-formed JSON that does not satisfy the schema after repair."""
    shape = ResponseShape(
        finish_reason="stop", body_chars=80, whitespace_fraction=0.1, parsed_as_json=True
    )
    failure = classify_provider_failure(
        SchemaValidationError("missing required field", attempts=3), shape=shape
    )
    assert failure.kind is ProviderFailureKind.SCHEMA_GRAMMAR_FAILURE
    assert not failure.is_r86_signature


# ---------------------------------------------------------------------------
# Properties over the whole vocabulary
# ---------------------------------------------------------------------------


def test_every_kind_has_an_attribution() -> None:
    """Total, so a new kind cannot be added without deciding whose it is."""
    from app.llm.failure_taxonomy import _ATTRIBUTION

    assert set(_ATTRIBUTION) == set(ProviderFailureKind)


def test_only_none_is_not_a_failure() -> None:
    for kind in ProviderFailureKind:
        assert kind.is_failure is (kind is not ProviderFailureKind.NONE)


def test_exactly_the_two_non_provider_kinds_are_excluded_from_reliability() -> None:
    """Stated as an exact set, so widening it is a visible edit.

    Excluding a kind from the reliability rate is how a failure rate is quietly
    improved, and there are exactly two defensible exclusions: a control working,
    and our own malformed request.
    """
    excluded = {
        k for k in ProviderFailureKind if k.is_failure and not k.counts_toward_provider_reliability
    }
    assert excluded == {
        ProviderFailureKind.UPSTREAM_BLOCKED,
        ProviderFailureKind.UPSTREAM_CLIENT_ERROR,
    }


def test_no_kind_is_named_for_a_model_being_wrong() -> None:
    """The vocabulary must not offer a place to put a reasoning error."""
    forbidden = ("WRONG", "INCORRECT", "BAD_ANSWER", "HALLUCIN", "QUALITY")
    for kind in ProviderFailureKind:
        assert not any(token in kind.value for token in forbidden), kind


def test_the_response_shape_carries_no_content() -> None:
    """A reliability report is exported. There must be no field a note could fit in.

    Asserted over the dataclass rather than over one instance: a `body` or `sample`
    field added later is exactly what would leak clinical text into an escalation.
    """
    from dataclasses import fields

    names = {f.name for f in fields(ResponseShape)}
    assert names == {
        "finish_reason",
        "body_chars",
        "whitespace_fraction",
        "parsed_as_json",
        "satisfied_schema",
        "prompt_tokens",
        "completion_tokens",
    }
    for field_name in names:
        assert not any(
            token in field_name for token in ("text", "body_content", "sample", "excerpt")
        )


def test_the_detail_is_an_exception_type_not_a_message() -> None:
    """An upstream message can echo request content back into a committed report."""
    secret = "PATIENT NAME: Jane Doe, MRN 12345"
    failure = classify_provider_failure(UpstreamFailureError(f"upstream said: {secret}"))
    assert failure.detail == "UpstreamFailureError"
    assert secret not in failure.detail
