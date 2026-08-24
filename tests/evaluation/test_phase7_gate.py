"""Phase 7: the pre-agent gate. Source verification is not qualified review.

The single failure this file exists to prevent: **engineering work being mistaken
for a review decision.** Phase 7 transcribed 42 CFR 410.32(b)(3) and span-verified
it, which is real progress and closes nothing. Every test below is a way of making
that distinction hold under pressure.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
import yaml

from app.core.verification import (
    DependencyResolution,
    QualifiedReviewStatus,
    SourceVerification,
    VerificationRecord,
)

pytestmark = pytest.mark.evaluation

REPO = Path(__file__).resolve().parents[2]
CRITERIA = REPO / "data/criteria/inventory.jsonl"
VERIFICATION = REPO / "data/criteria/verification.json"
MATRIX = REPO / "data/criteria/coverage_matrix.jsonl"
DEPENDENCIES = REPO / "data/review/policy_dependencies.json"
ADMISSIBILITY = REPO / "data/review/slice_admissibility.json"
FOCUSED = REPO / "data/review/focused_review.jsonl"
PROVENANCE = REPO / "data/review/evaluation_provenance.json"
V2 = REPO / "eval/datasets/retrieval_v2/questions.yaml"
V3 = REPO / "eval/datasets/retrieval_v3/questions.yaml"
GOLD = REPO / "data/gold/cases/gold_v1.jsonl"
GOLD_MANIFEST = REPO / "data/gold/manifests/gold_v1.manifest.json"

C03 = "42_CFR_410_32_2026_08_13_C03"
C07 = "42_CFR_410_32_2026_08_13_C07"
C08 = "42_CFR_410_32_2026_08_13_C08"


def _jsonl(path: Path) -> list[dict[str, Any]]:
    return [
        json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()
    ]


# ---------------------------------------------------------------------------
# 410.32(b)(3) transcription
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def criteria() -> dict[str, dict[str, Any]]:
    return {c["criterion_id"]: c for c in _jsonl(CRITERIA)}


def test_b3_is_transcribed_and_span_verified(criteria: dict[str, dict[str, Any]]) -> None:
    """The baseline requirement, located in the authoritative source.

    Its text is the FLOOR - "at least a general level of supervision" - not the
    applicable level, and the interpretation must say so, because a criterion that
    reads as "the applicable level" while carrying the floor would be silently
    wrong in the permissive direction.
    """
    record = criteria[C07]
    assert record["authoritative_text"] == (
        "must be furnished under at least a general level of supervision"
    )
    assert record["criterion_type"] == "REQUIRED"
    assert record["source_section"] == "Paragraph (b)"
    assert record["policy_version"] == "2026-08-13"
    assert record["source_span"][1] > record["source_span"][0]
    assert record["provenance"].startswith("authoritative-source")
    assert "FLOOR" in record["normalized_interpretation"]
    assert "physician fee schedule" in record["normalized_interpretation"]


def test_the_b4_exception_is_transcribed_as_an_exception(
    criteria: dict[str, dict[str, Any]],
) -> None:
    """(b)(4) lets RRA/RPA-performed tests substitute direct for personal.

    An EXCEPTION_CONDITION, not a requirement: failing it does not deny, it means
    the ordinary supervision level governs. Typed as REQUIRED it would become an
    extra hurdle, which is the opposite of what the regulation does.
    """
    record = criteria[C08]
    assert record["criterion_type"] == "EXCEPTION_CONDITION"
    assert record["policy_id"] == "42 CFR 410.32"


def test_the_span_gate_passed_with_no_failures() -> None:
    report = json.loads(VERIFICATION.read_text(encoding="utf-8"))
    assert report["passed"] is True
    assert report["failures"] == []
    assert report["criteria_verified"] == report["criteria_written"]


def test_every_criterion_carries_complete_source_provenance(
    criteria: dict[str, dict[str, Any]],
) -> None:
    """A citation whose derived fields cannot be joined is not verifiable."""
    for criterion_id, record in criteria.items():
        assert record["source_url"], criterion_id
        assert record["source_section"], criterion_id
        assert record["document_sha256"], criterion_id
        assert record["source_span"], criterion_id


# ---------------------------------------------------------------------------
# Source verification is not qualified review
# ---------------------------------------------------------------------------


def test_the_two_axes_are_separate_vocabularies() -> None:
    """No value appears in both, so neither can be read as the other."""
    source = {s.value for s in SourceVerification}
    review = {r.value for r in QualifiedReviewStatus}
    assert not source & review
    assert "SOURCE_VERIFIED" not in review
    assert "QUALIFIED_REVIEWED" not in source


def test_clinical_validation_has_no_member_anywhere() -> None:
    """Deliberately unrepresentable.

    A member for it would invite someone to set it, and nothing in this project is
    close to establishing it.
    """
    everything = (
        {s.value for s in SourceVerification}
        | {r.value for r in QualifiedReviewStatus}
        | {d.value for d in DependencyResolution}
    )
    assert not any("CLINICAL" in value for value in everything)


def test_a_settled_review_must_name_its_reviewer() -> None:
    """A review nobody signed cannot be attributed or revisited."""
    for status in (
        QualifiedReviewStatus.QUALIFIED_REVIEWED,
        QualifiedReviewStatus.QUALIFIED_REVIEW_REJECTED,
        QualifiedReviewStatus.QUALIFIED_REVIEW_INCONCLUSIVE,
    ):
        with pytest.raises(ValueError, match="no reviewer identity"):
            VerificationRecord(subject_id="x", review=status)


def test_source_verification_alone_does_not_permit_adjudication() -> None:
    """The central Phase 7 property.

    Transcribing a provision moves its dependency from UNRESOLVED to source-verified
    and no further. Treating transcription as permission would let engineering close
    a review question by doing engineering work.
    """
    assert not DependencyResolution.SOURCE_VERIFIED_REVIEW_PENDING.permits_adjudication
    assert not DependencyResolution.PARTIALLY_RESOLVABLE_FROM_SOURCE.permits_adjudication
    assert not DependencyResolution.UNRESOLVED.permits_adjudication
    assert DependencyResolution.RESOLVED.permits_adjudication

    record = VerificationRecord(subject_id=C07, source=SourceVerification.SOURCE_VERIFIED)
    assert record.is_source_verified
    assert not record.is_qualified_reviewed
    assert record.summary == "SOURCE_VERIFIED / QUALIFIED_REVIEW_PENDING"


# ---------------------------------------------------------------------------
# C03 dependency
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def dependencies() -> dict[str, Any]:
    return json.loads(DEPENDENCIES.read_text(encoding="utf-8"))["dependencies"]


def test_c03_is_still_not_independently_adjudicable(dependencies: dict[str, Any]) -> None:
    """Transcription did not close it, and the record says exactly why.

    Part of what C03 needs - which supervision level applies to a given test - is
    set by the physician fee schedule and is not in 42 CFR at all. No amount of
    transcribing this regulation reaches it.
    """
    entry = dependencies[C03]
    assert entry["independently_adjudicable"] is False
    dependency = entry["depends_on"][0]
    assert dependency["resolution"] == "PARTIALLY_RESOLVABLE_FROM_SOURCE"
    assert "physician fee schedule" in dependency["resolution_basis"]
    assert dependency["paragraph_path"] == "(b)(3)"


def test_a_dependency_closes_only_when_a_reviewer_closes_it(
    dependencies: dict[str, Any],
) -> None:
    """No dependency in the corpus is RESOLVED, because none has been reviewed."""
    resolutions = {d["resolution"] for entry in dependencies.values() for d in entry["depends_on"]}
    assert "RESOLVED" not in resolutions


# ---------------------------------------------------------------------------
# Admissibility gate
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def admissibility() -> dict[str, Any]:
    return json.loads(ADMISSIBILITY.read_text(encoding="utf-8"))


def test_the_gate_still_blocks_410_32_on_the_dependency(
    admissibility: dict[str, Any],
) -> None:
    """The gate was not altered to obtain a pass.

    Transcribing (b)(3) is exactly the kind of progress that tempts a loosened
    check. 410.32 must still fail, and on the same condition.
    """
    assert admissibility["designated_slice"] is None
    assert admissibility["nearest_candidate"] == "REGULATION:42 CFR 410.32:2026-08-13"
    # Phase 8 note: the gate gained a `domain_decisions_resolved` condition, which
    # FOCUS-001 also failed while it was PENDING.
    #
    # **2026-08-24: the world changed.** FOCUS-001 was answered
    # `LEAVE_C03_NOT_ADJUDICABLE` and accepted, so `domain_decisions_resolved` now
    # passes. The dependency blocker did NOT clear, because that answer leaves C03
    # as written - which is what the impact table predicted before the answer
    # existed. The original point of this test survives intact and is now sharper:
    # a domain decision landed, and the gate still refuses the policy on the
    # engineering condition it always refused it on.
    assert admissibility["nearest_candidate_blockers"] == ["no_unresolved_dependency"]


def test_only_the_focus_001_decision_blocks_the_nearest_candidate(
    admissibility: dict[str, Any],
) -> None:
    """Everything except the C03 dependency passes for 42 CFR 410.32.

    Phase 8 note: the count moved from 6-of-7 to 9-of-11 because the gate grew four
    conditions and FOCUS-001 failed two of them.

    **2026-08-24: the world changed.** FOCUS-001 is accepted, so it is down to one
    failing condition - the unresolved dependency on the per-test supervision level,
    which the accepted answer deliberately leaves open. The substance this asserts is
    unchanged: exactly one thing blocks this policy, it traces to C03, and there is
    no engineering blocker hiding among the rest.
    """
    nearest = next(
        c
        for c in admissibility["assessment"]
        if c["policy_identity"] == admissibility["nearest_candidate"]
    )
    failing = set(nearest["failed_checks"])
    assert failing == {"no_unresolved_dependency"}
    assert len([name for name, ok in nearest["checks"].items() if ok]) == len(
        nearest["checks"]
    ) - len(failing)
    assert nearest["blocked_criteria"] == [C03]


# ---------------------------------------------------------------------------
# gold_v1
# ---------------------------------------------------------------------------


def test_gold_v1_is_byte_identical() -> None:
    """Phase 7 added criteria, changed adjudicability and derived a new eval set.

    None of that may touch a frozen dataset.
    """
    import hashlib

    manifest = json.loads(GOLD_MANIFEST.read_text(encoding="utf-8"))
    assert manifest["sha256"]["gold"] == hashlib.sha256(GOLD.read_bytes()).hexdigest()
    assert manifest["frozen"] is True
    assert manifest["scoring_budget"]["scorings_spent"] == 0
    assert len(_jsonl(GOLD)) == 156


def test_no_gold_case_references_a_criterion_added_in_phase_7() -> None:
    """The additions are additive: no existing case's meaning changed."""
    referenced = {
        entry["criterion_id"] for case in _jsonl(GOLD) for entry in case["expected"]["criteria"]
    }
    assert not referenced & {C07, C08}


