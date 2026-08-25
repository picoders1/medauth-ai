"""gold_v2's structural contract, and gold_v1's immutability. Parts B, K.

The one claim gold_v2 exists to make:

> **Every fact needed to derive a case's expected outcome is in structured data.**
> No ground truth lives only in narrative prose, in fixture behaviour, in a code
> comment or in a test-only assumption.

R-97 was that claim being false for eighteen cases, and it survived four phases
because nothing ever checked it - the runtime asserted `RESOLVED` and a stage that
never runs cannot disagree with a label.

So these tests **re-derive** applicability from the case's input plus the committed
linkage rather than reading the case's own assertion. A file that agrees with itself
is not evidence.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

import pytest
import yaml

pytestmark = pytest.mark.evaluation

REPO = Path(__file__).resolve().parents[2]
GOLD_V1 = REPO / "data/gold/cases/gold_v1.jsonl"
GOLD_V1_MANIFEST = REPO / "data/gold/manifests/gold_v1.manifest.json"
GOLD_V2 = REPO / "data/gold/cases/gold_v2.jsonl"
GOLD_V2_MANIFEST = REPO / "data/gold/manifests/gold_v2.manifest.json"
MIGRATION = REPO / "data/review/gold_v2_migration.json"
LINKAGE = REPO / "data/linkage/policy_code_links.yaml"
NONCOVERED = REPO / "data/linkage/noncovered_code_metadata.jsonl"

#: B1's field list. Asserted as an exact set - a field quietly dropped is a fact
#: quietly moved back into prose.
REQUIRED_INPUT = {
    "patient",
    "requested_service",
    "diagnosis_codes",
    "jurisdiction",
    "date_of_service",
    "clinical_note",
}
REQUIRED_EXPECTED = {
    "policy_type",
    "policy_id",
    "policy_version",
    "policy_title",
    "applicability",
    "criterion_states",
    "criterion_kinds",
    "policy_truth",
    "recommendation",
    "decision_rule",
    "missing_information",
    "evidence_refs",
    "evidence_ground_truth",
    "labelling",
}


@pytest.fixture(scope="module")
def cases() -> list[dict[str, Any]]:
    return [json.loads(line) for line in GOLD_V2.read_text().splitlines() if line.strip()]


@pytest.fixture(scope="module")
def manifest() -> dict[str, Any]:
    return json.loads(GOLD_V2_MANIFEST.read_text())


@pytest.fixture(scope="module")
def covered() -> set[tuple[str, str]]:
    linkage = yaml.safe_load(LINKAGE.read_text())
    return {
        (str(link["code"]), str(link["code_system"]))
        for link in linkage["links"]
        if str(link.get("link_type", "COVERED_PROCEDURE")) == "COVERED_PROCEDURE"
    }


# ---------------------------------------------------------------------------
# gold_v1 is immutable
# ---------------------------------------------------------------------------


def test_gold_v1_is_byte_identical_to_its_manifest() -> None:
    """The migration reads it, hashes it and refuses to run if it moved.

    Checked here as well, because the builder's own guard is only consulted when
    somebody runs the builder.
    """
    digest = hashlib.sha256(GOLD_V1.read_bytes()).hexdigest()
    assert digest == json.loads(GOLD_V1_MANIFEST.read_text())["sha256"]["gold"]


def test_the_migration_records_gold_v1_as_unchanged() -> None:
    migration = json.loads(MIGRATION.read_text())
    assert migration["gold_v1"]["immutable"] is True
    assert (
        migration["gold_v1"]["sha256"] == json.loads(GOLD_V1_MANIFEST.read_text())["sha256"]["gold"]
    )


# ---------------------------------------------------------------------------
# THE R-97 fix, re-derived rather than read
# ---------------------------------------------------------------------------


def test_every_applicability_state_follows_from_the_structured_input(
    cases: list[dict[str, Any]], covered: set[tuple[str, str]]
) -> None:
    """**The load-bearing test of gold_v2.**

    Derived from `input.requested_service` plus the committed linkage - never from
    `expected.applicability.state`, which would be the file agreeing with itself.
    """
    for case in cases:
        service = case["input"]["requested_service"]
        resolves = (str(service["procedure_code"]), str(service["code_system"])) in covered
        state = case["expected"]["applicability"]["state"]
        assert resolves == (state == "RESOLVED"), (
            f"{case['case_id']}: code {service['code_system']} "
            f"{service['procedure_code']} "
            f"{'resolves' if resolves else 'does not resolve'} but the case expects "
            f"{state}. This is R-97 recurring."
        )


def test_no_applicability_fact_lives_only_in_the_narrative(
    cases: list[dict[str, Any]],
) -> None:
    """The specific gold_v1 defect: "unlisted procedure 99199" in prose only.

    Asserted two ways - the old marker is gone, and every not-applicable case's own
    note names the structured code it actually carries.
    """
    for case in cases:
        note = case["input"]["clinical_note"]
        assert "99199" not in note, f"{case['case_id']} still names the narrative-only code"
        if case["expected"]["applicability"]["state"] != "RESOLVED":
            code = case["input"]["requested_service"]["procedure_code"]
            assert code in note, (
                f"{case['case_id']}: the narrative does not name the structured code "
                f"{code}, so the two halves of the case still disagree"
            )


def test_the_not_applicable_codes_are_real_and_deliberately_unlinked(
    covered: set[tuple[str, str]],
) -> None:
    """Fixing a fabricated label with a fabricated code would trade one for another.

    Every code used to construct a not-applicable case is verified against NLM
    Clinical Tables (existence and description only, never coverage) and is absent
    from the linkage. Both halves matter: a code that does not exist is not a fix,
    and a code that acquires a link later would silently make these cases applicable.
    """
    rows = [json.loads(line) for line in NONCOVERED.read_text().splitlines() if line.strip()]
    assert rows, "no non-covered codes are recorded"
    for row in rows:
        assert (row["code"], row["code_system"]) not in covered, (
            f"{row['code']} is linked in policy_code_links.yaml; it can no longer "
            "construct a not-applicable case"
        )
        assert row["source"] == "NLM Clinical Tables"
        assert row["description"].strip()
        assert "NOT coverage" in row["authority"]


def test_the_previously_broken_cases_are_the_ones_that_changed() -> None:
    """Exactly the eighteen POLICY_NOT_APPLICABLE cases, and nothing else."""
    migration = json.loads(MIGRATION.read_text())
    structural = [
        a["case_id"]
        for a in migration["audits"]
        if a["classification"] == "REQUIRES_STRUCTURAL_FIX"
    ]
    assert len(structural) == 18
    changed = {c["case_id"] for c in migration["changes"] if c["applicability_changed"]}
    assert changed == set(structural)


# ---------------------------------------------------------------------------
# Structural completeness
# ---------------------------------------------------------------------------


def test_every_case_carries_the_required_fields(cases: list[dict[str, Any]]) -> None:
    for case in cases:
        assert REQUIRED_INPUT <= set(case["input"]), case["case_id"]
        assert REQUIRED_EXPECTED <= set(case["expected"]), case["case_id"]
        assert case["case_version"] == "gold_v2"
        assert case["schema_version"] == "2"
        assert case["scenario_type"]
        assert case["derived_from"]["dataset"] == "gold_v1"


def test_no_gold_value_leaks_into_the_inference_input(cases: list[dict[str, Any]]) -> None:
    """The system is handed `input` only.

    A label reachable from the input would make the evaluation a measurement of its
    own answer key - which is the one failure a gold set cannot survive.
    """
    forbidden = ("recommendation", "decision_rule", "criterion_states", "policy_truth", "expected")
    for case in cases:
        blob = json.dumps(case["input"]).lower()
        for token in forbidden:
            assert token not in blob, f"{case['case_id']}: input mentions {token!r}"


def test_the_evidence_ground_truth_is_honest_about_its_level(
    cases: list[dict[str, Any]],
) -> None:
    """Section-level references, and a statement that chunk-level is NOT established.

    Chunk ids are assigned at ingest. Recording them would tie the dataset to one
    database; inventing them would be fabricated ground truth. Saying so is the
    third option and the only correct one.
    """
    for case in cases:
        statement = case["expected"]["evidence_ground_truth"]
        assert statement.startswith("SECTION_LEVEL")
        assert "NOT established" in statement
        for refs in case["expected"]["evidence_refs"].values():
            for ref in refs:
                assert ref.count(":") >= 2, f"{case['case_id']}: {ref!r} is not policy:version:n"


def test_labels_are_derived_by_construction_not_judged(cases: list[dict[str, Any]]) -> None:
    for case in cases:
        labelling = case["expected"]["labelling"]
        assert "app.decision.table.decide" in labelling
        assert "NOT a clinical judgement" in labelling
        assert "NOT a model's opinion" in labelling


def test_recomputing_every_label_reproduces_the_dataset(cases: list[dict[str, Any]]) -> None:
    """ADR-015: a gold label is reproducible, not remembered.

    Re-runs `decide()` over each case's recorded criterion states and asserts the
    dataset's own recommendation and rule come back. A disagreement means the
    dataset and the system have drifted apart - which is exactly what a frozen
    label set exists to detect.
    """
    from app.core.types import CriterionKind, ResolutionStatus, Verdict
    from app.decision.table import CriterionOutcome, GuardrailState, ResolutionState, decide
    from eval.replay import gold_v1_semantics

    kinds = {k.value: k for k in CriterionKind}
    verdicts = {
        "SATISFIED": Verdict.SATISFIED,
        "NOT_SATISFIED": Verdict.NOT_SATISFIED,
        "UNKNOWN": Verdict.INSUFFICIENT_EVIDENCE,
    }
    for case in cases:
        expected = case["expected"]
        outcomes = tuple(
            CriterionOutcome(
                criterion_id=cid,
                kind=kinds[expected["criterion_kinds"][cid]],
                verdict=verdicts[state],
                has_valid_evidence=state != "UNKNOWN",
                missing_evidence=(cid,) if state == "UNKNOWN" else (),
            )
            for cid, state in expected["criterion_states"].items()
        )
        applicable = expected["applicability"]["state"] == "RESOLVED"
        recommendation = decide(
            outcomes,
            GuardrailState.CONTRADICTION
            if case["scenario_type"] == "CONFLICTING_EVIDENCE"
            else GuardrailState.PASSED,
            ResolutionState(
                ResolutionStatus.RESOLVED if applicable else ResolutionStatus.NONE_APPLICABLE,
                version_count=1 if applicable else 0,
            ),
            gold_v1_semantics(
                outcomes,
                policy_id=expected["policy_id"],
                policy_version=expected["policy_version"],
            ),
        )
        assert recommendation.outcome.value == expected["recommendation"], case["case_id"]
        assert int(recommendation.rule) == expected["decision_rule"], case["case_id"]


# ---------------------------------------------------------------------------
# The manifest and the migration report
# ---------------------------------------------------------------------------


def test_the_manifest_digest_matches_the_file(manifest: dict[str, Any]) -> None:
    assert hashlib.sha256(GOLD_V2.read_bytes()).hexdigest() == manifest["sha256"]["gold"]
    assert manifest["frozen"] is True
    assert "R-97" in manifest["resolves"]


def test_the_scoring_budget_starts_unspent(manifest: dict[str, Any]) -> None:
    budget = manifest["scoring_budget"]
    assert budget["allowed_scorings"] == 1
    assert budget["scorings_spent"] == 0
    assert budget["spent_by"] == []


def test_the_class_balance_is_inherited_not_engineered(manifest: dict[str, Any]) -> None:
    """A distribution shaped to look good is a dataset that answers a nicer question.

    Asserted against gold_v1's own distribution: every decision class must carry the
    same count, because no case was added, dropped or relabelled.
    """
    from collections import Counter

    v1 = [json.loads(line) for line in GOLD_V1.read_text().splitlines() if line.strip()]
    v1_decisions = Counter(c["expected"]["decision"] for c in v1)
    assert manifest["distribution"]["recommendation"] == dict(sorted(v1_decisions.items()))
    assert "not engineered" in manifest["balance_note"]


def test_every_case_is_audited_not_just_the_broken_ones(cases: list[dict[str, Any]]) -> None:
    """ "The other 138 were fine" must be a checked statement, not an assertion."""
    migration = json.loads(MIGRATION.read_text())
    v1_ids = {
        json.loads(line)["case_id"] for line in GOLD_V1.read_text().splitlines() if line.strip()
    }
    assert {a["case_id"] for a in migration["audits"]} == v1_ids
    for audit in migration["audits"]:
        assert audit["classification"] in {
            "UNCHANGED",
            "REQUIRES_STRUCTURAL_FIX",
            "REQUIRES_LABEL_REVIEW",
            "INVALID_FOR_GOLD_V2",
        }


def test_every_change_record_says_what_moved_and_why(cases: list[dict[str, Any]]) -> None:
    """B4. No silent changes."""
    migration = json.loads(MIGRATION.read_text())
    assert len(migration["changes"]) == len(cases)
    for change in migration["changes"]:
        assert change["gold_v1_reference"].startswith("gold_v1:")
        assert change["gold_v2_reference"].startswith("gold_v2:")
        assert change["changed_fields"]
        assert change["reason"]
        assert isinstance(change["decision_changed"], bool)
        assert isinstance(change["applicability_changed"], bool)


def test_the_case_count_is_preserved(cases: list[dict[str, Any]], manifest: dict[str, Any]) -> None:
    """No case was excluded. If one ever is, the migration must say which and why."""
    migration = json.loads(MIGRATION.read_text())
    assert len(cases) == manifest["case_count"]
    assert migration["excluded"] == len(migration["excluded_case_ids"])
    assert migration["admitted"] + migration["excluded"] == migration["gold_v1"]["case_count"]
