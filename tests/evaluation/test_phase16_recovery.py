"""The measurement-recovery artefacts: R-86 diagnostics, retrieval_v4, coverage.

Parts A2/A3, C, E, F, H and K. Each test guards one way the recovery could look done
without being done - a diagnostic that leaks note text, a benchmark that passes an
audit checking nothing, a coverage report with one denominator, an invented cost.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
import yaml

pytestmark = [pytest.mark.evaluation, pytest.mark.security]

REPO = Path(__file__).resolve().parents[2]
GRADIENT = REPO / "eval/reports/r86-gradient"
RETRIEVAL_V4 = REPO / "eval/datasets/retrieval_v4/questions.yaml"
RETRIEVAL_AUDIT = REPO / "data/review/retrieval_v4_provenance.json"
RETRIEVAL_BASELINE = REPO / "eval/reports/retrieval-v4-baseline/results.json"
PHASE15 = REPO / "eval/reports/phase15-410-33"
GOLD_V1 = REPO / "data/gold/cases/gold_v1.jsonl"


# ---------------------------------------------------------------------------
# A2/A3 - the R-86 harness
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def gradient() -> dict[str, Any]:
    return json.loads((GRADIENT / "results.json").read_text())


@pytest.fixture(scope="module")
def factorial() -> dict[str, Any]:
    return json.loads((GRADIENT / "factorial_results.json").read_text())


def test_the_gradient_was_preregistered_before_it_ran(gradient: dict[str, Any]) -> None:
    """The matrix, the bands and the trial count are fixed before the first call.

    A diagnostic assembled after seeing which lengths failed would be a description
    of the failure rather than a test of it.
    """
    plan = json.loads((GRADIENT / "preregistration.json").read_text())
    assert plan["experiment"] == gradient["experiment"]
    assert plan["bands_words"] == gradient["preregistration"]["bands_words"]
    assert plan["varied"] == ["payload_length_words"]
    assert gradient["observations_made"] == plan["observations_planned"]


def test_only_length_varies_in_the_gradient(gradient: dict[str, Any]) -> None:
    """Everything else is held constant, and the digests prove it rather than say it."""
    held = gradient["preregistration"]["held_constant"]
    for key in ("model_digest", "prompt", "schema", "gateway_configuration_digest"):
        assert held[key].startswith("sha256:"), key
    assert held["temperature"] == 0.0
    assert held["attempts_per_observation"] == 1


def test_the_gradient_refuses_causation_and_curve_fitting(gradient: dict[str, Any]) -> None:
    """Seven points on a binary outcome. A fitted curve would be a decoration."""
    refused = " ".join(gradient["interpretation"]["claims_refused"]).lower()
    assert "causes" in refused or "causation" in refused
    prohibitions = " ".join(gradient["preregistration"]["prohibitions"]).lower()
    assert "regression" in prohibitions
    assert "causation may not be claimed" in prohibitions


def test_the_factorial_says_it_followed_a_null_result(factorial: dict[str, Any]) -> None:
    """A follow-up prompted by a null result is ordinary science - and it has to say so.

    Presenting it as though it had been planned all along would make the gradient's
    refutation disappear, which is the finding.
    """
    plan = factorial["preregistration"]
    assert plan["follows"] == "r86-gradient-001"
    why = plan["why_it_exists"].lower()
    assert "0/56" in why
    assert "after the null result" in why
    assert "before any factorial observation" in why


def test_the_factorial_records_the_instrument_defect(factorial: dict[str, Any]) -> None:
    """The first execution found a bug in the classifier, not in the system.

    Recorded in the artefact rather than fixed silently: a matrix re-executed after
    a change needs to say what changed, or "we ran it twice" reads as fishing.
    """
    note = factorial["instrument_note"].lower()
    assert "classifier" in note
    assert "malformed_response" in note
    assert "no hypothesis, threshold or cell was altered" in note


@pytest.mark.parametrize("report", ["results.json", "factorial_results.json"])
def test_no_clinical_text_reaches_an_r86_report(report: str) -> None:
    """The factorial SENDS real gold notes. None of their text may come back out.

    Checked against every sentence of every gold note rather than against a sample:
    a report that leaked one line would leak it in a file destined for a provider's
    support queue.
    """
    blob = (GRADIENT / report).read_text()
    notes = [
        json.loads(line)["input"]["clinical_note"]
        for line in GOLD_V1.read_text().splitlines()
        if line.strip()
    ]
    for note in notes:
        for sentence in (s.strip() for s in note.split("\n") if len(s.strip()) > 25):
            assert sentence not in blob, f"{report} contains clinical note text"


@pytest.mark.parametrize("report", ["results.json", "factorial_results.json"])
def test_no_deployment_value_reaches_an_r86_report(report: str) -> None:
    """Digests, never model ids or base URLs. These artefacts get exported."""
    blob = (GRADIENT / report).read_text().lower()
    for token in ("bearer ", "api_key", "localhost:", "http://", "jnan"):
        assert token not in blob, f"{report} contains {token!r}"


def test_the_r86_layer_is_still_undetermined(factorial: dict[str, Any]) -> None:
    """No factor result licenses naming the provider or the proxy.

    The factorial narrows what to vary; it cannot see past one hop, and the
    escalation asks the owner rather than answering for them.
    """
    refused = " ".join(factorial["interpretation"]["claims_refused"]).lower()
    assert "layer" in refused
    prohibitions = " ".join(factorial["preregistration"]["prohibitions"]).lower()
    assert "indistinguishable" in prohibitions


# ---------------------------------------------------------------------------
# C - retrieval_v4
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def audit() -> dict[str, Any]:
    return json.loads(RETRIEVAL_AUDIT.read_text())


def test_the_benchmark_is_provenance_clean(audit: dict[str, Any]) -> None:
    assert audit["counts"]["invalid_for_scoring"] == 0
    assert audit["categories_empty"] == []
    assert audit["counts"]["scorable"] == audit["counts"]["queries"]


def test_every_required_category_survives(audit: dict[str, Any]) -> None:
    """Ten categories, each non-empty. An empty one is reported, never dropped."""
    from scripts.build_retrieval_v4 import REQUIRED_CATEGORIES

    for category in REQUIRED_CATEGORIES:
        assert audit["categories_kept"].get(category, 0) > 0, category


def test_the_audit_rejects_a_broken_chain() -> None:
    """**Non-vacuity.** 36/36 passing proves nothing unless the audit can fail.

    Four independent breakages, one per link, each of which must be caught. Without
    this the audit could be `return True` and the benchmark would look verified.
    """
    from scripts.build_retrieval_v4 import _load_authority, audit_query

    authority = _load_authority()
    source = yaml.safe_load(RETRIEVAL_V4.read_text())
    healthy = next(q for q in source["questions"] if q["category"] == "DIRECT")
    assert audit_query(healthy, authority).scorable, "the control query must pass"

    breakages = {
        "unknown policy": {"expect": {**healthy["expect"], "policy_id": "42 CFR 999.99"}},
        "unknown criterion": {"expect": {**healthy["expect"], "criterion_id": "INVENTED_C99"}},
        "unlinked code": {"procedure_code": "ZZ999"},
        "no as_of": {"as_of": None},
    }
    for name, override in breakages.items():
        broken = {**healthy, **override}
        assert not audit_query(broken, authority).scorable, f"the audit accepted: {name}"


def test_a_negative_query_carries_no_relevant_label(audit: dict[str, Any]) -> None:
    """A negative query with a relevant section is not negative.

    It would also be scored in the wrong denominator, which is how a false-retrieval
    rate quietly becomes a recall figure.
    """
    source = yaml.safe_load(RETRIEVAL_V4.read_text())
    for query in source["questions"]:
        if query["category"] == "NEGATIVE":
            assert query.get("expect_no_relevant") is True, query["id"]
            assert not (query.get("expect") or {}).get("relevance"), query["id"]
            assert str(query.get("negative_reason", "")).strip(), query["id"]


def test_the_baseline_metrics_are_arithmetically_sound() -> None:
    """nDCG above 1 has been shipped by real systems. It cannot be here."""
    report = json.loads(RETRIEVAL_BASELINE.read_text())
    arm = report["arm"]
    assert 0.0 <= arm["ndcg_at_5"] <= 1.0
    assert 0.0 <= arm["mrr"] <= 1.0
    assert arm["recall_at_1"]["successes"] <= arm["recall_at_3"]["successes"]
    assert arm["recall_at_3"]["successes"] <= arm["recall_at_5"]["successes"]
    for k in (1, 3, 5):
        assert arm[f"recall_at_{k}"]["total"] == arm["ranking_denominator"]


def test_negatives_are_excluded_from_the_recall_denominator() -> None:
    """They have no relevant section to recall. Counting them flatters every arm."""
    report = json.loads(RETRIEVAL_BASELINE.read_text())
    arm = report["arm"]
    total = report["dataset"]["queries"]
    negatives = arm["false_retrieval_rate_on_negatives"]["total"]
    assert negatives > 0, "the benchmark has no negative queries to score separately"
    assert arm["ranking_denominator"] == total - negatives


def test_the_baseline_refuses_to_be_a_selection() -> None:
    """A baseline that could be quoted as 'the best configuration' is a selection."""
    report = json.loads(RETRIEVAL_BASELINE.read_text())
    assert report["configuration"]["status"] == "ENGINEERING_DEFAULT_UNRESOLVED"
    refused = " ".join(report["interpretation"]["claims_refused"]).lower()
    assert "best" in refused
    assert "separate arms" in refused


def test_the_benchmark_records_its_own_scoring_spend() -> None:
    source = yaml.safe_load(RETRIEVAL_V4.read_text())
    assert source["scorings_spent"] == 1
    assert source["scoring_budget"] == 1
    assert source["scored"] is True


# ---------------------------------------------------------------------------
# E, F, H - two denominators and no invented cost
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def coverage() -> dict[str, Any]:
    return json.loads((PHASE15 / "coverage.json").read_text())


def test_both_denominators_are_reported(coverage: dict[str, Any]) -> None:
    report = coverage["coverage"]
    assert report["operational"]["denominator"] == report["attempted"]
    assert report["decision_quality"]["denominator"] <= report["attempted"]
    assert "not overall system accuracy" in report["decision_quality"]["note"].lower()


def test_provider_failures_stay_in_the_operational_denominator(
    coverage: dict[str, Any],
) -> None:
    """The one thing Part E forbids: a coverage figure with the failures removed."""
    report = coverage["coverage"]
    failures = report["dispositions"]["PROVIDER_FAILURE"]["count"]
    assert failures > 0, "this run had no provider failures; the test proves nothing"
    assert report["operational"]["denominator"] == report["attempted"]
    assert report["attempted"] == report["operational"]["assessed"] + (
        report["attempted"] - report["operational"]["assessed"]
    )
    assert report["arithmetic"]["buckets_sum_to_attempted"] is True


def test_no_case_is_silently_excluded(coverage: dict[str, Any]) -> None:
    """Every attempted case is in exactly one bucket, and the buckets sum."""
    report = coverage["coverage"]
    total = sum(bucket["count"] for bucket in report["dispositions"].values())
    assert total == report["attempted"]
    assert report["unrecognised_dispositions"] == []


def test_a_provider_failure_is_never_called_a_model_error(coverage: dict[str, Any]) -> None:
    from eval.coverage import CaseDisposition

    names = {d.value for d in CaseDisposition}
    assert "MODEL_WRONG" not in names
    assert set(coverage["coverage"]["dispositions"]) == names
    assert (
        coverage["coverage"]["dispositions"]["PROVIDER_FAILURE"]["attributable_to"]
        == "PROVIDER_OR_FIREWALL"
    )


def test_only_assessed_cases_enter_decision_quality() -> None:
    from eval.coverage import CaseDisposition

    for disposition in CaseDisposition:
        assert disposition.enters_decision_quality is (disposition is CaseDisposition.ASSESSED)


def test_cost_is_unavailable_and_says_why(coverage: dict[str, Any]) -> None:
    """Part H. An estimate from a public price list would be a fabricated number."""
    cost = coverage["cost"]
    assert cost["status"] == "COST_NOT_AVAILABLE"
    assert cost["cost"] is None
    assert cost["prompt_tokens"] > 0
    assert "no price basis" in cost["why"].lower()
    assert cost["what_would_change_it"].strip()


def test_a_supplied_price_basis_is_computed_and_recorded() -> None:
    """**Non-vacuity for the test above.** The refusal is about missing data, not
    about an inability to divide."""
    from eval.coverage import cost_report

    computed = cost_report(
        prompt_tokens=2000,
        completion_tokens=1000,
        price_basis={"prompt_per_1k": 0.5, "completion_per_1k": 1.5, "currency": "USD"},
    )
    assert computed["status"] == "COMPUTED"
    assert computed["cost"] == pytest.approx(2.5)
    assert computed["price_basis"]["currency"] == "USD"


def test_the_re_report_did_not_modify_the_run_it_read(coverage: dict[str, Any]) -> None:
    """A re-analysis that rewrote its source would be a second scoring in disguise."""
    import hashlib

    for name, recorded in coverage["source_digests"].items():
        actual = f"sha256:{hashlib.sha256((PHASE15 / name).read_bytes()).hexdigest()}"
        assert actual == recorded, f"{name} changed after the re-report read it"
    assert "spends no scoring budget" in coverage["read_only"]
