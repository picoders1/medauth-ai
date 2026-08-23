"""Phase 4 guards: policy logic inventory, retrieval v2, the OD-19 package, leakage.

These check *artefacts*, not code. Each one exists because the artefact makes a
claim that could quietly stop being true - a benchmark losing its negative queries,
a review form acquiring pre-filled answers, a frozen gold set changing by a byte.

The gold-set tests are the strictest here on purpose. gold_v1 is a frozen record of
a completed construction; editing it in place destroys the ability to say what any
earlier measurement was measured against.
"""

from __future__ import annotations

import hashlib
import json
import random
from collections import Counter
from pathlib import Path
from typing import Any

import pytest
import yaml

from eval.runners.retrieval_v2 import GAIN, load_questions_v2, ndcg

pytestmark = pytest.mark.evaluation

REPO = Path(__file__).resolve().parents[2]
GOLD = REPO / "data/gold/cases/gold_v1.jsonl"
GOLD_MANIFEST = REPO / "data/gold/manifests/gold_v1.manifest.json"
INVENTORY = REPO / "data/criteria/inventory.jsonl"
LOGIC_INVENTORY = REPO / "data/policy_logic/inventory.json"
RETRIEVAL_V1 = REPO / "eval/datasets/retrieval/questions.yaml"
RETRIEVAL_V2 = REPO / "eval/datasets/retrieval_v2/questions.yaml"
REVIEW_PACKAGE = REPO / "data/review/od19_review_package.jsonl"
REVIEW_SUMMARY = REPO / "data/review/od19_summary.json"
LEAKAGE = REPO / "data/review/leakage_audit.json"


def _jsonl(path: Path) -> list[dict[str, Any]]:
    return [
        json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()
    ]


# ---------------------------------------------------------------------------
# gold_v1 immutability
# ---------------------------------------------------------------------------


def test_gold_v1_is_byte_identical_to_its_manifest() -> None:
    """The frozen set must not have changed by a single byte.

    Phase 4 added two criteria, changed the decision engine and reclassified a
    provision. None of that may touch gold_v1: a corrected label ships as gold_v2
    with a recorded reason, because editing a frozen split in place erases what
    every earlier measurement was measured against.
    """
    manifest = json.loads(GOLD_MANIFEST.read_text(encoding="utf-8"))
    assert manifest["frozen"] is True
    assert manifest["sha256"]["gold"] == hashlib.sha256(GOLD.read_bytes()).hexdigest()


def test_gold_v1_still_declares_zero_scorings_spent() -> None:
    """Phase 4 measured retrieval, never the gold set. The budget must show it."""
    manifest = json.loads(GOLD_MANIFEST.read_text(encoding="utf-8"))
    assert manifest["scoring_budget"]["scorings_spent"] == 0


def test_no_gold_v2_exists_without_a_recorded_reason() -> None:
    """A second gold version may exist only with the reason that forced it.

    Creating gold_v2 quietly would let a relabelling look like a regeneration.
    """
    for candidate in (REPO / "data/gold/cases").glob("gold_v[2-9].jsonl"):
        manifest = candidate.parent.parent / "manifests" / f"{candidate.stem}.manifest.json"
        assert manifest.exists(), f"{candidate.name} has no manifest"
        spec = json.loads(manifest.read_text(encoding="utf-8"))
        assert spec.get("supersedes_reason"), f"{candidate.name} does not say why it exists"


# ---------------------------------------------------------------------------
# Policy logic inventory
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def logic_inventory() -> dict[str, Any]:
    return json.loads(LOGIC_INVENTORY.read_text(encoding="utf-8"))


def test_every_policy_version_has_a_logic_form(logic_inventory: dict[str, Any]) -> None:
    valid = {"DECLARED", "ASSUMED_CONJUNCTION", "REVIEW_REQUIRED", "NO_CRITERIA"}
    policies = logic_inventory["policies"]
    assert policies
    for row in policies:
        assert row["logic_form"] in valid, row


def test_policies_with_exception_language_are_not_assumed_conjunctive(
    logic_inventory: dict[str, Any],
) -> None:
    """A signal without a declaration must produce doubt, not a default.

    This is the generalisation of the 410.32 defect: the engine applied a
    conjunction to a policy that had an exception in it. Wherever that wording
    appears again and no logic has been declared, the inventory must say
    REVIEW_REQUIRED rather than quietly assuming the same shape.
    """
    for row in logic_inventory["policies"]:
        if row["logic_form"] != "ASSUMED_CONJUNCTION":
            continue
        assert not row["signals"], (
            f"{row['policy_id']} {row['policy_version']} carries "
            f"{sorted(row['signals'])} language and is still assumed conjunctive"
        )


