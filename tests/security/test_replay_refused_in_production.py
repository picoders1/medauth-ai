"""Production refuses semantics it cannot attest, including the gold_v1 replay.

`app.decision` cannot read settings or the environment, so it has no way to ask
*whose* answer it is holding. `app.policy.semantics_guard.admissible` is where that
is decided, and this is what pins it.

Two independent locks, tested separately, because either one alone would be a
naming convention rather than a boundary:

* **Origin** - `GOLD_V1_REPLAY` is not a production origin.
* **Digest** - an attestation whose hash does not match the inventory loaded at
  startup is refused whatever it claims to be.

Removing either lock must fail a test here.
"""

from __future__ import annotations

import pytest

from app.config.settings import Environment
from app.core.types import CriterionKind, ResolutionStatus, Verdict
from app.decision.models import DecisionRule, Outcome
from app.decision.semantics import (
    Attestation,
    PolicySemantics,
    SemanticsOrigin,
    SemanticsStatus,
)
from app.decision.table import (
    CriterionOutcome,
    GuardrailState,
    ResolutionState,
    decide,
)
from app.policy.semantics_guard import admissible
from eval.replay import gold_v1_semantics

pytestmark = [pytest.mark.security, pytest.mark.unit]

CRITERIA = (CriterionOutcome("a", CriterionKind.REQUIRED, Verdict.SATISFIED, True),)
RESOLVED = ResolutionState(ResolutionStatus.RESOLVED, 1)
INVENTORY_DIGEST = "a" * 64


def _production(semantics: PolicySemantics) -> PolicySemantics:
    return admissible(
        semantics, environment=Environment.PRODUCTION, inventory_digest=INVENTORY_DIGEST
    )


def test_the_replay_semantics_execute_outside_production() -> None:
    """The control. If replay could never execute, the refusal proves nothing.

    gold_v1's 222 labels reproduce through this path, so it must genuinely work -
    and it is the fact that it works that makes refusing it in production a real
    boundary rather than a dead branch.
    """
    replay = gold_v1_semantics(CRITERIA, policy_id="42 CFR 410.33", policy_version="2026-08-13")
    assert replay.is_executable
    assert replay.origin is SemanticsOrigin.GOLD_V1_REPLAY

    development = admissible(
        replay, environment=Environment.DEVELOPMENT, inventory_digest=INVENTORY_DIGEST
    )
    assert development.is_executable
    got = decide(CRITERIA, GuardrailState.PASSED, RESOLVED, development)
    assert got.outcome is Outcome.APPROVE_RECOMMENDED


def test_production_refuses_the_replay_origin() -> None:
    """Lock A. The same value, in production, cannot adjudicate."""
    replay = gold_v1_semantics(CRITERIA, policy_id="42 CFR 410.33", policy_version="2026-08-13")
    guarded = _production(replay)

    assert not guarded.is_executable
    assert guarded.status is SemanticsStatus.POLICY_SEMANTICS_UNKNOWN
    assert any("not a production origin" in note for note in guarded.notes)

    got = decide(CRITERIA, GuardrailState.PASSED, RESOLVED, guarded)
    assert got.outcome is Outcome.HUMAN_REVIEW
    assert got.rule is DecisionRule.POLICY_SEMANTICS_UNVERIFIED


def test_production_refuses_a_digest_that_does_not_match_the_loaded_inventory() -> None:
    """Lock B. This is what stops "just build one yourself" being a bypass.

    A production origin is claimed, so Lock A passes. The digest does not match
    the inventory the process actually loaded, so the value is refused anyway.
    """
    forged = PolicySemantics.assumed(
        policy_id="p",
        policy_version="v",
        logic=gold_v1_semantics(CRITERIA, policy_id="p", policy_version="v").logic,
        attestation=Attestation(
            source="data/policy_logic/inventory.json",
            sha256="b" * 64,
            origin=SemanticsOrigin.POLICY_LOGIC_INVENTORY,
        ),
    )
    assert forged.is_executable, "the fixture must be executable or the test is vacuous"

    guarded = _production(forged)
    assert not guarded.is_executable
    assert any("digest does not match" in note for note in guarded.notes)


def test_production_admits_semantics_that_pass_both_locks() -> None:
    """The positive control for the guard itself.

    Without this, `admissible` returning `unconsulted()` unconditionally would
    satisfy every other test in this file.
    """
    genuine = PolicySemantics.assumed(
        policy_id="p",
        policy_version="v",
        logic=gold_v1_semantics(CRITERIA, policy_id="p", policy_version="v").logic,
        attestation=Attestation(
            source="data/policy_logic/inventory.json",
            sha256=INVENTORY_DIGEST,
            origin=SemanticsOrigin.POLICY_LOGIC_INVENTORY,
        ),
    )
    guarded = _production(genuine)
    assert guarded.is_executable
    assert guarded is genuine

    got = decide(CRITERIA, GuardrailState.PASSED, RESOLVED, guarded)
    assert got.outcome is Outcome.APPROVE_RECOMMENDED


def test_the_guard_does_not_re_demote_something_already_blocked() -> None:
    """A value that already cannot adjudicate comes back unchanged.

    Re-demoting would append a note about a restriction that never bit, which
    makes an audit trail describe a refusal that did not happen.
    """
    blocked = PolicySemantics.unconsulted()
    assert _production(blocked) is blocked


def test_the_replay_digest_can_never_equal_an_inventory_digest_by_accident() -> None:
    """The replay attestation names gold_v1's manifest, not the inventory.

    Naming the inventory would be a false claim about what justifies the
    assumption, and it would also let the digest match in production - which is
    precisely the case Lock B exists to catch.
    """
    replay = gold_v1_semantics(CRITERIA, policy_id="p", policy_version="v")
    assert replay.attestation is not None
    assert replay.attestation.source.endswith("gold_v1.manifest.json")
    assert "inventory" not in replay.attestation.source
