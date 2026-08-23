"""Phase 3 regression tests: the ground-truth layer must not overstate itself.

Every assertion here guards a *claim*, not a computation. The failure mode these
exist to prevent is silent optimism - a completeness flag flipping to true, an
`INFERRED` code link quietly becoming authoritative, a gold case being edited
into validity rather than reviewed into it.

None of these tests is vacuous: each is written so that the corresponding
overstatement makes it fail. Where a test asserts an exact count, that count is a
tripwire, not a target - it changes only when a documented decision changes it.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
import yaml

pytestmark = pytest.mark.evaluation

REPO = Path(__file__).resolve().parents[2]

COVERAGE_SUMMARY = REPO / "data/criteria/coverage_summary.json"
COVERAGE_MATRIX = REPO / "data/criteria/coverage_matrix.jsonl"
INVENTORY = REPO / "data/criteria/inventory.jsonl"
LINKAGE = REPO / "data/linkage/policy_code_links.yaml"
GOLD_AUDIT = REPO / "data/gold/manifests/gold_v1.audit.json"
GOLD_CASES = REPO / "data/gold/cases/gold_v1.jsonl"
RETRIEVAL_SET = REPO / "eval/datasets/retrieval/questions.yaml"

VALID_CLASSIFICATIONS = {
    "REPRESENTED_CRITERION",
    "NON_DECISION_RELEVANT",
    "REQUIRES_HUMAN_REVIEW",
}


def _jsonl(path: Path) -> list[dict]:
    return [
        json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()
    ]


@pytest.fixture(scope="module")
def summary() -> dict:
    return json.loads(COVERAGE_SUMMARY.read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def matrix() -> list[dict]:
    return _jsonl(COVERAGE_MATRIX)


# --------------------------------------------------------------------------
# 1. Completeness matrix validity
# --------------------------------------------------------------------------


def test_walk_is_exhaustive_and_completeness_is_not_claimed(summary: dict) -> None:
    """These are two different facts and the summary must keep them apart.

    `walk_exhaustive` says every provision was enumerated and classified.
    `completeness_verified` says the criterion set is known to be sufficient.
    The first is an engineering property and is true; the second requires a
    qualified reviewer and is false. Conflating them was a real defect - the
    first version of this summary reported completeness because nothing was
    unclassified, which is not the same claim at all.
    """
    assert summary["walk_exhaustive"] is True
    assert summary["completeness_verified"] is False, (
        "completeness_verified may only become true when OD-19 is resolved by a "
        "qualified reviewer, never as a side effect of classification finishing"
    )
    assert summary["provisions_awaiting_review"] > 0
    assert summary["completeness_blocked_by"]


def test_every_substantive_provision_is_classified(summary: dict, matrix: list[dict]) -> None:
    """An unclassified provision is a hole in the denominator."""
    assert summary["unclassified_substantive"] == 0
    substantive = [p for p in matrix if p["substantive"]]
    assert len(substantive) == summary["provisions_substantive"]
    awaiting = [p for p in substantive if p["classification"] == "REQUIRES_HUMAN_REVIEW"]
    assert len(awaiting) == summary["provisions_awaiting_review"]
    for p in substantive:
        assert p["classification"] in VALID_CLASSIFICATIONS, p["provision_id"]


def test_classification_counts_match_the_matrix(summary: dict, matrix: list[dict]) -> None:
    """The summary is derived, so it must not drift from what it summarises.

    `by_classification` spans every provision; `provisions_substantive` counts
    only those carrying content. Non-substantive provisions - headings, cross
    references - land in `NON_DECISION_RELEVANT`, which is why that bucket (80)
    exceeds the substantive dismissals (39).
    """
    counted: dict[str, int] = {}
    for p in matrix:
        counted[p["classification"]] = counted.get(p["classification"], 0) + 1
    assert counted == summary["by_classification"]
    assert summary["provisions_total"] == len(matrix)
    assert sum(counted.values()) == summary["provisions_total"]


def test_default_classification_is_review_not_dismissal(matrix: list[dict]) -> None:
    """`REQUIRES_HUMAN_REVIEW` must dominate `NON_DECISION_RELEVANT`.

    The dangerous direction is dismissal: a provision ruled irrelevant is
    removed from the completeness question permanently, whereas one sent to
    review is merely pending. If a future rule change inverted this ratio it
    would mean the classifier had started resolving uncertainty by discarding
    it, and that must break the build.
    """
    by = dict.fromkeys(VALID_CLASSIFICATIONS, 0)
    for p in matrix:
        if p["substantive"]:
            by[p["classification"]] += 1
    assert by["REQUIRES_HUMAN_REVIEW"] > by["NON_DECISION_RELEVANT"]


def test_every_dismissed_provision_carries_a_reason(matrix: list[dict]) -> None:
    """Silent exclusion is the failure mode this whole exercise exists to stop."""
    for p in matrix:
        if p["classification"] == "NON_DECISION_RELEVANT":
            assert p["reason"].strip(), p["provision_id"]


def test_represented_provisions_point_at_criteria_that_exist(matrix: list[dict]) -> None:
    """A dangling criterion id would make coverage look better than it is."""
    known = {c["criterion_id"] for c in _jsonl(INVENTORY)}
    assert known, "criterion inventory is empty"
    linked: set[str] = set()
    for p in matrix:
        if p["classification"] == "REPRESENTED_CRITERION":
            assert p["criterion_ids"], p["provision_id"]
            for cid in p["criterion_ids"]:
                assert cid in known, f"{p['provision_id']} cites unknown criterion {cid}"
            linked.update(p["criterion_ids"])
    assert linked == known, (
        "every verified criterion must be reachable from some provision; "
        f"orphaned: {sorted(known - linked)}"
    )


def test_no_provision_is_reviewed_yet(matrix: list[dict]) -> None:
    """Guards the audit trail: `reviewer_status` may only move by real review.

    If this ever fails, either a reviewer has genuinely worked the protocol - in
    which case this test is updated in the same change that records who, when
    and against what - or a script has marked its own output as reviewed.
    """
    for p in matrix:
        assert p["reviewer_status"] == "NOT_REVIEWED", p["provision_id"]


# --------------------------------------------------------------------------
# 2. Policy-type separation
# --------------------------------------------------------------------------


def test_corpus_is_cfr_only_and_says_so(matrix: list[dict]) -> None:
    """ADR-022 adopts NCDs as a *separate layer*, not as more CFR.

    Until NCDs are actually ingested, every provision is regulation. When they
    arrive, this test must be amended to assert the two layers stay distinguishable
    rather than deleted - merging them is the specific mistake it prevents.
    """
    policies = {p["policy_id"] for p in matrix}
    assert policies, "no policies in matrix"
    for pid in policies:
        assert pid.startswith("42 CFR "), (
            f"{pid!r} is not 42 CFR. If NCDs have been ingested, this test must "
            "assert layer separation, not be removed"
        )


def test_no_lcd_or_article_material_is_present() -> None:
    """LCDs sit behind an AMA/ADA/AHA licence gate (OD-21) and were not pursued.

    A file appearing under the coverage tree would mean the gate was crossed
    without the decision being made.
    """
    for pattern in ("*lcd*", "*article*"):
        hits = [p for p in (REPO / "data").rglob(pattern) if p.is_file() and ".venv" not in p.parts]
        assert not hits, f"unexpected coverage material: {hits}"


# --------------------------------------------------------------------------
# 3. Code-linkage classification
# --------------------------------------------------------------------------


@pytest.fixture(scope="module")
def linkage() -> dict:
    return yaml.safe_load(LINKAGE.read_text(encoding="utf-8"))


def test_no_link_claims_to_be_authoritative(linkage: dict) -> None:
    """42 CFR enumerates no procedure codes, so no link here *can* be authoritative.

    This is the honest consequence of using regulation rather than a coverage
    determination as the corpus. It becomes false only when an NCD or LCD supplies
    the linkage itself - and then the source, not the default, must say so.
    """
    assert linkage["linkage_class"] == "HUMAN_CURATED_ENGINEERING_LINKAGE"
    assert linkage["evidence_class_default"] != "AUTHORITATIVE"
    for link in linkage["links"]:
        assert link.get("evidence_class", linkage["evidence_class_default"]) != "AUTHORITATIVE", (
            link
        )


def test_every_link_is_classified_and_justified(linkage: dict) -> None:
    valid = {"AUTHORITATIVE", "HUMAN_CURATED", "INFERRED"}
    for link in linkage["links"]:
        assert link.get("evidence_class", linkage["evidence_class_default"]) in valid, link
        assert link["rationale"].strip(), link
        assert link["confidence"] in {"high", "medium", "low"}, link


def test_inferred_links_do_not_drive_gold_decision_logic(linkage: dict) -> None:
    """An `INFERRED` link rests on resemblance, which is exactly what ADR-004 forbids
    as a basis for applicability. Such a code may appear in the corpus - the system
    should have linkage it is sceptical of - but no gold case may depend on one."""
    inferred = {
        link["code"]
        for link in linkage["links"]
        if link.get("evidence_class", linkage["evidence_class_default"]) == "INFERRED"
    }
    if not inferred:
        pytest.skip("no INFERRED links to guard")
    for case in _jsonl(GOLD_CASES):
        code = case["input"].get("procedure_code")
        assert code not in inferred, (
            f"gold case {case['case_id']} resolves through INFERRED code {code}"
        )


# --------------------------------------------------------------------------
# 4. Gold-set audit honesty
# --------------------------------------------------------------------------


@pytest.fixture(scope="module")
def audit() -> dict:
    return json.loads(GOLD_AUDIT.read_text(encoding="utf-8"))


def test_audit_did_not_modify_the_gold_set(audit: dict) -> None:
    """An audit that edits what it audits destroys the record of the experiment.

    Corrections ship as `gold_v2` with a recorded reason, never as an in-place
    fix to a frozen split.
    """
    assert audit["gold_set_unmodified"] is True
    assert audit["cases"] == len(_jsonl(GOLD_CASES))
    assert len(audit["cases_detail"]) == audit["cases"]


def test_no_case_is_marked_valid_without_review(audit: dict) -> None:
    """`REQUIRES_REVIEW` is the honest status while completeness is unverified.

    A case's label is derived correctly from its criterion states - that part is
    sound. What is unestablished is whether those criteria are the *right* ones,
    and that uncertainty propagates to every case. Marking cases VALID before
    OD-19 closes would be asserting the conclusion.
    """
    assert set(audit["by_status"]) == {"REQUIRES_REVIEW"}
    assert audit["by_status"]["REQUIRES_REVIEW"] == audit["cases"]
    for detail in audit["cases_detail"]:
        assert detail["audit_status"] == "REQUIRES_REVIEW", detail["case_id"]


def test_audit_reason_is_recorded_per_case(audit: dict) -> None:
    for detail in audit["cases_detail"]:
        assert detail.get("findings"), detail["case_id"]


# --------------------------------------------------------------------------
# 5. Retrieval evaluation integrity
# --------------------------------------------------------------------------


@pytest.fixture(scope="module")
def retrieval() -> dict:
    return yaml.safe_load(RETRIEVAL_SET.read_text(encoding="utf-8"))


def test_retrieval_targets_reference_criteria_that_exist(retrieval: dict) -> None:
    known = {c["criterion_id"] for c in _jsonl(INVENTORY)}
    for q in retrieval["questions"]:
        cid = q["expect"].get("criterion_id")
        if cid is not None:
            assert cid in known, f"{q['id']} targets unknown criterion {cid}"


def test_retrieval_queries_are_not_copies_of_their_targets(retrieval: dict) -> None:
    """A query lifted from the text it targets measures string matching.

    One query in an earlier version - "Are hearing aids paid for?" - had 100%
    content-word overlap with its criterion and was rewritten. The bound is on
    content words only; shared function words are unavoidable and meaningless.
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
    }
    criteria = {c["criterion_id"]: c for c in _jsonl(INVENTORY)}
    for q in retrieval["questions"]:
        cid = q["expect"].get("criterion_id")
        if cid is None:
            continue
        target = criteria[cid].get("authoritative_text", "")
        qw = {w.strip(".,?()'\"").lower() for w in q["text"].split()} - stop
        tw = {w.strip(".,?()'\"").lower() for w in target.split()} - stop
        if not qw:
            continue
        overlap = len(qw & tw) / len(qw)
        assert overlap < 0.9, (
            f"{q['id']} is {overlap:.0%} lifted from its target; rephrase as a "
            "reviewer would ask it"
        )


