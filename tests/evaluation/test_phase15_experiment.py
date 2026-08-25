"""The Phase-15 experiment record, and the things that would let it drift.

Everything `test_frozen_experiment.py` checks about Phase 14 applies here too, and
the shared checks are not duplicated - both runs are scored by the same functions in
`scripts/score_frozen_410_33.py`, so a difference between the two reports is a
difference in the systems rather than in two scorers that grew apart.

What is new is what Phase 15 added, and each of these exists because it is a way the
record could be made to say more than it measured:

- that applicability was **resolved**, not designated - a replay carries `RESOLVED`
  too, and only the reason separates them;
- that the R-93 invariant held in the run itself, not only in the regression;
- that the validity status came from the **pre-registered** rule and not from one
  chosen after these numbers existed;
- that the Phase-14 artefacts were not touched while producing these.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

pytestmark = [pytest.mark.evaluation, pytest.mark.security]

REPO = Path(__file__).resolve().parents[2]
RUN = REPO / "eval/reports/phase15-410-33"
PHASE14 = REPO / "eval/reports/frozen-410-33"
FROZEN = REPO / "data/review/eval_410_33_frozen.json"

pytestmark = [
    *pytestmark,
    pytest.mark.skipif(
        not (RUN / "metrics.json").is_file(),
        reason="the Phase-15 run has not been executed in this checkout",
    ),
]

DEFINITIVE = {"APPROVE_RECOMMENDED", "DENY_RECOMMENDED"}


@pytest.fixture(scope="module")
def manifest() -> dict:
    return json.loads((RUN / "manifest.json").read_text())


@pytest.fixture(scope="module")
def per_case() -> list[dict]:
    return json.loads((RUN / "per_case.json").read_text())


@pytest.fixture(scope="module")
def metrics() -> dict:
    return json.loads((RUN / "metrics.json").read_text())


# ---------------------------------------------------------------------------
# It is a separate experiment, frozen first
# ---------------------------------------------------------------------------


def test_the_manifest_was_frozen_before_the_run(manifest: dict) -> None:
    assert manifest["frozen_at"] < manifest["ran_at"]
    assert manifest["status"] == "RUN_COMPLETE"


def test_it_is_a_separate_experiment_and_says_what_it_supersedes(manifest: dict) -> None:
    """Not a continuation. A continuation would invite the two to be compared.

    They can only be compared on axes the validity rule permits, and Phase 14's
    decision figures are not one of them - it measured a runtime that could not
    resolve applicability.
    """
    assert manifest["experiment"] == "phase15-410-33"
    assert manifest["supersedes"] == "frozen-410-33"
    assert "not a continuation" in manifest["supersession_note"].lower()
    assert RUN != PHASE14


def test_every_frozen_case_was_attempted_and_none_excluded(
    manifest: dict, per_case: list[dict], metrics: dict
) -> None:
    frozen = json.loads(FROZEN.read_text())
    assert sorted(r["case_id"] for r in per_case) == frozen["case_ids"]
    assert manifest["cases_attempted"] == len(frozen["case_ids"])
    assert metrics["cases_excluded"] == 0


def test_the_dataset_is_the_same_frozen_set(manifest: dict) -> None:
    """Same digest as Phase 14's manifest. A different corpus is a different claim."""
    phase14 = json.loads((PHASE14 / "manifest.json").read_text())
    assert manifest["dataset"]["digest"] == phase14["dataset"]["digest"]
    assert manifest["dataset"]["case_ids"] == phase14["dataset"]["case_ids"]


def test_nothing_was_tuned_between_the_two_runs(manifest: dict) -> None:
    """The comparison rests on this, so it is asserted rather than asserted about.

    Prompts, encoder, reranker, top_k and ceilings must be byte-identical to Phase
    14's manifest. If any of them moved, the second scoring measured two changes.
    """
    phase14 = json.loads((PHASE14 / "manifest.json").read_text())
    assert manifest["prompts"] == phase14["prompts"]
    for key in ("embedding_model", "reranker_model", "top_k", "rerank_top_n", "status"):
        assert manifest["retrieval"][key] == phase14["retrieval"][key], f"retrieval.{key} moved"
    assert manifest["model"]["temperature"] == phase14["model"]["temperature"]
    assert manifest["model"]["max_output_tokens"] == phase14["model"]["max_output_tokens"]
    assert manifest["model"]["digest"] == phase14["model"]["digest"]


