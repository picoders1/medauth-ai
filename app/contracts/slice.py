"""Schemas for the first AI vertical slice. Contract only - no runtime.

Every boundary in the future execution path gets a closed, validated shape here,
before anything is built against it. A contract discovered to be wrong after an
agent exists is a contract nobody changes.

    synthetic case -> intake -> resolution -> retrieval -> evidence selection
      -> criterion assessment -> policy logic -> citation validation
      -> abstention gate -> recommendation -> audit event

Three prohibitions run through all of it, and each is enforced by the shapes rather
than by a rule someone must remember:

**Intake cannot name an outcome.** `ClinicalFact` has no field in which one would
fit, and `app/intake` may not contain the tokens at all (AST-enforced).

**Assessment is per criterion and its vocabulary is closed.** `CriterionAssessment`
permits `SATISFIED`, `NOT_SATISFIED`, `UNKNOWN` and nothing else. A successful
prompt injection cannot emit an approval because no approval token exists in the
schema being filled.

**Every claim carries evidence ids.** A support state with no evidence is refused at
construction, so an unsupported free-text claim has nowhere to live.

Pydantic models with `extra="forbid"`: an unexpected field is a refusal, not a
silently-dropped value.
"""

from __future__ import annotations

from datetime import date
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.core.types import CodeSystem

__all__ = [
    "AssessmentState",
    "AuditEvent",
    "CriterionAssessment",
    "EvidenceMapping",
    "EvidenceReference",
    "ExtractedFact",
    "IntakeExtraction",
    "IntakeRequest",
    "IntakeResult",
    "SliceInput",
    "SupportState",
]


class _Strict(BaseModel):
    """Frozen and closed. An unexpected field is a refusal, not a dropped value."""

    model_config = ConfigDict(frozen=True, extra="forbid")


# ---------------------------------------------------------------------------
# Input
# ---------------------------------------------------------------------------


class SliceInput(_Strict):
    """One case entering the slice.

    `date_of_service` is required and has no default. Version selection is by date
    of service, never "latest" (ADR-004), and a default would silently make every
    undated request resolve against today's revision.
    """

    case_id: str = Field(min_length=1)
    #: Synthetic only. **No real PHI, ever.**
    clinical_note: str = Field(min_length=1)
    procedure_code: str = Field(min_length=1)
    code_system: CodeSystem
    date_of_service: date
    #: Reported to the reviewer, never used to decide applicability (ADR-004).
    diagnosis_codes: tuple[str, ...] = ()
    #: Absent means jurisdictional policies do NOT apply - never that they do.
    jurisdiction: str | None = None


# ---------------------------------------------------------------------------
# Intake
# ---------------------------------------------------------------------------


class IntakeRequest(_Strict):
    """What the intake step is asked for. Extraction only."""

    case_id: str = Field(min_length=1)
    clinical_note: str = Field(min_length=1)
    requested_service: str = Field(min_length=1)


class ClinicalFact(_Strict):
    """One extracted fact, anchored to the text it came from.

    The span is required. A fact that cannot be located in the note is a claim about
    the note rather than a reading of it, and it would be uncheckable downstream by
    exactly the reviewer who most needs to check it.

    There is deliberately no `outcome`, `recommendation` or `coverage` field: intake
    extracts what the note says and must not reason about what it means for
    coverage.
    """

    fact_id: str = Field(min_length=1)
    kind: str = Field(min_length=1)
    value: str = Field(min_length=1)
    span_start: int = Field(ge=0)
    span_end: int = Field(gt=0)
    #: Only if the model reports one. Never synthesised, and never used as a
    #: threshold - no threshold is calibrated (ADR-011, OD-8).
    model_reported_confidence: float | None = Field(default=None, ge=0.0, le=1.0)
    extraction_prompt_id: str = Field(min_length=1)

    @model_validator(mode="after")
    def _span_is_real(self) -> ClinicalFact:
        if self.span_end <= self.span_start:
            raise ValueError(f"{self.fact_id}: span {self.span_start}:{self.span_end} is empty")
        return self


