"""Configuration refuses rather than degrades.

A process running with a security boundary disabled is worse than one that will
not start: the failure is loud and immediate instead of silent and clinical.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from app.config.policy import DecisionPolicy, load_policy
from app.config.settings import ClinicalTextLogging, Settings
from app.core.errors import ConfigurationError

pytestmark = pytest.mark.unit

REPO = Path(__file__).resolve().parents[2]


def _settings(**overrides: object) -> Settings:
    base: dict[str, object] = {"_env_file": None}
    base.update(overrides)
    return Settings(**base)  # type: ignore[arg-type]


def _production(**overrides: object) -> Settings:
    params: dict[str, object] = {
        "environment": "production",
        "llm_api_key": "caller-key",
        # OD-43: production refuses the development authenticator, because it would
        # authenticate anybody who guessed a configured token name. A production
        # fixture therefore has to configure a real identity boundary.
        "auth_mode": "oidc",
        "oidc_issuer": "https://idp.test/realms/medauth",
        "oidc_audience": "medauth-api",
    }
    params.update(overrides)  # an override must be able to blank a default
    return _settings(**params)


# ------------------------------------------------------- production boundaries
def test_development_defaults_start() -> None:
    settings = _settings()
    assert not settings.is_production
    assert settings.llm_fail_closed
    assert settings.clinical_text_logging is ClinicalTextLogging.OFF


def test_a_correct_production_configuration_starts() -> None:
    """Guards against the refusal tests passing because production never starts."""
    assert _production().is_production


@pytest.mark.security
@pytest.mark.parametrize(
    ("label", "override"),
    [
        ("fail-closed disabled", {"llm_fail_closed": False}),
        ("clinical text logging", {"clinical_text_logging": "full"}),
        ("no caller key", {"llm_api_key": ""}),
        ("audit not required", {"audit_required": False}),
        ("streaming enabled", {"llm_streaming_enabled": True}),
        ("trusts every peer", {"trusted_proxies": "0.0.0.0/0"}),
        ("trusts every v6 peer", {"trusted_proxies": "::/0"}),
        ("no trusted proxies", {"trusted_proxies": ""}),
    ],
)
def test_production_refuses_a_disabled_boundary(label: str, override: dict[str, object]) -> None:
    with pytest.raises(ConfigurationError) as caught:
        _production(**override)
    assert "refusing to start in production" in str(caught.value), label


def test_development_permits_what_production_refuses() -> None:
    """The boundaries are production-only; local work stays one command."""
    assert _settings(llm_fail_closed=False, trusted_proxies="0.0.0.0/0") is not None


# --------------------------------------------------------------------- secrets
@pytest.mark.security
def test_the_caller_key_is_not_in_the_repr() -> None:
    settings = _settings(llm_api_key="super-secret-value")
    assert "super-secret-value" not in repr(settings)
    assert "super-secret-value" not in str(settings.model_dump())
    assert settings.llm_api_key.get_secret_value() == "super-secret-value"


def test_malformed_cidr_is_rejected() -> None:
    with pytest.raises(ValueError, match="not a CIDR"):
        _settings(trusted_proxies="not-an-address")


def test_llm_base_url_must_be_http() -> None:
    with pytest.raises(ValueError, match="http"):
        _settings(llm_base_url="ftp://example.test/v1")


# ---------------------------------------------------------------------- policy
def test_the_shipped_policy_loads() -> None:
    policy = load_policy(REPO / "config" / "decision-policy.yaml")
    assert isinstance(policy, DecisionPolicy)
    assert policy.version


def test_the_shipped_policy_has_no_calibrated_thresholds() -> None:
    """They are selected on the dev split in Phase 6, and not before.

    A plausible-looking number here would be a fabricated metric with clinical
    consequences. This test changes when ADR-011 records the calibration.
    """
    policy = load_policy(REPO / "config" / "decision-policy.yaml")
    assert policy.abstention_thresholds.approve is None
    assert policy.abstention_thresholds.deny is None
    assert not policy.scored_gate_calibrated


@pytest.mark.security
@pytest.mark.parametrize(
    "key", ["api_key", "secret", "auth_token", "db_password", "nested_key", "credentials"]
)
def test_secret_shaped_keys_are_structurally_rejected(key: str, tmp_path: Path) -> None:
    """A credential cannot be committed through the policy file."""
    file = tmp_path / "policy.yaml"
    file.write_text(f'version: "1"\nretrieval:\n  {key}: value\n')
    with pytest.raises(ConfigurationError, match="looks like a credential"):
        load_policy(file)


def test_deny_threshold_must_exceed_approve(tmp_path: Path) -> None:
    """A wrong denial withholds care; it needs the stricter bar (ADR-011)."""
    file = tmp_path / "policy.yaml"
    file.write_text('version: "1"\nabstention_thresholds:\n  approve: 0.9\n  deny: 0.6\n')
    with pytest.raises(ConfigurationError, match="must exceed"):
        load_policy(file)


def test_unknown_policy_field_is_rejected(tmp_path: Path) -> None:
    """Never silently repaired: a typo must not become a default."""
    file = tmp_path / "policy.yaml"
    file.write_text('version: "1"\nabstention_ruls:\n  max_contradictions: 5\n')
    with pytest.raises(ConfigurationError):
        load_policy(file)


def test_missing_policy_file_is_fatal(tmp_path: Path) -> None:
    with pytest.raises(ConfigurationError, match="not found"):
        load_policy(tmp_path / "absent.yaml")
