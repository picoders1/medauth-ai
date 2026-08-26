"""Structural enforcement of the governing invariant.

    Models produce per-criterion verdicts. Code produces the decision.

These tests parse the **source** rather than importing it, so a violation is
caught even in a module that is never executed, never imported, and never
covered by any other test. That property is the point: an architectural rule
enforced only by convention decays under maintenance pressure, and this one is
the reason a prompt injection cannot produce an approval (ADR-001, ADR-010).

Written in Phase 0, before there was anything to violate.
"""

from __future__ import annotations

import ast
from dataclasses import dataclass
from pathlib import Path

import pytest

pytestmark = pytest.mark.unit

APP = Path(__file__).resolve().parents[2] / "app"

#: Packages holding domain logic. None of them may reach orchestration or transport.
DOMAIN_PACKAGES = (
    "intake",
    "policy",
    "retrieval",
    "adjudication",
    "guardrail",
    "decision",
    "audit",
)

#: Packages forbidden from naming an outcome at all.
VERDICT_ONLY_PACKAGES = ("intake", "adjudication")

#: Tokens that must not appear in a package that may only produce verdicts.
OUTCOME_TOKENS = (
    "APPROVE_RECOMMENDED",
    "DENY_RECOMMENDED",
    "Recommendation",
    "Outcome",
    "DecisionRule",
)

#: Modules that perform I/O, reach the network, or read a clock. `app.decision`
#: must be a pure function of its arguments or the truth-table suite proves
#: nothing about production behaviour.
IMPURE_MODULES = frozenset(
    {
        "asyncio",
        "asyncpg",
        "httpx",
        "io",
        "os",
        "pathlib",
        "random",
        "requests",
        "secrets",
        "shutil",
        "socket",
        "sqlalchemy",
        "subprocess",
        "tempfile",
        "time",
        "urllib",
        "uuid",
    }
)

#: Attribute calls that introduce non-determinism even from an allowed module.
IMPURE_CALLS = frozenset({"now", "today", "utcnow", "monotonic", "perf_counter", "time"})


@dataclass(frozen=True)
class ModuleImports:
    """Absolute module names imported by one source file."""

    path: Path
    package: str
    imports: frozenset[str]
    tree: ast.Module

    @property
    def rel(self) -> str:
        return str(self.path.relative_to(APP.parent))


def _package_of(path: Path) -> str:
    rel = path.relative_to(APP)
    return rel.parts[0] if len(rel.parts) > 1 else ""


def _resolve(node: ast.ImportFrom, path: Path) -> str:
    """Resolve a relative ``from . import x`` to its absolute dotted name."""
    if not node.level:
        return node.module or ""
    # `app/llm/client.py` at level 1 is package `app.llm`; each extra level pops one.
    parts = list(path.relative_to(APP.parent).with_suffix("").parts)
    if parts[-1] == "__init__":
        parts.pop()
    base = parts[: len(parts) - node.level]
    return ".".join([*base, node.module] if node.module else base)


def _load() -> list[ModuleImports]:
    modules: list[ModuleImports] = []
    for path in sorted(APP.rglob("*.py")):
        source = path.read_text(encoding="utf-8")
        tree = ast.parse(source, filename=str(path))
        names: set[str] = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                names.update(alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom):
                resolved = _resolve(node, path)
                if resolved:
                    names.add(resolved)
                    names.update(f"{resolved}.{a.name}" for a in node.names)
        modules.append(
            ModuleImports(path=path, package=_package_of(path), imports=frozenset(names), tree=tree)
        )
    return modules


MODULES = _load()


def _in(package: str) -> list[ModuleImports]:
    return [m for m in MODULES if m.package == package]


def test_app_tree_is_non_empty() -> None:
    """Guard against every rule below passing vacuously on an empty tree."""
    assert len(MODULES) >= 10, f"only {len(MODULES)} modules found under {APP}"
    for package in (*DOMAIN_PACKAGES, "core"):
        assert (APP / package).is_dir(), f"missing package app/{package}"


