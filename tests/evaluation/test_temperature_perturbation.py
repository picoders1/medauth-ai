"""`r86-temperature-perturbation-001`: one variable, and proof it was the only one.

A diagnostic is only worth its wall-clock if the reader can believe the claim that
exactly one field changed. So most of this file is about that claim rather than about
the result: the registered instrument must still be at temperature 0.0, the request
must be built by the reproducer's own function rather than a copy, the trial count must
be fixed before the run, and the whole thing must be structurally incapable of
authorising an official evaluation.

The load-bearing test is `test_the_reproducer_default_temperature_is_still_registered`.
`_observe_cell` gained a `temperature` parameter so this experiment could vary it
through the same code path the seal uses. That parameter is also the way the registered
reproducer could silently start running at something other than 0.0, which would make
every future revalidation a measurement of a different system.
"""

from __future__ import annotations

import ast
import inspect
import json
from pathlib import Path

import pytest

import scripts.r86_gradient as reproducer
import scripts.r86_temperature_perturbation as perturbation

pytestmark = [pytest.mark.evaluation, pytest.mark.security]

REPO = Path(__file__).resolve().parents[2]
EXPERIMENT = REPO / "eval/experiments/r86-temperature-perturbation-001"
MANIFEST = EXPERIMENT / "manifest.json"
RESULTS = EXPERIMENT / "results.json"
SEAL = REPO / "data/escalations/r86-reproducer.manifest.json"


def manifest() -> dict:
    return json.loads(MANIFEST.read_text(encoding="utf-8"))


def results() -> dict:
    return json.loads(RESULTS.read_text(encoding="utf-8"))


# --------------------------------------------------------------------------- 1
# Only temperature differs
# ---------------------------------------------------------------------------


def test_the_reproducer_default_temperature_is_still_registered() -> None:
    """**The load-bearing test.**

    `_observe_cell` gained a `temperature` parameter so the perturbation could reuse
    the sealed request path instead of copying it. That parameter is also how the
    registered reproducer could quietly start running at something else, which would
    make every future revalidation a measurement of a different system.
    """
    assert reproducer.TEMPERATURE == 0.0
    default = inspect.signature(reproducer._observe_cell).parameters["temperature"].default
    assert default == reproducer.TEMPERATURE, (
        "the reproducer's observation path no longer defaults to the registered "
        "temperature; every caller that does not pass one is now measuring something "
        "the seal does not describe"
    )


def test_the_experiment_changes_temperature_and_names_it() -> None:
    changed = manifest()["changed"]
    assert changed["field"] == "temperature"
    assert changed["registered"] == 0.0
    assert changed["perturbed"] == 0.2
    assert perturbation.REGISTERED_TEMPERATURE == 0.0
    assert perturbation.PERTURBED_TEMPERATURE == 0.2


def test_every_sealed_digest_agrees_with_the_parent() -> None:
    """The configuration claim, checked against the seal rather than restated."""
    record = manifest()
    assert record["digests_agree_with_parent_seal"] is True
    sealed = json.loads(SEAL.read_text(encoding="utf-8"))["digests"]
    for name in ("model", "schema", "system_prompt", "intake_instructions_template", "note_frame"):
        assert record["digests"][name] == sealed[name], f"{name} drifted from the seal"
    assert record["parent_seal_sha256"] == sealed_digest_of_seal()


def sealed_digest_of_seal() -> str:
    return json.loads(SEAL.read_text(encoding="utf-8"))["sealed_sha256"]


def test_the_request_is_built_by_the_reproducers_own_function() -> None:
    """Not a copy. A second implementation agrees with the first until it does not."""
    source = Path(perturbation.__file__).read_text(encoding="utf-8")
    assert "_observe_cell" in source
    tree = ast.parse(source)
    # No local re-implementation of the request builder.
    defined = {
        node.name
        for node in ast.walk(tree)
        if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef)
    }
    assert "_factorial_request" not in defined
    assert "harden_schema" not in defined


def test_the_runner_aborts_if_the_configuration_drifted() -> None:
    """Verified over the source: `verify_against_seal` is consulted, and its result
    stops the run before any call rather than being logged beside one."""
    source = Path(perturbation.__file__).read_text(encoding="utf-8")
    assert "verify_against_seal" in source
    assert "ABORTED_CONFIGURATION_DRIFT" in source
    assert "ABORTED_INSTRUMENT_TEMPERATURE_MOVED" in source
    # The drift check must precede client construction in the same function.
    body = source[source.index("async def run(") :]
    assert body.index("verify_against_seal") < body.index("LlmClient("), (
        "the configuration is verified after the client is built; a drifted run could "
        "reach the provider before anything noticed"
    )


# --------------------------------------------------------------------------- 2
# The registration cannot follow the result
# ---------------------------------------------------------------------------


def test_the_trial_count_is_fixed_and_was_honoured() -> None:
    assert manifest()["trial_count"] == 6
    assert perturbation.TRIALS == 6
    report = results()
    assert report["trials_planned"] == 6
    assert report["trials_made"] == 6
    assert len(report["observations"]) == 6


def test_the_manifest_refuses_to_be_refrozen() -> None:
    """R-104, applied to a diagnostic. A registration that can be re-taken after the
    numbers are in is not a registration."""
    source = Path(perturbation.__file__).read_text(encoding="utf-8")
    tree = ast.parse(source)
    freeze = [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.If)
        and any(
            isinstance(sub, ast.Attribute) and sub.attr == "freeze_manifest"
            for sub in ast.walk(node.test)
        )
    ]
    assert freeze, "the --freeze-manifest branch has moved; re-point this test"
    assert any(
        isinstance(sub, ast.Attribute) and sub.attr == "is_file" for sub in ast.walk(freeze[0])
    )


