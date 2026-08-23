"""Phase 8 artefacts: the FOCUS-001 record, benchmark readiness, slice admissibility.

Three claims that must not quietly stop being true: that the decision record is
unanswered, that no contaminated benchmark can be scored, and that production stays
blocked while the decision is open.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

pytestmark = pytest.mark.evaluation

REPO = Path(__file__).resolve().parents[2]
DECISION = REPO / "data/review/focus_001_decision.json"
IMPACT = REPO / "data/review/focus_001_impact.json"
PACKET = REPO / "docs/review/FOCUS-001.md"
PROVENANCE = REPO / "data/review/evaluation_provenance.json"
READINESS = REPO / "data/review/retrieval_benchmark_readiness.json"
ADMISSIBILITY = REPO / "data/review/slice_admissibility.json"
GOLD = REPO / "data/gold/cases/gold_v1.jsonl"
GOLD_MANIFEST = REPO / "data/gold/manifests/gold_v1.manifest.json"
SYNTHETIC = REPO / "data/synthetic/cases/cases.jsonl"

PERMITTED = {
    "NARROW_C03_TO_BASELINE",
    "SPLIT_C03",
    "LEAVE_C03_NOT_ADJUDICABLE",
    "OTHER",
}


def _jsonl(path: Path) -> list[dict[str, Any]]:
    return [
        json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()
    ]


# ---------------------------------------------------------------------------
# FOCUS-001 decision record
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def decision() -> dict[str, Any]:
    return json.loads(DECISION.read_text(encoding="utf-8"))


def test_focus_001_is_pending_and_unanswered(decision: dict[str, Any]) -> None:
    """The committed record must show no answer, not an empty-looking one."""
    assert decision["status"] == "PENDING"
    assert decision["is_resolved"] is False
    assert decision["blocks_production"] is True
    for field in (
        "reviewer",
        "reviewer_identity",
        "reviewer_qualification",
        "reviewer_decision",
        "reviewer_rationale",
        "review_timestamp",
        "accepted_by",
    ):
        assert decision[field] is None, f"{field} is populated in a PENDING record"


def test_the_option_set_is_closed_and_complete(decision: dict[str, Any]) -> None:
    """An answer must not be able to quietly change the question it was asked."""
    assert set(decision["permitted_decisions"]) == PERMITTED


def test_the_record_names_what_it_affects(decision: dict[str, Any]) -> None:
    """A reviewer must see the blast radius from the record itself."""
    gold_ids = {case["case_id"] for case in _jsonl(GOLD)}
    assert decision["affected_criteria"] == ["42_CFR_410_32_2026_08_13_C03"]
    assert decision["affected_cases"]
    assert set(decision["affected_cases"]) <= gold_ids
    assert any("410.32" in ref for ref in decision["source_references"])


def test_the_record_states_that_no_code_path_can_answer_it(
    decision: dict[str, Any],
) -> None:
    note = decision["note"]
    assert "DOMAIN decision" in note
    assert "no code path" in note
    assert "blocked" in note


# ---------------------------------------------------------------------------
# Impact table
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def impact() -> dict[str, Any]:
    return json.loads(IMPACT.read_text(encoding="utf-8"))


def test_every_permitted_outcome_has_a_computed_impact(
    impact: dict[str, Any], decision: dict[str, Any]
) -> None:
    outcomes = {row["outcome"] for row in impact["outcomes"]}
    assert outcomes == set(decision["permitted_decisions"])
    assert impact["computed_before_any_decision"] is True


def test_the_impact_table_does_not_recommend(impact: dict[str, Any]) -> None:
    """Some options cost more; that is a fact about them, not an argument.

    A table that named a preferred outcome would be the analysis making the domain
    decision it exists to inform.
    """
    note = impact["note"]
    assert "does NOT recommend" in note
    assert "wrong reason" in note
    for row in impact["outcomes"]:
        assert "recommended" not in json.dumps(row).lower()


def test_affected_case_counts_match_the_corpus(impact: dict[str, Any]) -> None:
    """The table cannot drift from the data it describes."""
    referencing = {
        case["case_id"]
        for case in _jsonl(GOLD)
        if any(
            entry["criterion_id"] == "42_CFR_410_32_2026_08_13_C03"
            for entry in case["expected"]["criteria"]
        )
    }
    for row in impact["outcomes"]:
        if row["gold_v2_required"]:
            assert set(row["gold_cases_affected"]) == referencing
            assert row["gold_cases_affected_count"] == len(referencing)


def test_no_outcome_claims_admissibility_it_cannot_deliver(
    impact: dict[str, Any],
) -> None:
    """Only an outcome that both closes the dependency AND leaves nothing else
    blocking may report admissibility."""
    for row in impact["outcomes"]:
        if row["policy_admissible_after"]:
            assert not row["still_blocked_by"], row["outcome"]
            assert row["unblocks"], row["outcome"]


# ---------------------------------------------------------------------------
# Reviewer packet
# ---------------------------------------------------------------------------


def test_the_reviewer_packet_carries_the_source_and_no_recommendation() -> None:
    """It must give the reviewer what they need and nothing that steers them."""
    text = PACKET.read_text(encoding="utf-8")
    assert "Levels of supervision" in text
    assert "General supervision means" in text
    assert "Direct supervision in the office setting" in text
    assert "Personal supervision means" in text
    assert "physician fee schedule" in text
    for option in PERMITTED:
        assert option in text
    assert "Nothing in this packet recommends an outcome" in text
    lowered = text.lower()
    for steer in ("we recommend", "recommended option", "the obvious choice", "should choose"):
        assert steer not in lowered


# ---------------------------------------------------------------------------
# Retrieval provenance and benchmark readiness
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def provenance() -> dict[str, Any]:
    return json.loads(PROVENANCE.read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def readiness() -> dict[str, Any]:
    return json.loads(READINESS.read_text(encoding="utf-8"))


def test_all_three_retrieval_sets_are_audited(provenance: dict[str, Any]) -> None:
    assert set(provenance["sets"]) == {"retrieval_v1", "retrieval_v2", "retrieval_v3"}


def test_a_set_with_any_unscorable_query_is_contaminated(
    provenance: dict[str, Any],
) -> None:
    """Not "mostly clean". A comparison over a set containing unscorable queries
    reports a rate whose denominator includes measurements that mean nothing."""
    for name, block in provenance["sets"].items():
        assert block["contaminated"] is (block["scorable"] != block["queries"]), name
        assert block["scorable"] + block["unscorable"] == block["queries"]


def test_v3_is_provenance_clean_and_v1_v2_are_not(provenance: dict[str, Any]) -> None:
    assert provenance["sets"]["retrieval_v3"]["contaminated"] is False
    assert provenance["sets"]["retrieval_v1"]["contaminated"] is True
    assert provenance["sets"]["retrieval_v2"]["contaminated"] is True


def test_no_benchmark_is_ready_and_that_is_stated(readiness: dict[str, Any]) -> None:
    """A clean set that cannot discriminate is not ready; a discriminating set that
    is contaminated is not ready. If none qualifies, say so."""
    assert readiness["status"] in {"RETRIEVAL_BENCHMARK_READY", "RETRIEVAL_BENCHMARK_NOT_READY"}
    assert readiness["status"] == "RETRIEVAL_BENCHMARK_NOT_READY"
    assert readiness["ready_sets"] == []
    assert "manufacture a result" in readiness["note"]


def test_readiness_requires_both_clean_provenance_and_discrimination(
    readiness: dict[str, Any],
) -> None:
    """Each set fails for its own reason, and both reasons are real."""
    by_set = {entry["set"]: entry for entry in readiness["assessment"]}
    assert "provenance_clean" in by_set["retrieval_v2"]["failed_checks"]
    assert by_set["retrieval_v2"]["checks"]["discriminates_between_arms"] is True
    assert by_set["retrieval_v3"]["checks"]["provenance_clean"] is True
    assert "has_been_scored" in by_set["retrieval_v3"]["failed_checks"]


def test_an_unscored_set_does_not_pass_the_discrimination_check(
    readiness: dict[str, Any],
) -> None:
    """Unknown is not the same as passing.

    A never-scored set has no evidence that it discriminates, and treating absence
    of evidence as a pass is how an untested benchmark becomes the one everything
    is compared on.
    """
    for entry in readiness["assessment"]:
        if not entry["checks"]["has_been_scored"]:
            assert entry["checks"]["discriminates_between_arms"] is False, entry["set"]


# ---------------------------------------------------------------------------
# Slice admissibility
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def admissibility() -> dict[str, Any]:
    return json.loads(ADMISSIBILITY.read_text(encoding="utf-8"))


def test_the_gate_reports_blocked_with_no_middle_state(
    admissibility: dict[str, Any],
) -> None:
    """READY or BLOCKED. There is no "close enough"."""
    assert admissibility["status"] in {"READY", "BLOCKED"}
    assert admissibility["status"] == "BLOCKED"
    assert admissibility["designated_slice"] is None


def test_an_open_domain_decision_blocks_the_policy_it_names(
    admissibility: dict[str, Any], decision: dict[str, Any]
) -> None:
    """The gate reads the decision record; it does not compute the answer.

    This is the link that makes production blocked *because* FOCUS-001 is open,
    rather than by coincidence.
    """
    assert decision["is_resolved"] is False
    candidate = next(
        c
        for c in admissibility["assessment"]
        if c["policy_id"] == decision["policy_id"]
        and c["policy_version"] == decision["policy_version"]
    )
    assert candidate["checks"]["domain_decisions_resolved"] is False
    assert not candidate["admissible"]


def test_all_eleven_conditions_are_assessed(admissibility: dict[str, Any]) -> None:
    required = {
        "semantics_declared",
        "criteria_span_verified",
        "no_unresolved_dependency",
        "temporally_resolvable",
        "coverage_status_established_or_not_required",
        "no_engineering_inferred_linkage",
        "citation_provenance_complete",
        "retrieval_scope_constructible",
        "evaluation_provenance_sufficient",
        "production_semantics_executable",
        "domain_decisions_resolved",
    }
    for candidate in admissibility["assessment"]:
        assert set(candidate["checks"]) == required, candidate["policy_identity"]


def test_no_policy_was_special_cased_to_pass(admissibility: dict[str, Any]) -> None:
    """Admissibility is the conjunction, computed the same way for every candidate."""
    for candidate in admissibility["assessment"]:
        assert candidate["admissible"] is all(candidate["checks"].values())


# ---------------------------------------------------------------------------
# gold_v1
# ---------------------------------------------------------------------------


def test_gold_v1_is_byte_identical() -> None:
    import hashlib

    manifest = json.loads(GOLD_MANIFEST.read_text(encoding="utf-8"))
    assert manifest["sha256"]["gold"] == hashlib.sha256(GOLD.read_bytes()).hexdigest()
    assert manifest["frozen"] is True
    assert manifest["scoring_budget"]["scorings_spent"] == 0
    assert len(_jsonl(GOLD)) == 156
    assert len(_jsonl(SYNTHETIC)) == 222


def test_no_gold_v2_exists_yet() -> None:
    """Two outcomes would force one. Neither has been chosen, so none exists."""
    assert not list((REPO / "data/gold/cases").glob("gold_v[2-9].jsonl"))
