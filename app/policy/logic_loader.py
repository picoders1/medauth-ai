"""Load declared policy logic from YAML into `app.decision.logic` nodes.

This lives in `app.policy`, not `app.decision`, and that placement is the point.
`app.decision` may not perform I/O - a test parses the AST and asserts it - so the
decision layer stays a pure function of its arguments and remains exhaustively
testable with nothing loaded. Reading a file is this module's job; deciding is
not.

The parser is strict on purpose. An unknown node type, a missing key, an empty
branch or a criterion id that is not in the inventory raises rather than
defaulting. A policy's logic is a clinical behaviour specification: a typo that
silently degrades `unless` into `all` would turn an alternative pathway back into
an absolute requirement, which is the exact defect Phase 4 exists to remove.
"""

from __future__ import annotations

from datetime import date
from pathlib import Path
from typing import Any

import yaml

from app.decision.logic import (
    All,
    AtLeast,
    Leaf,
    LogicForm,
    Node,
    Not,
    PolicyLogic,
    Unless,
    When,
)
from app.decision.logic import (
    Any as AnyOf,
)

__all__ = ["LogicSpecError", "load_policy_logic", "load_policy_logic_dir", "parse_node"]


class LogicSpecError(ValueError):
    """A declared logic file is malformed. Never recovered from by defaulting."""


def parse_node(spec: object, *, path: str = "requirements") -> Node:
    """Turn one YAML mapping into a node. One key per mapping, always."""
    if not isinstance(spec, dict):
        raise LogicSpecError(f"{path}: expected a mapping, got {type(spec).__name__}")
    if len(spec) != 1:
        raise LogicSpecError(
            f"{path}: expected exactly one node key, got {sorted(spec)}. "
            "Wrap multiple children in `all:` or `any:` explicitly."
        )

    ((key, body),) = spec.items()

    def children(name: str) -> tuple[Node, ...]:
        if not isinstance(body, list) or not body:
            raise LogicSpecError(f"{path}.{name}: expected a non-empty list")
        return tuple(parse_node(c, path=f"{path}.{name}[{i}]") for i, c in enumerate(body))

    match key:
        case "leaf":
            if not isinstance(body, str) or not body.strip():
                raise LogicSpecError(f"{path}.leaf: expected a criterion id")
            return Leaf(body.strip())
        case "all":
            return All(children("all"))
        case "any":
            return AnyOf(children("any"))
        case "not":
            return Not(parse_node(body, path=f"{path}.not"))
        case "at_least":
            if not isinstance(body, dict) or "n" not in body or "of" not in body:
                raise LogicSpecError(f"{path}.at_least: expected keys `n` and `of`")
            items = tuple(
                parse_node(c, path=f"{path}.at_least.of[{i}]") for i, c in enumerate(body["of"])
            )
            return AtLeast(int(body["n"]), items)
        case "unless":
            if not isinstance(body, dict) or set(body) != {"rule", "exception"}:
                raise LogicSpecError(
                    f"{path}.unless: expected exactly `rule` and `exception`, got {sorted(body) if isinstance(body, dict) else body!r}"
                )
            return Unless(
                parse_node(body["rule"], path=f"{path}.unless.rule"),
                parse_node(body["exception"], path=f"{path}.unless.exception"),
            )
        case "when":
            if not isinstance(body, dict) or set(body) != {"condition", "then"}:
                raise LogicSpecError(f"{path}.when: expected exactly `condition` and `then`")
            return When(
                parse_node(body["condition"], path=f"{path}.when.condition"),
                parse_node(body["then"], path=f"{path}.when.then"),
            )
        case _:
            raise LogicSpecError(f"{path}: unknown node type {key!r}")


def _leaves(node: Node) -> list[str]:
    match node:
        case Leaf(criterion_id=cid):
            return [cid]
        case All(children=cs) | AnyOf(children=cs) | AtLeast(children=cs):
            return [i for c in cs for i in _leaves(c)]
        case Not(child=child):
            return _leaves(child)
        case Unless(rule=rule, exception=exception):
            return _leaves(rule) + _leaves(exception)
        case When(condition=condition, then=then):
            return _leaves(condition) + _leaves(then)


def load_policy_logic(path: Path, *, known_criteria: frozenset[str] | None = None) -> PolicyLogic:
    """Read one declared-logic file.

    `known_criteria`, when given, is checked against every referenced id. A
    dangling reference is always UNKNOWN at evaluation time, which would quietly
    make an alternative pathway unreachable and the requirement absolute again -
    a silent reversal of the fix. So it raises here instead.
    """
    spec: dict[str, Any] = yaml.safe_load(path.read_text(encoding="utf-8"))
    for required in ("policy_id", "policy_version", "requirements"):
        if required not in spec:
            raise LogicSpecError(f"{path.name}: missing `{required}`")

    requirements = parse_node(spec["requirements"])
    exclusions = (
        parse_node(spec["exclusions"], path="exclusions")
        if spec.get("exclusions") is not None
        else None
    )

    if known_criteria is not None:
        referenced = set(_leaves(requirements))
        if exclusions is not None:
            referenced |= set(_leaves(exclusions))
        unknown = sorted(referenced - known_criteria)
        if unknown:
            raise LogicSpecError(
                f"{path.name}: references criteria absent from the inventory: {unknown}"
            )

    def as_date(value: object) -> date | None:
        if value is None:
            return None
        return value if isinstance(value, date) else date.fromisoformat(str(value))

    return PolicyLogic(
        policy_id=str(spec["policy_id"]),
        policy_version=str(spec["policy_version"]),
        requirements=requirements,
        exclusions=exclusions,
        form=LogicForm(str(spec.get("form", "DECLARED")).upper()),
        effective_from=as_date(spec.get("effective_from")),
        effective_to=as_date(spec.get("effective_to")),
        review_notes=tuple(str(n).strip() for n in spec.get("review_notes", ())),
    )


def load_policy_logic_dir(
    directory: Path, *, known_criteria: frozenset[str] | None = None
) -> dict[tuple[str, str], PolicyLogic]:
    """Load every declared-logic file, keyed by (policy_id, policy_version).

    A policy with no file here is not an error: it means no logic has been
    declared for it, and the decision engine will build an explicit
    `ASSUMED_CONJUNCTION` and label it as such.
    """
    loaded: dict[tuple[str, str], PolicyLogic] = {}
    for path in sorted(directory.glob("*.yaml")):
        logic = load_policy_logic(path, known_criteria=known_criteria)
        key = (logic.policy_id, logic.policy_version)
        if key in loaded:
            raise LogicSpecError(f"duplicate declared logic for {key}")
        loaded[key] = logic
    return loaded