def test_at_least_one_policy_is_declared(logic_inventory: dict[str, Any]) -> None:
    """410.32 must be declared, or the exception fix is not actually wired in."""
    declared = [r for r in logic_inventory["policies"] if r["logic_form"] == "DECLARED"]
    assert declared
    assert any(r["policy_id"] == "42 CFR 410.32" for r in declared)


def test_unresolved_semantics_are_recorded_for_every_policy(
    logic_inventory: dict[str, Any],
) -> None:
    for row in logic_inventory["policies"]:
        assert row["unresolved_semantics"], row["policy_id"]


def test_assumed_conjunction_is_not_presented_as_confirmed(
    logic_inventory: dict[str, Any],
) -> None:
    """The summary must say what a lexical scan can and cannot establish."""
    note = logic_inventory["note"].lower()
    assert "not classifications" in note or "not confirmed" in note
    assert "cannot read meaning" in note


# ---------------------------------------------------------------------------
# Retrieval evaluation v2
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def v2() -> dict[str, Any]:
    return yaml.safe_load(RETRIEVAL_V2.read_text(encoding="utf-8"))


REQUIRED_CATEGORIES = {
    "DIRECT",
    "PARAPHRASED",
    "PARTIAL_INFORMATION",
    "AMBIGUOUS",
    "NEGATIVE",
    "HISTORICAL_VERSION",
    "EXCEPTION",
    "DISTRACTOR",
    "CROSS_POLICY",
    "CROSS_VERSION",
}


def test_every_required_category_is_present(v2: dict[str, Any]) -> None:
    counts = Counter(q["category"] for q in v2["questions"])
    missing = REQUIRED_CATEGORIES - set(counts)
    assert not missing, f"categories with no queries: {sorted(missing)}"
    for category in REQUIRED_CATEGORIES:
        assert counts[category] >= 3, f"{category} has only {counts[category]} queries"


def test_negative_queries_exist_and_declare_no_relevant_section(v2: dict[str, Any]) -> None:
    """The gap v1 could not close: queries with no answer in the corpus.

    A negative query that also named a relevant section would not be negative, so
    the loader rejects that combination and this pins the intent.
    """
    negatives = [q for q in v2["questions"] if q.get("expect_no_relevant")]
    assert len(negatives) >= 5
    for q in negatives:
        assert "expect" not in q or not q["expect"].get("relevance"), q["id"]
        assert q["negative_reason"].strip(), q["id"]


def test_ambiguous_queries_name_two_relevant_sections(v2: dict[str, Any]) -> None:
    ambiguous = [q for q in v2["questions"] if q["category"] == "AMBIGUOUS"]
    assert ambiguous
    for q in ambiguous:
        fully = [r for r in q["expect"]["relevance"] if r["label"] == "RELEVANT"]
        assert len(fully) >= 1, q["id"]
        assert len(q["expect"]["relevance"]) >= 2, q["id"]
        assert q["ambiguity_note"].strip(), q["id"]


def test_temporal_queries_target_a_superseded_revision(v2: dict[str, Any]) -> None:
    """A historical query that resolves to the current revision tests nothing."""
    historical = [q for q in v2["questions"] if q["category"] == "HISTORICAL_VERSION"]
    assert len(historical) >= 4
    for q in historical:
        assert q["expect"]["revision_id"] != "2026-08-13", q["id"]
        assert str(q["as_of"]) < "2026-01-01", q["id"]


def test_cross_version_pairs_share_text_and_differ_only_by_date(v2: dict[str, Any]) -> None:
    """The pair isolates temporal scoping by holding everything else constant."""
    by_id = {q["id"]: q for q in v2["questions"]}
    pairs = [q for q in v2["questions"] if q["category"] == "CROSS_VERSION"]
    assert len(pairs) >= 4
    for q in pairs:
        other = by_id[q["pairs_with"]]
        assert other["text"] == q["text"], q["id"]
        assert other["procedure_code"] == q["procedure_code"], q["id"]
        assert other["as_of"] != q["as_of"], q["id"]
        assert other["expect"]["revision_id"] != q["expect"]["revision_id"], q["id"]


