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

import hashlib
import json
from dataclasses import dataclass
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
from app.decision.semantics import (
    Attestation,
    PolicySemantics,
    SemanticsOrigin,
)
from app.decision.table import CriterionOutcome, assumed_conjunction

__all__ = [
    "LogicSpecError",
    "SemanticsSource",
    "load_policy_logic",
    "load_policy_logic_dir",
    "load_semantics_source",
    "parse_node",
    "semantics_for",
]


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


# ---------------------------------------------------------------------------
# Policy semantics: what the inventory says, and the digest that proves it
# ---------------------------------------------------------------------------


def _digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


@dataclass(frozen=True, slots=True)
class SemanticsSource:
    """The logic inventory and declarations, loaded together with their digests.

    Loaded once at startup and passed down, rather than read per decision. Two
    reasons, and the second is the load-bearing one: reading a file inside an
    adjudication would put I/O on the decision path, and a digest computed per
    call could not detect the artefact changing underneath a running process.
    """

    inventory: dict[tuple[str, str], str]
    declared: dict[tuple[str, str], PolicyLogic]
    inventory_digest: str
    inventory_path: str


def load_semantics_source(
    inventory_path: Path,
    logic_dir: Path,
    *,
    known_criteria: frozenset[str] | None = None,
) -> SemanticsSource:
    """Read `inventory.json` and every declared-logic file, and hash the inventory.

    Refuses rather than defaults, in keeping with the rest of this module: a
    malformed inventory is a startup failure, not a reason to fall back to
    assuming conjunctions.
    """
    try:
        spec: dict[str, Any] = json.loads(inventory_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise LogicSpecError(f"{inventory_path.name}: unreadable logic inventory ({exc})") from exc

    rows = spec.get("policies")
    if not isinstance(rows, list) or not rows:
        raise LogicSpecError(f"{inventory_path.name}: no `policies` array")

    inventory: dict[tuple[str, str], str] = {}
    for row in rows:
        try:
            key = (str(row["policy_id"]), str(row["policy_version"]))
            form = str(row["logic_form"])
        except (KeyError, TypeError) as exc:
            raise LogicSpecError(f"{inventory_path.name}: malformed row {row!r}") from exc
        if key in inventory:
            raise LogicSpecError(f"{inventory_path.name}: duplicate entry for {key}")
        inventory[key] = form

    return SemanticsSource(
        inventory=inventory,
        declared=load_policy_logic_dir(logic_dir, known_criteria=known_criteria),
        inventory_digest=_digest(inventory_path),
        inventory_path=str(inventory_path),
    )


def semantics_for(
    source: SemanticsSource,
    *,
    policy_id: str,
    policy_version: str,
    criteria: tuple[CriterionOutcome, ...],
) -> PolicySemantics:
    """Ask the inventory what this policy version's logic is.

    The only production route to an executable `PolicySemantics`. Every branch
    that is not an executable answer returns a value that cannot adjudicate, and a
    policy version absent from the inventory is `unconsulted` - **not** an assumed
    conjunction. An unlisted policy is one the inventory never assessed, and the
    whole of R-59 is that "not assessed" and "assessed and found unremarkable"
    must not behave identically.
    """
    key = (policy_id, policy_version)
    form = source.inventory.get(key)

    if form is None:
        return PolicySemantics.unconsulted(
            policy_id=policy_id,
            policy_version=policy_version,
            notes=(
                f"{policy_id} {policy_version} does not appear in "
                f"{source.inventory_path}; its logic has never been assessed",
            ),
        )

    if form == LogicForm.REVIEW_REQUIRED.value:
        return PolicySemantics.review_required(
            policy_id=policy_id,
            policy_version=policy_version,
            notes=(
                "the logic inventory classifies this version REVIEW_REQUIRED: it "
                "carries exception, alternative or conditional wording that a "
                "conjunction may misread, and no logic has been declared (OD-19)",
            ),
        )

    if form == LogicForm.NO_CRITERIA.value:
        return PolicySemantics.no_criteria(
            policy_id=policy_id,
            policy_version=policy_version,
            notes=("nothing has been transcribed from this policy version",),
        )

    inventory_attestation = Attestation(
        source=source.inventory_path,
        sha256=source.inventory_digest,
        origin=SemanticsOrigin.POLICY_LOGIC_INVENTORY,
    )

    if form == LogicForm.DECLARED.value:
        declared = source.declared.get(key)
        return PolicySemantics.declared(
            policy_id=policy_id,
            policy_version=policy_version,
            logic=declared,
            # The declaration is what executes, but the inventory's digest is what
            # the production guard checks, so the attestation names the inventory.
            attestation=inventory_attestation if declared is not None else None,
            notes=declared.review_notes
            if declared is not None
            else ("the inventory says DECLARED but no declaration file was loaded",),
        )

    if form == LogicForm.ASSUMED_CONJUNCTION.value:
        return PolicySemantics.assumed(
            policy_id=policy_id,
            policy_version=policy_version,
            logic=assumed_conjunction(criteria, policy_id=policy_id, policy_version=policy_version),
            attestation=inventory_attestation,
            notes=(
                "no exception, alternative or conditional wording was found by the "
                "inventory scan; that is weak evidence, not a finding",
            ),
        )

    return PolicySemantics.unconsulted(
        policy_id=policy_id,
        policy_version=policy_version,
        notes=(f"unrecognised logic_form {form!r} in {source.inventory_path}",),
    )
