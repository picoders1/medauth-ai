"""`/ready` is a contract, and its classification is the substance.

The property under test is not "readiness reports checks" but **only required
failures return 503**. An advisory dependency going down must not take the
service with it - the reviewer console is where humans work cases that already
exist, and a model-path outage must not log them out (ADR-018).
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.api.readiness import Check, ReadinessReport, Requirement, evaluate_readiness
from app.config.policy import load_policy
from app.config.settings import Settings

pytestmark = pytest.mark.api

UNREACHABLE_DB = "postgresql+asyncpg://x:x@127.0.0.1:1/x"


def _settings(**overrides: object) -> Settings:
    base: dict[str, object] = {"_env_file": None, "database_url": UNREACHABLE_DB}
    base.update(overrides)
    return Settings(**base)  # type: ignore[arg-type]


# ------------------------------------------------------- classification logic
def test_only_required_failures_make_the_service_unready() -> None:
    advisory_down = ReadinessReport(
        checks=(
            Check("configuration", True, Requirement.REQUIRED, ""),
            Check("llm_firewall", False, Requirement.ADVISORY, "unreachable"),
        )
    )
    assert advisory_down.ready
    assert advisory_down.status_code == 200

    required_down = ReadinessReport(
        checks=(
            Check("configuration", True, Requirement.REQUIRED, ""),
            Check("database", False, Requirement.REQUIRED, "unreachable"),
        )
    )
    assert not required_down.ready
    assert required_down.status_code == 503


async def test_the_database_requirement_follows_audit_required() -> None:
    """When a recommendation may not be issued unaudited, the store is load-bearing."""
    policy = load_policy("config/decision-policy.yaml")

    strict = await evaluate_readiness(
        settings=_settings(audit_required=True), policy=policy, engine=None
    )
    relaxed = await evaluate_readiness(
        settings=_settings(audit_required=False), policy=policy, engine=None
    )

    assert (
        next(c for c in strict.checks if c.name == "database").requirement is Requirement.REQUIRED
    )
    assert (
        next(c for c in relaxed.checks if c.name == "database").requirement is Requirement.ADVISORY
    )


async def test_the_firewall_is_advisory() -> None:
    """Deliberate: a model-path outage stops new work, it does not end a shift."""
    report = await evaluate_readiness(
        settings=_settings(), policy=load_policy("config/decision-policy.yaml"), engine=None
    )
    firewall = next(c for c in report.checks if c.name == "llm_firewall")
    assert firewall.requirement is Requirement.ADVISORY


async def test_a_raising_probe_becomes_a_failed_check_not_a_failed_request() -> None:
    """`/ready` must stay answerable when a dependency is down - that is its job."""
    report = await evaluate_readiness(settings=_settings(), policy=None, engine=None)
    names = {c.name for c in report.checks}
    assert names == {"configuration", "decision_policy", "database", "llm_firewall"}
    assert not report.ready  # decision_policy is required and was not loaded


# ------------------------------------------------------------------ endpoints
def test_health_checks_no_dependency() -> None:
    """Liveness answers 200 even with every dependency unreachable."""
    from app.api.main import create_app

    with TestClient(create_app(_settings())) as client:
        response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_ready_reports_every_check_with_its_classification() -> None:
    from app.api.main import create_app

    with TestClient(create_app(_settings())) as client:
        response = client.get("/ready")

    body = response.json()
    assert response.status_code in {200, 503}
    assert set(body) == {"status", "checks"}
    for check in body["checks"]:
        assert set(check) == {"name", "passed", "requirement", "detail"}
        assert check["requirement"] in {"required", "advisory"}


def test_metrics_content_type_matches_the_body_format() -> None:
    """A gateway in the sibling project was unscrapeable for seventeen phases
    because it advertised OpenMetrics while emitting text format. Asserting the
    endpoint exists would not have caught it."""
    from app.api.main import create_app

    with TestClient(create_app(_settings())) as client:
        response = client.get("/metrics")

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/plain")
    assert "version=" in response.headers["content-type"]
    assert response.text.startswith("#") or response.text == ""


def test_metrics_can_be_disabled() -> None:
    from app.api.main import create_app

    with TestClient(create_app(_settings(metrics_enabled=False))) as client:
        assert client.get("/metrics").status_code == 404


def test_docs_are_closed_in_production() -> None:
    from app.api.main import create_app

    application = create_app(
        _settings(environment="production", llm_api_key="k", trusted_proxies="10.0.0.0/8")
    )
    assert application.docs_url is None