# --------------------------------------------------------------------------- 1
def test_core_imports_nothing_from_app() -> None:
    """`app.core` is the base of the dependency graph and depends on no layer.

    Its own modules may compose - `hashing` builds on `normalize` - so the rule is
    "no *other* app package", not "no app import at all". Phase 0 wrote the stricter
    form because core had no internal imports yet; Phase 1 added one and exposed it.
    """
    for module in _in("core"):
        offenders = {
            i
            for i in module.imports
            if (i == "app" or i.startswith("app.")) and not i.startswith("app.core")
        }
        assert not offenders, (
            f"{module.rel} imports another app package: {sorted(offenders)}. "
            "app.core is the base of the dependency graph."
        )


# --------------------------------------------------------------------------- 2
def test_decision_imports_only_core() -> None:
    """`app.decision` may reach `app.core` and its own modules, nothing else.

    A package composing its own modules is not a layer violation - the rule is about
    which *other* layers may be reached. Phase 0 wrote this as "nothing but core"
    because every package was then a single module. Phase 1 exposed the same
    oversight in rule 1, and the data-foundation phase exposed it here.
    """
    for module in _in("decision"):
        offenders = {
            i
            for i in module.imports
            if i.startswith("app.") and not i.startswith(("app.core", "app.decision"))
        }
        assert not offenders, (
            f"{module.rel} reaches another layer: {sorted(offenders)}. "
            "The decision surface must stay a pure function of its arguments."
        )


def test_decision_is_pure() -> None:
    """No I/O, no network, no database, no clock, no randomness in `app.decision`."""
    for module in _in("decision"):
        impure = {i for i in module.imports if i.split(".")[0] in IMPURE_MODULES}
        assert not impure, f"{module.rel} imports impure module(s): {sorted(impure)}"

        for node in ast.walk(module.tree):
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
                assert node.func.attr not in IMPURE_CALLS, (
                    f"{module.rel}:{node.lineno} calls .{node.func.attr}() - "
                    "a clock or entropy source makes decide() irreproducible."
                )


# --------------------------------------------------------------------------- 3
def test_verdict_packages_cannot_reach_the_decision() -> None:
    """`app.intake` and `app.adjudication` cannot import `app.decision`."""
    for package in VERDICT_ONLY_PACKAGES:
        for module in _in(package):
            offenders = {i for i in module.imports if i.startswith("app.decision")}
            assert not offenders, f"{module.rel} imports {sorted(offenders)}"


@pytest.mark.security
def test_no_outcome_vocabulary_in_verdict_packages() -> None:
    """An approval or denial cannot even be *named* where a model's output is shaped.

    This is the schema test. A model filling a closed schema in these packages has
    no field to write an outcome into, because the token does not exist here.
    """
    for package in VERDICT_ONLY_PACKAGES:
        for module in _in(package):
            source = module.path.read_text(encoding="utf-8")
            for token in OUTCOME_TOKENS:
                assert token not in source, (
                    f"{module.rel} names '{token}'. Packages that shape model output "
                    "may produce per-criterion verdicts only (ADR-010)."
                )


# --------------------------------------------------------------------------- 4
def test_domain_cannot_reach_orchestration_or_transport() -> None:
    """Domain logic is callable and testable without a graph or an HTTP layer."""
    for package in DOMAIN_PACKAGES:
        for module in _in(package):
            offenders = {i for i in module.imports if i.startswith(("app.graph", "app.api"))}
            assert not offenders, f"{module.rel} imports {sorted(offenders)}"


# --------------------------------------------------------------------------- 5
def test_langgraph_is_confined_to_the_graph_package() -> None:
    """The orchestration framework stays replaceable (ADR-002)."""
    for module in MODULES:
        if module.package == "graph":
            continue
        offenders = {i for i in module.imports if i.split(".")[0] == "langgraph"}
        assert not offenders, (
            f"{module.rel} imports langgraph. It belongs only in app/graph/, so that "
            "every domain step stays a plain async function."
        )


# --------------------------------------------------------------------------- 6
#: Roots production may never import. `tests` is here so a fixture gateway cannot
#: become a production code path - see the docstring below.
FORBIDDEN_ROOTS = frozenset({"eval", "scripts", "tests"})


