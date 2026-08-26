"""Everything must stay exactly where it is while R-86 is unresolved. Parts H, J.

An evaluation hold is only a hold if the artefacts it protects are still the ones
that were frozen when it started. The failure mode is not dramatic: a dataset gets
"tidied", a benchmark gets one query "fixed", a threshold gets rounded - and the run
that eventually happens is scored against something nobody agreed to.

So this file pins the three frozen artefacts by digest, pins the threshold, and
asserts that no evaluation output has appeared while the gate is blocked.
"""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
from typing import Any

import pytest
import yaml

pytestmark = [pytest.mark.evaluation, pytest.mark.security]

REPO = Path(__file__).resolve().parents[2]
GOLD_V1 = REPO / "data/gold/cases/gold_v1.jsonl"
GOLD_V1_MANIFEST = REPO / "data/gold/manifests/gold_v1.manifest.json"
GOLD_V2 = REPO / "data/gold/cases/gold_v2.jsonl"
GOLD_V2_MANIFEST = REPO / "data/gold/manifests/gold_v2.manifest.json"
RETRIEVAL_V4 = REPO / "eval/datasets/retrieval_v4/questions.yaml"
BASELINE = REPO / "eval/reports/retrieval-v4-baseline/results.json"
PHASE16 = REPO / "eval/reports/phase16-410-33"
SEAL = REPO / "data/escalations/r86-reproducer.manifest.json"


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


# ---------------------------------------------------------------------------
# The frozen artefacts
# ---------------------------------------------------------------------------


def test_gold_v1_is_byte_identical() -> None:
    """Twelve phases and counting. Its committed reports depend on this."""
    assert digest(GOLD_V1) == json.loads(GOLD_V1_MANIFEST.read_text())["sha256"]["gold"]


def test_gold_v2_is_unchanged_since_its_freeze() -> None:
    manifest = json.loads(GOLD_V2_MANIFEST.read_text())
    assert digest(GOLD_V2) == manifest["sha256"]["gold"]
    assert manifest["frozen"] is True
    assert manifest["case_count"] == 156


def test_gold_v2_matches_what_the_experiment_manifest_froze() -> None:
    """The DATA the run would score, against what the experiment manifest froze.

    Two independent records of the same digest, and they must agree: the dataset's
    own manifest could be regenerated alongside the dataset, while the experiment
    manifest is frozen separately and cannot.

    **The gold_v2 *manifest file* is deliberately not compared byte-for-byte.** It
    gained a `supersedes_reason` field later in Phase 16, after the experiment
    manifest had been frozen and before anything was ever scored, so its bytes
    legitimately differ. What must not differ is anything that changes what a run
    would measure, so those fields are compared individually instead of hashing a
    file that also carries prose.
    """
    frozen = json.loads((PHASE16 / "manifest.json").read_text())["source_digests"]
    assert frozen["gold_v2"] == f"sha256:{digest(GOLD_V2)}", "the DATASET moved"
    assert frozen["retrieval_v4"] == f"sha256:{digest(RETRIEVAL_V4)}"

    experiment = json.loads((PHASE16 / "manifest.json").read_text())["dataset"]
    manifest = json.loads(GOLD_V2_MANIFEST.read_text())
    assert experiment["digest"] == f"sha256:{manifest['sha256']['gold']}"
    assert experiment["case_count"] == manifest["case_count"]
    assert experiment["case_ids"] == manifest["case_ids"]
    assert experiment["resolves"] == manifest["resolves"]


def test_retrieval_v4_is_unchanged_and_its_budget_stays_spent() -> None:
    """One baseline scoring, already taken. A second needs an ADR in advance."""
    dataset = yaml.safe_load(RETRIEVAL_V4.read_text())
    assert dataset["version"] == "retrieval_v4"
    assert dataset["scorings_spent"] == 1
    assert dataset["scoring_budget"] == 1
    assert len(dataset["questions"]) == 36


