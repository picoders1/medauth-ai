"""The frozen 410.33 experiment artefact must stay honest after the fact.

An experiment record is only worth what its provenance is. These check the things
that would let a result be quietly improved later: a manifest written after the run,
a case dropped from the denominator, a metric that flatters by counting a right
answer reached the wrong way.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

pytestmark = [pytest.mark.evaluation, pytest.mark.security]

REPO = Path(__file__).resolve().parents[2]
RUN = REPO / "eval/reports/frozen-410-33"
FROZEN = REPO / "data/review/eval_410_33_frozen.json"


@pytest.fixture(scope="module")
def manifest() -> dict:
    return json.loads((RUN / "manifest.json").read_text())


@pytest.fixture(scope="module")
def per_case() -> list[dict]:
    return json.loads((RUN / "per_case.json").read_text())


@pytest.fixture(scope="module")
def metrics() -> dict:
    return json.loads((RUN / "metrics.json").read_text())


def test_the_manifest_was_frozen_before_the_run(manifest: dict) -> None:
    """The whole mechanism. A configuration recorded after a run could have been
    chosen because of it."""
    assert manifest["frozen_at"] < manifest["ran_at"]
    assert manifest["status"] == "RUN_COMPLETE"


def test_every_frozen_case_was_attempted_and_none_excluded(
    manifest: dict, per_case: list[dict], metrics: dict
) -> None:
    """Dropping a hard case is how an evaluation reports a number about an easier
    corpus than the one it names."""
    frozen = json.loads(FROZEN.read_text())
    assert sorted(r["case_id"] for r in per_case) == frozen["case_ids"]
    assert len(per_case) == frozen["case_count"] == 26
    assert metrics["cases_excluded"] == 0


def test_the_retrieval_configuration_is_labelled_unresolved(manifest: dict) -> None:
    """It was fixed so it would not be a variable - not selected, and not optimal."""
    assert manifest["retrieval"]["status"] == "ENGINEERING_DEFAULT_UNRESOLVED"
    assert "NOT optimal" in manifest["retrieval"]["note"]


def test_no_confidence_threshold_was_calibrated(manifest: dict, metrics: dict) -> None:
    assert manifest["abstention"]["scored_gate"] == "UNCALIBRATED"
    assert metrics["abstention"]["scored_gate"] == "UNCALIBRATED"


def test_right_answer_and_right_reason_are_reported_separately(metrics: dict) -> None:
    """The gap between them is where a metric flatters a system.

    Two POLICY_NOT_APPLICABLE cases reached the correct outcome through row 6 instead
    of row 1. Reporting only `accuracy` would count them as successes.
    """
    d = metrics["decision"]
    assert "accuracy_right_for_the_right_reason" in d
    assert d["accuracy_right_for_the_right_reason"]["successes"] <= d["accuracy"]["successes"]
    for row in d["outcome_correct_wrong_rule"]:
        assert row["expected_rule"] != row["actual_rule"]


def test_r86_occurrences_are_tracked_and_never_became_a_recommendation(
    metrics: dict,
) -> None:
    """The safety claim under a live provider failure."""
    r = metrics["r86"]
    assert r["classification"] == "PROVIDER/DECODER_FAILURE"
    assert "NOT FIXED" in r["status"]
    assert r["became_approve_or_deny"] == []
    assert r["cases_excluded"] == 0
    assert r["occurrence_count"] == len(r["affected_cases"])


def test_every_safety_invariant_is_zero(metrics: dict) -> None:
    for name, rate in metrics["safety"]["violations"].items():
        assert rate["successes"] == 0, f"{name} is non-zero"
    assert metrics["safety"]["all_zero"] is True


def test_grounding_is_deterministic_not_model_judged(metrics: dict) -> None:
    """A model judging its own grounding is the same component marking its own work."""
    assert metrics["grounding"]["llm_as_judge"] is None


def test_no_cost_is_invented(metrics: dict) -> None:
    assert metrics["operational"]["cost"] is None


def test_a_failure_record_exists_for_every_imperfect_case(
    per_case: list[dict],
) -> None:
    """Including the ones with the right outcome by the wrong row."""
    failures = json.loads((RUN / "failures.json").read_text())
    expected = {
        r["case_id"]
        for r in per_case
        if not r["decision_correct"] or r["expected_rule"] != r["actual_rule"]
    }
    assert {f["case_id"] for f in failures} == expected
    for f in failures:
        assert f["root_cause"].strip()
        assert f["stage_of_failure"]
        assert f["severity"]


def test_the_interpretation_is_stated_and_is_not_clinical(metrics: dict) -> None:
    text = metrics["interpretation"].lower()
    assert "frozen engineering gold set" in text
    assert "not clinical accuracy" in text
    assert any("no clinical validation" in limit for limit in metrics["limitations"])