def test_app_does_not_import_the_evaluation_harness_or_the_test_doubles() -> None:
    """`eval/` and `scripts/` may construct semantics production must refuse.

    `tests/` is on the same list, and for a sharper reason: `tests/support_slice.py`
    holds `FakeGateway`, which returns whatever a caller tells it to. A production
    module that imported it could produce a fully-formed recommendation with no model,
    no retrieval and no firewall involved - and every downstream check would pass,
    because the shape would be perfect. The rule is what keeps the fixture a fixture.

    `eval/replay.py` builds the assumed conjunction gold_v1's labels were computed
    under - the behaviour Phase 5 removed from production. It lives outside `app/`
    precisely so that this rule can exist: a production module importing it would
    make the replay path reachable from an adjudication, and the `semantics_guard`
    digest check would then be the only thing standing between a misconfiguration
    and an approval.
    """
    for module in MODULES:
        offenders = {i for i in module.imports if i.split(".")[0] in FORBIDDEN_ROOTS}
        assert not offenders, (
            f"{module.rel} imports {sorted(offenders)}. Neither the evaluation "
            "harness nor the test doubles are importable from production code."
        )


def test_the_replay_origin_is_referenced_only_where_it_is_defined() -> None:
    """No production module *reads* `GOLD_V1_REPLAY`, only its definition names it.

    Checked over the AST rather than the raw text, deliberately. An earlier version
    grepped for the string and flagged `app/policy/semantics_guard.py`, whose
    docstring explains why the replay origin is refused - documentation, not
    behaviour, and deleting it would have made the guard harder to understand in
    order to satisfy a test.

    What must not exist is a production code path that *recognises* the replay
    origin, because that is how a special case for it gets written. The origin is
    refused by not being in `PRODUCTION_ORIGINS` - by absence, not by a branch.
    """
    offenders: list[str] = []
    for module in MODULES:
        if module.rel == "app/decision/semantics.py":
            continue  # the definition
        for node in ast.walk(module.tree):
            named = (
                (isinstance(node, ast.Attribute) and node.attr == "GOLD_V1_REPLAY")
                or (isinstance(node, ast.Name) and node.id == "GOLD_V1_REPLAY")
                or (
                    isinstance(node, ast.ImportFrom)
                    and any(a.name == "GOLD_V1_REPLAY" for a in node.names)
                )
            )
            if named:
                offenders.append(module.rel)
                break
    assert not offenders, (
        f"{offenders} reference GOLD_V1_REPLAY in code. Production must not "
        "recognise the replay origin - it is refused by absence from "
        "PRODUCTION_ORIGINS, never by a branch that names it."
    )


# --------------------------------------------------------------------------- 7
def test_there_is_exactly_one_production_gate() -> None:
    """Two gates that mostly agree are worse than one gate that is wrong.

    The disagreement surfaces as a case one path admitted and another refused, and
    whichever was consulted last wins. `app/production_gate.py` is authoritative;
    a second module defining a gate would be a competing answer to the same
    question.
    """
    defining = [
        module.rel
        for module in MODULES
        if any(
            isinstance(node, ast.FunctionDef) and node.name == "evaluate_gate"
            for node in ast.walk(module.tree)
        )
    ]
    assert defining == ["app/production_gate.py"], (
        f"a production gate is defined in {defining}; there must be exactly one"
    )


def test_the_production_gate_cannot_consult_historical_replay() -> None:
    """Replay reproducing gold_v1 says nothing about whether production may run.

    The gate has no input through which replay could reach it, and this keeps it
    that way - a gate that could see replay is a gate that could be satisfied by it.
    """
    gate = next(m for m in MODULES if m.rel == "app/production_gate.py")
    source = gate.path.read_text(encoding="utf-8")
    offenders = {i for i in gate.imports if "replay" in i.lower()}
    assert not offenders, f"the production gate imports {sorted(offenders)}"
    # It may NAME replay in prose to explain the exclusion; it may not call it.
    assert "gold_v1_semantics" not in source