def test_exception_queries_target_the_410_32_exception(v2: dict[str, Any]) -> None:
    """The provision whose absence produced the Phase 3 decision defect."""
    targeted = {
        q["expect"].get("criterion_id")
        for q in v2["questions"]
        if q["category"] in {"EXCEPTION", "PARAPHRASED"} and "expect" in q
    }
    assert "42_CFR_410_32_2026_08_13_C05" in targeted
    assert "42_CFR_410_32_2026_08_13_C06" in targeted


#: Criteria transcribed AFTER retrieval_eval_v2 was frozen. A frozen set cannot
#: cover a criterion that did not exist when it was authored, and editing it to add
#: one would destroy the record of what its committed report measured.
#:
#: Listed explicitly rather than computed, so the exemption stays a tripwire: a
#: query REMOVED from v2 still fails this test.
CRITERIA_ADDED_AFTER_V2 = frozenset(
    {
        "42_CFR_410_32_2026_08_13_C07",  # Phase 7: (b)(3) supervision baseline
        "42_CFR_410_32_2026_08_13_C08",  # Phase 7: (b)(4) RRA/RPA exception
    }
)


def test_every_criterion_is_covered_by_at_least_one_query(v2: dict[str, Any]) -> None:
    """v1 left 12 of 33 uncovered; a criterion with no query cannot fail.

    Phase 7 note: two criteria were transcribed from 42 CFR 410.32(b)(3) and (b)(4)
    after v2 was frozen. v2 is not edited to cover them - a frozen set records what
    was measured, and adding queries would make its committed report describe a
    different set. They are recorded as an explicit gap for the next benchmark
    version instead, and the exemption is a literal list so a query DELETED from v2
    still fails here.
    """
    known = {c["criterion_id"] for c in _jsonl(INVENTORY)}
    targeted = {
        q["expect"]["criterion_id"]
        for q in v2["questions"]
        if "expect" in q and q["expect"].get("criterion_id")
    }
    uncovered = known - targeted - CRITERIA_ADDED_AFTER_V2
    assert not uncovered, f"uncovered criteria: {sorted(uncovered)}"
    assert CRITERIA_ADDED_AFTER_V2 <= known, (
        "the post-v2 exemption names a criterion that no longer exists; it is a "
        "record of a real gap, not a permanent allowance"
    )


def test_every_query_states_why_it_exists(v2: dict[str, Any]) -> None:
    """A question with no reason to exist is padding, and padding inflates a
    denominator - which makes every rate in the report look better founded than it
    is."""
    for q in v2["questions"]:
        assert q["reason_for_inclusion"].strip(), q["id"]
        assert len(q["reason_for_inclusion"].split()) >= 8, q["id"]


def test_relevance_labels_are_explicit_and_valid(v2: dict[str, Any]) -> None:
    for q in v2["questions"]:
        for entry in q.get("expect", {}).get("relevance", []):
            assert entry["label"] in GAIN, (q["id"], entry)


def test_queries_are_not_copied_from_the_text_they_target(v2: dict[str, Any]) -> None:
    """A query lifted from its target measures string matching.

    Bounded on content words only; shared function words are unavoidable.
    """
    stop = {
        "a",
        "an",
        "the",
        "is",
        "are",
        "do",
        "does",
        "for",
        "of",
        "to",
        "in",
        "on",
        "and",
        "or",
        "be",
        "have",
        "has",
        "must",
        "we",
        "it",
        "that",
        "this",
        "with",
        "if",
        "can",
        "what",
        "when",
        "which",
        "any",
        "before",
        "at",
        "by",
        "under",
        "was",
        "were",
        "still",
        "there",
        "how",
        "who",
        "our",
        "not",
    }
    criteria = {c["criterion_id"]: c for c in _jsonl(INVENTORY)}
    for q in v2["questions"]:
        cid = q.get("expect", {}).get("criterion_id")
        if not cid:
            continue
        target = criteria[cid].get("authoritative_text", "")
        qw = {w.strip(".,?()'\";:").lower() for w in q["text"].split()} - stop
        tw = {w.strip(".,?()'\";:").lower() for w in target.split()} - stop
        if not qw:
            continue
        overlap = len(qw & tw) / len(qw)
        if overlap >= 0.8:
            # A one- or two-word query has no room to differ from its target, and
            # demanding that it does would force padding into a query whose whole
            # point is being underspecified. The exemption is narrow: it applies
            # only to the two categories that are deliberately terse, and only
            # when the query is actually that short.
            assert len(qw) < 4 and q["category"] in {
                "PARTIAL_INFORMATION",
                "AMBIGUOUS",
            }, f"{q['id']} is {overlap:.0%} lifted from its target"


