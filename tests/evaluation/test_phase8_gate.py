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


def test_focus_001_carries_a_fully_attributed_answer(decision: dict[str, Any]) -> None:
    """**The world changed on 2026-08-24: FOCUS-001 was answered and accepted.**

    This test previously asserted the record was PENDING with every reviewer field
    null. That expectation was correct until a reviewer supplied a decision; keeping
    it would now assert the project had not progressed. What it checks instead is the
    property that actually matters and holds in both states: a record must never be
    half-attributed. Either nobody has answered and every field is null, or someone
    has and every field is populated.

    The answer was `LEAVE_C03_NOT_ADJUDICABLE`, which resolves the gate without
    making 42 CFR 410.32 admissible - see `test_the_answer_did_not_unblock_the_policy`.
    """
    assert decision["status"] == "ACCEPTED"
    assert decision["is_resolved"] is True
    assert decision["blocks_production"] is False
    for field in (
        "reviewer_identity",
        "reviewer_qualification",
        "reviewer_decision",
        "reviewer_rationale",
        "review_timestamp",
        "submitted_at",
        "accepted_at",
        "accepted_by",
    ):
        assert decision[field], f"{field} is empty on an ACCEPTED record"
    assert decision["reviewer_decision"] in decision["permitted_decisions"]
    assert decision["accepted_at"] >= decision["submitted_at"]


def test_the_relaxed_control_is_visible_on_the_record(decision: dict[str, Any]) -> None:
    """This decision was accepted by its own submitter under the ADR-026 exemption.

    That is permitted and it is not free: the record says so on its face. A reader
    who did not know the project's circumstances can still see that the
    independent-acceptance control did not hold here.
    """
    if decision["accepted_by"] == decision["reviewer_identity"]:
        assert decision["separation_of_duties"] == "SINGLE_PARTY_EXEMPTED"
        assert any("ADR-026" in note for note in decision["notes"])
    else:
        assert decision["separation_of_duties"] == "TWO_PARTY"


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
    # **2026-08-25: v3 was scored and the gate flipped to READY.** This asserted
    # NOT_READY, which was a fact about the corpus rather than about the gate. What
    # it guards now holds either way: the status and the ready-set list must agree,
    # and a set may only be listed ready if it passes BOTH conditions.
    assert readiness["status"] in {"RETRIEVAL_BENCHMARK_READY", "RETRIEVAL_BENCHMARK_NOT_READY"}
    ready = readiness["ready_sets"]
    if readiness["status"] == "RETRIEVAL_BENCHMARK_NOT_READY":
        assert ready == []
        assert "manufacture a result" in readiness["note"]
    else:
        assert ready, "READY with no ready set is the 'close enough' this refuses"
        by_set = {e["set"]: e for e in readiness["assessment"]}
        for name in ready:
            assert by_set[name]["checks"]["provenance_clean"] is True
            assert by_set[name]["checks"]["discriminates_between_arms"] is True
            assert by_set[name]["checks"]["has_been_scored"] is True


def test_readiness_requires_both_clean_provenance_and_discrimination(
    readiness: dict[str, Any],
) -> None:
    """Each set fails for its own reason, and both reasons are real."""
    by_set = {entry["set"]: entry for entry in readiness["assessment"]}
    # v2 discriminates and is contaminated. That has not changed and is why v3 exists.
    assert "provenance_clean" in by_set["retrieval_v2"]["failed_checks"]
    assert by_set["retrieval_v2"]["checks"]["discriminates_between_arms"] is True
    # v3 is clean. **2026-08-25: it has now also been scored**, so it no longer fails
    # `has_been_scored` - the check the earlier version asserted it failed.
    assert by_set["retrieval_v3"]["checks"]["provenance_clean"] is True
    assert by_set["retrieval_v3"]["failed_checks"] == [] or (
        "has_been_scored" in by_set["retrieval_v3"]["failed_checks"]
    ), "v3 must be either clean-and-scored or explicitly unscored, never in between"


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
    """READY or BLOCKED. There is no "close enough".

    **2026-08-24: the gate went READY** when 42 CFR 410.33's logic was declared.
    This previously asserted BLOCKED, which was a fact about the corpus rather than
    about the gate. What it guards now cannot go stale: the two states are the only
    ones, and each must agree with the designated slice. A READY report naming no
    slice, or a BLOCKED one naming a slice, is the "close enough" this refuses.
    """
    assert admissibility["status"] in {"READY", "BLOCKED"}
    if admissibility["status"] == "READY":
        assert admissibility["designated_slice"] in admissibility["admissible"]
    else:
        assert admissibility["designated_slice"] is None


