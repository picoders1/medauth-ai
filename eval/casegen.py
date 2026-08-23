"""Criterion-driven synthetic case generation.

The generation order is fixed and is the whole point:

    Policy -> Criteria -> Case template -> synthetic facts -> note -> criterion states

Generating patients first and then hunting for a policy that fits produces cases
whose labels are an opinion. Generating from criteria means the criterion states
are chosen *first*, the note is written to realise them, and the expected decision
is computed from those states by the same ``decide()`` the system uses (ADR-015).
A label is therefore a property of the construction, not a judgement about it.

Two consequences worth stating plainly:

* **The cases are only as good as the criteria**, and the criteria are only as good
  as the documents they were transcribed from. The current documents are
  CMS-*shaped*, so every case inherits ``provenance: synthetic``.
* **Constructed cases are cleaner than real submissions.** Facts appear once,
  unambiguously, in the section a reader expects. Measured performance on them is
  an upper bound, and the claim that it transfers to real clinical documentation is
  refused.

Determinism: everything derives from an explicit integer seed. The same seed
rebuilds the corpus byte-for-byte, which is what makes a dataset version mean
something.
"""

from __future__ import annotations

import hashlib
import random
import re
from dataclasses import dataclass, field
from datetime import date, timedelta
from enum import StrEnum
from typing import Any

from app.core.types import CriterionKind, ResolutionStatus, Verdict
from app.decision.models import Outcome
from app.decision.table import CriterionOutcome, GuardrailState, ResolutionState, decide
from app.policy.criteria import CriterionType, VerifiedCriterion

__all__ = ["CaseCategory", "CasePlan", "CriterionState", "GeneratedCase", "build_cases"]

SCHEMA_VERSION = "1"


class CriterionState(StrEnum):
    """The gold label at criterion level. This is the primary label."""

    SATISFIED = "SATISFIED"
    NOT_SATISFIED = "NOT_SATISFIED"
    UNKNOWN = "UNKNOWN"


class CaseCategory(StrEnum):
    """Why the case exists. Every category is deliberate, none is filler."""

    CLEARLY_SATISFIES = "CLEARLY_SATISFIES"
    CLEARLY_FAILS = "CLEARLY_FAILS"
    EXCLUSION_PRESENT = "EXCLUSION_PRESENT"
    MISSING_DOCUMENTATION = "MISSING_DOCUMENTATION"
    INSUFFICIENT_EVIDENCE = "INSUFFICIENT_EVIDENCE"
    BORDERLINE = "BORDERLINE"
    CONFLICTING_EVIDENCE = "CONFLICTING_EVIDENCE"
    POLICY_NOT_APPLICABLE = "POLICY_NOT_APPLICABLE"


#: A category's intent, recorded in the dataset so a reader need not infer it.
CATEGORY_INTENT: dict[CaseCategory, str] = {
    CaseCategory.CLEARLY_SATISFIES: "every required criterion evidenced, no exclusion present",
    CaseCategory.CLEARLY_FAILS: "one required criterion evidenced as NOT met",
    CaseCategory.EXCLUSION_PRESENT: "an exclusion positively evidenced",
    CaseCategory.MISSING_DOCUMENTATION: "one required criterion has no evidence in the note",
    CaseCategory.INSUFFICIENT_EVIDENCE: "several required criteria have no evidence",
    CaseCategory.BORDERLINE: "a numeric fact sits exactly on the policy threshold",
    CaseCategory.CONFLICTING_EVIDENCE: "the note asserts a fact and its contradiction",
    CaseCategory.POLICY_NOT_APPLICABLE: "requested procedure resolves to no policy",
}


@dataclass(frozen=True, slots=True)
class PolicyRef:
    """The policy version a case is built against."""

    policy_id: str
    revision_id: str
    document_title: str
    jurisdiction: str | None
    effective_date: date
    end_date: date | None
    procedure_code: str
    code_system: str
    diagnosis_codes: tuple[str, ...]
    criteria: tuple[VerifiedCriterion, ...]

    @property
    def is_current(self) -> bool:
        return self.end_date is None