def test_v2_does_not_reuse_a_single_v1_query(v2: dict[str, Any]) -> None:
    """Independence: v2 must be a new measurement, not v1 with additions."""
    v1_texts = {
        q["text"].strip().lower()
        for q in yaml.safe_load(RETRIEVAL_V1.read_text(encoding="utf-8"))["questions"]
    }
    shared = [q["id"] for q in v2["questions"] if q["text"].strip().lower() in v1_texts]
    assert not shared, f"v2 reuses v1 queries: {shared}"


def test_v1_is_not_modified_by_the_existence_of_v2() -> None:
    """v1 keeps its own version marker; its numbers stay attached to it."""
    v1 = yaml.safe_load(RETRIEVAL_V1.read_text(encoding="utf-8"))
    assert str(v1["version"]) == "3"


def test_the_dataset_loads_through_the_runner(v2: dict[str, Any]) -> None:
    """Schema validity, enforced by the loader that the report actually uses."""
    questions = load_questions_v2(RETRIEVAL_V2)
    assert len(questions) == len(v2["questions"])


# ---------------------------------------------------------------------------
# nDCG cannot exceed 1
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("seed", range(50))
def test_ndcg_never_exceeds_one(seed: int) -> None:
    """The v1 bug, fuzzed.

    v1 assumed exactly one relevant chunk, so a query whose target section spanned
    several produced an ideal DCG that was too small and an nDCG above 1.0. That
    impossibility was the only reason the defect was noticed at all. Here the ideal
    is the same multiset as the gains, so the bound holds by construction - this
    checks the construction, over random graded rankings including degenerate ones.
    """
    rng = random.Random(seed)
    gains = [rng.choice([0, 0, 1, 2]) for _ in range(rng.randint(1, 12))]
    for k in (1, 3, 5, 10):
        value = ndcg(gains, k)
        assert 0.0 <= value <= 1.0, (gains, k, value)


def test_ndcg_is_one_for_a_perfect_ranking() -> None:
    assert ndcg([2, 2, 1, 0], 5) == 1.0
    assert ndcg([2], 5) == 1.0


def test_ndcg_penalises_a_reversed_ranking() -> None:
    assert ndcg([0, 1, 2], 5) < ndcg([2, 1, 0], 5)


def test_ndcg_of_an_all_zero_ranking_is_zero_not_undefined() -> None:
    """Negative queries produce exactly this, so it must not divide by zero."""
    assert ndcg([0, 0, 0], 5) == 0.0


# ---------------------------------------------------------------------------
# OD-19 reviewer package
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def review_rows() -> list[dict[str, Any]]:
    return _jsonl(REVIEW_PACKAGE)


def test_no_reviewer_decision_is_pre_filled(review_rows: list[dict[str, Any]]) -> None:
    """The package prepares the work; it must not do it.

    A pre-filled decision would let a lexical suggestion become a recorded human
    judgement the moment someone accepted the defaults - which is precisely how an
    unreviewed criterion set would come to look reviewed.
    """
    for row in review_rows:
        assert row["reviewer_decision"] is None, row["provision_id"]
        assert row["reviewer_rationale"] is None, row["provision_id"]
        assert row["reviewer_id"] is None, row["provision_id"]


def test_the_package_covers_every_pending_provision(review_rows: list[dict[str, Any]]) -> None:
    matrix = _jsonl(REPO / "data/criteria/coverage_matrix.jsonl")
    pending = {p["provision_id"] for p in matrix if p["classification"] == "REQUIRES_HUMAN_REVIEW"}
    assert {r["provision_id"] for r in review_rows} == pending