class ExtractedFact(_Strict):
    """One fact AS THE MODEL REPORTS IT. The model-facing half of `ClinicalFact`.

    It exists because of a defect found during live activation on 2026-08-25.
    `IntakeResult` was handed to the model directly, and it requires `prompt_id`,
    `model_id` and per-fact `extraction_prompt_id` - **values the model has no way
    to know**. Under grammar-constrained decoding the model could not produce them
    and could not stop either, because the grammar forbids terminating an incomplete
    document. It padded with whitespace until the token ceiling: 2000 tokens, 96% of
    them spaces, three times per case, 180 seconds, no result.

    The rule that follows is worth stating plainly: **a model-facing schema must
    contain only fields the model can actually produce.** Our metadata is joined
    afterwards by `extract_facts`, which is where it was always coming from.
    """

    fact_id: str = Field(min_length=1)
    kind: str = Field(min_length=1)
    value: str = Field(min_length=1)
    span_start: int = Field(ge=0)
    span_end: int = Field(gt=0)
    model_reported_confidence: float | None = Field(default=None, ge=0.0, le=1.0)


class IntakeExtraction(_Strict):
    """What the intake call returns. Extraction only, and nothing we already know.

    Same three-state discipline as `CriterionAssessment`: no outcome field exists
    here either, so there is nothing for an injection to aim at.
    """

    case_id: str = Field(min_length=1)
    diagnoses: tuple[ExtractedFact, ...] = ()
    procedures: tuple[ExtractedFact, ...] = ()
    clinical_facts: tuple[ExtractedFact, ...] = ()
    temporal_facts: tuple[ExtractedFact, ...] = ()
    documentation_facts: tuple[ExtractedFact, ...] = ()

    @property
    def buckets(self) -> dict[str, tuple[ExtractedFact, ...]]:
        return {
            "diagnoses": self.diagnoses,
            "procedures": self.procedures,
            "clinical_facts": self.clinical_facts,
            "temporal_facts": self.temporal_facts,
            "documentation_facts": self.documentation_facts,
        }


class IntakeResult(_Strict):
    """Structured clinical evidence. **Never an outcome.**"""

    case_id: str = Field(min_length=1)
    diagnoses: tuple[ClinicalFact, ...] = ()
    procedures: tuple[ClinicalFact, ...] = ()
    clinical_facts: tuple[ClinicalFact, ...] = ()
    temporal_facts: tuple[ClinicalFact, ...] = ()
    documentation_facts: tuple[ClinicalFact, ...] = ()
    #: Which prompt version produced this, so an extraction is reproducible.
    prompt_id: str = Field(min_length=1)
    model_id: str = Field(min_length=1)

    @property
    def all_facts(self) -> tuple[ClinicalFact, ...]:
        return (
            *self.diagnoses,
            *self.procedures,
            *self.clinical_facts,
            *self.temporal_facts,
            *self.documentation_facts,
        )

    @model_validator(mode="after")
    def _fact_ids_are_unique(self) -> IntakeResult:
        ids = [fact.fact_id for fact in self.all_facts]
        if len(set(ids)) != len(ids):
            raise ValueError(f"{self.case_id}: duplicate fact ids")
        return self


# ---------------------------------------------------------------------------
# Evidence mapping
# ---------------------------------------------------------------------------


class SupportState(StrEnum):
    """How a clinical fact bears on a criterion.

    `MISSING` and `UNCERTAIN` are distinct on purpose: "the note does not address
    this" and "the note addresses it and the reading is unclear" send a reviewer to
    different places, and merging them is how a request for records gets sent when
    a clinical judgement was needed.
    """

    SUPPORTED = "SUPPORTED"
    CONTRADICTED = "CONTRADICTED"
    MISSING = "MISSING"
    UNCERTAIN = "UNCERTAIN"


class EvidenceReference(_Strict):
    """A located quote from a policy chunk. Derived fields are joined, never given.

    `source_url`, `effective_date` and `document_title` are deliberately absent:
    they come from the database at render time. Accepting them from a model would
    let it assert provenance it cannot have (ADR-009).
    """

    evidence_id: str = Field(min_length=1)
    chunk_id: str = Field(min_length=1)
    policy_identity: str = Field(min_length=1)
    section_path: str = Field(min_length=1)
    quote: str = Field(min_length=1)