@dataclass
class GeneratedCase:
    case_id: str
    category: CaseCategory
    policy: PolicyRef
    date_of_service: date
    criterion_states: dict[str, CriterionState]
    note_lines: list[str]
    patient: dict[str, Any]
    expected_outcome: Outcome
    expected_rule: int
    missing_information: tuple[str, ...]
    conflicting: bool = False
    borderline: bool = False
    notes: str = ""

    @property
    def temporal_class(self) -> str:
        """Whether the case exercises the current revision or a superseded one."""
        if self.policy.end_date is not None and self.date_of_service <= self.policy.end_date:
            return "HISTORICAL_POLICY"
        return "CURRENT_POLICY"

    def to_record(self) -> dict[str, Any]:
        """INPUT and EXPECTED are separate objects.

        The production system is handed ``input`` only. Nothing under ``expected``
        may appear inside it, and a test asserts that no gold value leaks across.
        """
        return {
            "case_id": self.case_id,
            "schema_version": SCHEMA_VERSION,
            "provenance": "synthetic",
            "category": self.category.value,
            "temporal_class": self.temporal_class,
            "borderline": self.borderline,
            "input": {
                "patient": self.patient,
                "requested_procedure": {
                    "code": self.policy.procedure_code,
                    "code_system": self.policy.code_system,
                },
                "diagnosis_codes": list(self.policy.diagnosis_codes),
                "jurisdiction": self.policy.jurisdiction,
                "date_of_service": self.date_of_service.isoformat(),
                "clinical_note": "\n".join(self.note_lines),
            },
            "expected": {
                "policy_id": self.policy.policy_id,
                "policy_revision": self.policy.revision_id,
                "policy_title": self.policy.document_title,
                "applicability_rationale": (
                    f"{self.policy.procedure_code} is listed as a covered procedure in "
                    f"{self.policy.policy_id} rev {self.policy.revision_id}, in force on "
                    f"{self.date_of_service.isoformat()}"
                    + (
                        f" for jurisdiction {self.policy.jurisdiction}"
                        if self.policy.jurisdiction
                        else ""
                    )
                ),
                "criteria": [
                    {
                        "criterion_id": criterion.id,
                        "fact_key": criterion.fact_key,
                        "criterion_type": criterion.criterion_type.value,
                        "state": self.criterion_states[criterion.id].value,
                    }
                    for criterion in self.policy.criteria
                    if criterion.id in self.criterion_states
                ],
                "decision": self.expected_outcome.value,
                "decision_rule": self.expected_rule,
                "missing_information": list(self.missing_information),
                "notes": self.notes,
            },
        }


def _numeric(threshold: str | None, direction: str, rng: random.Random) -> str:
    """Realise a numeric fact on the required side of a threshold."""
    if threshold is None:
        return ""
    try:
        base = float(threshold)
    except ValueError:
        return threshold
    if direction == "at":
        value = base
    else:
        margin = rng.choice([1, 2, 3, 4]) if base > 8 else 1
        value = base + margin if direction == "plus" else max(0.0, base - margin)
    return str(int(value)) if value == int(value) else f"{value:.1f}"


def _render(
    criterion: VerifiedCriterion,
    state: CriterionState,
    templates: dict[str, dict[str, Any]],
    rng: random.Random,
    *,
    at_threshold: bool = False,
) -> str | None:
    """One note sentence for a criterion in a given state, or None to omit it."""
    template = templates.get(criterion.fact_key)
    if template is None:
        raise KeyError(
            f"no case template for fact_key {criterion.fact_key!r} "
            f"(criterion {criterion.id}). Every criterion must be expressible."
        )
    if state is CriterionState.UNKNOWN:
        # Deliberately silent. A real submission omits what it does not address.
        return None

    key = "satisfied" if state is CriterionState.SATISFIED else "not_satisfied"
    sentence = template.get(key)
    if not sentence:
        return None

    if "{value}" in sentence:
        spec = template.get(f"{key}_value", "{threshold_plus}")
        direction = "at" if at_threshold else ("plus" if "plus" in str(spec) else "minus")
        sentence = sentence.replace("{value}", _numeric(criterion.threshold, direction, rng))
    if "{recency}" in sentence:
        sentence = sentence.replace("{recency}", str(rng.choice([1, 2, 3])))
    return sentence


#: Where a fact plausibly appears in a real submission. Criterion sentences are
#: distributed across these rather than listed in criterion order, because a note
#: whose facts appear in policy order is trivially easy to read and nothing like a
#: real one.
NOTE_HEADERS = (
    "HISTORY OF PRESENT ILLNESS",
    "EXAMINATION",
    "ASSESSMENT",
    "PLAN",
    "DOCUMENTATION SUBMITTED",
)

#: Abbreviations a real note uses. Applied to distractors only - never to a
#: criterion sentence, because abbreviating the evidence would change what the
#: adjudicator has to find and could make ground truth arguable.
_ABBREVIATIONS = {
    "patient": "pt",
    "history": "hx",
    "treatment": "tx",
    "diagnosis": "dx",
    "within normal limits": "WNL",
}


def _abbreviate(sentence: str, rng: random.Random) -> str:
    for long_form, short in _ABBREVIATIONS.items():
        if long_form in sentence.lower() and rng.random() < 0.4:
            sentence = re.sub(long_form, short, sentence, count=1, flags=re.I)
    return sentence


