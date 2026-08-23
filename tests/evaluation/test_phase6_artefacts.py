"""Phase 6 artefacts: NCD review queues, gold impact, slice admissibility.

Each guards a claim that could quietly stop being true - a review queue acquiring
pre-filled answers, a coverage status appearing without evidence, an admissibility
report designating a slice that no longer passes its own checks.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
import yaml

pytestmark = pytest.mark.evaluation

REPO = Path(__file__).resolve().parents[2]
NCD_STATUS = REPO / "data/review/ncd_status_review.jsonl"
NCD_LINKAGE_REVIEW = REPO / "data/review/ncd_linkage_review.jsonl"
NCD_SUMMARY = REPO / "data/review/ncd_review_summary.json"
NCD_LINKAGE = REPO / "data/linkage/ncd_code_links.yaml"
GOLD_IMPACT = REPO / "data/review/gold_impact.json"
ADMISSIBILITY = REPO / "data/review/slice_admissibility.json"
GOLD = REPO / "data/gold/cases/gold_v1.jsonl"


def _jsonl(path: Path) -> list[dict[str, Any]]:
    return [
        json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()
    ]


# ---------------------------------------------------------------------------
# NCD coverage-status review queue
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def status_rows() -> list[dict[str, Any]]:
    return _jsonl(NCD_STATUS)


def test_no_coverage_status_is_pre_filled(status_rows: list[dict[str, Any]]) -> None:
    """A candidate is a starting point. A decision is a person's."""
    for row in status_rows:
        assert row["review_state"] == "PENDING", row["review_id"]
        assert row["reviewer_status"] is None
        assert row["reviewer_id"] is None
        assert row["reviewer_rationale"] is None


def test_every_candidate_is_labelled_engineering_derived(
    status_rows: list[dict[str, Any]],
) -> None:
    """`ENGINEERING_DERIVED` is inadmissible as a coverage conclusion.

    Labelling it anything else would let a phrase scan become the system's answer
    about whether an item is covered.
    """
    for row in status_rows:
        assert row["candidate_origin"] == "ENGINEERING_DERIVED", row["review_id"]
        assert "INADMISSIBLE" in row["candidate_basis"]


def test_a_candidate_carries_the_text_it_came_from(status_rows: list[dict[str, Any]]) -> None:
    """A reviewer must be able to check the phrase, not just read a verdict."""
    for row in status_rows:
        if row["candidate_status"] is None:
            continue
        assert row["evidence_references"], row["review_id"]
        for reference in row["evidence_references"]:
            section = {
                "Indications and Limitations of Coverage": "indications_limitations",
                "Reasons for Denial": "reasons_for_denial",
            }[reference["section_path"]]
            text = row["coverage_text"][section]
            assert text[reference["span_start"] : reference["span_end"]] == reference["quote"], (
                f"{row['review_id']}: reference does not locate in the text it names"
            )


def test_some_determinations_get_no_candidate_at_all(
    status_rows: list[dict[str, Any]],
) -> None:
    """A scan that always produces a candidate is a classifier, not a starting point.

    A determination matching no unambiguous phrase, or matching conflicting ones,
    must come back with nothing rather than a guess.
    """
    without = [r for r in status_rows if r["candidate_status"] is None]
    assert without, "every determination got a candidate; the scan is guessing"


def test_every_row_carries_full_provenance(status_rows: list[dict[str, Any]]) -> None:
    for row in status_rows:
        assert row["source_url"].startswith("https://api.coverage.cms.gov/")
        assert row["retrieved_at"]
        assert row["content_sha256"]
        assert row["policy_identity"].startswith("NCD:")


def test_undated_determinations_are_present_in_the_queue(
    status_rows: list[dict[str, Any]],
) -> None:
    """They cannot be resolved by date, and they still need a status recorded.

    Dropping them would quietly narrow the review queue to the tractable subset.
    """
    assert any(row["temporal_status"] == "UNDATED" for row in status_rows)
    for row in status_rows:
        if row["temporal_status"] == "UNDATED":
            assert row["effective_date"] is None
            assert row["effective_date_source"].strip()


# ---------------------------------------------------------------------------
# NCD code linkage
# ---------------------------------------------------------------------------


def test_no_ncd_link_claims_to_be_source_stated() -> None:
    """The NCD record carries no procedure-code field, so none can be.

    19 fields, none of them codes - verified by live probe. A SOURCE_STATED link
    here would be a claim CMS did not make.
    """
    spec = yaml.safe_load(NCD_LINKAGE.read_text(encoding="utf-8"))
    assert spec["default_provenance"] != "SOURCE_STATED"
    for link in spec["links"]:
        assert link.get("provenance", spec["default_provenance"]) != "SOURCE_STATED", link


def test_every_link_carries_a_rationale_and_a_confidence() -> None:
    spec = yaml.safe_load(NCD_LINKAGE.read_text(encoding="utf-8"))
    for link in spec["links"]:
        assert link["rationale"].strip()
        assert len(link["rationale"].split()) >= 10, link["code"]
        assert link["confidence"] in {"high", "medium", "low"}
        assert link["description"].strip()