def test_the_second_scoring_was_declared_in_advance(manifest: dict) -> None:
    """A frozen split has a budget, and this run spends the second of two."""
    gold = json.loads((REPO / "data/gold/manifests/gold_v1.manifest.json").read_text())
    budget = gold["scoring_budget"]
    assert budget["allowed_scorings"] == len(budget["allowance_declarations"])
    assert budget["scorings_spent"] <= budget["allowed_scorings"]
    assert manifest["gold_scoring"]["spends"] == 2
    assert "ADR-028" in manifest["gold_scoring"]["declared_in"]


# ---------------------------------------------------------------------------
# R-93: applicability was resolved, and the invariant held in the run
# ---------------------------------------------------------------------------


def test_the_applicability_implementation_is_frozen_in_the_manifest(manifest: dict) -> None:
    """ "Applicability was resolved" is uncheckable without naming what resolved it."""
    applicability = manifest["applicability"]
    assert applicability["version"] == "applicability.v1"
    assert applicability["digest"].startswith("sha256:")
    assert applicability["mode"] == "PRODUCTION"
    assert applicability["states"] == 6


def test_every_case_recorded_an_applicability_state(per_case: list[dict]) -> None:
    for row in per_case:
        assert row["applicability_state"], f"{row['case_id']} has no applicability state"
        assert row["applicability_reason"], f"{row['case_id']} has no applicability reason"
        assert row["run_mode"] == "PRODUCTION"


def test_no_case_was_designated_without_resolution(metrics: dict) -> None:
    """A replay finding in a production run would be the Phase-14 shape wearing a label.

    `DESIGNATED_WITHOUT_RESOLUTION` carries state `RESOLVED`, so a report reading the
    state alone could not tell them apart. This reads the reason.
    """
    applicability = metrics["applicability"]
    assert applicability["present"] is True
    assert applicability["designated_without_resolution"] == []


def test_no_definitive_decision_survived_a_refused_applicability(
    metrics: dict, per_case: list[dict]
) -> None:
    """THE R-93 invariant, measured on the run rather than argued from the code.

    The regression proves the code refuses. This proves the run did.
    """
    assert metrics["applicability"]["definitive_without_resolution"] == []
    for row in per_case:
        if not row["applicability_resolved"]:
            assert row["actual_recommendation"] not in DEFINITIVE, (
                f"{row['case_id']} reached {row['actual_recommendation']} without "
                "resolved applicability - this is R-93 recurring"
            )


def test_a_refused_case_spent_nothing_on_the_model(per_case: list[dict]) -> None:
    """No retrieval, no model call, no quotable assessments.

    A refused case that still carries verified citations is a refused case somebody
    can quote out of context.
    """
    for row in per_case:
        if not row["applicability_resolved"]:
            assert row["model_calls"] == 0, f"{row['case_id']} called the model anyway"
            assert row["citations_verified"] == 0
            assert row["assessments_total"] == 0


def test_the_census_is_recorded_for_every_case(per_case: list[dict]) -> None:
    """The counts behind the reason, so a state can be re-derived rather than trusted."""
    for row in per_case:
        census = row["applicability_census"]
        assert census is not None, f"{row['case_id']} recorded no census"
        assert census["in_force"] <= census["total"]
        assert census["in_jurisdiction"] <= census["total"]


# ---------------------------------------------------------------------------
# The validity rule was pre-registered, not chosen afterwards
# ---------------------------------------------------------------------------


def test_the_validity_rule_was_frozen_in_the_manifest(manifest: dict) -> None:
    from eval.validity import VALIDITY_RULE_ID

    rule = manifest["experiment_validity_rule"]
    assert rule["id"] == VALIDITY_RULE_ID
    assert "ADR-028" in rule["preregistered_in"]
    assert rule["direction"] == "demote-only; no evidence promotes"


def test_the_manifest_names_its_failure_mode_before_the_result(manifest: dict) -> None:
    """A pre-registered failure mode must not later be presented as a discovery."""
    text = manifest["experiment_validity_rule"]["preregistered_failure_mode"].lower()
    assert "degraded_by_provider_failure" in text
    assert "not a discovery" in text
    assert "not a reason to raise the ceiling" in text


def test_the_status_came_from_the_rule_the_manifest_froze(manifest: dict, metrics: dict) -> None:
    validity = metrics["experiment_validity"]
    assert validity["rule_id"] == manifest["experiment_validity_rule"]["id"]
    assert validity["rule_matches_manifest"] is True
    assert validity["status"] in {
        "VALID_FOR_PERFORMANCE_ANALYSIS",
        "DEGRADED_BY_PROVIDER_FAILURE",
    }


