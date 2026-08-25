"""The first AI vertical slice, end to end, for one policy version.

```
case -> intake [model] -> resolution [given] -> retrieval [port] -> mapping [code]
     -> assessment [model, one call per criterion] -> citations [code]
     -> policy logic [pure] -> abstention [code] -> recommendation + audit
```

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

import time
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import date
from typing import Protocol

from app.adjudication.assess import ASSESSMENT_PROMPT_ID, CriterionRequest, assess_criterion
from app.adjudication.evidence_block import EvidenceEntry
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
from app.decision.models import Outcome, Recommendation
from app.decision.semantics import PolicySemantics
from app.decision.table import CriterionOutcome, GuardrailState, ResolutionState, decide
from app.guardrail.citations import CitationReport, validate_citations
from app.intake.extract import INTAKE_PROMPT_ID, extract_facts
from app.llm.gateway import GatewayFailure, GatewayOutcome, ModelGateway
from app.production_gate import GateDecision
from app.retrieval.evidence import EvidenceChunk

__all__ = [
    "RetrievalPort",
    "SliceCriterion",
    "SliceOutcome",
    "SliceRunner",
]


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


@dataclass(frozen=True, slots=True)
class SliceOutcome:
    """Everything one run produced, including what it refused to do."""

    case_id: str
    identity: PolicyIdentity
    recommendation: Recommendation
    assessments: tuple[CriterionAssessment, ...] = ()
    mappings: tuple[EvidenceMapping, ...] = ()
    citations: CitationReport = field(default_factory=CitationReport)
    abstention: AbstentionRecord | None = None
    audit: tuple[AuditEvent, ...] = ()
    facts: tuple[ClinicalFact, ...] = ()
    #: Wall-clock per stage. Measured, never estimated; absent where a stage did
    #: not run rather than recorded as zero.
    timings_ms: dict[str, float] = field(default_factory=dict)
    model_id: str = ""

    @property
    def outcome(self) -> Outcome:
        return self.recommendation.outcome


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
        self._gateway = gateway
        self._retrieval = retrieval
        self._identity = identity
        self._criteria = criteria
        self._semantics = semantics
        self._config_version = decision_config_version
        self._gate = gate
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
            return self._abstain(case, self._gateway_abstention(failure), audit, timings, event)
        timings["intake"] = (self._clock() - started) * 1000

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
                )

            entries = tuple(
                EvidenceEntry(evidence_id=f"E{index + 1}", chunk=chunk)
                for index, chunk in enumerate(chunks)
            )
            for entry in entries:
                all_chunks[entry.chunk.chunk_id] = entry.chunk

            try:
                assessment = await assess_criterion(
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
                return self._abstain(case, self._gateway_abstention(failure), audit, timings, event)

            assessments.append(assessment)
            by_evidence_id = {e.evidence_id: e for e in entries}
            cited = tuple(by_evidence_id[eid] for eid in assessment.evidence_ids)
            claims.extend((entry.chunk.chunk_id, entry.chunk.text) for entry in cited)
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
                model_id=intake.model_id,
            )

        # ---- deterministic decision --------------------------------------
        started = self._clock()
        recommendation = decide(
            tuple(self._outcome(c, a) for c, a in zip(self._criteria, assessments, strict=True)),
            GuardrailState.PASSED,
            ResolutionState(status=ResolutionStatus.RESOLVED, version_count=1),
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
        )

        return SliceOutcome(
            case_id=case.case_id,
            identity=self._identity,
            recommendation=recommendation,
            assessments=tuple(assessments),
            mappings=tuple(mappings),
            citations=report,
            audit=tuple(audit),
            facts=facts,
            timings_ms=timings,
            model_id=intake.model_id,
        )

    # -- helpers ----------------------------------------------------------

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
