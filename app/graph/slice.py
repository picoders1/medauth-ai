"""The first AI vertical slice, end to end, for one policy version.

```
case -> applicability [SQL, six states] -> intake [model] -> retrieval [port]
     -> mapping [code] -> assessment [model, one call per criterion]
     -> citations [code] -> contradiction [code] -> policy logic [pure]
     -> abstention [code] -> recommendation + audit
```

**Phase 15 changed the first arrow, and it was the important one.** It used to read
`resolution [given]`: the runner was handed a `PolicyIdentity` and passed
`ResolutionState(RESOLVED, 1)` to `decide()` as a literal. Rows 1 and 2 of the
decision table - the rows that refuse to decide when no policy applies, or when
several might - were therefore unreachable from this runtime for the whole of
Phases 11 to 14. CASE-0073 was adjudicated against a policy that does not govern it
and produced `DENY_RECOMMENDED` supported by seven citations that all verified
(R-93). Applicability now runs first, from the structured request, and only
`RESOLVED` continues.

Orchestration lives here because it is the only layer allowed to see every other
one. Two consequences that are the point rather than an accident:

**This module owns all routing.** `app/intake` and `app/adjudication` cannot name a
gateway outcome - the enum member carries a token the layer-boundary test refuses in
those packages - so they let `GatewayFailure` propagate and it is classified here.
That is the correct place: what a blocked call means for a case is a decision about
the case, not about the call.

**The model never reaches `decide()`.** Model output is per-criterion assessments;
this module translates them into `CriterionOutcome` values and `decide()` computes
the recommendation. A successful injection has no token to aim at, because the
approval and denial members do not exist in any schema the model fills.

Not implemented here, deliberately: no LangGraph, no agent loop, no retry policy
beyond the gateway's own. One case, one pass, one policy version.
"""

from __future__ import annotations

import hashlib
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import date
from enum import StrEnum
from typing import Protocol

from app.adjudication.assess import ASSESSMENT_PROMPT_ID, CriterionRequest, assess_criterion
from app.adjudication.evidence_block import EvidenceEntry, evidence_id_for
from app.contracts.slice import (
    AssessmentState,
    AuditEvent,
    ClinicalFact,
    CriterionAssessment,
    EvidenceMapping,
    EvidenceReference,
    IntakeRequest,
    SliceInput,
    SupportState,
)
from app.core.identity import PolicyIdentity
from app.core.types import CriterionKind, ResolutionStatus, Verdict
from app.decision.abstention import AbstentionReason, AbstentionRecord, abstention_for
from app.decision.models import DecisionRule, Outcome, Recommendation
from app.decision.semantics import PolicySemantics
from app.decision.table import CriterionOutcome, GuardrailState, ResolutionState, decide
from app.guardrail.citations import CitationReport, validate_citations
from app.guardrail.contradiction import (
    ContradictionReport,
    ContradictionState,
    analyse_contradictions,
    guardrail_state_for,
)
from app.intake.extract import INTAKE_PROMPT_ID, extract_facts
from app.llm.gateway import GatewayFailure, GatewayOutcome, ModelGateway
from app.policy.applicability import (
    ApplicabilityFinding,
    ApplicabilityReason,
    ApplicabilityRequest,
    designated_without_resolution,
)
from app.production_gate import GateDecision
from app.retrieval.evidence import EvidenceChunk


def _digest(model_id: str) -> str | None:
    """A model identity that can be compared without naming the model.

    Concrete ids are deployment values held in `.env` and appear nowhere in this
    repository - including in an audit row, which is exactly the artefact that gets
    exported.
    """
    return f"sha256:{hashlib.sha256(model_id.encode()).hexdigest()[:12]}" if model_id else None


__all__ = [
    "PRODUCTION_MODES",
    "ApplicabilityPort",
    "RetrievalPort",
    "RunMode",
    "SliceCriterion",
    "SliceOutcome",
    "SliceRunner",
]