def test_the_outcome_bands_were_registered_before_the_run() -> None:
    """And the band the run landed in is one of them, not a fourth invented after."""
    bands = manifest()["success_criterion"]["bands"]
    assert bands == {k: list(v) for k, v in perturbation.OUTCOME_BANDS.items()}
    assert results()["classification"]["outcome"] in bands


def test_the_interpretation_is_the_registered_one_verbatim() -> None:
    """A sentence chosen once the numbers are known is a conclusion looking for its
    evidence. `classify_outcome` holds the prose, so the run cannot author it."""
    report = results()
    expected = perturbation.classify_outcome(report["failures"], report["trials_made"])
    assert report["classification"]["interpretation"] == expected["interpretation"]
    assert report["classification"]["outcome"] == expected["outcome"]


@pytest.mark.parametrize(
    ("failures", "expected"),
    [
        (0, "RUNAWAY_REDUCED"),
        (2, "RUNAWAY_REDUCED"),
        (3, "MIXED"),
        (5, "MIXED"),
        (6, "RUNAWAY_PERSISTS"),
    ],
)
def test_every_band_is_reachable_so_the_classifier_is_not_vacuous(
    failures: int, expected: str
) -> None:
    """Positive controls across the whole space. A classifier that returns one value
    would have passed every test above."""
    assert perturbation.classify_outcome(failures, 6)["outcome"] == expected


def test_the_registered_interpretations_refuse_both_overreaches() -> None:
    reduced = perturbation.classify_outcome(0, 6)["interpretation"]
    persists = perturbation.classify_outcome(6, 6)["interpretation"]
    assert "does NOT establish temperature as the root cause" in reduced
    assert "does NOT establish that temperature is unrelated" in persists


# --------------------------------------------------------------------------- 3
# It cannot authorise anything
# ---------------------------------------------------------------------------


def test_the_experiment_cannot_open_the_official_gate() -> None:
    """Structurally: the gate does not know this experiment exists.

    Not "it currently returns BLOCKED" - it reads only the seal and the sealed
    revalidations, so no diagnostic can reach it whatever the diagnostic found.
    """
    from eval.official_gate import AuthorisationState, OfficialEvaluationGate

    gate_source = (REPO / "eval/official_gate.py").read_text(encoding="utf-8")
    assert "temperature-perturbation" not in gate_source
    assert "r86_temperature_perturbation" not in gate_source

    authorisation = OfficialEvaluationGate.evaluate()
    assert authorisation.state is AuthorisationState.BLOCKED
    assert not authorisation.permits_official_evaluation


def test_r86_remains_blocked_regardless_of_the_perturbation_result() -> None:
    report = results()
    assert "Nothing" in report["authorises"]
    assert "BLOCKED" in report["authorises"]
    attribution = json.loads(
        (REPO / "data/escalations/r86-provider-attribution.json").read_text(encoding="utf-8")
    )
    assert attribution["r86"]["resolution"] == "UNRESOLVED"
    assert attribution["r86"]["official_evaluation"] == "BLOCKED"


def test_no_official_evaluation_artefact_exists() -> None:
    present = {p.name for p in (REPO / "eval/reports/phase16-410-33").iterdir()}
    assert present == {"manifest.json", "AUTHORISATION.json"}


def test_production_temperature_was_not_changed() -> None:
    """Part G. The diagnostic observes; it does not adopt."""
    from app.llm.client import LlmClient

    assert inspect.signature(LlmClient.chat).parameters["temperature"].default == 0.0


# --------------------------------------------------------------------------- 4
# The result, as recorded
# ---------------------------------------------------------------------------


def test_the_runaway_persisted_and_the_record_says_how() -> None:
    report = results()
    assert report["failures"] == 6
    assert report["classification"]["outcome"] == "RUNAWAY_PERSISTS"
    assert report["temperature"] == 0.2
    assert report["registered_temperature"] == 0.0
    assert all(o["finish_reason"] == "length" for o in report["observations"])
    assert all(o["parsed_as_json"] is False for o in report["observations"])


def test_the_one_divergent_trial_is_preserved_not_smoothed_away() -> None:
    """Trial 5 escaped the whitespace pattern and still failed to terminate.

    It is the whole finding, and a summary that reported only the median would have
    erased it - so the per-trial rows are asserted to still carry it.
    """
    observations = results()["observations"]
    divergent = [o for o in observations if o["whitespace_fraction"] < 0.5]
    assert len(divergent) == 1, "the heterogeneity across trials has been lost"
    trial = divergent[0]
    assert trial["non_whitespace_chars"] > 3000
    assert trial["finish_reason"] == "length"
    assert trial["parsed_as_json"] is False
    assert trial["is_r86_signature"] is False
    assert results()["deterministic"] is False


def test_the_report_contains_no_clinical_text() -> None:
    report = results()
    assert "None" in report["clinical_text_in_this_report"]
    for observation in report["observations"]:
        for key, value in observation.items():
            if isinstance(value, str) and key not in {
                "cell",
                "payload_digest",
                "payload_label",
                "finish_reason",
                "failure_kind",
                "attribution",
                "status_class",
            }:
                assert len(value) < 200, f"{key} is long enough to be text"