def test_the_gate_follows_the_decision_record_rather_than_computing_it(
    admissibility: dict[str, Any], decision: dict[str, Any]
) -> None:
    """The gate reads the decision record; it does not compute the answer.

    **The world changed on 2026-08-24.** This previously asserted the check was
    False because FOCUS-001 was open. The link it was really testing - that
    `domain_decisions_resolved` tracks the record and nothing else - is now testable
    in the more convincing direction: the check flipped to True the moment a
    reviewer's answer was accepted, with no code change.
    """
    candidate = next(
        c
        for c in admissibility["assessment"]
        if c["policy_id"] == decision["policy_id"]
        and c["policy_version"] == decision["policy_version"]
    )
    assert candidate["checks"]["domain_decisions_resolved"] is decision["is_resolved"]


def test_the_answer_did_not_unblock_the_policy(
    admissibility: dict[str, Any], decision: dict[str, Any]
) -> None:
    """`LEAVE_C03_NOT_ADJUDICABLE` resolves the question without making the policy
    adjudicable, and the impact table said so before the answer was given.

    Worth asserting explicitly: resolving a domain decision and unblocking a policy
    are different things, and a gate that conflated them would have reported 410.32
    admissible the moment any answer arrived.
    """
    assert decision["reviewer_decision"] == "LEAVE_C03_NOT_ADJUDICABLE"
    candidate = next(
        c
        for c in admissibility["assessment"]
        if c["policy_id"] == decision["policy_id"]
        and c["policy_version"] == decision["policy_version"]
    )
    assert candidate["checks"]["domain_decisions_resolved"] is True
    assert candidate["checks"]["no_unresolved_dependency"] is False
    assert not candidate["admissible"]
    # The gate as a whole may now be READY on a DIFFERENT policy - 410.33 was
    # declared on 2026-08-24. That is the point rather than a complication: the
    # policy FOCUS-001 was about is still refused, and the slice went elsewhere.
    assert admissibility["designated_slice"] != candidate["policy_identity"]


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
    # **2026-08-25: one scoring was spent** by the frozen 410.33 experiment. The
    # cases stay byte-identical; the budget counter is meant to move.
    budget = manifest["scoring_budget"]
    assert budget["scorings_spent"] <= budget["allowed_scorings"]
    assert len(budget.get("spent_by", [])) == budget["scorings_spent"]
    assert len(_jsonl(GOLD)) == 156
    assert len(_jsonl(SYNTHETIC)) == 222


def test_a_gold_v2_exists_and_says_what_forced_it() -> None:
    """Phase 16 note: the expectation changed because the world did.

    This asserted that NO gold_v2 existed - correct while the only thing that could
    have forced one was an FOCUS-001 outcome nobody had chosen. R-97 forced one
    instead: eighteen gold_v1 cases carry an applicability label unreachable from
    their own structured input, which no relabelling of gold_v1 could fix because
    gold_v1 is frozen.

    What the test defends is unchanged - a gold version must never appear quietly -
    so it now checks the reason rather than the absence.
    """
    versions = sorted((REPO / "data/gold/cases").glob("gold_v[2-9].jsonl"))
    assert versions, "gold_v2 should exist as of Phase 16"
    for candidate in versions:
        manifest = candidate.parent.parent / "manifests" / f"{candidate.stem}.manifest.json"
        spec = json.loads(manifest.read_text(encoding="utf-8"))
        assert spec["supersedes"] == "gold_v1"
        assert "R-97" in spec["resolves"]
        assert len(spec["supersedes_reason"]) > 100, "the reason must be a reason, not a label"
        assert spec["derived_from"]["immutable"] is True
