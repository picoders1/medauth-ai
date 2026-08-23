"""A small three-valued policy logic. Pure, inspectable, serialisable.

Phase 3 found that the decision table was assuming something no regulation
guarantees: that every required criterion must hold, conjunctively, for coverage
to follow. 42 CFR 410.32(a) disproves it in one sentence - a qualified
interpreting physician *may* order a diagnostic mammogram from screening findings
"even though the physician does not treat the beneficiary". The ordering
requirement has an alternative route through it, and a conjunction cannot say so.

So this module lets a policy state its own shape. What it deliberately is not is
a general theorem prover: there are seven node types, no quantifiers, no
variables, and no inference. A policy's logic must be readable by the person
reviewing it, or the representation has bought expressiveness at the cost of the
only property that matters here.

**Three values, not two.** `UNKNOWN` is a first-class truth value under Kleene's
strong semantics, and that is the whole point. Under two-valued logic an absent
fact has to be guessed - and guessing it false is how automated prior
authorization denies people for paperwork they were never asked for. Under Kleene:

    ANY(TRUE, UNKNOWN)  = TRUE     the alternative route already carries it
    ALL(FALSE, UNKNOWN) = FALSE    the failure is decisive on its own
    ANY(FALSE, UNKNOWN) = UNKNOWN  genuinely open
    ALL(TRUE, UNKNOWN)  = UNKNOWN  genuinely open

The first line is the improvement: a case can now be satisfied *despite* an
unknown, when the policy offers a path that does not depend on it.

**What this module does not decide.** Kleene FALSE means "false under every
completion of the unknowns" - logically decisive, and if that were the only
consideration a denial would follow. It is not the only consideration. Whether an
unresolved question should stop a case before a denial is reached is a safety
choice, not a logical one, and it is made in `app.decision.table` where it can be
read, ordered and tested as a policy of this system rather than as a property of
the connectives. See `PolicyEvaluation.unknown_criteria`.

Purity: no I/O, no clock, no model. A date of service is an *argument*, never a
reading of the current time - `app.decision` may not import a clock, and a
temporal predicate that consulted one would make the truth table untestable.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from enum import StrEnum
from typing import Literal

from app.core.types import CriterionKind, Verdict

__all__ = [
    "All",
    "Any",
    "AtLeast",
    "Leaf",
    "LogicForm",
    "Node",
    "Not",
    "PolicyEvaluation",
    "PolicyLogic",
    "PolicyTruth",
    "Tri",
    "Unless",
    "When",
    "evaluate",
    "leaf_value",
]


class Tri(StrEnum):
    """Kleene's three truth values."""

    TRUE = "TRUE"
    FALSE = "FALSE"
    UNKNOWN = "UNKNOWN"


class PolicyTruth(StrEnum):
    """What the policy's own logic concludes, before any recommendation exists.

    Separated from `Outcome` on purpose. "The policy's conditions are met" and
    "approve this authorization" are different claims: the first is a statement
    about a regulation, the second is advice to a human reviewer that also has to
    account for evidence quality, guardrail state and unresolved questions. A
    system that conflates them cannot explain which of the two it got wrong.
    """

    POLICY_SATISFIED = "POLICY_SATISFIED"
    POLICY_NOT_SATISFIED = "POLICY_NOT_SATISFIED"
    POLICY_INDETERMINATE = "POLICY_INDETERMINATE"


class LogicForm(StrEnum):
    """How a policy version's logic came to be what it is.

    `ASSUMED_CONJUNCTION` is the honest name for what the engine used to do
    silently. It still behaves the same way, but it now appears on the
    recommendation and in the logic inventory, so an unreviewed assumption is
    visible rather than structural.
    """

    DECLARED = "DECLARED"
    ASSUMED_CONJUNCTION = "ASSUMED_CONJUNCTION"
    REVIEW_REQUIRED = "REVIEW_REQUIRED"

    #: Nothing has been transcribed from this policy version, so there is no tree
    #: to describe. Present so this enum matches the vocabulary
    #: `scripts/build_logic_inventory.py` emits - a classification the inventory
    #: can produce but the type system cannot name is a gap waiting to be filled
    #: by a default.
    NO_CRITERIA = "NO_CRITERIA"