# ---------------------------------------------------------------------------
# Evaluation provenance and the v3 repair
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def provenance() -> dict[str, Any]:
    return json.loads(PROVENANCE.read_text(encoding="utf-8"))


def test_every_query_carries_a_provenance_chain(provenance: dict[str, Any]) -> None:
    """query -> policy -> version -> criterion -> evidence, or a classification."""
    for block in provenance["sets"].values():
        assert block["entries"]
        for entry in block["entries"]:
            assert entry["classification"] in {
                "VALID_AUTHORITATIVE",
                "VALID_HUMAN_CURATED",
                "INVALID_INFERRED",
                "REQUIRES_REVIEW",
            }
            assert "chain" in entry
            if entry["classification"].startswith("VALID"):
                assert not entry["reasons"]
            else:
                assert entry["reasons"], entry["id"]


def test_inferred_linkage_queries_are_flagged_not_repaired(
    provenance: dict[str, Any],
) -> None:
    """410.61 is reachable only through inferred links, which production refuses.

    Those queries are marked INVALID_INFERRED and left exactly where they are. The
    links are NOT restored to recover them - reinstating a refused link to make an
    evaluation look better would be exactly backwards.
    """
    entries = provenance["sets"]["retrieval_v2"]["entries"]

    # EVERY query targeting 410.61 must be caught, not merely some query somewhere.
    # An earlier version asserted only that the invalid set was non-empty, and a
    # mutation reclassifying 11 of 12 left one survivor and passed.
    targets = [e for e in entries if e["chain"]["intended_policy"] == "42 CFR 410.61"]
    assert targets, "no query targets 410.61; the fixture proves nothing"
    for entry in targets:
        assert entry["classification"] == "INVALID_INFERRED", (
            f"{entry['id']} targets 42 CFR 410.61, which is reachable only through "
            "ENGINEERING_INFERRED links that production refuses, yet it is "
            f"classified {entry['classification']}"
        )

    # Positive control: most queries are NOT invalid, so the classifier is not
    # simply rejecting everything.
    valid = [e for e in entries if e["classification"].startswith("VALID")]
    assert len(valid) > len(targets)
    assert "NOT repaired here" in provenance["note"]


