"""The official-evaluation gate: authoritative, and bypass-proof by construction.

Part J. The gate's job is to make one thing impossible while R-86 is unresolved:
scoring a frozen hold-out. "Impossible" is a strong word and it is earned two ways
here, not one.

**By behaviour.** A FAIL blocks, an INCONCLUSIVE blocks, a stale or unsealed evidence
chain blocks, and a PASS obtained under a moved threshold blocks. Each is injected
and confirmed, and `AUTHORISED` is proven reachable so nothing passes vacuously.

**By construction.** `eval/official_gate.py` is parsed and asserted to contain no
override parameter and no environment read. A behavioural test can be satisfied by a
gate with a `force=True` nobody exercised; an AST test cannot.
"""

from __future__ import annotations

import ast
import json
from pathlib import Path
from typing import Any

import pytest

from eval.official_gate import (
    AuthorisationState,
    EvaluationBlocked,
    OfficialEvaluationGate,
)
from eval.official_gate import _seal_digest as seal_digest

pytestmark = [pytest.mark.evaluation, pytest.mark.security]

REPO = Path(__file__).resolve().parents[2]
GATE_SOURCE = REPO / "eval/official_gate.py"
SEAL = REPO / "data/escalations/r86-reproducer.manifest.json"
REVALIDATIONS = REPO / "eval/reports/r86-revalidation"

#: Anything that would let a caller answer the gate's question for it.
BYPASS_TOKENS = (
    "force",
    "skip",
    "override",
    "bypass",
    "assume",
    "ignore",
    "disable",
    "debug",
    "unsafe",
    "allow_",
)


def sealed() -> dict[str, Any]:
    return json.loads(SEAL.read_text())


def revalidation(
    result: str, *, seal_sha: str | None = None, threshold: float = 0.1
) -> dict[str, Any]:
    """A revalidation record in the shape the gate reads."""
    return {
        "seal_sha256": seal_sha if seal_sha is not None else sealed()["sealed_sha256"],
        "ran_at": "2026-08-25T00:00:00+00:00",
        "gate": {
            "result": result,
            "acceptance_threshold": threshold,
            "production_failure_rate": 0.0 if result == "PASS" else 0.5,
            "why": f"synthetic {result} for a test",
            "permits_official_evaluation": result == "PASS",
        },
    }