def test_the_linkage_file_states_that_it_is_not_cms_supplied() -> None:
    """The claim that must never be made about this file."""
    text = NCD_LINKAGE.read_text(encoding="utf-8")
    assert "NOTHING HERE MAY BE PRESENTED AS CMS-SUPPLIED LINKAGE" in text
    assert "no procedure-code field" in text.lower()


def test_the_linkage_review_queue_is_unpopulated() -> None:
    for row in _jsonl(NCD_LINKAGE_REVIEW):
        assert row["review_status"] == "PENDING", row["review_id"]
        assert row["reviewer_id"] is None
        assert row["reviewer_rationale"] is None


def test_inferred_links_are_marked_inadmissible_in_the_queue() -> None:
    """A reviewer must see which links production already refuses."""
    rows = _jsonl(NCD_LINKAGE_REVIEW)
    inferred = [r for r in rows if r["provenance"] == "ENGINEERING_INFERRED"]
    assert inferred, "no inferred link is recorded; the refusal path is untested"
    for row in inferred:
        assert row["admissible_in_production"] is False
        assert row["is_authoritative"] is False


def test_no_link_is_authoritative(status_rows: list[dict[str, Any]]) -> None:
    summary = json.loads(NCD_SUMMARY.read_text(encoding="utf-8"))
    assert summary["authoritative_links"] == 0
    assert summary["prefilled_status_decisions"] == 0
    assert summary["prefilled_linkage_decisions"] == 0


# ---------------------------------------------------------------------------
# Gold impact
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def impact() -> dict[str, Any]:
    return json.loads(GOLD_IMPACT.read_text(encoding="utf-8"))


def test_impact_names_the_cases_a_decision_would_reach(impact: dict[str, Any]) -> None:
    """A reviewer must see the blast radius before deciding, not after."""
    gold_ids = {case["case_id"] for case in _jsonl(GOLD)}
    touching = [e for e in impact["entries"] if e["forces_gold_v2"]]
    assert touching, "no reviewable subject reaches gold; the analysis found nothing"
    for entry in touching:
        assert entry["gold_cases_affected"]
        assert set(entry["gold_cases_affected"]) <= gold_ids


def test_impact_analysis_did_not_modify_gold(impact: dict[str, Any]) -> None:
    """It is a projection. gold_v1 is immutable."""
    assert impact["gold_cases_total"] == len(_jsonl(GOLD))
    assert "nothing here modifies it" in impact["note"]


def test_the_known_r51_dependency_reaches_gold(impact: dict[str, Any]) -> None:
    """410.32 C03 is the designated slice's only blocker; its reach must be known."""
    entry = next(e for e in impact["entries"] if e["subject_id"] == "42_CFR_410_32_2026_08_13_C03")
    assert entry["forces_gold_v2"]
    assert entry["gold_cases_affected"]


# ---------------------------------------------------------------------------
# Slice admissibility
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def admissibility() -> dict[str, Any]:
    return json.loads(ADMISSIBILITY.read_text(encoding="utf-8"))


def test_admissibility_is_the_conjunction_of_every_check(
    admissibility: dict[str, Any],
) -> None:
    """A slice failing one condition is not admissible, however many it passes."""
    for candidate in admissibility["assessment"]:
        expected = all(candidate["checks"].values())
        assert candidate["admissible"] is expected, candidate["policy_identity"]
        assert candidate["failed_checks"] == sorted(
            name for name, ok in candidate["checks"].items() if not ok
        )


def test_a_designated_slice_exists_only_if_something_passes(
    admissibility: dict[str, Any],
) -> None:
    """The report must not name a slice it cannot justify."""
    if admissibility["admissible"]:
        assert admissibility["designated_slice"] in admissibility["admissible"]
    else:
        assert admissibility["designated_slice"] is None
        assert admissibility["nearest_candidate_blockers"], (
            "no slice qualifies and no blocker is named; 'nothing qualifies' is not "
            "an actionable finding"
        )


def test_the_nearest_candidate_names_its_blockers(admissibility: dict[str, Any]) -> None:
    nearest = next(
        c
        for c in admissibility["assessment"]
        if c["policy_identity"] == admissibility["nearest_candidate"]
    )
    assert nearest["failed_checks"] == admissibility["nearest_candidate_blockers"]


#: The Phase 6 conditions. Phase 8 ADDED four; a condition may be added, and one
#: may never quietly disappear - dropping one makes the conjunction weaker than it
#: reads while every count in the report stays the same.
PHASE_6_CONDITIONS = frozenset(
    {
        "semantics_declared",
        "criteria_span_verified",
        "no_unresolved_dependency",
        "temporally_resolvable",
        "coverage_status_established_or_not_required",
        "no_engineering_inferred_linkage",
        "citation_provenance_complete",
    }
)


def test_no_admissibility_condition_was_dropped(admissibility: dict[str, Any]) -> None:
    """A condition silently dropped would make the conjunction weaker than it reads.

    Phase 8 note: this asserted an exact set of seven. Phase 8 added four more
    (retrieval scope, evaluation provenance, executable semantics, open domain
    decisions), so the assertion becomes a SUBSET check - additions are expected,
    removals are not.
    """
    for candidate in admissibility["assessment"]:
        assert PHASE_6_CONDITIONS <= set(candidate["checks"]), (
            f"{candidate['policy_identity']} lost condition(s) "
            f"{sorted(PHASE_6_CONDITIONS - set(candidate['checks']))}"
        )
