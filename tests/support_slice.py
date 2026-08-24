"""Deterministic doubles for the first vertical slice.

Everything here is a stand-in for something that would otherwise need a container, a
network or a model. **No model call is made anywhere in this file**, and that is not
a convenience: a slice whose safety properties were only demonstrated against a live
model would have its guarantees measured on a moving target.

The corpus is built from the real 42 CFR 410.33 document, so a quote that verifies
here verifies against the same text production would retrieve.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import Any

from pydantic import BaseModel

from app.contracts.slice import (
    AssessmentState,
    ClinicalFact,
    CriterionAssessment,
    IntakeResult,
)
from app.core.identity import PolicyIdentity, PolicyType
from app.core.types import CriterionKind
from app.graph.slice import SliceCriterion
from app.llm.gateway import GatewayFailure, GatewayOutcome, ModelRequest, ModelResponse
from app.retrieval.evidence import EvidenceChunk, content_hash

REPO = Path(__file__).resolve().parents[1]
SOURCE = REPO / "data/cms/CFR-410_33-2026-08-13.md"

IDENTITY = PolicyIdentity(
    policy_type=PolicyType.REGULATION, policy_id="42 CFR 410.33", version="2026-08-13"
)
AS_OF = date(2026, 9, 27)

#: The five transcribed criteria, as the inventory records them.
CRITERIA: tuple[SliceCriterion, ...] = (
    SliceCriterion(
        criterion_id="42_CFR_410_33_2026_08_13_C01",
        kind=CriterionKind.REQUIRED,
        authoritative_text=(
            "must be specifically ordered in writing by the physician who is treating "
            "the beneficiary"
        ),
        interpretation="A verbal or standing order is insufficient.",
        missing_evidence_hint="a written order from the treating physician",
    ),
    SliceCriterion(
        criterion_id="42_CFR_410_33_2026_08_13_C02",
        kind=CriterionKind.REQUIRED,
        authoritative_text="The order must specify the diagnosis or other basis for the testing",
        interpretation="An order naming only the procedure does not satisfy this.",
        missing_evidence_hint="the diagnosis or clinical basis stated on the order",
    ),
    SliceCriterion(
        criterion_id="42_CFR_410_33_2026_08_13_C03",
        kind=CriterionKind.REQUIRED,
        authoritative_text=(
            "must evidence proficiency in the performance and interpretation of each "
            "type of diagnostic procedure"
        ),
        interpretation="Documented by specialty certification or carrier-accepted criteria.",
        missing_evidence_hint="the supervising physician's proficiency documentation",
    ),
    SliceCriterion(
        criterion_id="42_CFR_410_33_2026_08_13_C04",
        kind=CriterionKind.REQUIRED,
        authoritative_text="must demonstrate the basic qualifications to perform the tests in question",
        interpretation="Evidenced by State licensure or certification.",
        missing_evidence_hint="licensure or certification for the technician",
    ),
    SliceCriterion(
        criterion_id="42_CFR_410_33_2026_08_13_C05",
        kind=CriterionKind.EXCLUSION,
        authoritative_text=(
            "must be limited to providing general supervision to no more than three IDTF sites"
        ),
        interpretation="Supervising a fourth concurrent site breaches the limit.",
        missing_evidence_hint="how many sites the supervising physician covers",
    ),
)


def _paragraph(starts_with: str) -> str:
    """One paragraph of the real regulation, verbatim."""
    text = SOURCE.read_text(encoding="utf-8")
    start = text.index(starts_with)
    end = text.find("\n", start)
    return text[start : end if end > 0 else len(text)].strip()


def chunk(chunk_id: str, starts_with: str, section: str) -> EvidenceChunk:
    """A chunk carrying real regulation text, so quotes verify against the source."""
    body = _paragraph(starts_with)
    return EvidenceChunk(
        chunk_id=chunk_id,
        policy_version_id="410-33-v1",
        policy_id="42 CFR 410.33",
        document_type="REGULATION",
        document_title="§ 410.33 Independent diagnostic testing facility.",
        revision_id="2026-08-13",
        section_path=section,
        page_from=1,
        page_to=1,
        text=body,
        text_sha256=content_hash(body),
        effective_date=date(2026, 8, 13),
        end_date=None,
        source_url="https://www.ecfr.gov/current/title-42/section-410.33",
    )


#: One chunk per criterion, each holding the paragraph that criterion came from.
CORPUS: dict[str, EvidenceChunk] = {
    "42_CFR_410_33_2026_08_13_C01": chunk("c-d-1", "(d) Ordering of tests.", "Ordering of tests"),
    "42_CFR_410_33_2026_08_13_C02": chunk("c-d-2", "(d) Ordering of tests.", "Ordering of tests"),
    "42_CFR_410_33_2026_08_13_C03": chunk(
        "c-b-2", "(2) The supervising physician must evidence", "Supervising physician"
    ),
    "42_CFR_410_33_2026_08_13_C04": chunk(
        "c-c-1", "(c) Nonphysician personnel.", "Nonphysician personnel"
    ),
    "42_CFR_410_33_2026_08_13_C05": chunk(
        "c-b-1", "(b) Supervising physician. (1)", "Supervising physician"
    ),
}


NOTE = (
    "IDTF encounter note. Written order received from Dr Chen, the treating "
    "physician, specifying suspected pulmonary embolism as the basis for the study. "
    "Supervising physician holds board certification in diagnostic radiology and "
    "covers two IDTF sites. Technician is State licensed."
)


class FixtureRetrieval:
    """Returns one chunk per criterion. Scope is already applied, as the port requires."""

    def __init__(self, corpus: dict[str, EvidenceChunk] | None = None) -> None:
        self.corpus = CORPUS if corpus is None else corpus
        self.calls: list[str] = []

    async def evidence_for(
        self, criterion: SliceCriterion, *, identity: PolicyIdentity, as_of: date
    ) -> tuple[EvidenceChunk, ...]:
        self.calls.append(criterion.criterion_id)
        found = self.corpus.get(criterion.criterion_id)
        return (found,) if found else ()


class FailingRetrieval:
    """Retrieval that cannot produce an evidence set."""

    async def evidence_for(
        self, criterion: SliceCriterion, *, identity: PolicyIdentity, as_of: date
    ) -> tuple[EvidenceChunk, ...]:
        raise ConnectionError("index unreachable")


def fact(fact_id: str, kind: str, value: str, start: int, end: int) -> ClinicalFact:
    return ClinicalFact(
        fact_id=fact_id,
        kind=kind,
        value=value,
        span_start=start,
        span_end=end,
        extraction_prompt_id="intake.v1",
    )


DEFAULT_FACTS = (
    fact("F1", "DOCUMENTATION", "written order from Dr Chen", 31, 57),
    fact("F2", "DIAGNOSIS", "suspected pulmonary embolism", 96, 124),
    fact("F3", "DOCUMENTATION", "board certification in diagnostic radiology", 160, 202),
    fact("F4", "DOCUMENTATION", "technician State licensed", 230, 255),
)


@dataclass
class FakeGateway:
    """A gateway that returns exactly what a test tells it to.

    `assessments` maps criterion id to the state the model "returns". Anything not
    listed comes back UNKNOWN, which is the safe default for a double: a fixture
    that silently satisfied unlisted criteria would make a test pass by omission.
    """

    assessments: dict[str, AssessmentState] = field(default_factory=dict)
    facts: tuple[ClinicalFact, ...] = DEFAULT_FACTS
    #: Evidence ids to cite per criterion. `None` means "cite E1 when deciding".
    citations: dict[str, tuple[str, ...]] = field(default_factory=dict)
    fail_intake: GatewayOutcome | None = None
    fail_assessment: GatewayOutcome | None = None
    raw_assessment: Callable[[str], CriterionAssessment] | None = None
    model_id: str = "fixture-model"
    calls: list[ModelRequest] = field(default_factory=list)

    async def call[M: BaseModel](self, request: ModelRequest, schema: type[M]) -> ModelResponse[M]:
        self.calls.append(request)

        if request.prompt_id == "intake.v1":
            if self.fail_intake is not None:
                raise GatewayFailure(self.fail_intake, "fixture intake failure")
            value: Any = IntakeResult(
                case_id="CASE-FIXTURE",
                clinical_facts=self.facts,
                prompt_id="intake.v1",
                model_id=self.model_id,
            )
        else:
            if self.fail_assessment is not None:
                raise GatewayFailure(self.fail_assessment, "fixture assessment failure")
            criterion_id = _criterion_from(request.instructions)
            if self.raw_assessment is not None:
                value = self.raw_assessment(criterion_id)
            else:
                state = self.assessments.get(criterion_id, AssessmentState.UNKNOWN)
                cited = self.citations.get(
                    criterion_id, () if state is AssessmentState.UNKNOWN else ("E1",)
                )
                value = CriterionAssessment(
                    criterion_id=criterion_id,
                    assessment=state,
                    evidence_ids=cited,
                    rationale_summary="fixture assessment",
                )

        return ModelResponse(
            value=value,
            outcome=GatewayOutcome.OK,
            model_id=self.model_id,
            prompt_id=request.prompt_id,
            attempts=1,
            latency_ms=1.0,
        )


def _criterion_from(instructions: str) -> str:
    for line in instructions.splitlines():
        if line.startswith("criterion_id:"):
            return line.split(":", 1)[1].strip()
    raise AssertionError("the assessment prompt no longer names its criterion_id")
