"""The dataset boundary, and the proof that the official gate is actually called.

Closure audit, R-103/R-104. Three controls this repository *documented* were resting
on discipline:

1. `eval/official_gate.py` calls itself "the sole authorisation boundary" and had
   **no call site** outside its own tests. Every behavioural test passed. The gate
   was correct, complete, unbypassable - and nothing asked it anything.
2. CLAUDE.md has named `eval/schema.py:require_tunable(split)` since Phase 0 as the
   library boundary enforcing dev-only calibration, and both `R-23` and `R-25`
   recorded it as their mitigation. The module did not exist.
3. `scripts/phase16_prerun_gate.py --freeze-manifest` would overwrite an already
   frozen manifest whose digest `AUTHORISATION.json` records.

Each is the same failure in a different place: a control whose existence was asserted
by a document rather than exercised by a caller. So the tests here are deliberately
weighted towards **call-graph** and **AST** assertions rather than behaviour - a
behavioural test proves the gate works, and the thing that was broken is that nobody
used it.
"""

from __future__ import annotations

import ast
import json
from pathlib import Path

import pytest

from eval.schema import (
    TUNABLE_PARTITIONS,
    FrozenSplitError,
    Partition,
    ScoringBudgetExhausted,
    budget_for,
    require_scoring_budget,
    require_tunable,
)

pytestmark = [pytest.mark.evaluation, pytest.mark.security]

REPO = Path(__file__).resolve().parents[2]
SCRIPTS = REPO / "scripts"
SCHEMA_SOURCE = REPO / "eval/schema.py"
FROZEN_MANIFEST = REPO / "eval/reports/phase16-410-33/manifest.json"

#: The filenames that constitute an official evaluation result. A directory holding
#: any of these is a scored experiment to anyone reading the repository later.
OFFICIAL_ARTEFACTS = {"per_case.json", "metrics.json", "failures.json", "coverage.json"}

#: Anything that would let a caller answer a boundary's question for it. Same list
#: the official-gate suite uses; kept in step deliberately.
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


def official_artefact_writers() -> dict[Path, set[str]]:
    """Every script that writes an official evaluation artefact, found by parsing.

    Discovered, never enumerated. A hand-maintained list of runners is a list
    somebody forgets to add the next runner to, and the next runner is exactly the
    one that would not call the gate.
    """
    found: dict[Path, set[str]] = {}
    for script in sorted(SCRIPTS.glob("*.py")):
        tree = ast.parse(script.read_text(encoding="utf-8"))
        writes: set[str] = set()
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            if not isinstance(node.func, ast.Attribute):
                continue
            if node.func.attr not in {"write_text", "write_bytes", "open"}:
                continue
            # `(OUT / "per_case.json").write_text(...)` - the artefact name is a
            # constant somewhere in the receiver expression.
            for sub in ast.walk(node.func.value):
                if isinstance(sub, ast.Constant) and sub.value in OFFICIAL_ARTEFACTS:
                    writes.add(str(sub.value))
        if writes:
            found[script] = writes
    return found


# --------------------------------------------------------------------------- 1
# The gate is called
# ---------------------------------------------------------------------------


def gate_call_lines(script: Path) -> list[int]:
    """Lines where this script actually **calls** the gate.

    Deliberately not a substring search. The first draft of this test looked for
    `"OfficialEvaluationGate" in source` and was satisfied by the *import line* -
    so deleting the call while leaving the import passed it. That is the same class
    of defect the whole audit is about (a control that looks present), reproduced
    inside the test written to catch it, and it was found by the mutation harness
    rather than by reading.
    """
    calls: list[int] = []
    for node in ast.walk(ast.parse(script.read_text(encoding="utf-8"))):
        if (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr == "require"
            and isinstance(node.func.value, ast.Name)
            and node.func.value.id == "OfficialEvaluationGate"
        ):
            calls.append(node.lineno)
    return calls


def test_the_official_gate_has_at_least_one_call_site() -> None:
    """**The load-bearing test of this file.**

    Before the closure audit this failed: `OfficialEvaluationGate` was referenced by
    `eval/official_gate.py` and by `tests/`, and called by nothing. A gate with no
    caller passes every test it has and protects nothing.
    """
    callers = [path.name for path in sorted(SCRIPTS.glob("*.py")) if gate_call_lines(path)]
    assert callers, (
        "no script calls eval/official_gate.py. The module documents itself as "
        "the sole authorisation boundary for an official evaluation; a boundary "
        "nobody crosses is a comment."
    )


