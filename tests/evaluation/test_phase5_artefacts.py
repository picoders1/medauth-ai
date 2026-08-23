"""Phase 5 artefacts: NCD provenance, the review workflow, the dependency report.

These check *artefacts*, not code. Each guards a claim that could quietly stop
being true - an acquisition registry that stops recording refusals, a review form
that acquires pre-filled answers, a dependency report that starts calling a blocked
criterion adjudicable.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
import yaml

pytestmark = pytest.mark.evaluation

REPO = Path(__file__).resolve().parents[2]
SELECTION = REPO / "data/coverage/ncd_selection.yaml"
REGISTRY = REPO / "data/coverage/registry.yaml"
REVIEW = REPO / "data/review/od19_review_package.jsonl"
REVIEW_SUMMARY = REPO / "data/review/od19_summary.json"
DEPENDENCIES = REPO / "data/review/policy_dependencies.json"
COVERAGE = REPO / "data/policy_logic/production_coverage.json"
GOLD = REPO / "data/gold/cases/gold_v1.jsonl"
CASES = REPO / "data/synthetic/cases/cases.jsonl"


def _jsonl(path: Path) -> list[dict[str, Any]]:
    return [
        json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()
    ]


# ---------------------------------------------------------------------------
# NCD selection and acquisition
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def selection() -> dict[str, Any]:
    return yaml.safe_load(SELECTION.read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def registry() -> dict[str, Any]:
    return yaml.safe_load(REGISTRY.read_text(encoding="utf-8"))


def test_the_selection_rule_does_not_select_on_the_outcome(selection: dict[str, Any]) -> None:
    """Selecting datable NCDs would bias the corpus and hide it.

    "Exclude the undated ones" quietly becomes "select the datable ones", and the
    selection record would then describe a biased sample without saying so. The
    datable fraction must be a measured property, not a criterion.
    """
    rule = selection["selection_rule"].lower()
    assert "not selected on whether the effective date parses" in rule
    assert selection["ncds"]


def test_every_selected_ncd_states_why_it_was_chosen(selection: dict[str, Any]) -> None:
    for entry in selection["ncds"]:
        assert entry["reason"].strip(), entry["ncdid"]
        assert len(entry["reason"].split()) >= 10, entry["ncdid"]


def test_no_licence_gated_endpoint_was_requested(selection: dict[str, Any]) -> None:
    """LCD and Article endpoints sit behind an AMA/ADA/AHA gate (OD-21)."""
    used = " ".join(selection["endpoints_used"])
    assert "/lcd" not in used
    assert "/article" not in used
    refused = {e["path"] for e in selection["endpoints_refused"]}
    assert refused == {"/lcd", "/article"}


def test_the_registry_records_provenance_for_every_version(registry: dict[str, Any]) -> None:
    """Source, timestamp, hash and version identity, for each acquired version."""
    assert registry["documents"]
    for document in registry["documents"]:
        assert document["policy_id"].startswith("NCD "), document
        for version in document["versions"]:
            assert version["source_url"].startswith("https://api.coverage.cms.gov/")
            assert version["retrieved_at"]
            assert version["version"] >= 1
            assert version["temporal_status"] in {"DATED", "UNDATED", "AMBIGUOUS"}


def test_refusals_are_recorded_rather_than_dropped(registry: dict[str, Any]) -> None:
    """A refusal is evidence about the source, not a gap to be quietly filled.

    NCD 30.4 publishes a retirement date that PRECEDES its own effective date,
    identical across all three versions. That is the record proving
    `effective_end_date` is document-level rather than a version window, and
    discarding it silently would discard the evidence.
    """
    assert registry["refused"] >= 1
    assert len(registry["refusals"]) == registry["refused"]
    for refusal in registry["refusals"]:
        assert refusal["reason"].strip()
        assert refusal["observed"]


def test_acquisition_coverage_is_stated_not_implied(registry: dict[str, Any]) -> None:
    """The corpus must never be described as "the CMS NCD corpus".

    It is 10 determinations chosen deliberately. The registry states selected,
    acquired, refused and unreachable so no reader has to infer coverage.
    """
    assert registry["selected"] == len(yaml.safe_load(SELECTION.read_text())["ncds"])
    assert (
        registry["acquired"] + registry["refused"] + registry["unreachable"] == registry["selected"]
    )


def test_the_unresolvable_fraction_is_measured_and_non_zero(registry: dict[str, Any]) -> None:
    """If every acquired NCD were datable, the fail-closed path would be untested.

    The selection deliberately includes undated determinations so the temporal
    refusal is exercised against real data rather than only against fixtures.
    """
    total = registry["versions"]
    resolvable = registry["versions_temporally_resolvable"]
    assert 0 < resolvable < total, (
        f"{resolvable}/{total} versions are resolvable; the corpus needs both kinds"
    )


def test_no_ncd_document_is_committed() -> None:
    """Downloaded, never committed (ADR-003). The registry is the committed record."""
    import shutil
    import subprocess

    git = shutil.which("git")
    assert git, "git is required to check what is tracked"
    tracked = subprocess.run(  # noqa: S603
        [git, "ls-files", "data/coverage/documents"],
        cwd=REPO,
        capture_output=True,
        text=True,
        check=False,
    ).stdout.strip()
    assert not tracked, f"NCD documents are tracked by git: {tracked.splitlines()[:3]}"


# ---------------------------------------------------------------------------
# Production adjudicability
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def coverage() -> dict[str, Any]:
    return json.loads(COVERAGE.read_text(encoding="utf-8"))


def test_the_recorded_gold_impact_matches_the_datasets(coverage: dict[str, Any]) -> None:
    """The documentation cannot drift from the data it describes.

    If a policy version's classification changes, these counts change with it, and
    a stale number in a document becomes a failing test rather than a quiet lie.
    """
    adjudicable = {
        (row["policy_id"], row["policy_version"])
        for row in coverage["versions"]
        if row["adjudicable_in_production"]
    }
    for name, path in (("gold_v1", GOLD), ("synthetic", CASES)):
        cases = _jsonl(path)
        blocked = sum(
            1
            for case in cases
            if (case["expected"]["policy_id"], case["expected"]["policy_revision"])
            not in adjudicable
        )
        recorded = coverage["corpora"][name]
        assert recorded["cases"] == len(cases)
        assert recorded["blocked_by_policy_semantics"] == blocked


def test_blocked_cases_are_not_described_as_invalid(coverage: dict[str, Any]) -> None:
    """Their labels remain correct records of a completed construction."""
    note = coverage["note"]
    assert "NOT invalid" in note
    assert "eval/replay.py" in note


def test_the_semantics_gate_is_not_simply_blocking_everything(
    coverage: dict[str, Any],
) -> None:
    """The positive control, restated for what Phase 7 measured.

    It used to assert at least one version was adjudicable. That is now FALSE and
    honestly so: adjudicability is semantics AND dependencies, and the one version
    with executable semantics (42 CFR 410.32) contains a criterion that invokes an
    untranscribed provision, so a verdict on it would be unfounded (R-51).

    The control it was providing still matters, so it moves to the axis that still
    has a non-zero answer: at least one version's SEMANTICS execute. If that ever
    reached zero, fail-closed would be indistinguishable from a system that simply
    does not work.
    """
    assert coverage["versions_semantics_executable"] >= 1
    assert coverage["versions_semantics_executable"] < coverage["versions_total"]
    # And the two axes must not be silently merged back together.
    assert coverage["versions_adjudicable"] <= coverage["versions_semantics_executable"]
    assert coverage["versions_blocked_by_dependency"] >= 1

    # The load-bearing clause: executable semantics plus a dependency-blocked
    # criterion must NOT be adjudicable. Without this, dropping the dependency
    # conjunct from the report leaves every count above unchanged and the test
    # green - which it did, until this was added.
    for row in coverage["versions"]:
        if row["semantics_executable"] and row["dependency_blocked_criteria"]:
            assert not row["adjudicable_in_production"], (
                f"{row['policy_id']} {row['policy_version']} is reported adjudicable "
                f"while {row['dependency_blocked_criteria']} invoke an untranscribed "
                "provision; a verdict on those would be unfounded (R-51)"
            )


# ---------------------------------------------------------------------------
# OD-19 review workflow
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def review_rows() -> list[dict[str, Any]]:
    return _jsonl(REVIEW)


def test_every_row_starts_pending_and_nothing_is_approved(
    review_rows: list[dict[str, Any]],
) -> None:
    """A workflow that can approve its own rows will eventually approve all of them."""
    summary = json.loads(REVIEW_SUMMARY.read_text(encoding="utf-8"))
    assert summary["automatically_approved"] == 0
    assert summary["prefilled_decisions"] == 0
    for row in review_rows:
        assert row["review_status"] == "PENDING", row["review_id"]
        assert row["reviewer_decision"] is None
        assert row["reviewer_rationale"] is None
        assert row["reviewer_id"] is None
        assert row["reviewed_at"] is None


def test_every_row_carries_a_workflow_identity_and_the_permitted_states(
    review_rows: list[dict[str, Any]],
) -> None:
    expected = {
        "PENDING",
        "IN_REVIEW",
        "APPROVED",
        "REJECTED",
        "MERGE_REQUIRED",
        "INTERPRETATION_REQUIRED",
        "CLINICAL_REVIEW_REQUIRED",
    }
    ids = set()
    for row in review_rows:
        assert row["review_id"].startswith("OD19-")
        assert set(row["permitted_statuses"]) == expected
        ids.add(row["review_id"])
    assert len(ids) == len(review_rows), "review ids are not unique"


def test_a_decision_maps_to_exactly_one_workflow_state() -> None:
    """So a reviewer cannot leave the two fields disagreeing."""
    summary = json.loads(REVIEW_SUMMARY.read_text(encoding="utf-8"))
    mapping = summary["decision_to_status"]
    assert set(mapping) == set(summary["permitted_decisions"])
    assert set(mapping.values()) <= set(summary["permitted_statuses"])
    assert "PENDING" not in mapping.values()


# ---------------------------------------------------------------------------
# Dependency model
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def dependencies() -> dict[str, Any]:
    return json.loads(DEPENDENCIES.read_text(encoding="utf-8"))


def test_a_criterion_with_an_open_dependency_is_not_independently_adjudicable(
    dependencies: dict[str, Any],
) -> None:
    """The R-51 property, made structural.

    A criterion that invokes a rule it does not contain cannot be adjudicated on
    its own evidence, and must never be presented as if it could.
    """
    assert dependencies["criteria_blocked_by_unresolved_dependencies"] >= 1
    for criterion_id, entry in dependencies["dependencies"].items():
        open_deps = [d for d in entry["depends_on"] if d["review_status"] != "APPROVED"]
        if open_deps:
            assert entry["independently_adjudicable"] is False, criterion_id


def test_the_known_r51_dependency_is_present(dependencies: dict[str, Any]) -> None:
    """410.32 C03 depends on the supervision levels in paragraph (b)(3)."""
    entry = dependencies["dependencies"]["42_CFR_410_32_2026_08_13_C03"]
    assert entry["independently_adjudicable"] is False
    assert any(d["paragraph_path"] == "(b)(3)" for d in entry["depends_on"])


def test_every_dependency_names_a_real_provision(dependencies: dict[str, Any]) -> None:
    matrix = {p["provision_id"] for p in _jsonl(REPO / "data/criteria/coverage_matrix.jsonl")}
    for entry in dependencies["dependencies"].values():
        for dependency in entry["depends_on"]:
            assert dependency["provision_id"] in matrix
            assert dependency["authoritative_text"].strip()


def test_dependencies_are_recorded_not_detected(dependencies: dict[str, Any]) -> None:
    """A regex over criterion text finds none - the criteria never cite paragraphs."""
    assert "established by inspection, never detected" in dependencies["note"]
