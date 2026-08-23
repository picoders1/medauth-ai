"""The one gate. Production inference is blocked unless every condition passes.

There is deliberately exactly one of these. Two gates that mostly agree are worse
than one gate that is wrong, because the disagreement surfaces as a case that one
path admitted and another refused - and whichever was consulted last wins. A test
asserts no second implementation exists.

## What it requires

Production inference is permitted only when **all** of these hold:

1. Every open domain decision affecting the policy is `ACCEPTED` (FOCUS-001).
2. The candidate policy version is admissible on every condition of the
   admissibility gate.
3. The declared semantics would actually execute.

They are read from committed artefacts, never computed here. This module answers
"may inference run?" - it does not decide what any of those artefacts should say.

## What it deliberately does not do

**It does not consider historical replay.** `eval/replay.py` reproduces gold_v1's
labels under semantics production refuses, and that path exists precisely so the
historical experiment stays reproducible. Replay running successfully says nothing
about whether production may run, and this gate has no input through which it could.

## Fail closed

Every failure mode - a missing artefact, an unreadable one, an unrecognised status -
produces `BLOCKED` with the reason recorded. There is no path where an error reading
the gate's own inputs results in permission.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path
from typing import Any

__all__ = [
    "GateDecision",
    "ProductionGate",
    "ProductionStatus",
    "evaluate_gate",
]


class ProductionStatus(StrEnum):
    """Whether production inference may run. Two values, and no middle one.

    There is no `DEGRADED`, no `LIMITED` and no `WARN`. Each would be a state that
    permits inference while recording a reservation nobody acts on.
    """

    READY = "READY"
    BLOCKED = "BLOCKED"


@dataclass(frozen=True, slots=True)
class GateDecision:
    """The gate's answer, with every reason it refused."""

    status: ProductionStatus
    policy_identity: str | None = None
    blockers: tuple[str, ...] = ()
    checks: dict[str, bool] = field(default_factory=dict)
    notes: tuple[str, ...] = field(default_factory=tuple)

    @property
    def permits_inference(self) -> bool:
        return self.status is ProductionStatus.READY

    def require(self) -> None:
        """Raise unless production may run. For a caller that cannot proceed.

        Named `require` rather than `check` because the failure is the point: a
        boolean that a caller can ignore is not a gate.
        """
        if not self.permits_inference:
            raise PermissionError("production inference is BLOCKED: " + "; ".join(self.blockers))


@dataclass(frozen=True, slots=True)
class ProductionGate:
    """Where the gate reads its evidence from. Paths, not values."""

    admissibility_report: Path
    decision_records: tuple[Path, ...]

    def evaluate(self) -> GateDecision:
        return evaluate_gate(self)


def _load(path: Path) -> dict[str, Any] | None:
    try:
        loaded = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        # An unreadable artefact is not an absent restriction. Returning None here
        # and blocking below is the difference between "the gate could not check"
        # and "the gate found nothing wrong".
        return None
    return loaded if isinstance(loaded, dict) else None


def evaluate_gate(gate: ProductionGate) -> GateDecision:
    """May production inference run? Fails closed on anything it cannot verify."""
    blockers: list[str] = []
    notes: list[str] = []
    checks: dict[str, bool] = {}

    # ---------------------------------------------------- domain decisions
    unresolved: list[str] = []
    for path in gate.decision_records:
        record = _load(path)
        if record is None:
            unresolved.append(f"{path.name} is missing or unreadable")
            continue
        if not record.get("is_resolved"):
            unresolved.append(
                f"{record.get('focus_id', path.name)} is {record.get('status', 'UNKNOWN')}"
            )
    checks["domain_decisions_accepted"] = not unresolved
    blockers.extend(unresolved)

    # ------------------------------------------------------- admissibility
    report = _load(gate.admissibility_report)
    if report is None:
        checks["policy_slice_admissible"] = False
        checks["admissibility_gate_readable"] = False
        blockers.append(
            f"{gate.admissibility_report.name} is missing or unreadable; the gate "
            "cannot verify that any policy version is admissible"
        )
        return GateDecision(
            status=ProductionStatus.BLOCKED,
            blockers=tuple(blockers),
            checks=checks,
            notes=("failed closed: the gate could not read its own evidence",),
        )

    checks["admissibility_gate_readable"] = True
    designated = report.get("designated_slice")
    admissible = report.get("admissible") or []
    checks["policy_slice_admissible"] = bool(designated) and designated in admissible

    if not checks["policy_slice_admissible"]:
        nearest = report.get("nearest_candidate")
        failed = report.get("nearest_candidate_blockers") or []
        blockers.append(
            "no policy version is admissible"
            + (f"; nearest is {nearest} failing {failed}" if nearest else "")
        )

    # `status` is the admissibility script's own verdict. Checked as well as the
    # designated slice so that a report claiming READY with no slice, or a slice
    # with a BLOCKED status, is caught rather than half-believed.
    checks["admissibility_status_ready"] = report.get("status") == "READY"
    if checks["policy_slice_admissible"] != checks["admissibility_status_ready"]:
        blockers.append(
            f"the admissibility report is internally inconsistent: status="
            f"{report.get('status')!r} with designated_slice={designated!r}"
        )

    # ------------------------------------------------- executable semantics
    executable = False
    if designated:
        candidate = next(
            (c for c in report.get("assessment", []) if c.get("policy_identity") == designated),
            None,
        )
        executable = bool(
            candidate and candidate.get("checks", {}).get("production_semantics_executable")
        )
    checks["semantics_executable"] = executable
    if designated and not executable:
        blockers.append(f"{designated} has no executable declared semantics")

    if not blockers:
        notes.append(
            "Historical replay is NOT considered by this gate. eval/replay.py "
            "reproduces gold_v1 under semantics production refuses, and its success "
            "says nothing about production."
        )

    status = ProductionStatus.READY if not blockers else ProductionStatus.BLOCKED
    return GateDecision(
        status=status,
        policy_identity=designated if status is ProductionStatus.READY else None,
        blockers=tuple(blockers),
        checks=checks,
        notes=tuple(notes),
    )