def test_every_writer_of_an_official_artefact_calls_the_gate() -> None:
    """Discovery, not a checklist - see `official_artefact_writers`."""
    writers = official_artefact_writers()
    assert writers, (
        "no script was detected as writing an official artefact. That is more likely "
        "a broken detector than a repository with no evaluation runners - check "
        "OFFICIAL_ARTEFACTS against what the runners actually emit."
    )

    offenders = [
        f"{script.name} writes {sorted(artefacts)}"
        for script, artefacts in writers.items()
        if not gate_call_lines(script)
    ]
    assert not offenders, (
        f"these scripts can produce an official evaluation result without asking the "
        f"gate: {offenders}. While R-86 is unresolved, each is a path to a scored "
        "hold-out that the authorisation boundary never sees."
    )


def test_the_gate_is_consulted_before_the_artefacts_are_written() -> None:
    """Order matters as much as presence.

    A run that scores 156 cases and *then* discovers it was unauthorised has already
    spent the budget. The check must precede every write, so its line number must be
    lower than the first artefact write in the same file.
    """
    for script, _ in official_artefact_writers().items():
        tree = ast.parse(script.read_text(encoding="utf-8"))
        gate_lines = gate_call_lines(script)
        write_lines = [
            node.lineno
            for node in ast.walk(tree)
            if isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr in {"write_text", "write_bytes"}
            and any(
                isinstance(sub, ast.Constant) and sub.value in OFFICIAL_ARTEFACTS
                for sub in ast.walk(node.func.value)
            )
        ]
        assert gate_lines, f"{script.name} never calls .require()"
        assert min(gate_lines) < min(write_lines), (
            f"{script.name} writes an official artefact at line {min(write_lines)} "
            f"but only consults the gate at line {min(gate_lines)}. A run authorised "
            "after it has scored is a run that scored."
        )


def test_the_gate_currently_blocks_every_runner() -> None:
    """Non-vacuity for the wiring above: the gate is not merely *called*, it *bites*.

    If R-86 is ever resolved and a revalidation PASSes, this assertion becomes wrong
    and should be changed then, in the same commit that records the PASS - not
    before. That is why it asserts the reason and not merely the state.
    """
    from eval.official_gate import AuthorisationState, OfficialEvaluationGate

    authorisation = OfficialEvaluationGate.evaluate()
    assert authorisation.state is AuthorisationState.BLOCKED
    assert not authorisation.permits_official_evaluation
    assert any("R-86" in reason for reason in authorisation.reasons)


# --------------------------------------------------------------------------- 2
# require_tunable
# ---------------------------------------------------------------------------


def test_exactly_one_partition_is_tunable() -> None:
    """Refusal by absence. A second member here is a design change, not a tweak."""
    assert TUNABLE_PARTITIONS == frozenset({Partition.DEVELOPMENT})


@pytest.mark.parametrize(
    "partition",
    [Partition.VALIDATION, Partition.GOLD, Partition.RETRIEVAL_BENCHMARK],
)
def test_a_frozen_partition_cannot_be_tuned_on(partition: Partition) -> None:
    with pytest.raises(FrozenSplitError, match="frozen"):
        require_tunable(partition)


def test_development_is_tunable_so_the_check_is_not_vacuous() -> None:
    """The positive control. Without it, `require_tunable` raising on everything
    would pass every test above and be useless."""
    assert require_tunable("development") is Partition.DEVELOPMENT


def test_an_unknown_split_is_refused_rather_than_admitted() -> None:
    """Failing in the safe direction. A name nobody recognises is not a new tunable
    partition - it is a typo, and a typo must not grant permission."""
    with pytest.raises(FrozenSplitError, match="not a partition"):
        require_tunable("dev")  # the plausible near-miss, not a nonsense string


# --------------------------------------------------------------------------- 3
# scoring budgets
# ---------------------------------------------------------------------------


def test_an_undeclared_budget_is_zero_not_one(tmp_path: Path) -> None:
    """The concrete defect this replaced.

    `scripts/score_retrieval_v4_baseline.py` read `dataset.get("scoring_budget", 1)`.
    A benchmark that declared no budget therefore acquired one, silently, from a
    default argument.
    """
    undeclared = tmp_path / "questions.yaml"
    undeclared.write_text("version: nameless\nquestions: []\n", encoding="utf-8")
    with pytest.raises(ScoringBudgetExhausted, match="no scoring allowance"):
        budget_for(undeclared)


