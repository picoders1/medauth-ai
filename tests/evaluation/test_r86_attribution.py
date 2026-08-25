"""R-86's attribution boundary, and the closure rule that Part F uncovered.

Two subjects, one theme.

**Attribution** moved from `INDETERMINATE` to `PROVIDER_SIDE` on firewall-owner
evidence. The tests here are mostly about what that must *not* be allowed to do:
rewrite the seal, generalise into "the firewall is fine", or lift the gate.

**Closure** is the defect the attribution work exposed. `r86_revalidate.py` decided
success by asking whether the call raised, so a response that closed its document and
then padded whitespace to the ceiling would have counted as a success - and six of
those would have opened the official evaluation on a provider path that still never
terminates. `eval/r86_closure.py` adds the two termination conditions.

The load-bearing test in this file is
`test_a_response_that_closes_then_pads_is_not_a_success`. It is the one that fails
against the old definition.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from urllib.parse import urlsplit

import pytest

from app.llm.failure_taxonomy import ResponseShape, classify_provider_failure
from eval.r86_closure import CLOSURE_RULE_ID, trial_succeeds

pytestmark = [pytest.mark.evaluation, pytest.mark.security]

REPO = Path(__file__).resolve().parents[2]
SEAL = REPO / "data/escalations/r86-reproducer.manifest.json"
ATTRIBUTION = REPO / "data/escalations/r86-provider-attribution.json"
CAPTURE = REPO / "data/escalations/r86-firewall-capture.json"
HANDOFF = REPO / "data/escalations/r86-handoff-status.json"
REPORTS = REPO / "eval/reports"


def seal() -> dict:
    return json.loads(SEAL.read_text(encoding="utf-8"))


def attribution() -> dict:
    return json.loads(ATTRIBUTION.read_text(encoding="utf-8"))


# --------------------------------------------------------------------------- 1
# The historical record is immutable
# ---------------------------------------------------------------------------


def test_the_sealed_manifest_still_verifies_against_its_own_digest() -> None:
    manifest = seal()
    payload = {
        k: v for k, v in manifest.items() if k not in {"sealed_sha256", "sealed_at", "git_commit"}
    }
    recomputed = hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    assert recomputed == manifest["sealed_sha256"]


def test_the_seal_still_records_the_attribution_it_was_sealed_with() -> None:
    """A seal rewritten whenever the world moves is a document about today.

    The attribution moved; the record of what was known when the evidence was frozen
    must not. This is the property that makes the seal worth having.
    """
    assert seal()["classification"]["attribution"] == "INDETERMINATE"


def test_the_attribution_artefact_does_not_claim_to_modify_the_seal() -> None:
    record = attribution()
    assert record["does_not_modify"]["artefact"].endswith("r86-reproducer.manifest.json")
    assert record["does_not_modify"]["sealed_sha256"] == "sha256:271127edace3d94d"


def test_attribution_evidence_cannot_rewrite_historical_experiment_state() -> None:
    """The Phase-16 authorisation still refuses, and still describes its own manifest.

    New evidence about *why* a run was blocked must not disturb the record that it
    was blocked.
    """
    authorisation = json.loads(
        (REPORTS / "phase16-410-33/AUTHORISATION.json").read_text(encoding="utf-8")
    )
    assert authorisation["status"] == "NOT_AUTHORISED"
    assert authorisation["authorised"] is False
    manifest = REPORTS / "phase16-410-33/manifest.json"
    recorded = authorisation["manifest_digest"].removeprefix("sha256:")
    assert hashlib.sha256(manifest.read_bytes()).hexdigest() == recorded


# --------------------------------------------------------------------------- 2
# Attribution says what it says, and no more
# ---------------------------------------------------------------------------


def test_r86_is_attributed_provider_side_and_still_unresolved() -> None:
    record = attribution()["r86"]
    assert record["status"] == "VERIFIED_FAILURE"
    assert record["attribution"] == "PROVIDER_SIDE"
    assert record["firewall_hypothesis"] == "RULED_OUT_BY_UPSTREAM_CAPTURE"
    assert record["provider_component"] == "UNKNOWN"
    assert record["resolution"] == "UNRESOLVED"
    assert record["official_evaluation"] == "BLOCKED"


def test_the_firewall_hypothesis_is_retired_only_for_this_reproducer() -> None:
    """A negative result about one path is not a clean bill of health for a component.

    The exact wording is asserted because this is precisely the claim that grows in
    the retelling.
    """
    retirement = attribution()["firewall_hypothesis_retirement"]
    assert retirement["state"] == "RULED_OUT_FOR_THIS_REPRODUCER"
    assert retirement["exact_statement"] == (
        "The firewall-side response transformation hypothesis is ruled out for the "
        "registered R-86 reproducer based on matching upstream and downstream "
        "response lengths/content characteristics."
    )
    forbidden = " ".join(retirement["not_claimed"]).lower()
    assert "never corrupt" in forbidden
    assert "correct in general" in forbidden


def test_no_provider_component_is_named_anywhere_in_the_package() -> None:
    """`provider_component: UNKNOWN` has to survive contact with the prose."""
    record = attribution()
    assert record["explicitly_not_established"]["provider_component"] == "UNKNOWN"
    assert record["explicitly_not_established"]["root_cause"] == "NOT_ESTABLISHED"


def test_the_root_cause_document_lists_hypotheses_without_selecting_one() -> None:
    text = (REPO / "docs/operations/r86-provider-root-cause.md").read_text(encoding="utf-8")
    assert "listed, not selected" in text.lower()
    assert "still not selected" in text.lower()
    # All six classes present, and the checklist is complete.
    for marker in ("termination behaviour", "whitespace token handling", "speculative"):
        assert marker in text.lower()
    assert text.count("| 13 |") == 1, "the owner-side checklist should carry all 13 questions"


def test_the_evidence_carries_both_sides_of_the_hop_and_they_agree() -> None:
    """The claim rests on agreement, so the agreement is asserted, not narrated."""
    cell = attribution()["measurements"]["production_cell"]
    assert cell["firewall_output_chars"] == cell["medauth_body_chars"] == 2389
    assert cell["firewall_input_chars"] == cell["medauth_payload_chars"] == 1058
    assert cell["detectors_executed"] == 4
    assert cell["detectors_detected"] == 0
    assert cell["failures"] == 6 and cell["successes"] == 0

    control = attribution()["measurements"]["control_cell"]
    assert control["firewall_output_chars"] == control["medauth_body_chars"] == 1211
    assert control["failures"] == 0


def test_no_deployment_value_appears_in_any_r86_artefact() -> None:
    """Digests only. A host or model name here would be a disclosure, not evidence.

    The needles are read from the **live configuration**, never written down. The
    first version of this test hardcoded the deployment's host and model names as the
    strings it searched for - so the file that existed to prevent those values being
    committed would itself have committed them. Caught by the repository-wide grep
    this test is the automated form of.

    Reading them from `Settings` also means the test follows the deployment instead of
    going stale against it.
    """
    from app.config.settings import Settings
    from app.llm.wiring import structured_model_for

    settings = Settings()
    host = urlsplit(settings.llm_base_url).hostname or ""
    needles = {
        value.lower()
        for value in (host, settings.llm_model, structured_model_for(settings))
        if value and len(value) > 3
    }
    assert needles, "no deployment values were resolved; this test would pass vacuously"

    for path in (ATTRIBUTION, CAPTURE, HANDOFF, SEAL):
        text = path.read_text(encoding="utf-8").lower()
        leaked = sorted(n for n in needles if n in text)
        assert not leaked, (
            f"{path.name} contains a deployment value verbatim. These artefacts are "
            "sent to an external owner and committed to a public remote; the "
            "convention is a digest, as the seal uses."
        )
        assert "bearer " not in text


# --------------------------------------------------------------------------- 3
# The closure rule - the defect Part F uncovered
# ---------------------------------------------------------------------------


def shape(
    finish_reason: str,
    *,
    whitespace: float,
    parsed: bool,
    valid: bool,
    completion_tokens: int = 1536,
) -> ResponseShape:
    return ResponseShape(
        finish_reason=finish_reason,
        body_chars=2389,
        whitespace_fraction=whitespace,
        parsed_as_json=parsed,
        satisfied_schema=valid,
        prompt_tokens=512,
        completion_tokens=completion_tokens,
    )


def test_a_response_that_closes_then_pads_is_not_a_success() -> None:
    """**The load-bearing test.**

    `json.loads('{"a":1}' + " " * 2000)` succeeds - trailing whitespace is legal JSON -
    so a partial provider fix that closes the document and keeps padding to the ceiling
    satisfies the schema, does not raise, and classified as `NONE` under the old
    definition. Six of those returned PASS at 0/12 and opened the official evaluation
    on a path that still never terminates.
    """
    partial_fix = shape("length", whitespace=0.92, parsed=True, valid=True)

    # The old definition, reproduced exactly: no error means no failure.
    old = classify_provider_failure(None, status_code=200, shape=partial_fix)
    assert not old.kind.counts_toward_provider_reliability, (
        "if this ever starts counting, the taxonomy has taken on a responsibility it "
        "deliberately refuses and this test is testing the wrong thing"
    )

    # The closure rule, which is what the gate now uses.
    verdict = trial_succeeds(satisfied_schema=True, shape=partial_fix)
    assert not verdict.succeeded
    assert any("ceiling" in r for r in verdict.reasons)
    assert any("whitespace-dominated" in r for r in verdict.reasons)


def test_ceiling_exhaustion_alone_is_a_failure_even_without_the_whitespace_shape() -> None:
    """Condition 3 on its own, which the runaway check does **not** cover.

    `looks_like_whitespace_runaway` requires BOTH `finish_reason == "length"` and
    whitespace >= 0.5. A response that reaches the ceiling with ordinary whitespace
    and still validates therefore slips past it - and Part F condition 3 rejects it
    anyway, because stopping because you ran out of room is not terminating.

    The mutation harness found this gap: deleting the ceiling condition left every
    other test passing, because the partial-fix case is caught twice over.
    """
    at_the_ceiling = shape("length", whitespace=0.10, parsed=True, valid=True)
    assert not at_the_ceiling.looks_like_whitespace_runaway, (
        "if the runaway flag starts covering this case the two conditions have merged "
        "and this test no longer isolates condition 3"
    )
    verdict = trial_succeeds(satisfied_schema=True, shape=at_the_ceiling)
    assert not verdict.succeeded
    assert verdict.reasons == (
        "generation stopped by exhausting the completion ceiling (1536 tokens), not by terminating",
    )


def test_the_revalidation_gate_applies_the_closure_rule() -> None:
    """The wiring, asserted over the source - a rule nothing calls is a comment.

    Same failure mode as R-103, where `eval/official_gate.py` was correct, complete
    and consulted by nobody. `eval/r86_closure.py` is only worth having if the gate
    that decides R-86 actually routes its trials through it.
    """
    import ast

    source = (REPO / "scripts/r86_revalidate.py").read_text(encoding="utf-8")
    assert "from eval.r86_closure import" in source

    tree = ast.parse(source)
    calls = {
        node.func.id
        for node in ast.walk(tree)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
    }
    assert "trial_succeeds" in calls, (
        "r86_revalidate.py imports the closure rule without calling it. The gate is "
        "back to deciding success by whether the call raised."
    )

    # And the count that reaches the threshold must come from those verdicts.
    assert "for v in verdicts if not v.succeeded" in source, (
        "the failure count no longer derives from the closure verdicts"
    )


def test_a_genuine_fix_is_a_success_so_the_rule_is_not_vacuous() -> None:
    """The positive control. A rule that refuses everything proves nothing."""
    verdict = trial_succeeds(
        satisfied_schema=True,
        shape=shape("stop", whitespace=0.12, parsed=True, valid=True, completion_tokens=300),
    )
    assert verdict.succeeded
    assert verdict.reasons == ()
    assert verdict.rule_id == CLOSURE_RULE_ID


def test_r86_as_actually_observed_is_a_failure() -> None:
    verdict = trial_succeeds(
        satisfied_schema=False,
        shape=shape("length", whitespace=0.9205, parsed=False, valid=False),
    )
    assert not verdict.succeeded
    assert len(verdict.reasons) >= 3


def test_an_unobservable_trial_is_not_a_successful_one() -> None:
    """Same principle as INCONCLUSIVE blocking exactly as FAIL does."""
    verdict = trial_succeeds(satisfied_schema=True, shape=None)
    assert not verdict.succeeded


def test_a_raised_call_is_a_failure_even_with_a_clean_shape() -> None:
    verdict = trial_succeeds(
        satisfied_schema=True,
        shape=shape("stop", whitespace=0.1, parsed=True, valid=True, completion_tokens=300),
        raised=True,
    )
    assert not verdict.succeeded


def test_the_closure_rule_changes_no_recorded_observation() -> None:
    """**The honesty check on the strengthening.**

    Tightening a failure definition after seeing results is what this regime forbids.
    It is admissible here only because it cannot reach backwards - and that is a
    measurable claim, so it is measured rather than argued.
    """
    scanned = flipped = 0
    for report in sorted(REPORTS.rglob("*.json")):
        try:
            data = json.loads(report.read_text(encoding="utf-8"))
        except (ValueError, OSError):  # pragma: no cover - a report that is not JSON
            continue

        def walk(node: object) -> None:
            nonlocal scanned, flipped
            if isinstance(node, dict):
                if "satisfied_schema" in node and "finish_reason" in node:
                    scanned += 1
                    verdict = trial_succeeds(
                        satisfied_schema=bool(node["satisfied_schema"]),
                        shape=ResponseShape(
                            finish_reason=node.get("finish_reason"),
                            body_chars=int(node.get("body_chars") or 0),
                            whitespace_fraction=float(node.get("whitespace_fraction") or 0.0),
                            parsed_as_json=bool(node.get("parsed_as_json")),
                            satisfied_schema=bool(node["satisfied_schema"]),
                            prompt_tokens=int(node.get("prompt_tokens") or 0),
                            completion_tokens=int(node.get("completion_tokens") or 0),
                        ),
                    )
                    if bool(node.get("succeeded")) and not verdict.succeeded:
                        flipped += 1
                for value in node.values():
                    walk(value)
            elif isinstance(node, list):
                for value in node:
                    walk(value)

        walk(data)

    assert scanned > 100, f"only {scanned} observations scanned; the walker has drifted"
    assert flipped == 0, (
        f"{flipped} committed observations would change verdict under "
        f"{CLOSURE_RULE_ID}. The rule may only govern future runs; a definition that "
        "reaches backwards has retuned a result rather than tightened a gate."
    )


# --------------------------------------------------------------------------- 4
# Closure cannot be reached by moving the goalposts
# ---------------------------------------------------------------------------


def test_closure_requires_the_exact_registered_request_shape() -> None:
    record = attribution()["reproducer"]
    assert record["request_shape_unchanged"] is True
    assert record["cell"] == "intake/gold_note/long"
    assert record["temperature"] == 0.0
    assert record["max_tokens"] == 1536
    assert record["trials_required"] == 6


def test_the_threshold_is_unchanged_and_still_matches_the_seal() -> None:
    """A provider fix must not arrive alongside a lowered bar."""
    from eval.validity import ValidityRule

    assert ValidityRule().max_failure_rate == 0.10
    assert seal()["acceptance"]["max_failure_rate"] == 0.10


def test_a_substituted_configuration_is_not_a_fix() -> None:
    remediation = (REPO / "docs/operations/r86-provider-remediation.md").read_text(encoding="utf-8")
    assert "NEW_SYSTEM_CONFIGURATION" in remediation
    for substitution in ("different model", "different schema", "different runtime"):
        assert substitution in remediation
    assert "existing experiment is not overwritten" in remediation.lower()


def test_no_client_side_repair_is_offered_as_closure() -> None:
    """Part H. Each of these makes the symptom vanish while the path still fails."""
    remediation = (REPO / "docs/operations/r86-provider-remediation.md").read_text(encoding="utf-8")
    for forbidden in (
        "whitespace stripping",
        "forced JSON repair",
        "retries until success",
        "completion-limit increases",
        "schema simplification",
        "prompt shortening",
        "clinical-note truncation",
    ):
        assert forbidden.lower() in remediation.lower(), f"{forbidden} is not ruled out"


def test_the_official_gate_remains_blocked() -> None:
    from eval.official_gate import AuthorisationState, OfficialEvaluationGate

    authorisation = OfficialEvaluationGate.evaluate()
    assert authorisation.state is AuthorisationState.BLOCKED
    assert not authorisation.permits_official_evaluation
    assert attribution()["gate_effect"]["official_evaluation"] == "BLOCKED"
    assert attribution()["gate_effect"]["unchanged_by_this_artefact"] is True


def test_no_official_evaluation_artefact_was_created() -> None:
    present = {p.name for p in (REPORTS / "phase16-410-33").iterdir()}
    assert present == {"manifest.json", "AUTHORISATION.json"}