def test_the_retrieval_baseline_was_not_re_scored() -> None:
    """Part J of Phase 17: the next official run uses THIS baseline.

    Re-scoring it under a different configuration would be
    `SYSTEM_CONFIGURATION_DRIFT`, and the drift would be invisible in a report that
    quoted only the newer number.
    """
    baseline = json.loads(BASELINE.read_text())
    configuration = baseline["configuration"]
    assert configuration["status"] == "ENGINEERING_DEFAULT_UNRESOLVED"
    assert configuration["embedding_model"] == "BAAI/bge-base-en-v1.5"
    assert configuration["reranker_model"] == "cross-encoder/ms-marco-MiniLM-L-6-v2"
    assert configuration["top_k"] == 40
    assert configuration["rerank_top_n"] == 5
    assert baseline["arm"]["recall_at_1"]["successes"] == 24
    assert baseline["arm"]["recall_at_1"]["total"] == 31


def test_the_gold_v2_scoring_budget_is_still_unspent() -> None:
    """The hold's whole purpose. A spent budget is not recoverable."""
    budget = json.loads(GOLD_V2_MANIFEST.read_text())["scoring_budget"]
    assert budget["scorings_spent"] == 0
    assert budget["allowed_scorings"] == 1
    assert budget["spent_by"] == []


# ---------------------------------------------------------------------------
# The threshold
# ---------------------------------------------------------------------------


def test_the_threshold_is_defined_once() -> None:
    """Every artefact that names it must agree with `ValidityRule`.

    Three records of one number is three places it can drift, so they are compared
    rather than trusted. Lowering it is the cheapest possible way to fake a fix.
    """
    from eval.validity import ValidityRule

    ceiling = ValidityRule().max_failure_rate
    seal = json.loads(SEAL.read_text())
    manifest = json.loads((PHASE16 / "manifest.json").read_text())
    assert seal["acceptance"]["max_failure_rate"] == ceiling
    assert manifest["experiment_validity_rule"]["max_failure_rate"] == ceiling
    assert ceiling == 0.10


def test_the_recorded_thresholds_have_not_moved() -> None:
    """Across every artefact that judged something under one."""
    from eval.validity import ValidityRule

    ceiling = ValidityRule().max_failure_rate
    for path in (
        REPO / "eval/reports/r86-gate-recheck/results.json",
        *sorted((REPO / "eval/reports/r86-revalidation").glob("*.json")),
    ):
        gate = json.loads(path.read_text())["gate"]
        assert gate["acceptance_threshold"] == ceiling, path.name


# ---------------------------------------------------------------------------
# Nothing was scored while the gate was blocked
# ---------------------------------------------------------------------------


def test_no_official_evaluation_output_exists() -> None:
    """The hold, asserted as an absence.

    A gate that blocks and lets the artefacts appear anyway has blocked nothing, and
    a partial `per_case.json` in a report directory is indistinguishable from a
    completed one to whoever reads it next.
    """
    from eval.official_gate import OfficialEvaluationGate

    assert not OfficialEvaluationGate.evaluate().permits_official_evaluation
    for artefact in ("per_case.json", "metrics.json", "failures.json", "coverage.json"):
        assert not (PHASE16 / artefact).is_file(), f"{artefact} exists under an evaluation hold"


def test_the_only_files_under_the_experiment_are_the_manifest_and_its_decision() -> None:
    """Stated as an exact set. A new file here is a new claim."""
    assert {p.name for p in PHASE16.iterdir()} == {"manifest.json", "AUTHORISATION.json"}


def test_the_earlier_experiment_reports_are_untouched() -> None:
    """Phase 14's seal still holds, and Phase 15's record is unchanged.

    Part G: no earlier phase may be reinterpreted. The cheapest reinterpretation is
    an edit, so the bytes are checked.
    """
    sealed = json.loads((REPO / "eval/reports/frozen-410-33/STATUS.json").read_text())
    for name, recorded in sealed["files"].items():
        path = REPO / "eval/reports/frozen-410-33" / name
        assert f"sha256:{digest(path)}" == recorded, name

    coverage = json.loads((REPO / "eval/reports/phase15-410-33/coverage.json").read_text())
    for name, recorded in coverage["source_digests"].items():
        path = REPO / "eval/reports/phase15-410-33" / name
        assert f"sha256:{digest(path)}" == recorded, name


def test_no_new_evaluation_metric_was_produced() -> None:
    """Part G. The revalidation records a provider result, not a system score.

    A revalidation file carrying an accuracy, an F1 or a confusion matrix would be
    an end-to-end evaluation wearing a diagnostic's name.
    """
    forbidden = ("accuracy", "macro_f1", "confusion_matrix", "precision", "recall")
    for path in sorted((REPO / "eval/reports/r86-revalidation").glob("*.json")):
        blob = path.read_text().lower()
        for token in forbidden:
            assert token not in blob, f"{path.name} contains {token!r}"


