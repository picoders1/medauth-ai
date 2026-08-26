"""``/ready`` is a contract, and the classification is the substance.

Each check is ``required`` or ``advisory``, and **only required failures return
503**. That distinction is a design decision, not a detail: an unreachable
firewall stops *new* recommendations, but the reviewer console is where humans
work the cases that already exist. Failing readiness for it would turn a model
outage into a total outage and take the humans offline too (ADR-018, ADR-016).

The database is classified by ``audit_required``. When a recommendation may not
be issued without an audit row, the audit store is load-bearing and its loss is
required-fatal (ADR-013).
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from enum import StrEnum

import httpx
import structlog
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from app.config.policy import DecisionPolicy
from app.config.settings import Settings

__all__ = ["Check", "ReadinessReport", "Requirement", "evaluate_readiness"]

log = structlog.get_logger(__name__)


class Requirement(StrEnum):
    REQUIRED = "required"
    ADVISORY = "advisory"


@dataclass(frozen=True, slots=True)
class Check:
    name: str
    passed: bool
    requirement: Requirement
    detail: str


@dataclass(frozen=True, slots=True)
class ReadinessReport:
    checks: tuple[Check, ...]

    @property
    def ready(self) -> bool:
        return all(c.passed for c in self.checks if c.requirement is Requirement.REQUIRED)

    @property
    def status_code(self) -> int:
        return 200 if self.ready else 503

    def as_dict(self) -> dict[str, object]:
        return {
            "status": "ready" if self.ready else "not_ready",
            "checks": [
                {
                    "name": c.name,
                    "passed": c.passed,
                    "requirement": c.requirement.value,
                    "detail": c.detail,
                }
                for c in self.checks
            ],
        }


async def _guarded(
    name: str, requirement: Requirement, probe: Callable[[], Awaitable[str]]
) -> Check:
    """Run one probe. A raising probe is a failed check, never a failed request."""
    try:
        detail = await probe()
    except Exception as exc:
        return Check(name, False, requirement, f"{type(exc).__name__}: {exc}"[:200])
    return Check(name, True, requirement, detail)


async def evaluate_readiness(
    *,
    settings: Settings,
    policy: DecisionPolicy | None,
    engine: AsyncEngine | None,
    llm_probe_url: str | None = None,
    authenticator: object | None = None,
) -> ReadinessReport:
    """Evaluate every readiness check concurrently."""

    async def configuration() -> str:
        # Re-assert the startup invariants so validation and readiness cannot drift.
        if settings.is_production and not settings.llm_fail_closed:
            raise RuntimeError("fail-closed disabled in production")
        return f"environment={settings.environment.value}"

    async def decision_policy() -> str:
        if policy is None:
            raise RuntimeError("decision policy was not loaded at startup")
        calibrated = (
            "calibrated" if policy.scored_gate_calibrated else "rule-stage only (uncalibrated)"
        )
        return f"version={policy.version}, abstention gate {calibrated}"

    async def database() -> str:
        if engine is None:
            raise RuntimeError("engine not initialised")
        async with engine.connect() as connection:
            await connection.execute(text("SELECT 1"))
        return "reachable"

    async def llm_firewall() -> str:
        url = llm_probe_url or settings.llm_base_url.removesuffix("/v1") + "/health"
        async with httpx.AsyncClient(timeout=httpx.Timeout(3.0)) as client:
            response = await client.get(url)
        if response.status_code != 200:
            raise RuntimeError(f"health returned {response.status_code}")
        return "reachable"

    async def reviewer_identity() -> str:
        """Whether a human reviewer could authenticate at all.

        **REQUIRED**, unlike the model path. A deployment that cannot authenticate a
        reviewer cannot finalise a case, and every case ends at a human - so this is not
        a degraded mode, it is a stopped one. Reporting READY while no review could be
        recorded would be the readiness endpoint lying about the thing it exists for.

        Reports the *mechanism*, never a credential, an issuer secret or a token.
        """
        if authenticator is None:
            raise RuntimeError("no human authenticator is configured; reviews would be refused")
        mechanism = type(authenticator).__name__
        if settings.auth_mode == "oidc":
            return f"{mechanism}, issuer configured, discovery={settings.oidc_discovery}"
        return f"{mechanism} (development adapter; refused in production)"

    database_requirement = Requirement.REQUIRED if settings.audit_required else Requirement.ADVISORY

    checks = await asyncio.gather(
        _guarded("configuration", Requirement.REQUIRED, configuration),
        _guarded("decision_policy", Requirement.REQUIRED, decision_policy),
        _guarded("database", database_requirement, database),
        # Advisory on purpose: a model-path outage must not take the reviewer
        # console down with it.
        _guarded("llm_firewall", Requirement.ADVISORY, llm_firewall),
        _guarded("reviewer_identity", Requirement.REQUIRED, reviewer_identity),
    )
    return ReadinessReport(checks=tuple(checks))