class RunMode(StrEnum):
    """Whether this run resolves applicability or was handed a policy.

    The two are kept apart because Phase 14 blurred them and the blur cost a
    fully-cited denial against an inapplicable policy (R-93). A designated policy is
    legitimate for a controlled fixture, a historical replay and a known-policy test;
    it is not legitimate as production's *proof* that the policy governs the case.

    There is no default. `gate` and `semantics` have none for the same reason: a
    default mode is a mode nobody chose, and the one it would have to be is the one
    that skips the check.
    """

    #: Applicability is resolved from the request. Requires an `ApplicabilityPort`.
    PRODUCTION = "PRODUCTION"

    #: A policy is designated by the harness and no resolution is performed. Every
    #: outcome and every audit row says so.
    REPLAY = "REPLAY"


#: Modes a production deployment may run in. `REPLAY` is refused by **absence**,
#: never by a branch that names it - the same technique that keeps the gold-v1
#: replay origin out of `PRODUCTION_ORIGINS`. A branch is a place to add an
#: exception to; an absence is not.
PRODUCTION_MODES: frozenset[RunMode] = frozenset({RunMode.PRODUCTION})


@dataclass(frozen=True, slots=True)
class SliceCriterion:
    """One criterion the slice will assess, as transcribed."""

    criterion_id: str
    kind: CriterionKind
    authoritative_text: str
    interpretation: str
    #: What a reviewer would be asked to supply if this comes back UNKNOWN.
    missing_evidence_hint: str = ""


class RetrievalPort(Protocol):
    """Evidence for one criterion, already scoped.

    A port rather than a direct call so the slice runs identically against pgvector
    and against a fixture corpus. The scope is the port's responsibility: whatever
    implements this must already have applied the policy type, the resolved version
    ids and the date of service, because a slice that could widen its own scope
    would make every containment argument here conditional on a caller.
    """

    async def evidence_for(
        self, criterion: SliceCriterion, *, identity: PolicyIdentity, as_of: date
    ) -> tuple[EvidenceChunk, ...]: ...


class ApplicabilityPort(Protocol):
    """Does the designated policy govern this request? (R-93)

    A port for the same reason retrieval is one: the slice must run identically
    against the database and against a fixture, and the six-state machine has to be
    exercisable without a container. What implements this owns discovery, the
    temporal predicate and the jurisdiction predicate - the slice owns only what to
    do with the answer.

    **It must not raise.** A resolver that throws would be caught by the slice's
    generic handler and reported as something else, and "the database was down" must
    never reach a reviewer as "no policy covers this procedure". Infrastructure
    failure is `RESOLUTION_ERROR`, which is a state, not an exception.
    """

    async def applicability_for(
        self, request: ApplicabilityRequest, *, designated: PolicyIdentity
    ) -> ApplicabilityFinding: ...


@dataclass(frozen=True, slots=True)
class SliceOutcome:
    """Everything one run produced, including what it refused to do."""

    case_id: str
    identity: PolicyIdentity
    recommendation: Recommendation
    assessments: tuple[CriterionAssessment, ...] = ()
    mappings: tuple[EvidenceMapping, ...] = ()
    citations: CitationReport = field(default_factory=CitationReport)
    #: What contradiction analysis concluded. Defaults to UNDETERMINED, not to
    #: NO_CONTRADICTION: a case that never reached the check must not read as one
    #: that passed it.
    contradictions: ContradictionReport = field(
        default_factory=lambda: ContradictionReport(state=ContradictionState.UNDETERMINED)
    )
    abstention: AbstentionRecord | None = None
    audit: tuple[AuditEvent, ...] = ()
    facts: tuple[ClinicalFact, ...] = ()
    #: Wall-clock per stage. Measured, never estimated; absent where a stage did
    #: not run rather than recorded as zero.
    timings_ms: dict[str, float] = field(default_factory=dict)
    #: Tokens actually consumed, summed across every model call this case made.
    #: Measured, never estimated - a case that made no call reports zero and says so
    #: through `model_calls`, which is a different fact from "cost nothing".
    tokens: dict[str, int] = field(default_factory=dict)
    model_calls: int = 0
    model_id: str = ""
    #: Whether applicability was RESOLVED or DESIGNATED. Recorded on the outcome so
    #: a report cannot present a replay as a resolution by omitting the distinction.
    mode: RunMode = RunMode.REPLAY
    #: What the applicability stage concluded. Defaults to the fail-closed reading -
    #: a `SliceOutcome` built by hand has not resolved anything and must not read as
    #: though it had.
    applicability: ApplicabilityFinding | None = None

    @property
    def outcome(self) -> Outcome:
        return self.recommendation.outcome

    @property
    def resolved_applicability(self) -> bool:
        """Whether a real resolution ran and admitted this case.

        `state is RESOLVED` is not enough: a replay finding also carries RESOLVED,
        because a policy *was* designated. The reason is what separates them.
        """
        return (
            self.applicability is not None
            and self.applicability.reason is ApplicabilityReason.DESIGNATED_POLICY_APPLIES
        )


