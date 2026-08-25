"""The one authority that may authorise an official evaluation. Part F.

    from eval.official_gate import OfficialEvaluationGate
    OfficialEvaluationGate.evaluate().require()

While R-86 is unresolved, an official run of a frozen hold-out must be impossible -
not discouraged, not guarded by a convention, not gated behind a flag somebody can
set. This module is the only thing that may say yes, and it is built so that saying
yes for the wrong reason requires editing it.

## What is deliberately absent, and why absence is the mechanism

There is **no** `force`, `skip`, `override`, `assume_pass` or `debug` parameter on
any function here. There is **no** environment variable read. A parameter is
somewhere to pass `True` from; an absence is not, and
`tests/evaluation/test_official_gate.py` asserts both properties over the module's
own AST so a future addition fails a test rather than a review.

The same technique keeps `RunMode.REPLAY` out of `PRODUCTION_MODES` and
`GOLD_V1_REPLAY` out of `PRODUCTION_ORIGINS`. It is the third time this repository
has needed it.

## `require()` raises; it does not return a boolean

A boolean is something a caller can ignore, and the interesting callers are scripts
written in a hurry. `require()` raises `EvaluationBlocked`, so the failure mode of
forgetting to check is a traceback rather than a scored hold-out.

## Replay is a different question and stays separate

`RunMode.REPLAY` reproduces a historical label under a designated policy. It has its
own mode, its own finding reason and its own audit stamp, and **it is not a route to
an official evaluation** - it neither consults this gate nor can satisfy it. A gate
that could be satisfied by a replay would be satisfiable by a fixture.

## What the gate reads

1. the sealed reproducer manifest - is the live configuration still the one the
   evidence describes?
2. the most recent revalidation - did the registered production shape pass, under
   the pre-registered threshold?

Both must hold. Either missing is `INCONCLUSIVE`, which blocks exactly as `FAIL`
does: "we could not tell" is not permission.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parents[1]
SEAL = REPO / "data/escalations/r86-reproducer.manifest.json"
REVALIDATIONS = REPO / "eval/reports/r86-revalidation"

__all__ = [
    "Authorisation",
    "AuthorisationState",
    "EvaluationBlocked",
    "OfficialEvaluationGate",
]


class AuthorisationState(StrEnum):
    """Three states. `AUTHORISED` is reachable only by satisfying every condition."""

    AUTHORISED = "AUTHORISED"
    BLOCKED = "BLOCKED"
    #: The evidence cannot decide - no seal, no revalidation, a stale one, or a
    #: configuration that has moved since the evidence was taken. **Blocks exactly
    #: as BLOCKED does**; it exists so uncertainty has somewhere to go that is not
    #: the more convenient neighbour.
    INDETERMINATE = "INDETERMINATE"

    @property
    def permits_official_evaluation(self) -> bool:
        """Written as an identity test against the one admitting value.

        A membership test over the refusing states would admit a fourth state by
        omission, which is how a vocabulary grows a hole.
        """
        return self is AuthorisationState.AUTHORISED


class EvaluationBlocked(RuntimeError):
    """An official evaluation was attempted without authorisation.

    Raised rather than returned. A boolean is something a caller can ignore, and the
    callers that matter are scripts written at the end of a long day.
    """


@dataclass(frozen=True, slots=True)
class Authorisation:
    """The verdict, with every reason behind it."""

    state: AuthorisationState
    reasons: tuple[str, ...] = ()
    evidence: dict[str, Any] = field(default_factory=dict)

    @property
    def permits_official_evaluation(self) -> bool:
        return self.state.permits_official_evaluation

    def require(self) -> None:
        """Raise unless authorised. **The only supported way to check.**"""
        if not self.permits_official_evaluation:
            raise EvaluationBlocked(
                f"official evaluation is {self.state.value}: "
                + "; ".join(self.reasons or ("no reason recorded",))
            )

    def as_dict(self) -> dict[str, Any]:
        return {
            "state": self.state.value,
            "permits_official_evaluation": self.permits_official_evaluation,
            "reasons": list(self.reasons),
            "evidence": self.evidence,
            "decided_at": datetime.now(UTC).isoformat(),
        }


def _seal_digest(manifest: dict[str, Any]) -> str:
    """Recomputed here rather than imported from `scripts/`.

    `app/` and `eval/` may not import the harness, and a gate that depended on a
    script would be a gate a script could change. Two implementations of one hash is
    a real cost; a gate reaching into `scripts/` to decide whether a hold-out may be
    scored is a larger one.
    """
    payload = {
        k: v for k, v in manifest.items() if k not in {"sealed_sha256", "sealed_at", "git_commit"}
    }
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


class OfficialEvaluationGate:
    """The sole authorisation boundary. Stateless, and it takes no arguments.

    `evaluate()` has no parameters on purpose. Anything it could accept would be
    something a caller could supply, and the point of this class is that a caller
    cannot influence the answer.
    """

    @staticmethod
    def evaluate() -> Authorisation:
        """Read the sealed evidence and the latest revalidation. Never raises."""
        reasons: list[str] = []
        evidence: dict[str, Any] = {}

        # ---- 1. the seal exists and still describes this system ----------
        if not SEAL.is_file():
            return Authorisation(
                AuthorisationState.INDETERMINATE,
                ("no sealed R-86 reproducer exists; run scripts/seal_r86_reproducer.py",),
            )
        seal = json.loads(SEAL.read_text())
        recorded = seal.get("sealed_sha256")
        recomputed = _seal_digest(seal)
        evidence["seal"] = {
            "experiment_id": seal.get("experiment_id"),
            "sealed_sha256": recorded,
            "intact": recorded == recomputed,
        }
        if recorded != recomputed:
            return Authorisation(
                AuthorisationState.INDETERMINATE,
                (
                    "the sealed reproducer manifest does not match its own digest; "
                    "it has been edited by hand and no longer attests to anything",
                ),
                evidence,
            )

        # ---- 2. a revalidation exists ------------------------------------
        runs = sorted(REVALIDATIONS.glob("*.json")) if REVALIDATIONS.is_dir() else []
        if not runs:
            return Authorisation(
                AuthorisationState.INDETERMINATE,
                ("no R-86 revalidation has been run; run scripts/r86_revalidate.py",),
                evidence,
            )
        latest = json.loads(runs[-1].read_text())
        evidence["revalidation"] = {
            "file": runs[-1].name,
            "ran_at": latest.get("ran_at"),
            "result": (latest.get("gate") or {}).get("result"),
        }

        # ---- 3. it was run against THIS seal -----------------------------
        # A PASS obtained under a different configuration is a PASS for a different
        # system. The seal digest travels on the revalidation for exactly this.
        if latest.get("seal_sha256") != recorded:
            return Authorisation(
                AuthorisationState.INDETERMINATE,
                (
                    "the latest revalidation was run against a different sealed "
                    f"configuration (seal {str(latest.get('seal_sha256'))[:16]} vs "
                    f"{str(recorded)[:16]}); it does not describe this system",
                ),
                evidence,
            )

        # ---- 4. and it passed, under the pre-registered threshold --------
        gate = latest.get("gate") or {}
        result = gate.get("result")
        evidence["threshold"] = gate.get("acceptance_threshold")
        evidence["observed_failure_rate"] = gate.get("production_failure_rate")
        sealed_threshold = (seal.get("acceptance") or {}).get("max_failure_rate")
        if sealed_threshold is not None and gate.get("acceptance_threshold") != sealed_threshold:
            return Authorisation(
                AuthorisationState.INDETERMINATE,
                (
                    f"the revalidation used threshold {gate.get('acceptance_threshold')} "
                    f"and the sealed evidence registers {sealed_threshold}; a "
                    "threshold that moved is not a system that improved",
                ),
                evidence,
            )
        if result == "PASS":
            return Authorisation(
                AuthorisationState.AUTHORISED,
                (
                    f"R-86 revalidation PASSED at "
                    f"{gate.get('production_failure_rate')} against the "
                    f"pre-registered ceiling {gate.get('acceptance_threshold')}",
                ),
                evidence,
            )
        if result == "FAIL":
            reasons.append(f"R-86 revalidation FAILED: {gate.get('why', 'no reason recorded')}")
            return Authorisation(AuthorisationState.BLOCKED, tuple(reasons), evidence)
        return Authorisation(
            AuthorisationState.INDETERMINATE,
            (f"R-86 revalidation is {result}: {gate.get('why', 'no reason recorded')}",),
            evidence,
        )

    @staticmethod
    def require() -> None:
        """Convenience for a call site that only wants to proceed or stop."""
        OfficialEvaluationGate.evaluate().require()