def test_both_committed_manifest_shapes_are_read_by_one_implementation() -> None:
    """A gold manifest nests the budget; a retrieval questions file does not.

    Two shapes were previously read by two hand-written implementations. This asserts
    one function reads both, which is the point of the boundary.
    """
    gold = budget_for(REPO / "data/gold/manifests/gold_v2.manifest.json")
    retrieval = budget_for(REPO / "eval/datasets/retrieval_v4/questions.yaml")
    assert (gold.allowed, gold.spent) == (1, 0)
    assert (retrieval.allowed, retrieval.spent) == (1, 1)


def test_gold_v2s_single_scoring_is_still_unspent() -> None:
    """The fact the whole R-86 hold turns on. Asserted here as well as in the hold
    suite, because this file is the one a future runner's author reads."""
    budget = require_scoring_budget(
        REPO / "data/gold/manifests/gold_v2.manifest.json", experiment="closure-audit"
    )
    assert budget.spent == 0
    assert budget.remaining == 1


def test_an_exhausted_budget_raises() -> None:
    """gold_v1 has spent both of its declared scorings (Phase 14 and Phase 15)."""
    with pytest.raises(ScoringBudgetExhausted, match="budget is spent"):
        require_scoring_budget(
            REPO / "data/gold/manifests/gold_v1.manifest.json", experiment="closure-audit"
        )


# --------------------------------------------------------------------------- 4
# the boundary itself has no door
# ---------------------------------------------------------------------------


def test_the_schema_boundary_has_no_override_parameter() -> None:
    """Same structural test the official gate carries, for the same reason: a
    behavioural suite is green against a `force=True` nobody passes."""
    tree = ast.parse(SCHEMA_SOURCE.read_text(encoding="utf-8"))
    offenders: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef):
            names = [
                a.arg
                for a in [*node.args.posonlyargs, *node.args.args, *node.args.kwonlyargs]
                if a.arg not in {"self", "cls"}
            ]
            offenders += [
                f"{node.name}({name})"
                for name in names
                if any(token in name.lower() for token in BYPASS_TOKENS)
            ]
    assert not offenders, f"eval/schema.py accepts {offenders}"


def test_the_schema_boundary_reads_no_environment_variable() -> None:
    source = SCHEMA_SOURCE.read_text(encoding="utf-8")
    assert "import os" not in source
    assert "from os import" not in source
    tree = ast.parse(source)
    for node in ast.walk(tree):
        if isinstance(node, ast.Attribute) and node.attr in {"getenv", "environ"}:
            pytest.fail(f"eval/schema.py reads the environment at line {node.lineno}")


# --------------------------------------------------------------------------- 5
# a freeze cannot be re-taken
# ---------------------------------------------------------------------------


def test_the_frozen_manifest_refuses_to_be_refrozen() -> None:
    """R-104, asserted over the source because running it would need the database.

    `AUTHORISATION.json` records the digest of the manifest it decided about.
    Re-freezing rewrites the manifest and leaves the authorisation attesting to a
    configuration that no longer exists, without either file looking wrong.
    """
    source = (SCRIPTS / "phase16_prerun_gate.py").read_text(encoding="utf-8")
    tree = ast.parse(source)

    freeze_branch = [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.If)
        and any(
            isinstance(sub, ast.Attribute) and sub.attr == "freeze_manifest"
            for sub in ast.walk(node.test)
        )
    ]
    assert freeze_branch, "the --freeze-manifest branch has moved; re-point this test"
    guarded = any(
        isinstance(sub, ast.Attribute) and sub.attr == "is_file"
        for sub in ast.walk(freeze_branch[0])
    )
    assert guarded, (
        "--freeze-manifest no longer checks whether a manifest already exists. A "
        "freeze that can be re-taken is not a freeze."
    )


def test_the_authorisation_still_matches_the_manifest_it_decided_about() -> None:
    """The property the refusal above protects, checked against the committed files."""
    import hashlib

    authorisation = json.loads(
        (FROZEN_MANIFEST.parent / "AUTHORISATION.json").read_text(encoding="utf-8")
    )
    recorded = authorisation["manifest_digest"].removeprefix("sha256:")
    actual = hashlib.sha256(FROZEN_MANIFEST.read_bytes()).hexdigest()
    assert recorded == actual, (
        "the frozen manifest no longer hashes to the digest AUTHORISATION.json "
        "recorded. Something re-froze it, and the authorisation now attests to a "
        "configuration that is not there."
    )
    assert authorisation["status"] == "NOT_AUTHORISED"