@pytest.fixture
def sandbox(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Point the gate at a temporary evidence chain.

    The real one is committed and must stay untouched: a test that rewrote the
    sealed manifest to exercise a branch would be doing the exact thing the seal
    exists to prevent.
    """
    from eval import official_gate

    seal_path = tmp_path / "seal.json"
    runs = tmp_path / "revalidation"
    runs.mkdir()
    seal_path.write_text(json.dumps(sealed()))
    monkeypatch.setattr(official_gate, "SEAL", seal_path)
    monkeypatch.setattr(official_gate, "REVALIDATIONS", runs)
    return tmp_path


def write_run(sandbox: Path, record: dict[str, Any], name: str = "20260825T000000Z.json") -> None:
    (sandbox / "revalidation" / name).write_text(json.dumps(record))


# ---------------------------------------------------------------------------
# Bypass-proof by construction
# ---------------------------------------------------------------------------


def test_the_gate_has_no_override_parameter() -> None:
    """**The load-bearing structural test.**

    A behavioural suite can be entirely green against a gate carrying a `force=True`
    that no test happens to pass. This parses the module and asserts the parameter
    does not exist to be passed.
    """
    tree = ast.parse(GATE_SOURCE.read_text(encoding="utf-8"))
    offenders: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef):
            arguments = node.args
            names = [
                a.arg
                for a in [*arguments.posonlyargs, *arguments.args, *arguments.kwonlyargs]
                if a.arg not in {"self", "cls"}
            ]
            for name in names:
                if any(token in name.lower() for token in BYPASS_TOKENS):
                    offenders.append(f"{node.name}({name})")
    assert not offenders, (
        f"the gate accepts {offenders}. A parameter is somewhere to pass True from; "
        "the mechanism here is that there is nowhere."
    )


def test_the_gate_reads_no_environment_variable() -> None:
    """An env read is a bypass with a config file's clothes on."""
    source = GATE_SOURCE.read_text(encoding="utf-8")
    tree = ast.parse(source)
    for node in ast.walk(tree):
        if isinstance(node, ast.Attribute) and node.attr in {"getenv", "environ"}:
            pytest.fail(f"the gate reads the environment at line {node.lineno}")
    assert "import os" not in source
    assert "from os import" not in source


def test_evaluate_takes_no_arguments() -> None:
    """A caller must not be able to influence the answer at all."""
    import inspect

    assert list(inspect.signature(OfficialEvaluationGate.evaluate).parameters) == []
    assert list(inspect.signature(OfficialEvaluationGate.require).parameters) == []


def test_no_script_offers_a_forced_evaluation_path() -> None:
    """Across every runner, not only the gate.

    A gate nobody can bypass and a runner with `--force` beside it is a gate with a
    door next to it.
    """
    offenders: list[str] = []
    for script in sorted((REPO / "scripts").glob("*.py")):
        tree = ast.parse(script.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            # argparse flags are the realistic shape a bypass would take.
            if (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Attribute)
                and node.func.attr == "add_argument"
            ):
                for argument in node.args:
                    if isinstance(argument, ast.Constant) and isinstance(argument.value, str):
                        flag = argument.value.lstrip("-").replace("-", "_").lower()
                        if any(flag.startswith(token) for token in BYPASS_TOKENS):
                            offenders.append(f"{script.name}: {argument.value}")
    assert not offenders, f"forced-evaluation flags exist: {offenders}"


def test_replay_is_not_a_route_to_an_official_evaluation() -> None:
    """Replay stays a separate question with a separate mode.

    A gate satisfiable by a replay would be satisfiable by a fixture, which is the
    whole reason `RunMode.REPLAY` is excluded from `PRODUCTION_MODES` by absence.
    """
    from app.graph.slice import PRODUCTION_MODES, RunMode

    assert RunMode.REPLAY not in PRODUCTION_MODES
    source = GATE_SOURCE.read_text(encoding="utf-8")
    tree = ast.parse(source)
    for node in ast.walk(tree):
        named = (isinstance(node, ast.Name) and node.id == "REPLAY") or (
            isinstance(node, ast.Attribute) and node.attr == "REPLAY"
        )
        assert not named, "the gate recognises the replay mode in code"


# ---------------------------------------------------------------------------
# The verdicts
# ---------------------------------------------------------------------------


def test_a_passing_revalidation_authorises(sandbox: Path) -> None:
    """**Non-vacuity for the whole file.** AUTHORISED must be reachable.

    Without this, every refusal below could be passing because the gate refuses
    unconditionally.
    """
    write_run(sandbox, revalidation("PASS"))
    authorisation = OfficialEvaluationGate.evaluate()
    assert authorisation.state is AuthorisationState.AUTHORISED
    assert authorisation.permits_official_evaluation
    authorisation.require()  # must not raise


def test_a_failing_revalidation_blocks(sandbox: Path) -> None:
    write_run(sandbox, revalidation("FAIL"))
    authorisation = OfficialEvaluationGate.evaluate()
    assert authorisation.state is AuthorisationState.BLOCKED
    with pytest.raises(EvaluationBlocked, match="BLOCKED"):
        authorisation.require()


def test_an_inconclusive_revalidation_blocks_exactly_as_a_failure_does(sandbox: Path) -> None:
    """ "We could not tell" is not permission."""
    write_run(sandbox, revalidation("INCONCLUSIVE"))
    authorisation = OfficialEvaluationGate.evaluate()
    assert authorisation.state is AuthorisationState.INDETERMINATE
    assert not authorisation.permits_official_evaluation
    with pytest.raises(EvaluationBlocked):
        authorisation.require()


def test_no_revalidation_at_all_blocks(sandbox: Path) -> None:
    """Absence of evidence is not evidence of a fix."""
    authorisation = OfficialEvaluationGate.evaluate()
    assert authorisation.state is AuthorisationState.INDETERMINATE
    assert "no R-86 revalidation" in authorisation.reasons[0]


def test_a_missing_seal_blocks(sandbox: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from eval import official_gate

    monkeypatch.setattr(official_gate, "SEAL", sandbox / "absent.json")
    authorisation = OfficialEvaluationGate.evaluate()
    assert authorisation.state is AuthorisationState.INDETERMINATE
    assert "no sealed R-86 reproducer" in authorisation.reasons[0]


def test_only_authorised_permits() -> None:
    """Over the whole state space, so a fourth state is refused by default."""
    for state in AuthorisationState:
        assert state.permits_official_evaluation is (state is AuthorisationState.AUTHORISED)


# ---------------------------------------------------------------------------
# The ways a PASS could be manufactured
# ---------------------------------------------------------------------------


def test_a_pass_against_a_different_seal_does_not_authorise(sandbox: Path) -> None:
    """A PASS obtained under another configuration is a PASS for another system.

    The most convincing way to be wrong available here: the numbers are real, the
    verdict is real, and it is about something else.
    """
    write_run(sandbox, revalidation("PASS", seal_sha="0" * 64))
    authorisation = OfficialEvaluationGate.evaluate()
    assert authorisation.state is AuthorisationState.INDETERMINATE
    assert "different sealed configuration" in authorisation.reasons[0]


def test_a_pass_under_a_moved_threshold_does_not_authorise(sandbox: Path) -> None:
    """Leave the system alone and move the line. Injected, and refused.

    The revalidation says PASS at a 0.60 ceiling; the seal registers 0.10. A
    threshold that moved is not a system that improved.
    """
    write_run(sandbox, revalidation("PASS", threshold=0.6))
    authorisation = OfficialEvaluationGate.evaluate()
    assert authorisation.state is AuthorisationState.INDETERMINATE
    assert "threshold that moved" in authorisation.reasons[0]


def test_a_hand_edited_seal_does_not_authorise(sandbox: Path) -> None:
    """A manifest that disagrees with its own digest attests to nothing.

    Injected by flipping a single acceptance value - the edit somebody would
    actually make - and the gate must notice without being told which field moved.
    """
    tampered = sealed()
    tampered["acceptance"]["max_failure_rate"] = 0.9
    (sandbox / "seal.json").write_text(json.dumps(tampered))
    write_run(sandbox, revalidation("PASS", threshold=0.9))

    authorisation = OfficialEvaluationGate.evaluate()
    assert authorisation.state is AuthorisationState.INDETERMINATE
    assert "does not match its own digest" in authorisation.reasons[0]


def test_restoring_the_seal_restores_the_pass(sandbox: Path) -> None:
    """Inject → fail → restore → pass, completed.

    Without this the tampering test could be passing because the sandbox is broken
    rather than because the gate detected anything.
    """
    tampered = sealed()
    tampered["acceptance"]["max_failure_rate"] = 0.9
    (sandbox / "seal.json").write_text(json.dumps(tampered))
    write_run(sandbox, revalidation("PASS", threshold=0.9))
    assert OfficialEvaluationGate.evaluate().state is AuthorisationState.INDETERMINATE

    (sandbox / "seal.json").write_text(json.dumps(sealed()))
    write_run(sandbox, revalidation("PASS"))
    assert OfficialEvaluationGate.evaluate().state is AuthorisationState.AUTHORISED


def test_the_latest_run_decides_not_the_best_one(sandbox: Path) -> None:
    """Runs accumulate; a later FAIL is not overruled by an earlier PASS.

    Otherwise "it passed once" becomes the operative fact and the gate reports the
    most flattering run rather than the current one.
    """
    write_run(sandbox, revalidation("PASS"), name="20260101T000000Z.json")
    write_run(sandbox, revalidation("FAIL"), name="20260601T000000Z.json")
    assert OfficialEvaluationGate.evaluate().state is AuthorisationState.BLOCKED


# ---------------------------------------------------------------------------
# The real, committed evidence chain
# ---------------------------------------------------------------------------


def test_the_real_gate_is_currently_blocked() -> None:
    """The state of the world, asserted so a silent change is a red test."""
    authorisation = OfficialEvaluationGate.evaluate()
    assert authorisation.state is AuthorisationState.BLOCKED
    assert not authorisation.permits_official_evaluation
    assert "FAILED" in authorisation.reasons[0]
    assert authorisation.evidence["observed_failure_rate"] == 0.5
    assert authorisation.evidence["threshold"] == 0.1


def test_the_committed_seal_is_intact() -> None:
    manifest = sealed()
    assert seal_digest(manifest) == manifest["sealed_sha256"]
    assert manifest["classification"]["status"] == "VERIFIED FAILURE"
    assert manifest["classification"]["attribution"] == "INDETERMINATE"
    assert manifest["classification"]["ownership"] == "OUTSIDE ENGINEERING CONTROL"


def test_at_least_one_revalidation_has_been_recorded() -> None:
    """The harness is not theoretical: it has been run against the live path."""
    runs = sorted(REVALIDATIONS.glob("*.json"))
    assert runs, "no revalidation has ever run; the harness is untested"
    latest = json.loads(runs[-1].read_text())
    assert latest["configuration_matches_seal"] is True
    assert latest["trials_made"] == latest["trials_planned"]
    assert latest["gate"]["result"] in {"PASS", "FAIL", "INCONCLUSIVE"}