def render_note(
    criterion_sentences: list[str],
    distractors: list[str],
    rng: random.Random,
    *,
    realistic: bool = True,
) -> list[str]:
    """Assemble a note that reads like a submission rather than a checklist.

    Realism is added only in ways that leave ground truth deterministic:

    * criterion sentences are **reordered and spread** across headed sections, so
      the adjudicator cannot rely on position;
    * clinically plausible **distractors** are interleaved - they bear on no
      criterion, so they cannot change a label;
    * one criterion sentence may be **restated** later in different words that
      carry the same fact, which is how real notes repeat themselves;
    * abbreviations are applied to distractors only.

    What is deliberately NOT done: no criterion sentence is dropped, contradicted
    or made ambiguous. Ambiguity that made a gold label arguable would destroy the
    dataset rather than harden it.
    """
    if not realistic:
        return list(criterion_sentences)

    ordered = list(criterion_sentences)
    rng.shuffle(ordered)
    noise = rng.sample(distractors, k=min(len(distractors), rng.randint(2, 4)))
    noise = [_abbreviate(sentence, rng) for sentence in noise]

    buckets: dict[str, list[str]] = {header: [] for header in NOTE_HEADERS}
    for index, sentence in enumerate(ordered):
        buckets[NOTE_HEADERS[index % len(NOTE_HEADERS)]].append(sentence)
    for index, sentence in enumerate(noise):
        buckets[NOTE_HEADERS[(index * 2 + 1) % len(NOTE_HEADERS)]].append(sentence)

    # A real note restates things. Echo one fact under a later heading.
    if ordered and rng.random() < 0.5:
        echoed = ordered[0]
        buckets[NOTE_HEADERS[-1]].append(f"As above: {echoed[0].lower()}{echoed[1:]}")

    lines: list[str] = []
    for header in NOTE_HEADERS:
        if not buckets[header]:
            continue
        lines.append(header)
        lines.extend(buckets[header])
        lines.append("")
    return list(lines[:-1]) if lines else []


def _patient(rng: random.Random) -> dict[str, Any]:
    """Demographics only, and deliberately thin.

    No decision-relevant fact lives here. Policies in this corpus turn on clinical
    findings and documentation, not on age or sex, so anything richer would be
    detail that must not affect the outcome - exactly what section 14 of the phase
    brief warns against generating.
    """
    return {
        "age": rng.randint(52, 84),
        "sex": rng.choice(["F", "M"]),
        "synthetic": True,
    }


@dataclass
class CasePlan:
    """How many cases of each category to build for one policy version."""

    policy: PolicyRef
    counts: dict[CaseCategory, int] = field(default_factory=dict)


def _states_for(
    category: CaseCategory,
    criteria: tuple[VerifiedCriterion, ...],
    rng: random.Random,
) -> tuple[dict[str, CriterionState], bool]:
    """Choose criterion states realising a category. Returns (states, at_threshold)."""
    required = [c for c in criteria if c.criterion_type is CriterionType.REQUIRED]
    exclusions = [c for c in criteria if c.criterion_type is CriterionType.EXCLUSION]
    informational = [c for c in criteria if c.criterion_type is CriterionType.INFORMATIONAL]

    states: dict[str, CriterionState] = {}
    for criterion in required:
        states[criterion.id] = CriterionState.SATISFIED
    for criterion in exclusions:
        states[criterion.id] = CriterionState.NOT_SATISFIED
    for criterion in informational:
        states[criterion.id] = CriterionState.NOT_SATISFIED

    at_threshold = False

    if category is CaseCategory.CLEARLY_FAILS and required:
        states[rng.choice(required).id] = CriterionState.NOT_SATISFIED
    elif category is CaseCategory.EXCLUSION_PRESENT and exclusions:
        states[rng.choice(exclusions).id] = CriterionState.SATISFIED
    elif category is CaseCategory.MISSING_DOCUMENTATION and required:
        states[rng.choice(required).id] = CriterionState.UNKNOWN
    elif category is CaseCategory.INSUFFICIENT_EVIDENCE and len(required) >= 2:
        for criterion in rng.sample(required, k=min(3, len(required))):
            states[criterion.id] = CriterionState.UNKNOWN
    elif category is CaseCategory.BORDERLINE:
        at_threshold = True
    elif category is CaseCategory.CONFLICTING_EVIDENCE and required:
        states[rng.choice(required).id] = CriterionState.SATISFIED

    return states, at_threshold