#: What each gateway failure means for the case. Declared as data so a new gateway
#: outcome cannot be added without deciding how a case carrying it is routed.
#: **Every entry routes toward a human. None routes toward a denial.**
_ABSTENTION_FOR_GATEWAY: dict[GatewayOutcome, AbstentionReason] = {
    GatewayOutcome.BLOCKED: AbstentionReason.MODEL_SCHEMA_FAILURE,
    GatewayOutcome.DETECTOR_UNAVAILABLE: AbstentionReason.MODEL_SCHEMA_FAILURE,
    GatewayOutcome.TIMEOUT: AbstentionReason.MODEL_SCHEMA_FAILURE,
    GatewayOutcome.UNREACHABLE: AbstentionReason.MODEL_SCHEMA_FAILURE,
    GatewayOutcome.SCHEMA_INVALID: AbstentionReason.MODEL_SCHEMA_FAILURE,
    GatewayOutcome.UNSUPPORTED: AbstentionReason.MODEL_SCHEMA_FAILURE,
}

#: What each non-RESOLVED applicability state means for the case. Declared as data
#: for the same reason the gateway mapping is: a seventh `ResolutionStatus` cannot be
#: introduced without deciding how a case carrying it is routed, and a test asserts
#: totality over the refusing states.
#:
#: **No entry routes toward a denial.** `NOT_APPLICABLE` in particular is NEEDS_INFO:
#: absence of an NCD or LCD generally means contractor discretion, not non-coverage,
#: and turning it into a denial is the single most harmful thing this system could
#: learn to do (ADR-004).
_ABSTENTION_FOR_RESOLUTION: dict[ResolutionStatus, AbstentionReason] = {
    ResolutionStatus.NOT_APPLICABLE: AbstentionReason.NO_APPLICABLE_POLICY,
    ResolutionStatus.MULTIPLE_CANDIDATES: AbstentionReason.MULTIPLE_CANDIDATE_POLICIES,
    ResolutionStatus.TEMPORALLY_UNRESOLVED: AbstentionReason.POLICY_TEMPORALLY_UNRESOLVED,
    ResolutionStatus.INSUFFICIENT_INFORMATION: (
        AbstentionReason.INSUFFICIENT_APPLICABILITY_INFORMATION
    ),
    ResolutionStatus.RESOLUTION_ERROR: AbstentionReason.POLICY_RESOLUTION_ERROR,
}

#: How a model's assessment becomes a verdict `decide()` understands. Total and
#: injective; `NOT_APPLICABLE` is unreachable from here on purpose, because whether
#: a criterion applies is answered by the declared logic, not by the model.
_VERDICT_FOR: dict[AssessmentState, Verdict] = {
    AssessmentState.SATISFIED: Verdict.SATISFIED,
    AssessmentState.NOT_SATISFIED: Verdict.NOT_SATISFIED,
    AssessmentState.UNKNOWN: Verdict.INSUFFICIENT_EVIDENCE,
}

#: What each assessment says about the fact/criterion relationship.
_SUPPORT_FOR: dict[AssessmentState, SupportState] = {
    AssessmentState.SATISFIED: SupportState.SUPPORTED,
    AssessmentState.NOT_SATISFIED: SupportState.CONTRADICTED,
    AssessmentState.UNKNOWN: SupportState.MISSING,
}