# ---------------------------------------------------------------------------
# Nodes
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class Leaf:
    """One criterion, referenced by id.

    The id is resolved against the case's criterion states at evaluation time. An
    id with no state is `UNKNOWN`, never `FALSE`: a criterion nobody adjudicated
    is an open question, not a failed one.
    """

    criterion_id: str
    kind: Literal["leaf"] = "leaf"


@dataclass(frozen=True, slots=True)
class All:
    """Conjunction. FALSE if any child is FALSE, TRUE only if all are TRUE."""

    children: tuple[Node, ...]
    kind: Literal["all"] = "all"


@dataclass(frozen=True, slots=True)
class Any:
    """Disjunction. TRUE if any child is TRUE, FALSE only if all are FALSE.

    This is how an alternative pathway is expressed - the mammography exception
    is `Any(ordered_by_treating_physician, <exception conditions>)`.
    """

    children: tuple[Node, ...]
    kind: Literal["any"] = "any"


@dataclass(frozen=True, slots=True)
class Not:
    """Negation. UNKNOWN negates to UNKNOWN, which is the only sane reading."""

    child: Node
    kind: Literal["not"] = "not"


@dataclass(frozen=True, slots=True)
class AtLeast:
    """`n` of the children must hold.

    Present because coverage policy states such rules directly ("at least two of
    the following findings"). Not a general counting quantifier: `n` is a literal.
    """

    n: int
    children: tuple[Node, ...]
    kind: Literal["at_least"] = "at_least"

    def __post_init__(self) -> None:
        if self.n < 1 or self.n > len(self.children):
            raise ValueError(
                f"AtLeast({self.n}) is unsatisfiable over {len(self.children)} children"
            )


@dataclass(frozen=True, slots=True)
class Unless:
    """`rule` holds unless `exception` does. Sugar for `Any(rule, exception)`.

    It exists as its own node because the two read differently to a reviewer and
    serialise differently in the inventory: `Unless` records that the regulation
    frames something as an exception to a stated requirement, which is
    information a bare disjunction throws away. The truth table is identical.
    """

    rule: Node
    exception: Node
    kind: Literal["unless"] = "unless"


@dataclass(frozen=True, slots=True)
class When:
    """Conditional applicability: `then` is evaluated only where `condition` holds.

    If the condition is FALSE the node is TRUE - a requirement that does not apply
    cannot fail. If the condition is UNKNOWN, so is the node: whether a rule
    applies is exactly the kind of question that must not be answered by guessing.
    """

    condition: Node
    then: Node
    kind: Literal["when"] = "when"


Node = Leaf | All | Any | Not | AtLeast | Unless | When


# ---------------------------------------------------------------------------
# Policy logic
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class PolicyLogic:
    """One policy version's logic, with its provenance and temporal window.

    `requirements` and `exclusions` are kept apart because they carry different
    consequences and are evaluated at different points in the recommendation
    ordering - an established exclusion denies, an unmet requirement may only
    deny once no question is left open.
    """

    policy_id: str
    policy_version: str
    requirements: Node
    exclusions: Node | None = None
    form: LogicForm = LogicForm.ASSUMED_CONJUNCTION
    effective_from: date | None = None
    effective_to: date | None = None
    review_notes: tuple[str, ...] = ()

    def in_force_on(self, as_of: date | None) -> bool:
        """The same temporal predicate resolution and retrieval apply.

        `as_of` is an argument. Reading a clock here would make the truth table a
        statement about the day it ran.
        """
        if as_of is None:
            return True
        if self.effective_from is not None and as_of < self.effective_from:
            return False
        return not (self.effective_to is not None and as_of > self.effective_to)


