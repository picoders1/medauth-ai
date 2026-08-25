"""The pre-registered validity rule, and the seal on Phase 14's artefacts.

Two things are being defended here, and they are the same thing at different scales.

**The rule must not be tunable.** Every condition can only demote, the function
cannot see any accuracy figure, and the thresholds live in a dataclass named in
ADR-028 rather than in a literal inside the scorer. A rule that could be adjusted
after seeing a result is a rule that will be.

**Phase 14's numbers must not move.** They record a system that no longer exists,
under a defect that has since been named, and that is exactly why they are worth
keeping. An experiment whose published figures can be quietly improved is not a
record of anything.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

import pytest

from eval.validity import (
    VALIDITY_RULE_ID,
    ExperimentValidity,
    ValidityRule,
    classify_validity,
)

pytestmark = pytest.mark.evaluation

REPO = Path(__file__).resolve().parents[2]
PHASE14 = REPO / "eval/reports/frozen-410-33"
ADR = REPO / "docs/adr/ADR-028-runtime-applicability-and-experiment-validity.md"


def case(
    *,
    failed: bool = False,
    expected: str = "APPROVE_RECOMMENDED",
    category: str = "CLEARLY_SATISFIES",
) -> dict[str, Any]:
    return {
        "provider_failure": failed,
        "expected_recommendation": expected,
        "category": category,
    }


def spread(n: int, failures: int) -> list[dict[str, Any]]:
    """`n` cases across four classes and four categories, `failures` of them failed.

    Spread deliberately: a helper that clustered its failures would make the
    concentration condition fire in tests that are about the rate, and the two would
    become impossible to tell apart.
    """
    classes = ["APPROVE_RECOMMENDED", "DENY_RECOMMENDED", "NEEDS_INFO", "HUMAN_REVIEW"]
    categories = ["A", "B", "C", "D"]
    return [
        case(
            failed=i < failures,
            expected=classes[i % len(classes)],
            category=categories[(i * 3) % len(categories)],
        )
        for i in range(n)
    ]


# ---------------------------------------------------------------------------
# The rule
# ---------------------------------------------------------------------------


def test_a_clean_run_is_valid_for_performance_analysis() -> None:
    """Non-vacuity for everything below: the rule can return VALID."""
    finding = classify_validity(spread(26, 0))
    assert finding.status is ExperimentValidity.VALID_FOR_PERFORMANCE_ANALYSIS
    assert finding.interpretable_as_performance
    assert finding.triggered == ()


def test_a_run_just_under_the_ceiling_is_still_valid() -> None:
    """2/26 = 0.0769 <= 0.10. The boundary is asserted from the passing side too.

    A threshold tested only from the failing side is satisfied by a rule that
    demotes everything.
    """
    finding = classify_validity(spread(26, 2))
    assert finding.status is ExperimentValidity.VALID_FOR_PERFORMANCE_ANALYSIS
    assert finding.failure_rate == pytest.approx(0.0769, abs=1e-4)


def test_the_failure_rate_condition_demotes() -> None:
    """4/26 = 0.1538 > 0.10."""
    finding = classify_validity(spread(26, 4))
    assert finding.status is ExperimentValidity.DEGRADED_BY_PROVIDER_FAILURE
    assert "FAILURE_RATE" in finding.triggered


def test_class_erasure_demotes_even_below_the_rate_ceiling() -> None:
    """A class with no surviving case cannot be spoken about at any rate.

    Two failures in 40 is 5% - comfortably inside the ceiling - and if both are the
    only cases expecting `HUMAN_REVIEW`, the experiment has nothing to say about
    that class. This is Phase 14's zero-approvals shape at a lower rate.
    """
    cases = [case(expected="APPROVE_RECOMMENDED", category=f"C{i % 4}") for i in range(38)]
    cases += [case(failed=True, expected="HUMAN_REVIEW", category="C0") for _ in range(2)]
    finding = classify_validity(cases)

    assert finding.failure_rate <= ValidityRule().max_failure_rate
    assert "FAILURE_RATE" not in finding.triggered
    assert finding.status is ExperimentValidity.DEGRADED_BY_PROVIDER_FAILURE
    assert finding.triggered == ("CLASS_ERASURE",)
    assert finding.erased_classes == ("HUMAN_REVIEW",)


def test_concentration_demotes_when_failures_cluster_in_one_category() -> None:
    """Failures that are not a random subset make the survivors unrepresentative."""
    cases = [case(category="EASY", expected="APPROVE_RECOMMENDED") for _ in range(20)]
    cases += [case(failed=i < 3, category="HARD", expected="DENY_RECOMMENDED") for i in range(4)]
    finding = classify_validity(cases)

    assert finding.status is ExperimentValidity.DEGRADED_BY_PROVIDER_FAILURE
    assert "CONCENTRATION" in finding.triggered
    assert any("HARD" in c for c in finding.concentrated_categories)


def test_a_tiny_category_does_not_trigger_concentration() -> None:
    """One failure out of two is not a pattern.

    Without the size floor this condition would demote almost every experiment, and
    a condition that always fires carries no information.
    """
    cases = [case(category="BIG", expected="APPROVE_RECOMMENDED") for _ in range(30)]
    cases += [case(failed=True, category="TINY", expected="NEEDS_INFO")]
    cases += [case(failed=False, category="TINY", expected="NEEDS_INFO")]
    finding = classify_validity(cases)

    assert "CONCENTRATION" not in finding.triggered
    assert finding.status is ExperimentValidity.VALID_FOR_PERFORMANCE_ANALYSIS


def test_the_rule_cannot_see_whether_the_answers_were_right() -> None:
    """A validity rule a good score could satisfy is not a validity rule.

    The same cases, one set scored entirely correct and one entirely wrong, must
    produce the identical finding.
    """
    correct = [
        c | {"decision_correct": True, "actual_recommendation": "APPROVE_RECOMMENDED"}
        for c in spread(26, 4)
    ]
    wrong = [
        c | {"decision_correct": False, "actual_recommendation": "HUMAN_REVIEW"}
        for c in spread(26, 4)
    ]
    assert classify_validity(correct) == classify_validity(wrong)


def test_an_empty_experiment_is_not_valid() -> None:
    finding = classify_validity([])
    assert finding.status is ExperimentValidity.DEGRADED_BY_PROVIDER_FAILURE
    assert finding.triggered == ("NO_CASES",)


def test_every_condition_can_only_demote() -> None:
    """Direction, asserted over the whole rule rather than per condition.

    Adding failures to a run can never improve its status. Written as a sweep from 0
    to n so that a future condition which promotes on some input is caught here.
    """
    seen: list[ExperimentValidity] = [classify_validity(spread(26, k)).status for k in range(0, 27)]
    degraded = ExperimentValidity.DEGRADED_BY_PROVIDER_FAILURE
    first = next(i for i, s in enumerate(seen) if s is degraded)
    assert all(s is degraded for s in seen[first:]), (
        "adding provider failures promoted a run back to VALID somewhere in the sweep"
    )


def test_the_rule_id_is_named_in_the_adr() -> None:
    """Pre-registration means an ADR names the rule this code implements."""
    assert ADR.is_file()
    text = ADR.read_text(encoding="utf-8")
    assert VALIDITY_RULE_ID in text
    rule = ValidityRule()
    assert str(rule.max_failure_rate) in text, "the ceiling is not stated in the ADR"


def test_the_preregistered_failure_mode_is_recorded() -> None:
    """A pre-registered failure mode must not later be presented as a discovery.

    ADR-011's regime requires it named in advance. Phase 15's is that R-86 may
    degrade this run again, which the ADR says before the run rather than after.
    """
    # Whitespace-normalised, because the ADR is prose and prose wraps. An assertion
    # that a maintainer can break by reflowing a paragraph is an assertion about
    # formatting, and it would be fixed by editing the test rather than the ADR.
    text = " ".join(ADR.read_text(encoding="utf-8").lower().split())
    assert "pre-registered failure mode" in text
    assert "not a discovery" in text
    assert "not a reason to raise the ceiling" in text


# ---------------------------------------------------------------------------
# Phase 14 is immutable
# ---------------------------------------------------------------------------


def test_the_phase_14_artefacts_match_their_seal() -> None:
    """Every file, byte for byte, against the checksum recorded when it was sealed.

    Not "the files exist". The Phase-15 scorer can be pointed at that directory with
    one flag, and this is what makes overwriting it a red test rather than a quiet
    improvement.
    """
    status = json.loads((PHASE14 / "STATUS.json").read_text())
    for name, recorded in status["files"].items():
        path = PHASE14 / name
        assert path.is_file(), f"sealed artefact {name} is missing"
        digest = f"sha256:{hashlib.sha256(path.read_bytes()).hexdigest()}"
        assert digest == recorded, (
            f"{name} changed since it was sealed. Phase-14 results are immutable: "
            "they record a system that no longer exists, under a defect that has "
            "since been named, and that is why they are worth keeping."
        )


def test_the_phase_14_status_refuses_to_be_a_baseline() -> None:
    """The figure travels; the caveat has to travel with it."""
    status = json.loads((PHASE14 / "STATUS.json").read_text())
    assert status["status"] == "EVALUATION_DEGRADED_BY_R-86_AND_R-93"
    assert status["decision_accuracy_interpretation"] == "EVALUATION_NOT_INTERPRETABLE"
    assert status["immutable"] is True
    assert "not a baseline" in status["decision_accuracy_note"].lower()
    assert len(status["why"]) >= 2


def test_the_rule_demotes_phase_14_retrospectively() -> None:
    """A check of the rule against a known case - not a re-scoring of Phase 14.

    10 of 26 is 0.3846, four times the ceiling. If the rule did NOT demote the one
    run everybody agrees was degraded, the thresholds would be wrong.
    """
    rows = json.loads((PHASE14 / "per_case.json").read_text())
    scored = [
        r
        | {
            "provider_failure": r["abstention_state"] == "MODEL_SCHEMA_FAILURE"
            and r["assessments_total"] == 0
        }
        for r in rows
    ]
    finding = classify_validity(scored)
    assert finding.status is ExperimentValidity.DEGRADED_BY_PROVIDER_FAILURE
    assert finding.provider_failures == 10
    assert finding.failure_rate == pytest.approx(0.3846, abs=1e-4)
    assert "FAILURE_RATE" in finding.triggered