def _expected(
    states: dict[str, CriterionState],
    criteria: tuple[VerifiedCriterion, ...],
    *,
    conflicting: bool,
    applicable: bool,
) -> tuple[Outcome, int, tuple[str, ...]]:
    """Derive the expected decision with the SAME function the system uses."""
    kind_map = {
        CriterionType.REQUIRED: CriterionKind.REQUIRED,
        CriterionType.EXCLUSION: CriterionKind.EXCLUSION,
        CriterionType.INFORMATIONAL: CriterionKind.INFORMATIONAL,
    }
    verdict_map = {
        CriterionState.SATISFIED: Verdict.SATISFIED,
        CriterionState.NOT_SATISFIED: Verdict.NOT_SATISFIED,
        CriterionState.UNKNOWN: Verdict.INSUFFICIENT_EVIDENCE,
    }

    outcomes = tuple(
        CriterionOutcome(
            criterion_id=criterion.id,
            kind=kind_map[criterion.criterion_type],
            verdict=verdict_map[states[criterion.id]],
            # A state chosen as UNKNOWN has, by construction, no supporting sentence
            # in the note - so it has no evidence behind it either.
            has_valid_evidence=states[criterion.id] is not CriterionState.UNKNOWN,
            missing_evidence=(
                (criterion.summary,) if states[criterion.id] is CriterionState.UNKNOWN else ()
            ),
        )
        for criterion in criteria
        if criterion.id in states
    )

    resolution = ResolutionState(
        ResolutionStatus.RESOLVED if applicable else ResolutionStatus.NONE_APPLICABLE,
        version_count=1 if applicable else 0,
    )
    guardrail = GuardrailState.CONTRADICTION if conflicting else GuardrailState.PASSED
    recommendation = decide(outcomes, guardrail, resolution)
    return recommendation.outcome, int(recommendation.rule), recommendation.missing_evidence


def build_cases(
    plans: list[CasePlan],
    templates: dict[str, dict[str, Any]],
    *,
    seed: int,
    distractors: list[str] | None = None,
    realistic: bool = True,
) -> list[GeneratedCase]:
    """Build the corpus. Deterministic for a given seed and set of plans."""
    rng = random.Random(seed)
    distractors = list(distractors or [])
    cases: list[GeneratedCase] = []
    counter = 0

    for plan in plans:
        policy = plan.policy
        for category, count in plan.counts.items():
            for _ in range(count):
                counter += 1
                case_id = f"CASE-{counter:04d}"
                applicable = category is not CaseCategory.POLICY_NOT_APPLICABLE
                conflicting = category is CaseCategory.CONFLICTING_EVIDENCE

                if not applicable:
                    # A procedure the corpus covers nowhere. Resolution returns
                    # nothing, and row 1 must yield NEEDS_INFO - never a denial.
                    states: dict[str, CriterionState] = {}
                    lines = [
                        "Requested service: unlisted procedure 99199.",
                        "History of chronic pain with prior conservative management.",
                    ]
                    at_threshold = False
                    lines = render_note(lines, distractors, rng, realistic=realistic)
                else:
                    states, at_threshold = _states_for(category, policy.criteria, rng)
                    lines = []
                    for criterion in policy.criteria:
                        if criterion.id not in states:
                            continue
                        sentence = _render(
                            criterion,
                            states[criterion.id],
                            templates,
                            rng,
                            at_threshold=at_threshold and criterion.threshold is not None,
                        )
                        if sentence:
                            lines.append(sentence)
                    if conflicting:
                        lines.append(
                            "Addendum: the record from the outside facility contradicts "
                            "the above and documents no completed course."
                        )
                    lines = render_note(lines, distractors, rng, realistic=realistic)

                # Date of service inside this revision's window, so the case
                # exercises the revision it was built against.
                start = policy.effective_date + timedelta(days=45)
                end = (
                    (policy.end_date - timedelta(days=15)) if policy.end_date else date(2024, 10, 1)
                )
                span = max((end - start).days, 1)
                date_of_service = start + timedelta(days=rng.randint(0, span))

                outcome, rule, missing = _expected(
                    states, policy.criteria, conflicting=conflicting, applicable=applicable
                )

                cases.append(
                    GeneratedCase(
                        case_id=case_id,
                        category=category,
                        policy=policy,
                        date_of_service=date_of_service,
                        criterion_states=states,
                        note_lines=lines,
                        patient=_patient(rng),
                        expected_outcome=outcome,
                        expected_rule=rule,
                        missing_information=missing,
                        conflicting=conflicting,
                        borderline=at_threshold,
                        notes=CATEGORY_INTENT[category],
                    )
                )

    return cases


def corpus_digest(records: list[dict[str, Any]]) -> str:
    """Stable hash of the corpus, for the dataset version."""
    import json

    payload = json.dumps(records, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode()).hexdigest()