class EvidenceMapping(_Strict):
    """`ClinicalFact` <-> `PolicyCriterion` <-> `EvidenceReference`.

    A `SUPPORTED` or `CONTRADICTED` mapping must cite both a fact and a policy span.
    Without them it is an assertion, and an assertion is what this whole structure
    exists to make impossible.
    """

    criterion_id: str = Field(min_length=1)
    clinical_fact_ids: tuple[str, ...] = ()
    evidence: tuple[EvidenceReference, ...] = ()
    support_state: SupportState
    citation: str | None = None
    provenance: str = Field(min_length=1)

    @model_validator(mode="after")
    def _claims_carry_evidence(self) -> EvidenceMapping:
        asserting = self.support_state in (SupportState.SUPPORTED, SupportState.CONTRADICTED)
        if asserting and not self.evidence:
            raise ValueError(
                f"{self.criterion_id}: {self.support_state.value} with no policy "
                "evidence. A mapping that asserts without citing is an unsupported "
                "free-text claim."
            )
        if asserting and not self.clinical_fact_ids:
            raise ValueError(
                f"{self.criterion_id}: {self.support_state.value} with no clinical "
                "fact. The mapping must say WHAT in the note it rests on."
            )
        return self


# ---------------------------------------------------------------------------
# Structured assessment
# ---------------------------------------------------------------------------


class AssessmentState(StrEnum):
    """The entire vocabulary available to a model assessing one criterion.

    Three members, and no case-level outcome among them. There is no
    `APPROVE`, no `DENY`, no `LIKELY_SATISFIED` and no `PARTIALLY_SATISFIED` -
    each would be a token an injection could aim at, or a hedge that a downstream
    step would have to interpret.

    `NOT_APPLICABLE` is deliberately absent too: whether a criterion applies is a
    policy-logic question answered by `When` in the declared logic, not a judgement
    for the model making the assessment.
    """

    SATISFIED = "SATISFIED"
    NOT_SATISFIED = "NOT_SATISFIED"
    UNKNOWN = "UNKNOWN"


class CriterionAssessment(_Strict):
    """One criterion's assessment. **Never a case-level decision.**

    `rationale_summary` exists for a reviewer to read and is never parsed. Anything
    the system acts on comes from `assessment` and `evidence_ids`, both closed and
    checkable - a system that acted on free text would be reasoning about prose a
    model wrote about prose a model read.
    """

    criterion_id: str = Field(min_length=1)
    assessment: AssessmentState
    evidence_ids: tuple[str, ...] = ()
    rationale_summary: str = Field(min_length=1, max_length=2000)
    #: The model's own words about what it was unsure of. Not a probability, not a
    #: threshold input.
    uncertainty: str | None = None

    @model_validator(mode="after")
    def _a_decided_assessment_cites_evidence(self) -> CriterionAssessment:
        if self.assessment is not AssessmentState.UNKNOWN and not self.evidence_ids:
            raise ValueError(
                f"{self.criterion_id}: {self.assessment.value} with no evidence. "
                "Only UNKNOWN may be reached without citing something."
            )
        return self


# ---------------------------------------------------------------------------
# Audit
# ---------------------------------------------------------------------------


class AuditEvent(_Strict):
    """One append-only record. **Never carries clinical text.**

    Payloads carry fact ids, chunk ids and spans; text is joined for display.
    Redaction is enforced at the structlog sink rather than per call site, and this
    shape makes the rule structural: there is no field a note could be put in.
    """

    event: str = Field(min_length=1)
    case_id: str = Field(min_length=1)
    stage: str = Field(min_length=1)
    fact_ids: tuple[str, ...] = ()
    chunk_ids: tuple[str, ...] = ()
    criterion_ids: tuple[str, ...] = ()
    outcome: str | None = None
    abstention_reason: str | None = None
    #: Which committed decision-policy version produced this. An audit row that
    #: cannot name it cannot be reproduced.
    decision_config_version: str = Field(min_length=1)