class SliceRunner:
    """One case, one policy version, one pass.

    `semantics` is supplied by the caller and is required by `decide()`. It is not
    loaded here: reading the inventory is I/O, and a runner that fetched its own
    semantics could be handed a case whose policy it then re-resolved.
    """

    def __init__(
        self,
        *,
        gateway: ModelGateway,
        retrieval: RetrievalPort,
        identity: PolicyIdentity,
        criteria: tuple[SliceCriterion, ...],
        semantics: PolicySemantics,
        decision_config_version: str,
        gate: GateDecision,
        mode: RunMode,
        applicability: ApplicabilityPort | None = None,
        clock: Callable[[], float] = time.perf_counter,
    ) -> None:
        # THE GATE IS ENFORCED HERE, not only in the script that calls this.
        #
        # It used to live in `scripts/run_first_slice.py` alone, which made every
        # admissibility argument in this repository conditional on a caller
        # remembering to check - and a caller who constructed this class directly
        # got no check at all. `gate` has no default for the same reason `semantics`
        # has none: a default would be a value nobody established.
        #
        # Enforced at construction rather than in `run()` so a blocked runner cannot
        # be built, held, and invoked later against a gate that was READY when it
        # was made. There is no window in which an unusable runner exists.
        if not isinstance(gate, GateDecision):
            raise TypeError(
                f"{identity}: gate must be a GateDecision produced by "
                "ProductionGate.evaluate(); a truthy stand-in is not a gate"
            )
        gate.require()
        if gate.policy_identity != str(identity):
            raise PermissionError(
                f"the gate designated {gate.policy_identity!r} but this runner was "
                f"built for {str(identity)!r}. Running against a policy the gate did "
                "not designate would measure something other than what it admitted."
            )
        if not criteria:
            raise ValueError(
                f"{identity}: a slice with no criteria would adjudicate nothing "
                "and report success for it"
            )
        # R-93. A PRODUCTION runner without a resolver is the Phase-14 runtime, and
        # the Phase-14 runtime produced a denial with seven verified citations
        # against a policy that did not govern the case.
        #
        # Refused at construction, like the gate: a runner that cannot resolve
        # applicability must not exist in production rather than fail per case,
        # because a per-case failure is 26 abstentions nobody reads as a defect.
        # `mode` has no default, so nobody arrives here without having chosen.
        if mode in PRODUCTION_MODES and applicability is None:
            raise ValueError(
                f"{identity}: {mode.value} requires an ApplicabilityPort. A runner "
                "handed a policy identity and asked to assume it governs is R-93; "
                "use RunMode.REPLAY explicitly if that is genuinely what you want, "
                "and the outcome will say so."
            )
        self._gateway = gateway
        self._retrieval = retrieval
        self._identity = identity
        self._criteria = criteria
        self._semantics = semantics
        self._config_version = decision_config_version
        self._gate = gate
        self._mode = mode
        self._applicability = applicability
        self._clock = clock

    # -- the run ----------------------------------------------------------

    async def run(self, case: SliceInput) -> SliceOutcome:
        """Run the chain. Never raises on a case; every failure becomes an outcome."""
        audit: list[AuditEvent] = []
        timings: dict[str, float] = {}

        def event(name: str, stage: str, **kwargs: object) -> None:
            audit.append(
                AuditEvent(
                    event=name,
                    case_id=case.case_id,
                    stage=stage,
                    decision_config_version=self._config_version,
                    **kwargs,
                )
            )

        # ---- policy applicability (R-93) --------------------------------
        #
        # FIRST. Before intake, before retrieval, before any model call.
        #
        # Not merely because it is cheap - though a case whose policy does not
        # govern should not cost a token - but because every later stage's output is
        # meaningless without it. Phase 14 ran retrieval and six model calls against
        # CASE-0073 and produced a denial supported by seven citations that all
        # verified, from a policy the case does not fall under. The citations were
        # genuine; the reasoning was sound; the document was wrong. Nothing
        # downstream of here can detect that, which is why it is upstream of here.
        started = self._clock()
        finding = await self._resolve_applicability(case)
        timings["applicability"] = (self._clock() - started) * 1000
        event(
            "slice.applicability.resolved",
            "applicability",
            resolution_state=finding.state.value,
            resolution_reason=finding.reason.value,
        )
        if not finding.permits_adjudication:
            return self._refuse_applicability(case, finding, audit, timings, event)

        # ---- intake -----------------------------------------------------
        started = self._clock()
        try:
            intake = await extract_facts(
                IntakeRequest(
                    case_id=case.case_id,
                    clinical_note=case.clinical_note,
                    requested_service=case.procedure_code,
                ),
                gateway=self._gateway,
            )
        except GatewayFailure as failure:
            timings["intake"] = (self._clock() - started) * 1000
            # No response object, so no usage to report. Zero here means "nothing
            # measurable", which is why `model_calls` is reported beside it - an
            # abstention that spent tokens and one that spent none are different
            # facts, and a bare 0 cannot tell them apart.
            return self._abstain(
                case,
                self._gateway_abstention(failure),
                audit,
                timings,
                event,
                model_calls=1,
                applicability=finding,
            )
        timings["intake"] = (self._clock() - started) * 1000
        tokens = {"prompt": intake.prompt_tokens, "completion": intake.completion_tokens}
        calls = 1

        facts = intake.result.all_facts
        event(
            "slice.intake.completed",
            "intake",
            fact_ids=tuple(f.fact_id for f in facts),
        )

        # ---- retrieval, mapping and assessment, one criterion at a time --
        assessments: list[CriterionAssessment] = []
        mappings: list[EvidenceMapping] = []
        all_chunks: dict[str, EvidenceChunk] = {}
        claims: list[tuple[str, str]] = []
        # criterion -> the CHUNKS it actually cited. Evidence ids are
        # criterion-local; chunk ids are what two criteria can genuinely share.
        cited_chunks: dict[str, frozenset[str]] = {}
        fact_tuples = tuple((f.fact_id, f.kind, f.value) for f in facts)

        started = self._clock()
        for criterion in self._criteria:
            try:
                chunks = await self._retrieval.evidence_for(
                    criterion, identity=self._identity, as_of=case.date_of_service
                )
            except Exception:
                timings["retrieval"] = (self._clock() - started) * 1000
                return self._abstain(
                    case,
                    abstention_for(
                        AbstentionReason.RETRIEVAL_FAILURE, subjects=(criterion.criterion_id,)
                    ),
                    audit,
                    timings,
                    event,
                    tokens=dict(tokens),
                    model_calls=calls,
                    applicability=finding,
                )

            entries = tuple(
                EvidenceEntry(evidence_id=evidence_id_for(index), chunk=chunk)
                for index, chunk in enumerate(chunks)
            )
            for entry in entries:
                all_chunks[entry.chunk.chunk_id] = entry.chunk

            try:
                assessment, assessment_tokens = await assess_criterion(
                    CriterionRequest(
                        criterion_id=criterion.criterion_id,
                        criterion_text=criterion.authoritative_text,
                        interpretation=criterion.interpretation,
                        evidence=entries,
                        facts=fact_tuples,
                    ),
                    gateway=self._gateway,
                )
            except GatewayFailure as failure:
                timings["assessment"] = (self._clock() - started) * 1000
                return self._abstain(
                    case,
                    self._gateway_abstention(failure),
                    audit,
                    timings,
                    event,
                    applicability=finding,
                )

            assessments.append(assessment)
            tokens["prompt"] += assessment_tokens[0]
            tokens["completion"] += assessment_tokens[1]
            calls += 1
            by_evidence_id = {e.evidence_id: e for e in entries}
            cited = tuple(by_evidence_id[eid] for eid in assessment.evidence_ids)
            claims.extend((entry.chunk.chunk_id, entry.chunk.text) for entry in cited)
            cited_chunks[criterion.criterion_id] = frozenset(
                entry.chunk.chunk_id for entry in cited
            )
            mappings.append(self._map(criterion, assessment, cited, facts))

        timings["assessment"] = (self._clock() - started) * 1000
        event(
            "slice.assessment.completed",
            "assessment",
            criterion_ids=tuple(a.criterion_id for a in assessments),
            chunk_ids=tuple(all_chunks),
        )

        # ---- citation validation ----------------------------------------
        started = self._clock()
        report = validate_citations(
            tuple(claims),
            evidence_set=tuple(all_chunks.values()),
            identity=self._identity,
        )
        timings["citations"] = (self._clock() - started) * 1000

        if not report.passed:
            event(
                "slice.citations.refused",
                "citation_validation",
                chunk_ids=tuple(cid for cid, _, _ in report.failures),
            )
            return self._abstain(
                case,
                abstention_for(
                    AbstentionReason.UNSUPPORTED_CITATION,
                    subjects=tuple(reason.value for reason in report.failure_reasons),
                ),
                audit,
                timings,
                event,
                assessments=tuple(assessments),
                mappings=tuple(mappings),
                citations=report,
                facts=facts,
                tokens=dict(tokens),
                model_calls=calls,
                model_id=intake.model_id,
                applicability=finding,
            )

        # ---- contradiction analysis --------------------------------------
        #
        # R-89. `GuardrailState.PASSED` used to be passed unconditionally here, which
        # made decision-table row 5 and the CONTRADICTORY_EVIDENCE abstention
        # unreachable from the live runtime for the whole of Phase 11 and 12. An
        # abstention state nothing can produce reads as coverage.
        started = self._clock()
        contradictions = analyse_contradictions(
            tuple(assessments), facts, cited_chunks=cited_chunks
        )
        timings["contradiction"] = (self._clock() - started) * 1000
        event(
            "slice.contradiction.analysed",
            "contradiction",
            contradiction_state=contradictions.state.value,
            criterion_ids=tuple(
                c for f in contradictions.findings for c in f.criterion_ids if c != "<intake>"
            ),
            fact_ids=tuple(i for f in contradictions.findings for i in f.fact_ids),
        )

        if contradictions.is_decisive:
            return self._abstain(
                case,
                abstention_for(
                    AbstentionReason.CONTRADICTORY_EVIDENCE,
                    subjects=tuple(f.kind for f in contradictions.findings),
                ),
                audit,
                timings,
                event,
                assessments=tuple(assessments),
                mappings=tuple(mappings),
                citations=report,
                contradictions=contradictions,
                facts=facts,
                tokens=dict(tokens),
                model_calls=calls,
                model_id=intake.model_id,
                applicability=finding,
            )

        # ---- deterministic decision --------------------------------------
        #
        # The resolution state comes from the finding, not from a literal. It used
        # to read `ResolutionState(RESOLVED, 1)` - a constant, written because the
        # runner had been handed an identity - and that constant is R-93 in one
        # line. Only RESOLVED reaches here now, so the value is the same on the
        # happy path; what changed is that it is now a *measurement*.
        started = self._clock()
        recommendation = decide(
            tuple(self._outcome(c, a) for c, a in zip(self._criteria, assessments, strict=True)),
            guardrail_state_for(contradictions),
            ResolutionState(status=finding.state, version_count=finding.version_count),
            self._semantics,
            as_of=case.date_of_service,
            decision_config_version=self._config_version,
        )
        timings["decision"] = (self._clock() - started) * 1000

        event(
            "slice.decision.computed",
            "decision",
            criterion_ids=tuple(a.criterion_id for a in assessments),
            outcome=recommendation.outcome.value,
            contradiction_state=contradictions.state.value,
            model_digest=_digest(intake.model_id),
        )

        # A contradiction reaches here as rule 5 from the table, and only then is an
        # abstention record built - so the record describes what `decide()` decided
        # rather than a parallel judgement made before it.
        abstention = (
            abstention_for(
                AbstentionReason.CONTRADICTORY_EVIDENCE,
                subjects=tuple(f.kind for f in contradictions.findings),
            )
            if recommendation.rule is DecisionRule.CONTRADICTORY_VERDICTS
            else None
        )
        if abstention is not None:
            event(
                abstention.audit_event,
                "abstention",
                abstention_reason=abstention.reason.value,
                outcome=abstention.outcome.value,
            )

        return SliceOutcome(
            case_id=case.case_id,
            identity=self._identity,
            recommendation=recommendation,
            abstention=abstention,
            assessments=tuple(assessments),
            mappings=tuple(mappings),
            citations=report,
            contradictions=contradictions,
            audit=tuple(audit),
            facts=facts,
            timings_ms=timings,
            tokens=tokens,
            model_calls=calls,
            model_id=intake.model_id,
            mode=self._mode,
            applicability=finding,
        )

    # -- helpers ----------------------------------------------------------

    async def _resolve_applicability(self, case: SliceInput) -> ApplicabilityFinding:
        """Ask the port whether the designated policy governs. Never raises.

        In `REPLAY` the port is not consulted even when one was supplied: a replay
        exists to reproduce a historical label, and a resolution that ran would make
        the reproduction conditional on today's corpus. The finding says
        `DESIGNATED_WITHOUT_RESOLUTION`, so the record cannot be read as a
        resolution that happened to agree.
        """
        if self._mode not in PRODUCTION_MODES or self._applicability is None:
            return designated_without_resolution(self._identity)

        request = ApplicabilityRequest(
            procedure_code=case.procedure_code,
            code_system=case.code_system,
            as_of=case.date_of_service,
            jurisdiction=case.jurisdiction,
            diagnosis_codes=case.diagnosis_codes,
        )
        try:
            return await self._applicability.applicability_for(request, designated=self._identity)
        except Exception as failure:  # a port that raises is itself a fault
            # The port contract says it must not raise. One that does is an
            # engineering fault, and it is recorded as RESOLUTION_ERROR rather than
            # allowed to reach the generic handler, where it would be reported as a
            # retrieval failure and diagnosed against the wrong subsystem.
            return ApplicabilityFinding(
                state=ResolutionStatus.RESOLUTION_ERROR,
                reason=ApplicabilityReason.RESOLVER_FAILED,
                designated=self._identity,
                notes=(
                    f"the applicability port raised {type(failure).__name__}; the "
                    "port contract requires it to classify, not raise",
                ),
            )

    def _refuse_applicability(
        self,
        case: SliceInput,
        finding: ApplicabilityFinding,
        audit: list[AuditEvent],
        timings: dict[str, float],
        event: Callable[..., None],
    ) -> SliceOutcome:
        """Stop the case at applicability. **No retrieval, no model, no tokens.**

        The recommendation is computed by `decide()` rather than taken from the
        abstention record, and the criteria tuple passed to it is empty. That is not
        a shortcut: rows 1, 2, 14, 15 and 16 all fire before anything reads a
        criterion, so an empty tuple is the honest input - this case has no verdicts
        because nothing was ever asked. The abstention record is then built from the
        rule `decide()` returned, which keeps one authority over the outcome instead
        of two that agree until they do not.
        """
        recommendation = decide(
            (),
            GuardrailState.PASSED,
            ResolutionState(status=finding.state, version_count=finding.version_count),
            self._semantics,
            as_of=case.date_of_service,
            decision_config_version=self._config_version,
        )
        record = abstention_for(
            _ABSTENTION_FOR_RESOLUTION[finding.state],
            subjects=(finding.reason.value,),
        )
        event(
            record.audit_event,
            "abstention",
            abstention_reason=record.reason.value,
            outcome=recommendation.outcome.value,
            resolution_state=finding.state.value,
            resolution_reason=finding.reason.value,
        )
        return SliceOutcome(
            case_id=case.case_id,
            identity=self._identity,
            recommendation=recommendation,
            abstention=record,
            audit=tuple(audit),
            timings_ms=timings,
            mode=self._mode,
            applicability=finding,
        )

    def _gateway_abstention(self, failure: GatewayFailure) -> AbstentionRecord:
        """Map a boundary failure to an abstention. Never to a denial.

        A `BLOCKED` response is never retried here or anywhere: retrying a request
        the firewall refused is an attempt to evade a security control, and a retry
        loop treating it as transient would keep trying until one got through.
        """
        reason = _ABSTENTION_FOR_GATEWAY[failure.outcome]
        return abstention_for(
            reason,
            subjects=(failure.outcome.value,),
            remedy=(
                f"the model boundary returned {failure.outcome.value}; route to a "
                "human. A blocked request is never retried."
                if not failure.outcome.is_retryable
                else f"the model boundary returned {failure.outcome.value}; the case "
                "may be re-run once, and routes to a human either way."
            ),
        )

    def _abstain(
        self,
        case: SliceInput,
        record: AbstentionRecord,
        audit: list[AuditEvent],
        timings: dict[str, float],
        event: Callable[..., None],
        **carried: object,
    ) -> SliceOutcome:
        """Stop the case, saying why and what would resolve it."""
        event(
            record.audit_event,
            "abstention",
            abstention_reason=record.reason.value,
            outcome=record.outcome.value,
        )
        recommendation = Recommendation(
            outcome=record.outcome,
            rule=record.rule,
            abstained=True,
            abstention_reason=record.reason.value,
            missing_evidence=record.subjects,
            decision_config_version=self._config_version,
            policy_semantics=self._semantics.status,
            **(
                {"semantics_origin": self._semantics.attestation.origin}
                if self._semantics.attestation
                else {}
            ),
        )
        return SliceOutcome(
            case_id=case.case_id,
            identity=self._identity,
            recommendation=recommendation,
            abstention=record,
            audit=tuple(audit),
            timings_ms=timings,
            mode=self._mode,
            **carried,  # type: ignore[arg-type]
        )

    def _outcome(
        self, criterion: SliceCriterion, assessment: CriterionAssessment
    ) -> CriterionOutcome:
        """Translate one assessment into what the decision table consumes.

        `has_valid_evidence` is the load-bearing field. A NOT_SATISFIED verdict with
        nothing behind it must not reach a denial - it is missing evidence wearing a
        verdict's clothes - so it is set from whether the assessment actually cited
        anything, never assumed.
        """
        return CriterionOutcome(
            criterion_id=criterion.criterion_id,
            kind=criterion.kind,
            verdict=_VERDICT_FOR[assessment.assessment],
            has_valid_evidence=bool(assessment.evidence_ids),
            missing_evidence=(
                (criterion.missing_evidence_hint or criterion.authoritative_text,)
                if assessment.assessment is AssessmentState.UNKNOWN
                else ()
            ),
        )

    def _map(
        self,
        criterion: SliceCriterion,
        assessment: CriterionAssessment,
        cited: tuple[EvidenceEntry, ...],
        facts: tuple[ClinicalFact, ...],
    ) -> EvidenceMapping:
        """Build the fact <-> criterion <-> evidence record a reviewer reads.

        An asserting state with no evidence is refused by the contract, so it is
        demoted to `UNCERTAIN` here rather than allowed to raise: the model said
        something, the mapping cannot support it, and "the reading is unclear" is
        the honest description of that - not "the note does not address it".
        """
        support = _SUPPORT_FOR[assessment.assessment]
        references = tuple(
            EvidenceReference(
                evidence_id=entry.evidence_id,
                chunk_id=entry.chunk.chunk_id,
                policy_identity=str(self._identity),
                section_path=entry.chunk.section_path,
                quote=entry.chunk.text,
            )
            for entry in cited
        )
        fact_ids = tuple(f.fact_id for f in facts)

        if support in (SupportState.SUPPORTED, SupportState.CONTRADICTED) and not (
            references and fact_ids
        ):
            support = SupportState.UNCERTAIN
            references = ()

        return EvidenceMapping(
            criterion_id=criterion.criterion_id,
            clinical_fact_ids=fact_ids if support != SupportState.UNCERTAIN else (),
            evidence=references,
            support_state=support,
            provenance=f"{ASSESSMENT_PROMPT_ID}+{INTAKE_PROMPT_ID}",
        )