# ---------------------------------------------------------------------------
# The sealed reproducer
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def seal() -> dict[str, Any]:
    return json.loads(SEAL.read_text())


def test_the_seal_verifies_against_its_own_digest(seal: dict[str, Any]) -> None:
    from eval.official_gate import _seal_digest

    assert _seal_digest(seal) == seal["sealed_sha256"]


def test_the_seal_carries_everything_an_owner_needs(seal: dict[str, Any]) -> None:
    """Part A's field list, asserted so a future edit cannot quietly drop one."""
    assert seal["experiment_id"]
    assert seal["sealed_at"]
    for name in (
        "model",
        "system_prompt",
        "schema",
        "gateway_configuration",
        "firewall_configuration",
        "caller_key_id",
    ):
        assert seal["digests"][name].startswith("sha256:"), name
    request = seal["request"]
    assert request["temperature"] == 0.0
    assert request["structured_mode"] == "json_schema"
    assert request["max_tokens"] == 1536
    assert request["prompt_tokens_observed"] > 0
    assert request["cell"] == "intake/gold_note/long"
    observed = seal["observed"]
    assert observed["trials"] == observed["failures"] + observed["successes"]
    assert observed["determinism"]["deterministic"] is True
    assert observed["failure_classification"].startswith("SCHEMA_GRAMMAR_FAILURE")


def test_the_seal_carries_nothing_it_must_not(seal: dict[str, Any]) -> None:
    """It is written to be emailed. A manifest that cannot be sent gets paraphrased.

    Checked against the live secrets themselves, not against a pattern: a regex for
    "looks like a key" would pass a key that does not look like one.
    """
    from app.config.settings import Settings

    settings = Settings()
    blob = SEAL.read_text()
    for secret in (
        settings.llm_api_key.get_secret_value(),
        settings.llm_base_url,
        settings.llm_model,
        settings.llm_structured_model,
    ):
        if secret:
            assert secret not in blob, "a deployment value reached the sealed manifest"

    notes = [
        json.loads(line)["input"]["clinical_note"]
        for line in GOLD_V1.read_text().splitlines()
        if line.strip()
    ]
    for note in notes:
        for sentence in (s.strip() for s in note.split("\n") if len(s.strip()) > 25):
            assert sentence not in blob, "clinical text reached the sealed manifest"


def test_the_seal_states_its_classification_without_overstating_it(
    seal: dict[str, Any],
) -> None:
    """A verified failure, an unknown owner, and an explicit consequence.

    The temptation in an escalation is to name a culprit. The seal names the
    evidence and the question instead.
    """
    classification = seal["classification"]
    assert classification["status"] == "VERIFIED FAILURE"
    assert classification["attribution"] == "INDETERMINATE"
    assert classification["ownership"] == "OUTSIDE ENGINEERING CONTROL"
    assert classification["evaluation_impact"] == "OFFICIAL EVALUATION BLOCKED"
    assert seal["still_ambiguous"] == [
        "PROVIDER_DECODER versus FIREWALL_PROXY - MEDAUTH observes one hop"
    ]


def test_the_seal_records_the_contrast_that_makes_it_a_finding(
    seal: dict[str, Any],
) -> None:
    """Without the two contrasts it is "it sometimes fails", which nobody can action.

    Ten more prompt tokens of filler succeeding is the sentence that tells an owner
    where to look.
    """
    contrast = seal["contrast"]["same_schema_same_length_different_content"]
    assert contrast["failures"] == 0
    assert contrast["prompt_tokens"] > seal["request"]["prompt_tokens_observed"]
    length_only = seal["contrast"]["length_alone"]
    assert length_only["failures"] == 0
    assert length_only["max_prompt_tokens"] > seal["request"]["prompt_tokens_observed"]


def _prose(path: Path) -> str:
    """Markdown reduced to comparable prose: no emphasis, no blockquote markers,
    one space between words. An assertion that a reflow can break is an assertion
    about formatting, and it gets fixed by editing the test rather than the doc."""
    text = path.read_text(encoding="utf-8").lower().replace("**", "")
    lines = [line.lstrip("> ").rstrip() for line in text.splitlines()]
    return " ".join(" ".join(lines).split())