@dataclass(frozen=True, slots=True)
class PolicyEvaluation:
    """What the logic concluded, and what it depended on.

    `unknown_criteria` lists every criterion that evaluated to UNKNOWN *anywhere*
    in the tree, including when the overall value came out FALSE. That is
    deliberate: the recommendation layer needs to know a question is still open
    even when the logic no longer needs the answer, because "we could deny on what
    we have" and "we should" are different claims.

    `false_criteria` lists the leaves that evaluated FALSE. Together with a
    satisfied result it is the signature of an alternative pathway: something
    failed, and the policy holds anyway. That is what distinguishes "every
    requirement was met" from "a requirement was not met but the regulation
    provides another route", and a reviewer must be able to tell those apart.

    `decisive_criteria` lists the leaves whose value actually drove the result,
    so an outcome can be explained by pointing at criteria rather than at a tree.
    """

    truth: PolicyTruth
    value: Tri
    form: LogicForm
    unknown_criteria: tuple[str, ...] = ()
    false_criteria: tuple[str, ...] = ()
    decisive_criteria: tuple[str, ...] = ()
    exclusion_value: Tri = Tri.FALSE
    unknown_exclusions: tuple[str, ...] = ()
    applicable: bool = True
    notes: tuple[str, ...] = field(default_factory=tuple)


# ---------------------------------------------------------------------------
# Kleene evaluation
# ---------------------------------------------------------------------------


def leaf_value(verdict: Verdict, *, has_valid_evidence: bool, kind: CriterionKind) -> Tri:
    """Map one criterion's adjudicated verdict to a truth value.

    One rule governs the whole mapping: **a verdict that lets a case escape the
    ordinary reading of the policy must carry evidence, or it is UNKNOWN.**
    Without that, an unsupported model output becomes load-bearing - which is the
    failure the citation contract exists to prevent, and the cheapest thing an
    injected instruction could attempt.

    Which value escapes the ordinary reading depends on the criterion's role, so
    the requirement lands on a different truth value for each:

    ============================ ================== =========================
    role                         escaping value     without evidence
    ============================ ================== =========================
    ``REQUIRED``                 FALSE (denies)     UNKNOWN
    ``EXCLUSION``                TRUE (denies)      UNKNOWN
    ``EXCEPTION_CONDITION``      TRUE (overrides)   UNKNOWN
    ``INFORMATIONAL``            neither            taken at face value
    ============================ ================== =========================

    The exception row is the one worth dwelling on. An exception condition that
    holds *overrides an explicit regulatory requirement* - 410.32(a)(1) lets a
    case through that paragraph (a) forbids. Claiming it unsupported would be the
    cheapest possible attack on this system, so an unevidenced exception claim
    holds the case rather than approving it.

    The ordinary directions need no evidence, and deliberately so:
    ``NOT_APPLICABLE`` on a requirement is TRUE because a rule that does not apply
    cannot block, and a failed exception condition is FALSE because all it means
    is that the ordinary rule governs after all - the conservative reading.
    """
    if verdict is Verdict.INSUFFICIENT_EVIDENCE:
        return Tri.UNKNOWN

    #: The truth value that would carry this criterion past the ordinary reading.
    escaping: dict[CriterionKind, Tri | None] = {
        CriterionKind.REQUIRED: Tri.FALSE,
        CriterionKind.EXCLUSION: Tri.TRUE,
        CriterionKind.EXCEPTION_CONDITION: Tri.TRUE,
        CriterionKind.INFORMATIONAL: None,
    }

    if verdict is Verdict.NOT_APPLICABLE:
        # An inapplicable criterion takes whichever value is inert for its role.
        return Tri.FALSE if kind is not CriterionKind.REQUIRED else Tri.TRUE

    value = Tri.TRUE if verdict is Verdict.SATISFIED else Tri.FALSE
    if value is escaping.get(kind) and not has_valid_evidence:
        return Tri.UNKNOWN
    return value


