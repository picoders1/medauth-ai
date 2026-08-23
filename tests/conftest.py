"""Shared fixtures.

Deliberately thin. The design goal is that most tests need no fixtures at all:
`decide()` is pure, the guardrail is deterministic, and the layer-boundary test
reads source. A test that needs elaborate setup to exercise a safety property is
usually testing the setup.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from app.config.policy import DecisionPolicy, load_policy
from app.config.settings import Settings

REPO_ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(scope="session")
def repo_root() -> Path:
    return REPO_ROOT


@pytest.fixture(scope="session")
def shipped_policy() -> DecisionPolicy:
    """The policy the application actually ships with, not a fixture copy."""
    return load_policy(REPO_ROOT / "config" / "decision-policy.yaml")


@pytest.fixture
def dev_settings() -> Settings:
    """Settings that ignore any local .env, so tests never depend on the machine."""
    return Settings(_env_file=None)  # type: ignore[call-arg]
