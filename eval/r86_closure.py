"""What it takes for R-86 to be closed. Part F, and a defect it uncovered.

    from eval.r86_closure import CLOSURE_RULE_ID, trial_succeeds

`scripts/r86_revalidate.py` decided whether a trial succeeded by asking the failure
taxonomy, which decides by asking whether the call **raised**:

    if error is None:
        return ProviderFailure(kind=ProviderFailureKind.NONE, ...)

That is correct for the taxonomy. `classify_provider_failure` classifies errors, a
successful call is not an error, and the module deliberately refuses any parameter
about whether the answer was good - adding one is the defect it exists to prevent.

It is **not** sufficient for closure, and the difference is exploitable by a partial
fix.

## The response that would have passed

Suppose the provider closes the document but keeps padding to the ceiling:

    {"conditions": [...], ... }<2000 characters of whitespace>

Then, in order:

    json.loads(body)                  succeeds - trailing whitespace is legal JSON
    satisfied_schema                  True
    the call does not raise           so failure_kind is NONE
    counts_toward_provider_reliability False
    the trial counts as a SUCCESS

Six of those and the gate returns **PASS** at 0/12, the official evaluation is
authorised, and the provider path is still burning 1536 completion tokens and 6.3
seconds per call on whitespace that means nothing. R-86 is *non-termination*. A
document that closes and then pads has not terminated; it has merely become parseable.

The taxonomy already computes `looks_like_whitespace_runaway` and records
`is_r86_signature` on every observation. **Nothing consulted either when deciding the
gate.** The signal was measured and discarded at the one place it decided something.

## Why this is a strengthening and not a retune

Changing what counts as a failure after seeing results is exactly what this regime
forbids, so two things are stated rather than assumed:

1. **It cannot alter any recorded result.** Of the 164 observations committed under
   `eval/reports/`, **zero** satisfied the schema while exhibiting the runaway shape.
   The Phase-17 gate recheck and the Phase-18 revalidation both still read 6/12 =
   0.5000. Checked, not asserted, and pinned by a test.
2. **It can only make PASS harder.** Every condition can add a failure; none can
   remove one. A rule that could only tighten cannot be a rule tuned to produce a
   favourable answer - the direction is wrong for that.

It is registered here, before the run it will govern, which is the order the
pre-registration regime requires.

## What is deliberately NOT changed

The **threshold** stays 0.10, in `eval/validity.py`, under
`provider-failure-validity.v1`, compared against the seal on every run. The
**request shape** stays exactly as sealed. The **taxonomy** keeps its contract and
its accuracy-blindness. This module adds a second, independent condition on top of
schema validity; it removes nothing.
"""

from __future__ import annotations

from dataclasses import dataclass

from app.llm.failure_taxonomy import ResponseShape

__all__ = [
    "CLOSURE_CONDITIONS",
    "CLOSURE_RULE_ID",
    "TrialVerdict",
    "trial_succeeds",
]

#: Versioned like a prompt id, for the same reason: a report that cites a verdict must
#: be able to say which rule produced it. Bump it if a condition changes; do not edit
#: the meaning of `v1` in place.
CLOSURE_RULE_ID = "r86-closure.v1"

#: Part F, as a list a reader can check the code against.
CLOSURE_CONDITIONS: tuple[str, ...] = (
    "the call completed without raising",
    "the body parsed as JSON",
    "the body satisfied the registered schema",
    "generation did not stop by exhausting the completion ceiling",
    "the response is not whitespace-dominated at the ceiling (the R-86 shape)",
)


@dataclass(frozen=True, slots=True)
class TrialVerdict:
    """One trial's verdict, with every reason it did not succeed.

    Reasons are accumulated rather than short-circuited. A trial that failed three
    conditions and reports one reads as a near-miss, and a near-miss is what somebody
    argues about.
    """

    succeeded: bool
    reasons: tuple[str, ...] = ()
    rule_id: str = CLOSURE_RULE_ID


def trial_succeeds(
    *,
    satisfied_schema: bool,
    shape: ResponseShape | None,
    raised: bool = False,
) -> TrialVerdict:
    """Whether one trial counts as a success for R-86 closure.

    Stricter than "the call did not raise" by exactly the two conditions Part F
    names: no completion-length exhaustion, and no whitespace runaway.

    A missing `shape` is a failure, not a pass. We cannot see whether the response
    terminated, and an unobservable trial must not be counted as a good one - the
    same reason `INCONCLUSIVE` blocks exactly as `FAIL` does at the gate above this.
    """
    reasons: list[str] = []

    if raised:
        reasons.append("the call raised")
    if not satisfied_schema:
        reasons.append("the body did not satisfy the registered schema")

    if shape is None:
        reasons.append(
            "no response shape was observed, so termination could not be checked; "
            "an unobservable trial is not a successful one"
        )
        return TrialVerdict(succeeded=False, reasons=tuple(reasons))

    if not shape.parsed_as_json:
        reasons.append("the body did not parse as JSON")

    # The two conditions the old definition missed. Both are about TERMINATION,
    # which is what R-86 is, and neither is implied by schema validity.
    if shape.finish_reason == "length":
        reasons.append(
            "generation stopped by exhausting the completion ceiling "
            f"({shape.completion_tokens} tokens), not by terminating"
        )
    if shape.looks_like_whitespace_runaway:
        reasons.append(
            f"whitespace-dominated at the ceiling ({shape.whitespace_fraction:.4f}) - "
            "the R-86 shape. A document that closes and then pads has not terminated"
        )

    return TrialVerdict(succeeded=not reasons, reasons=tuple(reasons))