def test_retrieval_set_difficulty_gap_is_recorded_not_hidden() -> None:
    """The set has no negative and no ambiguous queries. That is a known gap.

    This test does not demand the gap be closed - closing it is OD-22, and doing
    it hastily after seeing results would be worse than leaving it open. It
    demands the gap stay *documented*, so the numbers are never read as if the
    set were hard.
    """
    doc = (REPO / "docs/evaluation/retrieval-evaluation-assessment.md").read_text(encoding="utf-8")
    assert "not difficult enough" in doc.lower()
    assert "negative quer" in doc.lower()
    assert "ambiguous quer" in doc.lower()


def test_no_fabricated_coverage_claim_in_phase_3_docs() -> None:
    """Language rules are enforced, not merely written down.

    A document may *name* a forbidden phrase in order to forbid it - the language
    rules themselves have to quote what they ban, and the dataset card lists
    claims the data cannot support. So the check is contextual: within a short
    window around the phrase there must be a marker that frames it as prohibited.
    An unqualified assertion has no such marker and fails.
    """
    forbidden = (
        "hipaa compliant",
        "determines medical necessity",
        "clinically validated",
        "runs on kubernetes",
    )
    markers = (
        "never",
        "not ",
        "**not**",
        "refus",
        "forbid",
        "prohibit",
        "cannot",
        "must not",
        "unsupported",
        "may not be",
        "is not used for",
        "out-of-scope",
        "refused",
    )
    for path in (REPO / "docs").rglob("*.md"):
        lines = path.read_text(encoding="utf-8").lower().splitlines()
        for n, line in enumerate(lines):
            for phrase in forbidden:
                if phrase not in line:
                    continue
                window = " ".join(lines[max(0, n - 6) : n + 2])
                assert any(m in window for m in markers), (
                    f"{path}:{n + 1} uses {phrase!r} without framing it as prohibited"
                )