def test_every_row_carries_the_text_and_a_specific_question(
    review_rows: list[dict[str, Any]],
) -> None:
    """A reviewer must not have to go and find the provision they are ruling on."""
    for row in review_rows:
        assert row["authoritative_text"].strip(), row["provision_id"]
        assert row["review_question"].strip(), row["provision_id"]
        assert row["section_path"], row["provision_id"]
        assert set(row["permitted_decisions"]) == {
            "REPRESENT_AS_CRITERION",
            "NON_DECISION_RELEVANT",
            "MERGE_WITH_EXISTING_CRITERION",
            "REQUIRES_POLICY_INTERPRETATION",
            "REQUIRES_CLINICAL_REVIEW",
        }


def test_a_suggested_type_is_labelled_as_a_suggestion(
    review_rows: list[dict[str, Any]],
) -> None:
    """It comes from a word scan and must never read as a finding."""
    for row in review_rows:
        assert "SUGGESTION ONLY" in row["suggestion_basis"], row["provision_id"]


def test_priority_one_is_reserved_for_confirmed_dependencies(
    review_rows: list[dict[str, Any]],
) -> None:
    """Top priority means a transcribed criterion may be unevaluable without it.

    An earlier version of the ranking counted "shares a section with a criterion",
    which put 65 provisions here on a relationship most of them did not have, each
    carrying a review question that asserted a dependency that was not there.
    """
    top = [r for r in review_rows if r["priority"] == 1]
    assert top, "the known 410.32 (b)(3) and 410.38 (d)(1)(ii) dependencies must rank first"
    for row in top:
        assert row["cited_by_criteria"], row["provision_id"]
    paths = {(r["policy_id"], r["paragraph_path"]) for r in top}
    assert ("42 CFR 410.38", "(d)(1)(ii)(A)") in paths, (
        "R-51 - criteria C02/C03 cannot be adjudicated without the order timing"
    )
    # Phase 7 note: 42 CFR 410.32 (b)(3) was here until it was transcribed, which
    # reclassified it to REPRESENTED_CRITERION and dropped it out of this queue -
    # WHILE the dependency it blocks remained unresolved. Transcription quietly
    # retiring a review item is a real gap, and the question it left behind ("does
    # the new criterion make C03 adjudicable?") now lives in the focused review
    # package. `test_the_focused_review_owns_the_b3_question` is what guards it.
    assert ("42 CFR 410.32", "(b)(3)") not in paths


def test_prioritisation_does_not_reduce_the_denominator(
    review_rows: list[dict[str, Any]],
) -> None:
    """Ranking decides what is seen first, never what can be skipped."""
    summary = json.loads(REVIEW_SUMMARY.read_text(encoding="utf-8"))
    assert summary["provisions_awaiting_review"] == len(review_rows)
    assert summary["prefilled_decisions"] == 0
    assert "Nothing here reduces the denominator" in summary["note"]


# ---------------------------------------------------------------------------
# Leakage audit
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def leakage() -> dict[str, Any]:
    return json.loads(LEAKAGE.read_text(encoding="utf-8"))


def test_no_case_appears_in_two_splits(leakage: dict[str, Any]) -> None:
    for name in ("case_id_overlap_between_splits", "note_text_overlap_between_splits"):
        finding = next(f for f in leakage["findings"] if f["check"] == name)
        assert finding["status"] == "PASS", finding


def test_the_recorded_partition_matches_the_split_rule(leakage: dict[str, Any]) -> None:
    finding = next(
        f
        for f in leakage["findings"]
        if f["check"] == "partition_matches_the_deterministic_split_rule"
    )
    assert finding["status"] == "PASS", finding["detail"]


def test_linkage_reuse_is_reported_rather_than_claimed_absent(
    leakage: dict[str, Any],
) -> None:
    """The overlap is unavoidable, so the honest move is to bound what it costs.

    Every resolvable query must use a code the linkage table contains, because no
    other code resolves to anything. The consequence must be stated: resolution
    accuracy on a retrieval set measures the table's self-consistency, not whether
    resolution generalises.
    """
    finding = next(
        f for f in leakage["findings"] if f["check"] == "retrieval_queries_reuse_the_linkage_table"
    )
    assert finding["status"] == "KNOWN_LIMITATION"
    assert "self-consistency" in finding["note"]


def test_retrieval_sets_do_not_reuse_gold_case_text(leakage: dict[str, Any]) -> None:
    finding = next(
        f
        for f in leakage["findings"]
        if f["check"] == "retrieval_query_text_reused_from_gold_cases"
    )
    assert finding["status"] == "PASS", finding["detail"]