def test_a_degraded_status_carries_the_conditions_that_produced_it(metrics: dict) -> None:
    """A status without its reasons is an opinion.

    Written as an implication so it holds whichever way the run came out - and so it
    would still be meaningful if a later run is VALID.
    """
    validity = metrics["experiment_validity"]
    if validity["status"] == "DEGRADED_BY_PROVIDER_FAILURE":
        assert validity["conditions_triggered"], "degraded with no condition named"
        assert validity["interpretable_as_performance"] is False
        assert validity["notes"]
    else:
        assert validity["conditions_triggered"] == []
        assert validity["interpretable_as_performance"] is True


# ---------------------------------------------------------------------------
# Honesty of the record itself
# ---------------------------------------------------------------------------


def test_the_phase_14_artefacts_were_not_touched(metrics: dict) -> None:
    """Scoring Phase 15 must not have rewritten Phase 14. The scorer takes a flag.

    Checked here as well as in `test_experiment_validity.py` because THIS is the run
    that had the opportunity: same script, one argument apart.
    """
    import hashlib

    status = json.loads((PHASE14 / "STATUS.json").read_text())
    for name, recorded in status["files"].items():
        digest = f"sha256:{hashlib.sha256((PHASE14 / name).read_bytes()).hexdigest()}"
        assert digest == recorded, f"scoring Phase 15 modified the Phase-14 {name}"


def test_r86_is_tracked_and_never_became_a_recommendation(metrics: dict) -> None:
    r86 = metrics["r86"]
    assert r86["became_approve_or_deny"] == []
    assert r86["cases_excluded"] == 0
    assert "NOT FIXED" in r86["status"]
    assert set(r86["final_behaviour"]) <= {"HUMAN_REVIEW", "NEEDS_INFO", "NO_DECISION"}


def test_right_answer_and_right_reason_are_reported_separately(metrics: dict) -> None:
    """R-96 and R-98. An outcome-level match can hide a wrong row - now at two stages."""
    decision = metrics["decision"]
    assert "accuracy_right_for_the_right_reason" in decision
    assert (
        decision["accuracy_right_for_the_right_reason"]["successes"]
        <= decision["accuracy"]["successes"]
    )


def test_the_dataset_defect_is_reported_not_hidden(per_case: list[dict]) -> None:
    """R-97. The three POLICY_NOT_APPLICABLE cases must appear in the record.

    They are the cases whose labels this corpus cannot reach, and the temptation is
    to drop them - which would report a number about an easier corpus than the one
    the manifest names.
    """
    failures = json.loads((RUN / "failures.json").read_text())
    not_applicable = {r["case_id"] for r in per_case if r["category"] == "POLICY_NOT_APPLICABLE"}
    assert len(not_applicable) == 3

    recorded = {f["case_id"] for f in failures}
    for case_id in not_applicable:
        row = next(r for r in per_case if r["case_id"] == case_id)
        if not (row["decision_correct"] and row["expected_rule"] == row["actual_rule"]):
            assert case_id in recorded, f"{case_id} was neither correct nor recorded"


def test_every_failure_names_a_stage_and_a_remedy() -> None:
    failures = json.loads((RUN / "failures.json").read_text())
    stages = {
        "POLICY_RESOLUTION",
        "DATASET_DEFECT",
        "RETRIEVAL",
        "EVIDENCE_MAPPING",
        "MODEL_ASSESSMENT",
        "CONTRADICTION",
        "CITATION",
        "DECISION",
        "ABSTENTION",
        "PROVIDER_FAILURE",
    }
    for failure in failures:
        assert failure["stage_of_failure"] in stages, failure["stage_of_failure"]
        assert failure["root_cause"].strip()
        assert failure["severity"].strip()
        assert failure["proposed_remediation"].strip()


def test_no_clinical_text_leaks_into_the_record(per_case: list[dict]) -> None:
    """Ids, spans and counts. Never the note."""
    gold = [
        json.loads(line)
        for line in (REPO / "data/gold/cases/gold_v1.jsonl").read_text().splitlines()
        if line
    ]
    notes = {r["case_id"]: r["input"]["clinical_note"] for r in gold}
    blob = json.dumps(per_case)
    for case_id, note in notes.items():
        for sentence in (s.strip() for s in note.split("\n") if len(s.strip()) > 30):
            assert sentence not in blob, f"{case_id}'s note text is in the per-case record"


def test_no_cost_is_invented(metrics: dict) -> None:
    assert metrics["operational"]["cost"] is None


def test_the_interpretation_is_stated_and_is_not_clinical(metrics: dict) -> None:
    text = metrics["interpretation"].lower()
    assert "not clinical accuracy" in text
    assert any("no clinical validation" in limit for limit in metrics["limitations"])