def test_v2_is_untouched_by_the_repair() -> None:
    """A historical artefact records what was measured against it.

    Editing v2 would make its committed report describe a set that no longer
    exists.
    """
    spec = yaml.safe_load(V2.read_text(encoding="utf-8"))
    assert str(spec["version"]) == "2"
    assert len(spec["questions"]) == 52


def test_v3_is_derived_by_provenance_and_records_its_exclusions() -> None:
    """Selection is on provenance, computed before any arm ran - never on results."""
    spec = yaml.safe_load(V3.read_text(encoding="utf-8"))
    assert str(spec["version"]) == "3"
    assert spec["derived_from"].endswith("retrieval_v2/questions.yaml")
    assert "provenance only" in spec["selection_basis"]
    assert "scoring badly" in spec["selection_basis"]
    assert spec["excluded_from_v2"]
    for excluded in spec["excluded_from_v2"]:
        assert excluded["classification"] in {"INVALID_INFERRED", "REQUIRES_REVIEW"}
        assert excluded["reason"]


def test_v3_contains_no_query_that_cannot_resolve_in_production() -> None:
    """The point of the repair, asserted against the audit rather than assumed."""
    audit = json.loads(PROVENANCE.read_text(encoding="utf-8"))["sets"]["retrieval_v2"]
    verdicts = {entry["id"]: entry["classification"] for entry in audit["entries"]}
    spec = yaml.safe_load(V3.read_text(encoding="utf-8"))
    for question in spec["questions"]:
        assert verdicts[question["id"]].startswith("VALID"), question["id"]


