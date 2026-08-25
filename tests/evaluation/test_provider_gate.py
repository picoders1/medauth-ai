"""The provider gate: three verdicts, and only one authorises scoring. Part Q.

Every test here defends the same boundary from a different side:

> **An external dependency must not become an internal success metric.**

The ways that fails are all cheap and all invisible in a report: lower the threshold,
change the request shape, read the easy cells, drop the failing one, or let
"we could not tell" drift into `PASS`. Each has a test, and each is proven
non-vacuous by injecting the violation and confirming the gate catches it.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from scripts.r86_gate_recheck import (
    PRODUCTION_CELL_PREFIX,
    Drift,
    GateResult,
    apply_gate,
)

pytestmark = [pytest.mark.evaluation, pytest.mark.security]

REPO = Path(__file__).resolve().parents[2]
RECHECK = REPO / "eval/reports/r86-gate-recheck/results.json"
AUTHORISATION = REPO / "eval/reports/phase16-410-33/AUTHORISATION.json"
MANIFEST = REPO / "eval/reports/phase16-410-33/manifest.json"
GOLD_V2_MANIFEST = REPO / "data/gold/manifests/gold_v2.manifest.json"

#: Eight cells at six trials each, as registered.
PLANNED = 48


def cell(failures: int, trials: int = 6) -> dict[str, Any]:
    return {
        "trials": trials,
        "provider_failure_rate": {
            "successes": failures,
            "total": trials,
            "value": round(failures / trials, 4),
        },
        "r86_signature_rate": {"successes": failures, "total": trials},
    }


def matrix(production_failures: int, *, flat_failures: int = 0) -> dict[str, Any]:
    """A full 8-cell matrix. Production failures land in the long production cell.

    The flat cells are settable so a test can prove the gate reads the production
    shape and nothing else.
    """
    return {
        "flat/filler/short": cell(flat_failures),
        "flat/filler/long": cell(flat_failures),
        "flat/gold_note/short": cell(flat_failures),
        "flat/gold_note/long": cell(flat_failures),
        "intake/filler/short": cell(flat_failures),
        "intake/filler/long": cell(flat_failures),
        "intake/gold_note/short": cell(0),
        "intake/gold_note/long": cell(production_failures),
    }


def gate(cells: dict[str, Any], **kwargs: Any) -> dict[str, Any]:
    defaults: dict[str, Any] = {"drifts": [], "observations_made": PLANNED, "planned": PLANNED}
    return apply_gate(cells, **(defaults | kwargs))


# ---------------------------------------------------------------------------
# The three verdicts
# ---------------------------------------------------------------------------


def test_the_gate_passes_when_the_production_shape_is_clean() -> None:
    """**Non-vacuity for the whole file.** The gate must be able to say PASS.

    0/12 on the production cells, well under the 0.10 ceiling. Without this, every
    test below could be passing because the gate refuses everything.
    """
    result = gate(matrix(0))
    assert result["result"] == GateResult.PASS.value
    assert result["permits_official_evaluation"] is True
    assert result["production_failure_rate"] == 0.0


def test_the_gate_fails_when_the_production_shape_is_degraded() -> None:
    """The observed situation: 6/12 = 0.5000 against a ceiling of 0.10."""
    result = gate(matrix(6))
    assert result["result"] == GateResult.FAIL.value
    assert result["permits_official_evaluation"] is False
    assert result["production_failure_rate"] == 0.5
    assert result["worst_cell"] == "intake/gold_note/long"


def test_configuration_drift_is_inconclusive_not_a_verdict() -> None:
    """A clean matrix measured under changed conditions decides nothing.

    This is the dangerous case: the numbers look like a PASS. They are a PASS for a
    different experiment, and reporting them under this one would be the strongest
    possible way to fake a fix.
    """
    result = gate(
        matrix(0),
        drifts=[Drift("model_digest", "sha256:aaaaaaaaaaaa", "sha256:bbbbbbbbbbbb")],
    )
    assert result["result"] == GateResult.INCONCLUSIVE.value
    assert result["permits_official_evaluation"] is False
    assert "no longer matches the registered reproducer" in result["why"]


def test_a_partial_matrix_is_inconclusive_in_either_direction() -> None:
    """A run that stopped early cannot decide the gate, however it was going.

    Asserted for a clean partial run as well as a dirty one: an aborted matrix that
    happened to be failing is no more decisive than one that happened to be passing.
    """
    for failures in (0, 6):
        result = gate(matrix(failures), observations_made=24)
        assert result["result"] == GateResult.INCONCLUSIVE.value, failures
        assert "24 of 48" in result["why"]


def test_an_empty_matrix_is_inconclusive() -> None:
    result = gate({})
    assert result["result"] == GateResult.INCONCLUSIVE.value
    assert result["permits_official_evaluation"] is False


def test_inconclusive_is_not_a_soft_pass() -> None:
    """It stops the evaluation exactly as FAIL does, and says so in the artefact."""
    assert not GateResult.INCONCLUSIVE.permits_official_evaluation
    assert not GateResult.FAIL.permits_official_evaluation
    assert GateResult.PASS.permits_official_evaluation
    result = gate({})
    assert "not a soft PASS" in result["note"]


# ---------------------------------------------------------------------------
# The ways the gate could be gamed
# ---------------------------------------------------------------------------


def test_the_gate_reads_the_production_shape_and_ignores_the_easy_cells() -> None:
    """`r86-gradient-001` scored 0/56 on a two-field probe.

    A gate reading the flat cells would certify a green light through the exact
    outage that made two evaluations uninterpretable. Injected here: every flat cell
    failing, every production cell clean, and the gate must still PASS - it is not
    reading them.
    """
    result = gate(matrix(0, flat_failures=6))
    assert result["result"] == GateResult.PASS.value
    assert result["cells_read"] == sorted(
        n for n in matrix(0) if n.startswith(PRODUCTION_CELL_PREFIX)
    )
    assert all(n.startswith(PRODUCTION_CELL_PREFIX) for n in result["cells_read"])


def test_dropping_the_failing_cell_does_not_produce_a_pass() -> None:
    """Selective exclusion, injected. It must become INCONCLUSIVE, never PASS.

    Removing the cell that fails is the most tempting single edit in this phase, and
    the one that would look most like success in a report.
    """
    reduced = {n: c for n, c in matrix(6).items() if n != "intake/gold_note/long"}
    result = gate(reduced, observations_made=42, planned=PLANNED)
    assert result["result"] != GateResult.PASS.value
    assert result["result"] == GateResult.INCONCLUSIVE.value


def test_the_threshold_comes_from_the_rule_not_from_the_gate() -> None:
    """One definition, so there is one place it can move.

    The gate echoes `ValidityRule().max_failure_rate` into its own output; a second
    literal here would be a second number to keep in step.
    """
    from eval.validity import VALIDITY_RULE_ID, ValidityRule

    result = gate(matrix(6))
    assert result["acceptance_threshold"] == ValidityRule().max_failure_rate
    assert result["rule_id"] == VALIDITY_RULE_ID


def test_the_boundary_is_asserted_from_both_sides() -> None:
    """A threshold tested only where it fails is satisfied by a gate that always fails.

    12 trials, ceiling 0.10: 1 failure is 0.0833 and passes, 2 is 0.1667 and fails.
    """
    assert gate(matrix(1))["result"] == GateResult.PASS.value
    assert gate(matrix(2))["result"] == GateResult.FAIL.value


# ---------------------------------------------------------------------------
# The recorded run
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def recheck() -> dict[str, Any]:
    return json.loads(RECHECK.read_text())


def test_the_recheck_ran_under_the_registered_conditions(recheck: dict[str, Any]) -> None:
    """Part A. A re-run under changed conditions is a different experiment."""
    conditions = recheck["registered_conditions"]
    assert conditions["unchanged"] is True
    assert conditions["drift"] == []
    held = conditions["held_constant"]
    observed = conditions["observed"]
    for field in ("model_digest", "temperature", "max_output_tokens", "structured_mode"):
        assert str(held[field]) == str(observed[field]), field


def test_the_reproducer_was_not_modified(recheck: dict[str, Any]) -> None:
    """Same cells, same trials, same design as `r86-factorial-001`."""
    plan = json.loads(
        (REPO / "eval/reports/r86-gradient/factorial_preregistration.json").read_text()
    )
    assert recheck["registered_conditions"]["observed"]["cells"] == plan["cells"]
    assert (
        recheck["registered_conditions"]["observed"]["trials_per_cell"] == plan["trials_per_cell"]
    )
    assert set(recheck["cells"]) == set(plan["cells"])


def test_the_failing_cell_is_deterministic(recheck: dict[str, Any]) -> None:
    """6/6, identical completion tokens and whitespace - a clean reproducer to escalate.

    Determinism is the useful part: the owner can reproduce this exactly rather than
    hunting an intermittent.
    """
    failing = recheck["cells"]["intake/gold_note/long"]
    assert failing["r86_signature_rate"]["successes"] == failing["trials"]
    assert failing["deterministic"] is True
    assert failing["median_whitespace_fraction"] > 0.9
    assert set(failing["attributions"]) == {"INDETERMINATE"}


def test_the_result_reproduces_phase16_cell_for_cell(recheck: dict[str, Any]) -> None:
    """Identical under verified-identical conditions: the defect persists."""
    for name, comparison in recheck["comparison_with_phase16"]["per_cell"].items():
        assert comparison["phase16_r86"] == comparison["phase17_r86"], name


def test_the_recheck_refuses_the_claims_it_cannot_support(recheck: dict[str, Any]) -> None:
    refused = " ".join(recheck["claims_refused"]).lower()
    assert "r-86 is fixed" in refused
    assert "provider or the firewall" in refused
    assert "lowering the threshold" in refused


def test_no_clinical_text_reaches_the_recheck_report() -> None:
    """The factorial SENDS gold notes; none of their text may come back out."""
    blob = RECHECK.read_text()
    notes = [
        json.loads(line)["input"]["clinical_note"]
        for line in (REPO / "data/gold/cases/gold_v1.jsonl").read_text().splitlines()
        if line.strip()
    ]
    for note in notes:
        for sentence in (s.strip() for s in note.split("\n") if len(s.strip()) > 25):
            assert sentence not in blob


# ---------------------------------------------------------------------------
# The authorisation decision
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def authorisation() -> dict[str, Any]:
    return json.loads(AUTHORISATION.read_text())


def test_the_experiment_was_not_authorised(authorisation: dict[str, Any]) -> None:
    assert authorisation["authorised"] is False
    assert authorisation["status"] == "NOT_AUTHORISED"
    assert authorisation["blockers"] == ["provider_gate"]


def test_no_official_result_exists_for_an_unauthorised_experiment(
    authorisation: dict[str, Any],
) -> None:
    """**The load-bearing test of Phase 17.**

    An unauthorised experiment must have produced no per-case record, no metrics and
    no failure analysis. A gate that stops the run and lets the artefacts appear
    anyway has stopped nothing.
    """
    assert not authorisation["authorised"]
    for artefact in ("per_case.json", "metrics.json", "failures.json", "coverage.json"):
        assert not (MANIFEST.parent / artefact).is_file(), (
            f"{artefact} exists for an experiment that was never authorised"
        )


def test_the_scoring_budget_was_not_spent(authorisation: dict[str, Any]) -> None:
    """The whole point of stopping. A refused run must cost nothing irreversible."""
    budget = json.loads(GOLD_V2_MANIFEST.read_text())["scoring_budget"]
    assert budget["scorings_spent"] == 0
    assert budget["spent_by"] == []
    assert not authorisation["authorised"]


def test_every_other_precondition_passed(authorisation: dict[str, Any]) -> None:
    """ "The provider path is the only thing wrong" is a checked statement.

    It is a materially different claim from "the provider path is wrong and so are
    three other things", and only an exhaustive check can tell them apart - which is
    why the authorisation does not short-circuit.
    """
    failed = [c["name"] for c in authorisation["checks"] if not c["passed"]]
    assert failed == ["provider_gate"]
    assert len(authorisation["checks"]) >= 14


def test_gold_integrity_was_verified_before_any_decision(
    authorisation: dict[str, Any],
) -> None:
    """Part I. Checked even though the run was refused for another reason."""
    checks = {c["name"]: c for c in authorisation["checks"]}
    for name in (
        "gold_v1_immutable",
        "gold_v2_matches_its_manifest",
        "gold_v2_unmoved_since_the_experiment_freeze",
        "structured_applicability_provenance",
        "no_narrative_only_ground_truth",
    ):
        assert checks[name]["passed"], name
        assert checks[name]["part"] == "I"


def test_the_frozen_configuration_was_verified(authorisation: dict[str, Any]) -> None:
    """Part E. Every frozen digest against the live one, before scoring."""
    checks = {c["name"]: c for c in authorisation["checks"]}
    for name in (
        "prompt_versions",
        "model_digest",
        "applicability_version",
        "gateway_configuration_digest",
    ):
        assert checks[name]["passed"], name


def test_the_retrieval_baseline_matches_the_frozen_configuration(
    authorisation: dict[str, Any],
) -> None:
    """Part J. A baseline scored under different settings is SYSTEM_CONFIGURATION_DRIFT."""
    check = next(
        c
        for c in authorisation["checks"]
        if c["name"] == "retrieval_baseline_matches_the_frozen_configuration"
    )
    assert check["passed"]
    assert "24/31" in check["detail"]


def test_the_frozen_manifest_was_not_edited(authorisation: dict[str, Any]) -> None:
    """An authorisation is ABOUT a manifest, not part of one.

    Rewriting a frozen manifest to record that it was refused would make the freeze
    conditional on the outcome.
    """
    import hashlib

    digest = f"sha256:{hashlib.sha256(MANIFEST.read_bytes()).hexdigest()}"
    assert authorisation["manifest_digest"] == digest
    assert "not edited" in authorisation["manifest_untouched"]


def test_the_forbidden_responses_are_named(authorisation: dict[str, Any]) -> None:
    """Written into the artefact so the next reader does not have to re-derive them."""
    forbidden = " ".join(authorisation["not_permitted_responses"]).lower()
    for phrase in (
        "lowering the acceptance threshold",
        "changing the reproducer",
        "excluding the failing cell",
        "running anyway",
    ):
        assert phrase in forbidden


# ---------------------------------------------------------------------------
# OD-40: the live signal, honestly answered
# ---------------------------------------------------------------------------


def test_no_live_signal_is_faked(recheck: dict[str, Any]) -> None:
    """A `/health` probe reports the proxy, not whether a decoder terminates.

    Integrating one would let the gate report GREEN through the exact outage it
    exists to catch, so OD-40 stays open rather than being closed by a probe that
    cannot see the failure.
    """
    signal = recheck["live_signal"]
    assert signal["verdict"] == "NO_TRUSTWORTHY_LIVE_SIGNAL"
    assert signal["od"] == "OD-40"
    assert "stays OPEN" in signal["decision"]
    assert signal["what_would_change_it"].strip()
    # It was actually probed rather than dismissed on paper.
    assert signal["probes"]
