"""Why the system declined to decide - without pretending a threshold is calibrated.

Two things are deliberately kept apart here, because collapsing them is how an
uncalibrated system starts sounding calibrated:

**Structural abstention.** Something is missing, broken or unestablished, and no
threshold is involved. A citation that does not verify, a policy whose semantics
nobody has reviewed, a retrieval that failed - these are facts about the case, and
the system can name them today.

**Scored abstention.** The evidence is present and complete, and the system is
declining because a confidence signal fell below a threshold. **No such threshold
exists.** They are selected on the dev split in a later phase, under ADR-011 and
OD-8, and inventing one now would be a fabricated number with clinical
consequences.

So `AbstentionReason` covers only the structural cases, and `ScoredGate` records
that the scored gate is `UNCALIBRATED` rather than omitting it. A system that
silently has no gate and a system that has a gate set to zero look identical in a
report and mean opposite things.

Pure: no I/O, no clock, no thresholds read from anywhere.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum

from app.decision.models import DecisionRule, Outcome

__all__ = [
    "AbstentionReason",
    "AbstentionRecord",
    "ScoredGate",
    "abstention_for",
]


class AbstentionReason(StrEnum):
    """A structural reason to decline. Every one is a fact, not a score.

    Each maps to a decision rule that already exists, so an abstention is always
    explainable by pointing at the row of the table that produced it rather than at
    a number nobody can check.
    """

    #: Resolution found no applicable policy. Included as an abstention because the
    #: system is declining to decide - but it has a different character from the
    #: rest: absence of an NCD or LCD generally means contractor discretion, not a
    #: system failure and not non-coverage. It must never become a denial.
    NO_APPLICABLE_POLICY = "NO_APPLICABLE_POLICY"

    #: A required criterion has no evidence either way. The commonest, and the one
    #: that must never become a denial - it is the difference between "the note
    #: does not say" and "the note says otherwise".
    INSUFFICIENT_EVIDENCE = "INSUFFICIENT_EVIDENCE"

    #: A quote did not verify against the chunk it claimed to come from. No
    #: evidence, no decision - never a lowered score (R-10).
    UNSUPPORTED_CITATION = "UNSUPPORTED_CITATION"

    #: The corpus is unqualified for this policy version: nobody has read the
    #: regulation and established its logic (OD-19).
    UNRESOLVED_POLICY_SEMANTICS = "UNRESOLVED_POLICY_SEMANTICS"

    #: A criterion invokes a rule it does not contain, and that rule is not
    #: transcribed - so its evidence set cannot answer the question asked (R-51).
    UNRESOLVED_POLICY_DEPENDENCY = "UNRESOLVED_POLICY_DEPENDENCY"

    #: A coverage determination governs and what it establishes has not been
    #: recorded by a reviewer (OD-26). Distinct from "no determination governs",
    #: which is contractor discretion and is not an abstention at all.
    UNRESOLVED_COVERAGE = "UNRESOLVED_COVERAGE"

    #: The model returned something the closed schema rejects. Fails toward the
    #: human; never retried into an approval.
    MODEL_SCHEMA_FAILURE = "MODEL_SCHEMA_FAILURE"

    #: Retrieval could not produce an evidence set - an empty scope, an unreachable
    #: index, an embedding failure.
    RETRIEVAL_FAILURE = "RETRIEVAL_FAILURE"

    #: Verdicts disagree with each other. The system does not adjudicate its own
    #: inconsistency.
    CONTRADICTORY_EVIDENCE = "CONTRADICTORY_EVIDENCE"

    # -- Phase 15: what applicability resolution concluded -------------------
    #
    # `NO_APPLICABLE_POLICY` above is the fourth member of this group and predates
    # them; it keeps its name because it is written into committed artefacts.

    #: Several policies could govern, or one document has overlapping in-force
    #: versions. Which one controls is a human judgement and is never ranked.
    MULTIPLE_CANDIDATE_POLICIES = "MULTIPLE_CANDIDATE_POLICIES"

    #: A policy lists the procedure and no version of it was in force on the date
    #: of service. Distinct from "no policy governs": the corpus has the policy.
    POLICY_TEMPORALLY_UNRESOLVED = "POLICY_TEMPORALLY_UNRESOLVED"

    #: The request cannot establish applicability at all - no procedure code, no
    #: code system, or no date of service. The submitter can answer it.
    INSUFFICIENT_APPLICABILITY_INFORMATION = "INSUFFICIENT_APPLICABILITY_INFORMATION"

    #: Resolution failed, or returned a policy other than the one this runtime is
    #: wired to adjudicate. A wiring or infrastructure fault, never a denial.
    POLICY_RESOLUTION_ERROR = "POLICY_RESOLUTION_ERROR"

    #: Phase 16. The model path failed in a way attributable to the provider or the
    #: proxy rather than to the model's answer: a timeout, a 5xx, a connection that
    #: died, or a decoder that satisfied the grammar without ever terminating
    #: (R-86). Routes exactly where `MODEL_SCHEMA_FAILURE` does, and is a SEPARATE
    #: name because the two need different responses and different owners.
    #:
    #: `MODEL_SCHEMA_FAILURE` means the model answered and the answer was refused.
    #: This means there was no answer to refuse. Phase 14 reported ten of these as
    #: sixteen reasoning errors because one name covered both.
    PROVIDER_LIMITATION = "PROVIDER_LIMITATION"


class ScoredGate(StrEnum):
    """The state of the confidence-threshold gate.

    `UNCALIBRATED` is the only value this project may currently use, and it is
    recorded explicitly rather than left absent. "There is no gate" and "the gate
    passed" are different claims, and an audit row that cannot tell them apart
    would let an uncalibrated system read as a confident one.
    """

    #: No threshold has been selected. Thresholds are chosen on the dev split under
    #: ADR-011/OD-8, and none exists yet.
    UNCALIBRATED = "UNCALIBRATED"

    #: A calibrated gate ran and the case passed.
    PASSED = "PASSED"

    #: A calibrated gate ran and withheld the decision.
    WITHHELD = "WITHHELD"


#: Which decision rule each structural reason corresponds to. Declared as data so a
#: new reason cannot be added without deciding where it fires.
_RULE_FOR: dict[AbstentionReason, DecisionRule] = {
    AbstentionReason.NO_APPLICABLE_POLICY: DecisionRule.NO_APPLICABLE_POLICY,
    AbstentionReason.INSUFFICIENT_EVIDENCE: DecisionRule.INSUFFICIENT_EVIDENCE,
    AbstentionReason.UNSUPPORTED_CITATION: DecisionRule.INVALID_CITATION,
    AbstentionReason.UNRESOLVED_POLICY_SEMANTICS: DecisionRule.POLICY_SEMANTICS_UNRESOLVED,
    AbstentionReason.UNRESOLVED_POLICY_DEPENDENCY: DecisionRule.POLICY_SEMANTICS_UNVERIFIED,
    AbstentionReason.UNRESOLVED_COVERAGE: DecisionRule.POLICY_SEMANTICS_UNVERIFIED,
    AbstentionReason.MODEL_SCHEMA_FAILURE: DecisionRule.MODEL_PATH_FAILED,
    AbstentionReason.RETRIEVAL_FAILURE: DecisionRule.MODEL_PATH_FAILED,
    AbstentionReason.CONTRADICTORY_EVIDENCE: DecisionRule.CONTRADICTORY_VERDICTS,
    AbstentionReason.MULTIPLE_CANDIDATE_POLICIES: DecisionRule.CONFLICTING_POLICY,
    AbstentionReason.POLICY_TEMPORALLY_UNRESOLVED: DecisionRule.POLICY_TEMPORALLY_UNRESOLVED,
    AbstentionReason.INSUFFICIENT_APPLICABILITY_INFORMATION: (
        DecisionRule.RESOLUTION_INSUFFICIENT_INFORMATION
    ),
    AbstentionReason.POLICY_RESOLUTION_ERROR: DecisionRule.POLICY_RESOLUTION_ERROR,
    AbstentionReason.PROVIDER_LIMITATION: DecisionRule.MODEL_PATH_FAILED,
}

#: The outcome each reason produces. Only ONE reason yields `NO_DECISION`, and none
#: yields an approval or a denial - abstention is by definition neither.
_OUTCOME_FOR: dict[AbstentionReason, Outcome] = {
    AbstentionReason.NO_APPLICABLE_POLICY: Outcome.NEEDS_INFO,
    AbstentionReason.INSUFFICIENT_EVIDENCE: Outcome.NEEDS_INFO,
    AbstentionReason.UNSUPPORTED_CITATION: Outcome.NO_DECISION,
    AbstentionReason.UNRESOLVED_POLICY_SEMANTICS: Outcome.HUMAN_REVIEW,
    AbstentionReason.UNRESOLVED_POLICY_DEPENDENCY: Outcome.HUMAN_REVIEW,
    AbstentionReason.UNRESOLVED_COVERAGE: Outcome.HUMAN_REVIEW,
    AbstentionReason.MODEL_SCHEMA_FAILURE: Outcome.HUMAN_REVIEW,
    AbstentionReason.RETRIEVAL_FAILURE: Outcome.HUMAN_REVIEW,
    AbstentionReason.CONTRADICTORY_EVIDENCE: Outcome.HUMAN_REVIEW,
    AbstentionReason.MULTIPLE_CANDIDATE_POLICIES: Outcome.HUMAN_REVIEW,
    AbstentionReason.POLICY_TEMPORALLY_UNRESOLVED: Outcome.HUMAN_REVIEW,
    AbstentionReason.INSUFFICIENT_APPLICABILITY_INFORMATION: Outcome.NEEDS_INFO,
    AbstentionReason.POLICY_RESOLUTION_ERROR: Outcome.HUMAN_REVIEW,
    AbstentionReason.PROVIDER_LIMITATION: Outcome.HUMAN_REVIEW,
}


#: The audit event each reason emits. Declared as data so a new reason cannot be
#: added without deciding what it records - an abstention that emits nothing is
#: invisible in the trail that exists to explain refusals.
_AUDIT_EVENT_FOR: dict[AbstentionReason, str] = {
    AbstentionReason.NO_APPLICABLE_POLICY: "abstention.no_applicable_policy",
    AbstentionReason.INSUFFICIENT_EVIDENCE: "abstention.insufficient_evidence",
    AbstentionReason.UNSUPPORTED_CITATION: "abstention.unsupported_citation",
    AbstentionReason.UNRESOLVED_POLICY_SEMANTICS: "abstention.unresolved_policy_semantics",
    AbstentionReason.UNRESOLVED_POLICY_DEPENDENCY: "abstention.unresolved_policy_dependency",
    AbstentionReason.UNRESOLVED_COVERAGE: "abstention.unresolved_coverage",
    AbstentionReason.MODEL_SCHEMA_FAILURE: "abstention.model_schema_failure",
    AbstentionReason.RETRIEVAL_FAILURE: "abstention.retrieval_failure",
    AbstentionReason.CONTRADICTORY_EVIDENCE: "abstention.contradictory_evidence",
    AbstentionReason.MULTIPLE_CANDIDATE_POLICIES: "abstention.multiple_candidate_policies",
    AbstentionReason.POLICY_TEMPORALLY_UNRESOLVED: "abstention.policy_temporally_unresolved",
    AbstentionReason.INSUFFICIENT_APPLICABILITY_INFORMATION: (
        "abstention.insufficient_applicability_information"
    ),
    AbstentionReason.POLICY_RESOLUTION_ERROR: "abstention.policy_resolution_error",
    AbstentionReason.PROVIDER_LIMITATION: "abstention.provider_limitation",
}


@dataclass(frozen=True, slots=True)
class AbstentionRecord:
    """One abstention, with what would have to change for it to stop happening.

    `remedy` is required. An abstention that does not say what would resolve it is
    an apology, and the reviewer receiving it has to work out the next step from
    first principles.
    """

    reason: AbstentionReason
    remedy: str
    subjects: tuple[str, ...] = ()
    scored_gate: ScoredGate = ScoredGate.UNCALIBRATED
    notes: tuple[str, ...] = field(default_factory=tuple)

    def __post_init__(self) -> None:
        if not self.remedy.strip():
            raise ValueError(f"{self.reason.value} recorded with no remedy")

    @property
    def outcome(self) -> Outcome:
        return _OUTCOME_FOR[self.reason]

    @property
    def rule(self) -> DecisionRule:
        return _RULE_FOR[self.reason]

    @property
    def audit_event(self) -> str:
        """The event name this abstention emits into the append-only trail."""
        return _AUDIT_EVENT_FOR[self.reason]

    @property
    def is_scored(self) -> bool:
        """Whether a calibrated threshold produced this. Currently never true."""
        return self.scored_gate is not ScoredGate.UNCALIBRATED


def abstention_for(
    reason: AbstentionReason, *, subjects: tuple[str, ...] = (), remedy: str = ""
) -> AbstentionRecord:
    """Build an abstention, with a default remedy per reason.

    The defaults exist so that a caller cannot produce an abstention with nothing
    actionable in it, and are overridable because a specific case usually knows
    more than the category does.
    """
    defaults = {
        AbstentionReason.NO_APPLICABLE_POLICY: (
            "no policy governs this request. Absence of a determination generally "
            "means contractor discretion, so a human decides - it is never a denial"
        ),
        AbstentionReason.INSUFFICIENT_EVIDENCE: (
            "supply documentation addressing the criteria named in `subjects`"
        ),
        AbstentionReason.UNSUPPORTED_CITATION: (
            "the model cited text that does not appear in the evidence set; the case "
            "must be re-adjudicated or reviewed by a human. Never retried into an "
            "approval"
        ),
        AbstentionReason.UNRESOLVED_POLICY_SEMANTICS: (
            "a qualified reviewer must establish this policy version's decision "
            "logic (OD-19); no engineering change resolves it"
        ),
        AbstentionReason.UNRESOLVED_POLICY_DEPENDENCY: (
            "a criterion invokes a provision that is not transcribed; the provision "
            "must be reviewed and transcribed before this criterion can be "
            "adjudicated (R-51)"
        ),
        AbstentionReason.UNRESOLVED_COVERAGE: (
            "a reviewer must record what this determination establishes (OD-26); it "
            "is never inferred from the document text"
        ),
        AbstentionReason.MODEL_SCHEMA_FAILURE: (
            "the model returned a value the closed schema rejects; route to a human "
            "and record the raw response for diagnosis"
        ),
        AbstentionReason.RETRIEVAL_FAILURE: (
            "no evidence set could be produced; check the resolved scope and the "
            "index before re-running"
        ),
        AbstentionReason.CONTRADICTORY_EVIDENCE: (
            "verdicts disagree; a human must resolve which reading governs"
        ),
        AbstentionReason.MULTIPLE_CANDIDATE_POLICIES: (
            "more than one policy could govern this request; a human must decide "
            "which controls. Ranking them by similarity is exactly the failure "
            "deterministic resolution exists to prevent (ADR-004)"
        ),
        AbstentionReason.POLICY_TEMPORALLY_UNRESOLVED: (
            "a policy lists this procedure but no version of it was in force on the "
            "date of service; confirm the date, or have a reviewer establish which "
            "version governed. Version selection is by date of service, never latest"
        ),
        AbstentionReason.INSUFFICIENT_APPLICABILITY_INFORMATION: (
            "supply the missing element of the request named in `subjects` - "
            "procedure code, code system or date of service. Applicability cannot "
            "be inferred from the clinical narrative"
        ),
        AbstentionReason.POLICY_RESOLUTION_ERROR: (
            "policy resolution failed or returned a policy this runtime is not "
            "wired to adjudicate; this is an engineering fault. Route to a human "
            "and fix the wiring - never re-run against whatever policy was loaded"
        ),
        AbstentionReason.PROVIDER_LIMITATION: (
            "the model path failed at the provider or the proxy, not in the "
            "model's answer - there was no answer to refuse. Route to a human and "
            "record the classification for escalation. **No prompt change fixes "
            "this**, and re-running only re-rolls the same defect"
        ),
    }
    return AbstentionRecord(
        reason=reason,
        remedy=remedy or defaults[reason],
        subjects=subjects,
        scored_gate=ScoredGate.UNCALIBRATED,
    )
