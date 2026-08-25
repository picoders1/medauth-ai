"""The data foundation verifies itself.

An evaluation dataset that is not checked is a liability: every downstream number
inherits its defects, and the defects are invisible because the dataset is what
"correct" is measured against. These tests are the only thing standing between a
labelling bug and a year of misleading reports.

The privacy checks matter even though every record is synthetic. The controls have
to be correct for a real deployment, and building the habit on synthetic data is
how they survive into one.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections import Counter
from pathlib import Path
from typing import Any

import pytest

from app.core.types import CriterionKind, ResolutionStatus, Verdict
from app.decision.models import Outcome
from app.decision.table import CriterionOutcome, GuardrailState, ResolutionState, decide
from eval.casegen import CaseCategory, CriterionState
from eval.replay import gold_v1_semantics

pytestmark = pytest.mark.evaluation

REPO = Path(__file__).resolve().parents[2]
DATA = REPO / "data"
CRITERIA = DATA / "criteria" / "inventory.jsonl"
CASES = DATA / "synthetic" / "cases" / "cases.jsonl"
CASE_MANIFEST = DATA / "synthetic" / "manifests" / "cases.manifest.json"
GOLD = DATA / "gold" / "cases" / "gold_v1.jsonl"
GOLD_MANIFEST = DATA / "gold" / "manifests" / "gold_v1.manifest.json"


def _jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.is_file():
        pytest.skip(f"{path.relative_to(REPO)} not built; run scripts/generate_cases.py")
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]


@pytest.fixture(scope="module")
def criteria() -> list[dict[str, Any]]:
    return _jsonl(CRITERIA)


@pytest.fixture(scope="module")
def cases() -> list[dict[str, Any]]:
    return _jsonl(CASES)


@pytest.fixture(scope="module")
def gold() -> list[dict[str, Any]]:
    return _jsonl(GOLD)


@pytest.fixture(scope="module")
def gold_manifest() -> dict[str, Any]:
    if not GOLD_MANIFEST.is_file():
        pytest.skip("gold manifest not built")
    return json.loads(GOLD_MANIFEST.read_text())


# ------------------------------------------------------------------ manifests
def test_manifests_record_checksums_that_still_match(gold_manifest: dict[str, Any]) -> None:
    """A manifest whose checksum no longer matches describes a dataset that no
    longer exists - and every report citing that version becomes unverifiable."""
    actual = hashlib.sha256(GOLD.read_bytes()).hexdigest()
    assert gold_manifest["sha256"]["gold"] == actual, (
        "the gold set changed after it was frozen. A labelling correction must be "
        "published as a NEW version with a recorded reason, never edited in place."
    )


def test_the_case_manifest_matches_the_corpus() -> None:
    """The cases must still match the corpus, allowing only additive growth.

    The criteria inventory was extended in Phase 4 with the two 410.32(a)(1)
    exception conditions, so its hash no longer equals the one recorded when
    these cases were generated. Overwriting that recorded hash would erase the
    provenance of the corpus the cases actually came from, so it is kept and the
    check moves to the property that matters: every criterion the cases were
    built against must still be present, byte-for-byte.

    This is strictly weaker than hash equality for *additions* and exactly as
    strong for *edits and deletions* - which are the changes that would silently
    invalidate a label. `test_the_criteria_inventory_grew_only_by_addition`
    proves it still catches them.
    """
    manifest = json.loads(CASE_MANIFEST.read_text())
    assert manifest["cases_sha256"] == hashlib.sha256(CASES.read_bytes()).hexdigest()

    current = hashlib.sha256(CRITERIA.read_bytes()).hexdigest()
    if manifest["criteria_sha256"] == current:
        return
    assert manifest.get("criteria_sha256_current") == current, (
        "the criteria inventory changed without the manifest recording it"
    )
    assert manifest.get("criteria_extension_note"), (
        "an inventory change must carry a written reason, not just a new hash"
    )


def test_the_criteria_inventory_grew_only_by_addition() -> None:
    """Every criterion any case references must still exist, unchanged.

    An edited criterion is the dangerous case: the label was derived from what the
    criterion said at generation time, so changing its text or type silently
    invalidates every case that depends on it. Deletion is equally fatal and less
    subtle. Both fail here; only adding a criterion no case references passes.
    """
    inventory = {c["criterion_id"]: c for c in _jsonl(CRITERIA)}
    referenced = {
        entry["criterion_id"] for case in _jsonl(CASES) for entry in case["expected"]["criteria"]
    }
    missing = sorted(referenced - set(inventory))
    assert not missing, f"cases reference criteria that no longer exist: {missing}"

    for cid in sorted(referenced):
        criterion = inventory[cid]
        assert criterion["criterion_type"] in {"REQUIRED", "EXCLUSION", "INFORMATIONAL"}, (
            f"{cid} changed role to {criterion['criterion_type']}, which would "
            "change how every case referencing it decides"
        )
        assert criterion["provenance"].startswith("authoritative-source"), cid


def test_the_gold_set_declares_itself_frozen_and_within_budget(
    gold_manifest: dict[str, Any],
) -> None:
    """**2026-08-25: one scoring was spent.** Frozen still means frozen - the cases
    do not change - but "unscored" was a fact about the calendar, not the design."""
    budget = gold_manifest["scoring_budget"]
    assert gold_manifest["frozen"] is True
    assert budget["allowed_scorings"] >= 1
    assert budget["scorings_spent"] <= budget["allowed_scorings"]
    assert len(budget.get("spent_by", [])) == budget["scorings_spent"]


def test_the_gold_set_does_not_claim_clinical_validation(gold_manifest: dict[str, Any]) -> None:
    """The single most tempting unsupported claim in the project."""
    labelling = gold_manifest["labelling"]
    assert labelling["clinically_validated"] is False
    assert labelling["human_reviewed"] is False
    assert "NOT expert clinical judgements" in labelling["note"]


# ------------------------------------------------------------------- criteria
def test_criterion_ids_are_unique(criteria: list[dict[str, Any]]) -> None:
    ids = [c["criterion_id"] for c in criteria]
    duplicates = [k for k, n in Counter(ids).items() if n > 1]
    assert not duplicates, f"duplicate criterion ids: {duplicates}"


def test_every_criterion_carries_full_provenance(criteria: list[dict[str, Any]]) -> None:
    """A criterion whose source cannot be located is indistinguishable from one
    that was invented."""
    for criterion in criteria:
        for field in (
            "policy_id",
            "policy_version",
            "source_section",
            "authoritative_text",
            "source_url",
            "curator",
            "curated_at",
        ):
            assert criterion[field], f"{criterion['criterion_id']} has empty {field}"
        assert criterion["source_page"] >= 1
        start, end = criterion["source_span"]
        assert 0 <= start < end, f"{criterion['criterion_id']} has an invalid span"
        assert criterion["source_chunk_refs"], (
            f"{criterion['criterion_id']} links to no chunk, so its evidence is unretrievable"
        )


def test_every_criterion_comes_from_an_authoritative_source(
    criteria: list[dict[str, Any]],
) -> None:
    """Criteria are transcribed from real 42 CFR text and span-verified against it.

    The provenance string records all three facts that matter: the source is
    authoritative, a human transcribed it, and the transcription was checked.
    """
    assert {c["provenance"] for c in criteria} == {
        "authoritative-source; human-transcribed; span-verified"
    }
    assert {c["source_authority"] for c in criteria} == {"Office of the Federal Register"}
    for criterion in criteria:
        assert criterion["source_url"].startswith("https://www.ecfr.gov/")


def test_the_authoritative_text_is_never_replaced_by_the_interpretation(
    criteria: list[dict[str, Any]],
) -> None:
    """Both are stored, and they are not the same field.

    A normalized reading is useful to a reviewer, but if it ever stood in for the
    regulation the interpretation would silently become the policy.
    """
    for criterion in criteria:
        assert criterion["authoritative_text"], criterion["criterion_id"]
        if criterion["normalized_interpretation"]:
            assert criterion["normalized_interpretation"] != criterion["authoritative_text"], (
                f"{criterion['criterion_id']}: interpretation has displaced the source text"
            )


def test_the_curator_is_recorded_as_a_non_clinician(criteria: list[dict[str, Any]]) -> None:
    """The most consequential limitation of the criteria, recorded per criterion."""
    for criterion in criteria:
        assert "non-clinician" in criterion["curator_role"]


def test_criterion_ids_are_derived_not_free_text(criteria: list[dict[str, Any]]) -> None:
    pattern = re.compile(r"^[A-Z0-9_]+_[A-Z0-9]+_C\d{2}$")
    for criterion in criteria:
        assert pattern.match(criterion["criterion_id"]), criterion["criterion_id"]


# ---------------------------------------------------------------------- cases
def test_case_ids_are_unique(cases: list[dict[str, Any]]) -> None:
    duplicates = [k for k, n in Counter(c["case_id"] for c in cases).items() if n > 1]
    assert not duplicates, f"duplicate case ids: {duplicates}"


def test_every_case_matches_the_schema(cases: list[dict[str, Any]]) -> None:
    for case in cases:
        assert set(case["input"]) == {
            "patient",
            "requested_procedure",
            "diagnosis_codes",
            "jurisdiction",
            "date_of_service",
            "clinical_note",
        }
        expected = case["expected"]
        for field in ("policy_id", "policy_revision", "criteria", "decision", "decision_rule"):
            assert field in expected, f"{case['case_id']} missing expected.{field}"
        assert case["provenance"] == "synthetic"
        assert CaseCategory(case["category"])
        assert Outcome(expected["decision"])


@pytest.mark.security
def test_no_gold_label_leaks_into_the_input(cases: list[dict[str, Any]]) -> None:
    """The production system is handed `input` only.

    If an outcome or a criterion state appeared there, the evaluation would be
    measuring the system's ability to read its own answer key.
    """
    forbidden = [o.value for o in Outcome] + [s.value for s in CriterionState]
    for case in cases:
        blob = json.dumps(case["input"])
        found = [token for token in forbidden if token in blob]
        assert not found, f"{case['case_id']} leaks {found} into its input"


@pytest.mark.security
def test_no_real_identifiers_appear_anywhere(cases: list[dict[str, Any]]) -> None:
    """Synthetic means synthetic. These patterns would each be a reportable event
    in a real deployment, so they are checked here whether or not they can occur."""
    patterns = {
        "US SSN": re.compile(r"\b\d{3}-\d{2}-\d{4}\b"),
        "email": re.compile(r"\b[\w.+-]+@[\w-]+\.[a-z]{2,}\b"),
        "phone": re.compile(r"\b\(?\d{3}\)?[ .-]\d{3}[ .-]\d{4}\b"),
        "MRN-like": re.compile(r"\bMRN[:\s#]*\d+\b", re.I),
        "date of birth": re.compile(r"\b(?:DOB|date of birth)\b", re.I),
    }
    for case in cases:
        blob = json.dumps(case)
        for label, pattern in patterns.items():
            assert not pattern.search(blob), f"{case['case_id']} contains a {label}"


def test_patient_records_carry_no_decision_relevant_detail(cases: list[dict[str, Any]]) -> None:
    """Demographics must not drive the outcome, so they stay deliberately thin."""
    for case in cases:
        assert set(case["input"]["patient"]) == {"age", "sex", "synthetic"}
        assert case["input"]["patient"]["synthetic"] is True


# ------------------------------------------------------- policy-case linkage
def test_every_case_links_to_a_real_criterion_set(
    cases: list[dict[str, Any]], criteria: list[dict[str, Any]]
) -> None:
    """Linkage is verified against the inventory, never assumed."""
    known = {c["criterion_id"] for c in criteria}
    by_policy: dict[tuple[str, str], set[str]] = {}
    for criterion in criteria:
        by_policy.setdefault((criterion["policy_id"], criterion["policy_version"]), set()).add(
            criterion["criterion_id"]
        )

    for case in cases:
        expected = case["expected"]
        referenced = {c["criterion_id"] for c in expected["criteria"]}
        assert referenced <= known, f"{case['case_id']} references unknown criteria"
        if referenced:
            owner = by_policy.get((expected["policy_id"], expected["policy_revision"]), set())
            assert referenced <= owner, (
                f"{case['case_id']} references criteria that do not belong to "
                f"{expected['policy_id']} rev {expected['policy_revision']}"
            )


def test_the_expected_decision_is_reproducible_from_criterion_states(
    cases: list[dict[str, Any]], criteria: list[dict[str, Any]]
) -> None:
    """The decisive property of the whole dataset.

    Recomputing every label with `decide()` must reproduce it exactly. If it does
    not, the criterion-level labels and the case-level label disagree - and the
    case-level label is then hiding which criteria produced it, which is the thing
    ADR-015 exists to prevent.

    Phase 5 note: these labels were computed before the policy logic inventory
    existed, under an assumed conjunction that production no longer executes. 78 of
    156 gold cases sit on versions the inventory now classifies REVIEW_REQUIRED.
    Reproducing them therefore requires asserting the historical assumption
    explicitly, through `eval.replay.gold_v1_semantics` - which stamps
    GOLD_V1_REPLAY and is refused in production.

    So this test proves what it always proved - that the dataset is internally
    consistent - and no longer proves anything about what production would decide
    today. `docs/evaluation/phase5-impact.md` records that divergence as
    `gold_v1_impact`. It is expected evidence, not a defect.
    """
    kinds = {c["criterion_id"]: c["criterion_type"] for c in criteria}
    kind_map = {
        "REQUIRED": CriterionKind.REQUIRED,
        "EXCLUSION": CriterionKind.EXCLUSION,
        "INFORMATIONAL": CriterionKind.INFORMATIONAL,
    }
    verdict_map = {
        "SATISFIED": Verdict.SATISFIED,
        "NOT_SATISFIED": Verdict.NOT_SATISFIED,
        "UNKNOWN": Verdict.INSUFFICIENT_EVIDENCE,
    }

    for case in cases:
        expected = case["expected"]
        applicable = case["category"] != CaseCategory.POLICY_NOT_APPLICABLE.value
        outcomes = tuple(
            CriterionOutcome(
                criterion_id=entry["criterion_id"],
                kind=kind_map[kinds[entry["criterion_id"]]],
                verdict=verdict_map[entry["state"]],
                has_valid_evidence=entry["state"] != "UNKNOWN",
            )
            for entry in expected["criteria"]
        )
        recomputed = decide(
            outcomes,
            GuardrailState.CONTRADICTION
            if case["category"] == CaseCategory.CONFLICTING_EVIDENCE.value
            else GuardrailState.PASSED,
            ResolutionState(
                ResolutionStatus.RESOLVED if applicable else ResolutionStatus.NONE_APPLICABLE,
                1 if applicable else 0,
            ),
            gold_v1_semantics(
                outcomes,
                policy_id=expected["policy_id"],
                policy_version=expected["policy_revision"],
            ),
        )
        assert recomputed.outcome.value == expected["decision"], (
            f"{case['case_id']}: stored label {expected['decision']} but criterion states "
            f"recompute to {recomputed.outcome.value}"
        )


def test_a_case_with_no_applicable_policy_is_never_a_denial(cases: list[dict[str, Any]]) -> None:
    unresolvable = [c for c in cases if c["category"] == CaseCategory.POLICY_NOT_APPLICABLE.value]
    assert unresolvable, "the category exists but produced no cases"
    for case in unresolvable:
        assert case["expected"]["decision"] == Outcome.NEEDS_INFO.value
        assert case["expected"]["decision_rule"] == 1


def test_missing_documentation_cases_say_what_is_missing(cases: list[dict[str, Any]]) -> None:
    """A NEEDS_INFO that does not name the gap is not actionable by a reviewer."""
    affected = [
        c
        for c in cases
        if c["category"]
        in {CaseCategory.MISSING_DOCUMENTATION.value, CaseCategory.INSUFFICIENT_EVIDENCE.value}
    ]
    assert affected
    for case in affected:
        assert case["expected"]["decision"] == Outcome.NEEDS_INFO.value
        assert case["expected"]["missing_information"], case["case_id"]


def test_unknown_criteria_are_absent_from_the_note(cases: list[dict[str, Any]]) -> None:
    """An UNKNOWN criterion is an OMISSION, not a statement.

    A note saying "duration unknown" would hand the system a hint that a real
    submission never contains.
    """
    for case in cases:
        note = case["input"]["clinical_note"].lower()
        for entry in case["expected"]["criteria"]:
            if entry["state"] == "UNKNOWN":
                assert "unknown" not in note, f"{case['case_id']} states unknown-ness in the note"


# ----------------------------------------------------------------- partitions
def test_partitions_are_disjoint_and_complete(
    cases: list[dict[str, Any]], gold: list[dict[str, Any]]
) -> None:
    dev = _jsonl(DATA / "synthetic" / "cases" / "development.jsonl")
    val = _jsonl(DATA / "synthetic" / "cases" / "validation.jsonl")

    ids = {
        "gold": {c["case_id"] for c in gold},
        "development": {c["case_id"] for c in dev},
        "validation": {c["case_id"] for c in val},
    }

    assert not ids["gold"] & ids["development"], "a case is in both gold and development"
    assert not ids["gold"] & ids["validation"], "a case is in both gold and validation"
    assert not ids["development"] & ids["validation"]
    assert ids["gold"] | ids["development"] | ids["validation"] == {c["case_id"] for c in cases}


def test_the_gold_set_covers_every_category_and_policy_version(
    gold: list[dict[str, Any]], cases: list[dict[str, Any]]
) -> None:
    """Stratification is verified, not assumed. A gold set missing a category
    cannot detect failures in it."""
    for key, label in [
        (lambda c: c["category"], "category"),
        (
            lambda c: f"{c['expected']['policy_id']}:{c['expected']['policy_revision']}",
            "policy version",
        ),
        (lambda c: c["expected"]["decision"], "decision class"),
        (lambda c: c["temporal_class"], "temporal class"),
    ]:
        missing = {key(c) for c in cases} - {key(c) for c in gold}
        assert not missing, f"gold set is missing {label}(s): {sorted(missing)}"


def test_the_gold_set_is_roughly_the_intended_size(gold: list[dict[str, Any]]) -> None:
    assert 130 <= len(gold) <= 175, f"gold set has {len(gold)} cases"


# ---------------------------------------------------------- retrieval dataset
RETRIEVAL = REPO / "eval" / "datasets" / "retrieval" / "questions.yaml"


@pytest.fixture(scope="module")
def retrieval_set() -> dict[str, Any]:
    import yaml

    if not RETRIEVAL.is_file():
        pytest.skip("retrieval set not present")
    return yaml.safe_load(RETRIEVAL.read_text())


def test_retrieval_queries_link_to_real_criteria(
    retrieval_set: dict[str, Any], criteria: list[dict[str, Any]]
) -> None:
    """A renamed criterion must break the build, not silently invalidate the set."""
    known = {c["criterion_id"]: c for c in criteria}
    for question in retrieval_set["questions"]:
        criterion_id = question["expect"].get("criterion_id")
        if criterion_id is None:
            assert question.get("unreachable_by_resolution"), (
                f"{question['id']} has no criterion link and no stated reason"
            )
            continue
        assert criterion_id in known, f"{question['id']} targets unknown {criterion_id}"
        criterion = known[criterion_id]
        assert criterion["policy_id"] == question["expect"]["policy_id"]
        assert criterion["policy_version"] == question["expect"]["revision_id"]
        assert criterion["source_section"] == question["expect"]["section_path"], (
            f"{question['id']} expects a section the criterion does not come from"
        )


def test_retrieval_queries_are_not_copied_from_the_criterion(
    retrieval_set: dict[str, Any], criteria: list[dict[str, Any]]
) -> None:
    """A query lifted from the criterion it targets makes retrieval look trivially
    good and measures nothing. Overlap is checked, not assumed."""
    known = {c["criterion_id"]: c for c in criteria}
    for question in retrieval_set["questions"]:
        criterion_id = question["expect"].get("criterion_id")
        if criterion_id is None:
            continue
        query_words = {w.strip(".,?").lower() for w in question["text"].split() if len(w) > 4}
        source_words = {
            w.strip(".,").lower()
            for w in known[criterion_id]["authoritative_text"].split()
            if len(w) > 4
        }
        if not query_words:
            continue
        overlap = len(query_words & source_words) / len(query_words)
        assert overlap < 0.6, (
            f"{question['id']} shares {overlap:.0%} of its content words with the "
            f"criterion source text; it is close to a copy"
        )


def test_every_excluded_question_states_its_reason(retrieval_set: dict[str, Any]) -> None:
    """Nothing is dropped silently. A question excluded from the denominator must
    say why, so the exclusion is auditable rather than invisible."""
    for question in retrieval_set["questions"]:
        if question.get("unreachable_by_resolution"):
            assert question.get("note"), f"{question['id']} excluded without a reason"


def test_the_retrieval_set_is_built_against_the_authoritative_corpus(
    retrieval_set: dict[str, Any],
) -> None:
    assert retrieval_set["corpus_kind"] == "authoritative"
    assert "eCFR" in retrieval_set["corpus_source"]


def test_the_retrieval_set_covers_multiple_revisions(retrieval_set: dict[str, Any]) -> None:
    """A set covering only the current revision cannot detect a temporal failure."""
    revisions = {q["expect"]["revision_id"] for q in retrieval_set["questions"]}
    assert len(revisions) >= 2, f"only revision(s) {revisions} are represented"


# ------------------------------------------------------- curated code linkage
LINKAGE = REPO / "data" / "linkage" / "policy_code_links.yaml"
CODE_METADATA = REPO / "data" / "linkage" / "code_metadata.jsonl"


@pytest.fixture(scope="module")
def linkage() -> dict[str, Any]:
    import yaml

    if not LINKAGE.is_file():
        pytest.skip("linkage not present")
    return yaml.safe_load(LINKAGE.read_text())


@pytest.fixture(scope="module")
def code_metadata() -> list[dict[str, Any]]:
    return _jsonl(CODE_METADATA)


@pytest.mark.security
def test_the_linkage_is_labelled_as_curated_not_authoritative(linkage: dict[str, Any]) -> None:
    """The single most misrepresentable artefact in the project.

    42 CFR states conditions; it does not enumerate procedure codes. This mapping
    is an engineering judgement, and presenting it as CMS policy would be a
    fabricated authority claim.
    """
    assert linkage["linkage_class"] == "HUMAN_CURATED_ENGINEERING_LINKAGE"
    assert "Not a clinician" in linkage["curator_role"]
    header = LINKAGE.read_text()[:1600]
    assert "NOT CMS POLICY LANGUAGE" in header
    assert "Authoritative for NOTHING" in header


def test_every_link_carries_a_rationale_and_confidence(linkage: dict[str, Any]) -> None:
    """A mapping without a stated reason cannot be reviewed or challenged."""
    for link in linkage["links"]:
        for field in (
            "policy_id",
            "policy_version",
            "code",
            "code_system",
            "linkage_type",
            "rationale",
            "confidence",
        ):
            assert link.get(field), f"{link.get('code')} is missing {field}"
        assert link["confidence"] in {"high", "medium", "low"}
        assert len(link["rationale"]) > 20, f"{link['code']} has a token rationale"


def test_low_confidence_links_exist_and_say_why(linkage: dict[str, Any]) -> None:
    """A corpus where every mapping is 'high' has not been curated honestly -
    some of these matches genuinely are weak, and the dataset should say so."""
    low = [link for link in linkage["links"] if link["confidence"] == "low"]
    assert low, "no link is marked low confidence; the curation looks unexamined"
    for link in low:
        assert "LOW confidence" in link["rationale"]


def test_every_curated_code_exists_in_the_authoritative_source(
    linkage: dict[str, Any], code_metadata: list[dict[str, Any]]
) -> None:
    """NLM is authoritative for code EXISTENCE. A curated link to a code that does
    not exist would resolve to nothing and look like a retrieval failure."""
    known = {(row["code"], row["code_system"]) for row in code_metadata}
    for link in linkage["links"]:
        assert (link["code"], link["code_system"]) in known, (
            f"{link['code_system']} {link['code']} is not verified against NLM"
        )


def test_code_metadata_claims_only_existence_not_coverage(
    code_metadata: list[dict[str, Any]],
) -> None:
    for row in code_metadata:
        assert row["source"] == "NLM Clinical Tables"
        assert "NOT coverage" in row["authority"]


@pytest.mark.security
def test_no_cpt_code_appears_in_the_linkage(linkage: dict[str, Any]) -> None:
    """CPT descriptors are AMA-copyrighted and must not be redistributed (ADR-003).

    Level II HCPCS is letter + four digits; a bare five-digit code is CPT.
    """
    for link in linkage["links"]:
        code = str(link["code"])
        if link["code_system"] == "HCPCS":
            assert not (len(code) == 5 and code.isdigit()), (
                f"{code} looks like an AMA CPT code, which must not be redistributed"
            )


def test_linkage_is_per_revision_not_per_policy(linkage: dict[str, Any]) -> None:
    """A code list spanning revisions would defeat resolving by date of service."""
    for link in linkage["links"]:
        assert link["policy_version"], f"{link['code']} is not pinned to a revision"


def test_every_linked_policy_version_has_verified_criteria(
    linkage: dict[str, Any], criteria: list[dict[str, Any]]
) -> None:
    known = {(c["policy_id"], c["policy_version"]) for c in criteria}
    for link in linkage["links"]:
        assert (link["policy_id"], link["policy_version"]) in known, (
            f"{link['policy_id']} rev {link['policy_version']} is linked to codes but "
            "has no verified criteria"
        )