def test_the_escalation_quotes_the_sealed_digests(seal: dict[str, Any]) -> None:
    """A handoff document with a stale digest is worse than none.

    The escalation names four digests so the owner can confirm what they are looking
    at. If the seal is regenerated and the prose is not, they would be confirming a
    system that no longer exists - and would say so back to us with confidence.
    """
    escalation = (REPO / "docs/operations/r86-provider-escalation.md").read_text()
    for digest_value in (
        seal["digests"]["model"],
        seal["digests"]["caller_key_id"],
        seal["digests"]["schema"],
        f"sha256:{seal['sealed_sha256'][:16]}",
    ):
        assert digest_value in escalation, f"the escalation does not quote {digest_value}"


def test_the_escalation_asks_the_question_without_answering_it() -> None:
    """It must not attribute. The attribution is genuinely open.

    An escalation that names a culprit gets closed against the wrong team and
    reopened a month later.
    """
    # Blockquote markers are stripped before normalising: the question is quoted as
    # a `>` block and wraps across lines, so a naive whitespace join leaves "the >
    # non-terminating" and the assertion tests the renderer rather than the prose.
    escalation = _prose(REPO / "docs/operations/r86-provider-escalation.md")
    assert "which layer is producing the non-terminating" in escalation
    assert "we have not attributed this to either component" in escalation
    for overreach in (
        "the provider is responsible",
        "the firewall is responsible",
        "this is a provider bug",
        "this is a firewall bug",
    ):
        assert overreach not in escalation


def test_the_escalation_states_the_closure_criterion_and_refuses_to_bend_it() -> None:
    escalation = _prose(REPO / "docs/operations/r86-provider-escalation.md")
    assert "the threshold will not be adjusted" in escalation
    assert "the request shape will not be changed" in escalation
    assert "0.10" in escalation


def test_the_escalation_carries_no_secret_and_no_clinical_text() -> None:
    """It is written to be sent outside this machine."""
    from app.config.settings import Settings

    settings = Settings()
    blob = (REPO / "docs/operations/r86-provider-escalation.md").read_text()
    for secret in (
        settings.llm_api_key.get_secret_value(),
        settings.llm_base_url,
        settings.llm_model,
        settings.llm_structured_model,
    ):
        if secret:
            assert secret not in blob
    notes = [
        json.loads(line)["input"]["clinical_note"]
        for line in GOLD_V1.read_text().splitlines()
        if line.strip()
    ]
    for note in notes:
        for sentence in (s.strip() for s in note.split("\n") if len(s.strip()) > 25):
            assert sentence not in blob


# --------------------------------------------------------------------------- E-11
# The block, exercised rather than inspected
# ---------------------------------------------------------------------------


def test_an_evaluation_attempt_fails_before_the_first_gold_case() -> None:
    """**Behavioural, not structural.** Actually invoke a scorer and watch it refuse.

    Everything else in this file reads files and parses ASTs, which proves the block is
    *declared*. This proves it *bites*: the process is started with the live flag set,
    and it returns non-zero having produced nothing.

    The two assertions that make it non-vacuous are the last ones. A refusal that still
    wrote an artefact, or that still decremented a budget, would have stopped nothing -
    and R-101 is exactly that failure, recorded when a runner wrote `per_case.json`
    regardless of the gate.
    """
    import json
    import subprocess
    import sys

    reports = REPO / "eval/reports/phase16-410-33"
    before = {p.name for p in reports.iterdir()}
    budget_path = REPO / "data/gold/manifests/gold_v2.manifest.json"
    spent_before = json.loads(budget_path.read_text())["scoring_budget"]["scorings_spent"]

    result = subprocess.run(
        [sys.executable, "-m", "scripts.score_frozen_410_33"],
        cwd=REPO,
        capture_output=True,
        text=True,
        timeout=120,
        env={**os.environ, "MEDAUTH_LIVE_MODEL": "1"},
        check=False,
    )

    assert result.returncode != 0, "a scorer ran to completion while the gate was BLOCKED"
    assert "REFUSING" in result.stderr
    assert "BLOCKED" in result.stderr

    # Nothing was produced, and nothing was spent.
    assert {p.name for p in reports.iterdir()} == before, "the refused run left an artefact"
    assert (
        json.loads(budget_path.read_text())["scoring_budget"]["scorings_spent"] == spent_before
    ), "the refused run decremented the gold budget"
