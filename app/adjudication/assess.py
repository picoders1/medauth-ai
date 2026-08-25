"""One criterion, one model call, three possible answers.

Per-criterion isolation is the containment property, not a performance choice. Each
call sees only its own criterion's evidence, so a tampered chunk can influence only
the criterion that retrieved it - and that criterion's verdict still has to survive
span verification before it reaches the decision engine.

This package may produce verdicts and nothing else. It cannot import the decision
layer and cannot name an approval or a denial; the layer-boundary test reads the
source and refuses the tokens even in a comment. That also means it cannot classify
a gateway failure - the enum member that would describe one carries a forbidden
token - so `GatewayFailure` propagates to the orchestrator, which is the layer whose
job it is to route it.
"""

from __future__ import annotations

from dataclasses import dataclass

from app.adjudication.evidence_block import EvidenceEntry, render_evidence_block, render_fact_block
from app.contracts.slice import AssessmentState, CriterionAssessment
from app.llm.gateway import ModelGateway, ModelRequest, ModelRole

__all__ = ["ASSESSMENT_PROMPT_ID", "CriterionRequest", "assess_criterion"]

#: Versioned. Editing the template in place without incrementing this breaks audit
#: reproducibility and is a defect.
ASSESSMENT_PROMPT_ID = "adjudication.v1"

_INSTRUCTIONS = """\
Assess ONE criterion against the evidence provided.

criterion_id: {criterion_id}
criterion: {criterion_text}
what it means: {interpretation}

Return `assessment` as exactly one of SATISFIED, NOT_SATISFIED, UNKNOWN.

SATISFIED and NOT_SATISFIED each require at least one entry in `evidence_ids`. Only
UNKNOWN may be reached without citing anything - it is the one answer that rests on
an absence.

Quote policy text exactly if you rely on it. Quotes are checked character by
character against the retrieved passage, and a paraphrase stops the case.

There is no approval and no denial in your schema.\
"""


@dataclass(frozen=True, slots=True)
class CriterionRequest:
    """Everything one assessment call needs, and nothing that would let it wander."""

    criterion_id: str
    criterion_text: str
    interpretation: str
    evidence: tuple[EvidenceEntry, ...]
    #: `(fact_id, kind, value)` for the facts intake located in the note.
    facts: tuple[tuple[str, str, str], ...]


async def assess_criterion(
    request: CriterionRequest, *, gateway: ModelGateway
) -> tuple[CriterionAssessment, tuple[int, int]]:
    """Ask the model about one criterion. Returns a validated closed schema.

    Raises `GatewayFailure` on any boundary problem, deliberately un-caught here:
    deciding what a blocked or unavailable call means for a case is a routing
    decision, and routing lives above this layer.

    The returned `criterion_id` is overwritten with the one asked about. A model
    that answered about a different criterion would otherwise have its answer
    filed under a criterion nobody assessed - and the closed schema cannot catch
    that, because a wrong id is still a string.
    """
    call = ModelRequest(
        role=ModelRole.STRUCTURED_ADJUDICATION,
        prompt_id=ASSESSMENT_PROMPT_ID,
        instructions=_INSTRUCTIONS.format(
            criterion_id=request.criterion_id,
            criterion_text=request.criterion_text,
            interpretation=request.interpretation,
        ),
        evidence_block=(
            render_fact_block(request.facts) + "\n\n" + render_evidence_block(request.evidence)
        ),
        schema_name="CriterionAssessment",
        schema=CriterionAssessment.model_json_schema(),
        # One criterion, one small object, a two-sentence rationale. A ceiling this
        # tight is itself a check: a response that needs more is not the shape this
        # schema describes.
        max_output_tokens=512,
    )

    response = await gateway.call(call, CriterionAssessment)
    answer = response.value

    known = {entry.evidence_id for entry in request.evidence}
    cited = tuple(eid for eid in answer.evidence_ids if eid in known)

    # An evidence id the model invented is dropped rather than trusted. If dropping
    # it leaves a decided assessment with nothing behind it, the assessment becomes
    # UNKNOWN: a verdict whose only support was fabricated is not a weaker verdict,
    # it is an absence of one.
    used = (response.prompt_tokens, response.completion_tokens)

    if answer.assessment is not AssessmentState.UNKNOWN and not cited:
        return CriterionAssessment(
            criterion_id=request.criterion_id,
            assessment=AssessmentState.UNKNOWN,
            evidence_ids=(),
            rationale_summary=(
                "downgraded to UNKNOWN: the assessment cited no evidence that was in "
                f"this criterion's evidence set (claimed {list(answer.evidence_ids)})"
            ),
            uncertainty=answer.uncertainty,
        ), used

    return CriterionAssessment(
        criterion_id=request.criterion_id,
        assessment=answer.assessment,
        evidence_ids=cited,
        rationale_summary=answer.rationale_summary,
        uncertainty=answer.uncertainty,
    ), used