def test_v3_has_never_been_scored() -> None:
    """No number from v2's report may be attributed to it - denominators differ."""
    spec = yaml.safe_load(V3.read_text(encoding="utf-8"))
    assert spec["scored"] is False
    assert "NEVER been scored" in spec["scoring_note"]
    reports = list((REPO / "eval" / "reports").glob("*retrieval-v3*"))
    assert not reports, f"v3 claims to be unscored but a report exists: {reports}"


def test_v3_retains_every_query_category() -> None:
    """An exclusion that removed a whole category would silently narrow what the
    benchmark can detect - negative queries most of all."""
    v2_spec = yaml.safe_load(V2.read_text(encoding="utf-8"))
    v3_spec = yaml.safe_load(V3.read_text(encoding="utf-8"))
    v2_categories = {q["category"] for q in v2_spec["questions"]}
    v3_categories = {q["category"] for q in v3_spec["questions"]}
    assert v2_categories == v3_categories


# ---------------------------------------------------------------------------
# Focused review package
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def focused() -> list[dict[str, Any]]:
    return _jsonl(FOCUSED)


def test_the_focused_review_owns_the_b3_question(focused: list[dict[str, Any]]) -> None:
    """The gap this package exists to fill.

    Transcribing (b)(3) reclassified it out of the OD-19 queue while the dependency
    it blocks stayed open - so the question it left behind had nowhere to live.
    Exactly one priority-1 item, and it is that question.
    """
    priority_one = [row for row in focused if row["priority"] == 1]
    assert len(priority_one) == 1
    row = priority_one[0]
    assert row["source"]["policy_id"] == "42 CFR 410.32"
    assert row["source"]["hierarchy_path"] == "(b)(3)"
    assert row["criterion"]["criterion_id"] == C03
    assert "adjudicat" in row["review_question"], (
        "the priority-1 question must be about whether C03 can be adjudicated, not "
        "about whether the provision should be transcribed - that part is done"
    )
    assert len(row["answer_options"]) >= 3


def test_the_focused_package_is_unpopulated(focused: list[dict[str, Any]]) -> None:
    for row in focused:
        assert row["review_status"] == "PENDING", row["review_id"]
        assert row["reviewer_decision"] is None
        assert row["reviewer_id"] is None
        assert row["reviewed_at"] is None


def test_every_focused_item_carries_its_exact_text_and_a_reason(
    focused: list[dict[str, Any]],
) -> None:
    """A reviewer must not have to go and find what they are ruling on."""
    provisions = {p["provision_id"] for p in _jsonl(MATRIX)}
    for row in focused:
        assert row["exact_text"].strip()
        assert row["why_this_is_asked"].strip()
        assert row["review_question"].strip()
        assert row["source"]["provision_id"] in provisions
