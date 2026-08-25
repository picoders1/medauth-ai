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
from tests.corpus import corpus_available, skip_reason

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


def pytest_collection_modifyitems(items: list[pytest.Item]) -> None:
    """Skip corpus-dependent tests when the restricted CFR documents are absent.

    Applied at collection so the skip is visible in the report with its reason,
    rather than the suite aborting on an import error - which is what happened
    before, on every machine except the one that had already acquired the corpus.
    """
    if corpus_available():
        return
    skip = pytest.mark.skip(reason=skip_reason())
    for item in items:
        if item.get_closest_marker("corpus"):
            item.add_marker(skip)