def _eval(
    node: Node,
    states: dict[str, Tri],
    unknowns: set[str],
    used: set[str],
    falses: set[str] | None = None,
) -> Tri:
    """Kleene evaluation, collecting the unknown, false and consulted leaves."""
    match node:
        case Leaf(criterion_id=cid):
            value = states.get(cid, Tri.UNKNOWN)
            used.add(cid)
            if value is Tri.UNKNOWN:
                unknowns.add(cid)
            elif value is Tri.FALSE and falses is not None:
                falses.add(cid)
            return value

        case All(children=children):
            values = [_eval(c, states, unknowns, used, falses) for c in children]
            if Tri.FALSE in values:
                return Tri.FALSE
            return Tri.UNKNOWN if Tri.UNKNOWN in values else Tri.TRUE

        case Any(children=children):
            values = [_eval(c, states, unknowns, used, falses) for c in children]
            if Tri.TRUE in values:
                return Tri.TRUE
            return Tri.UNKNOWN if Tri.UNKNOWN in values else Tri.FALSE

        case Not(child=child):
            value = _eval(child, states, unknowns, used, falses)
            if value is Tri.TRUE:
                return Tri.FALSE
            return Tri.TRUE if value is Tri.FALSE else Tri.UNKNOWN

        case AtLeast(n=n, children=children):
            values = [_eval(c, states, unknowns, used, falses) for c in children]
            trues = values.count(Tri.TRUE)
            if trues >= n:
                return Tri.TRUE
            possible = trues + values.count(Tri.UNKNOWN)
            return Tri.FALSE if possible < n else Tri.UNKNOWN

        case Unless(rule=rule, exception=exception):
            return _eval(Any((rule, exception)), states, unknowns, used, falses)

        case When(condition=condition, then=then):
            applies = _eval(condition, states, unknowns, used, falses)
            if applies is Tri.FALSE:
                return Tri.TRUE
            body = _eval(then, states, unknowns, used, falses)
            if applies is Tri.UNKNOWN:
                # The rule may not apply at all, so a satisfied body is still
                # TRUE; anything else is genuinely open.
                return Tri.TRUE if body is Tri.TRUE else Tri.UNKNOWN
            return body


def _decisive(node: Node, states: dict[str, Tri], value: Tri) -> tuple[str, ...]:
    """Which leaves actually drove the result.

    A leaf is decisive when flipping it away from its current value would change
    the tree's value. Computed by re-evaluation rather than by reasoning about
    the tree, because the trees here are tiny and a wrong hand-rolled analysis
    would produce a confident and false explanation.
    """
    decisive: list[str] = []
    for cid, current in states.items():
        for alternative in (Tri.TRUE, Tri.FALSE, Tri.UNKNOWN):
            if alternative is current:
                continue
            probe = dict(states)
            probe[cid] = alternative
            if _eval(node, probe, set(), set()) is not value:
                decisive.append(cid)
                break
    return tuple(sorted(decisive))


def evaluate(
    logic: PolicyLogic,
    states: dict[str, Tri],
    *,
    as_of: date | None = None,
) -> PolicyEvaluation:
    """Evaluate a policy's logic against criterion truth values.

    Total: every input produces an evaluation. Unknown ids are UNKNOWN, an
    out-of-window policy is `applicable=False`, and there is no error path that
    a caller could forget to handle.
    """
    if not logic.in_force_on(as_of):
        return PolicyEvaluation(
            truth=PolicyTruth.POLICY_INDETERMINATE,
            value=Tri.UNKNOWN,
            form=logic.form,
            applicable=False,
            notes=(f"{logic.policy_id} {logic.policy_version} is not in force on {as_of}",),
        )

    unknowns: set[str] = set()
    used: set[str] = set()
    falses: set[str] = set()
    value = _eval(logic.requirements, states, unknowns, used, falses)

    exclusion_value = Tri.FALSE
    exclusion_unknowns: set[str] = set()
    if logic.exclusions is not None:
        exclusion_value = _eval(logic.exclusions, states, exclusion_unknowns, set())

    truth = {
        Tri.TRUE: PolicyTruth.POLICY_SATISFIED,
        Tri.FALSE: PolicyTruth.POLICY_NOT_SATISFIED,
        Tri.UNKNOWN: PolicyTruth.POLICY_INDETERMINATE,
    }[value]

    relevant = {cid: states.get(cid, Tri.UNKNOWN) for cid in used}
    return PolicyEvaluation(
        truth=truth,
        value=value,
        form=logic.form,
        unknown_criteria=tuple(sorted(unknowns)),
        false_criteria=tuple(sorted(falses)),
        decisive_criteria=_decisive(logic.requirements, relevant, value),
        exclusion_value=exclusion_value,
        unknown_exclusions=tuple(sorted(exclusion_unknowns)),
        notes=logic.review_notes,
    )
