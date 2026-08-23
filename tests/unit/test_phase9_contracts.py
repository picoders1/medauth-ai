"""Phase 9: the external-decision path, the migration planner, and the slice contract.

Three things must hold under pressure, and the pressure is real — FOCUS-001 blocks
every route to a first vertical slice:

**An answer cannot be forged.** Not by a default, not by a single call, not by
self-acceptance.

**A migration cannot mutate what it migrates from.** Planning has no write path.

**The contract shapes refuse what they were built to refuse.** An outcome token in
an assessment, an unsupported claim, a citation-free verdict.
"""

from __future__ import annotations

import hashlib
import inspect
import json
from pathlib import Path
from typing import Any

import pytest
from pydantic import ValidationError

from app.contracts.slice import (
    AssessmentState,
    AuditEvent,
    ClinicalFact,
    CriterionAssessment,
    EvidenceMapping,
    EvidenceReference,
    IntakeResult,
    SliceInput,
    SupportState,
)
from app.core.types import CodeSystem, Verdict
from app.decision.abstention import AbstentionReason
from app.production_gate import ProductionGate, ProductionStatus
from app.review.decision_gate import DecisionGate, DecisionStatus
from app.review.focus_impact import FocusOutcome
from app.review.ingest import (
    IngestError,
    accept_decision,
    ingest_submission,
    validate_submission,
)
from app.review.migration import plan_migration

pytestmark = [pytest.mark.unit, pytest.mark.security]

REPO = Path(__file__).resolve().parents[2]
GOLD = REPO / "data/gold/cases/gold_v1.jsonl"
FIXTURES = REPO / "tests/fixtures/slice"
OPTIONS = tuple(o.value for o in FocusOutcome)
REFERENCES = ("docs/review/FOCUS-001.md",)


def _gate() -> DecisionGate:
    return DecisionGate.pending(
        focus_id="FOCUS-001",
        question="q",
        policy_id="42 CFR 410.32",
        policy_version="2026-08-13",
        permitted_decisions=OPTIONS,
        source_references=REFERENCES,
    )


def _payload(**overrides: Any) -> dict[str, Any]:
    base = {
        "focus_id": "FOCUS-001",
        "reviewer_identity": "reviewer-1",
        "reviewer_qualification": "coverage analyst",
        "decision": FocusOutcome.SPLIT_C03.value,
        "rationale": "the escalation is not determinable from the regulation as written",
        "source_reference": "docs/review/FOCUS-001.md",
        "submitted_at": "2026-09-01",
    }
    return {**base, **overrides}


# ---------------------------------------------------------------------------
# External decision ingestion
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "field",
    [
        "reviewer_identity",
        "reviewer_qualification",
        "decision",
        "rationale",
        "source_reference",
        "submitted_at",
    ],
)
def test_a_submission_missing_any_required_field_is_refused(field: str) -> None:
    """A decision missing its rationale is not a decision with an empty rationale.

    It is an unattributable state change, and the difference matters because one of
    them can be waved through.
    """
    issues = validate_submission(
        _payload(**{field: ""}), gate=_gate(), expected_source_references=REFERENCES
    )
    assert any(issue.field == field for issue in issues)


def test_every_issue_is_reported_at_once() -> None:
    """A reviewer sending a decision back gets one list, not one round-trip each."""
    issues = validate_submission(
        _payload(reviewer_identity="", decision="MAYBE", submitted_at="soon"),
        gate=_gate(),
        expected_source_references=REFERENCES,
    )
    assert {issue.field for issue in issues} >= {
        "reviewer_identity",
        "decision",
        "submitted_at",
    }
    assert all(issue.remedy.strip() for issue in issues)


def test_an_unknown_decision_value_is_refused() -> None:
    issues = validate_submission(
        _payload(decision="LOOKS_FINE"), gate=_gate(), expected_source_references=REFERENCES
    )
    assert any("is not one of" in issue.problem for issue in issues)


def test_a_rubber_stamp_rationale_is_refused() -> None:
    """Not a quality bar — this only catches "ok", "yes", "agreed"."""
    issues = validate_submission(
        _payload(rationale="agreed"), gate=_gate(), expected_source_references=REFERENCES
    )
    assert any(issue.field == "rationale" for issue in issues)


def test_a_submission_citing_a_different_source_is_refused() -> None:
    """It may be a considered answer to a different question.

    Accepting it would silently rebase the decision onto a source nobody checked.
    """
    issues = validate_submission(
        _payload(source_reference="an internal wiki page"),
        gate=_gate(),
        expected_source_references=REFERENCES,
    )
    assert any(issue.field == "source_reference" for issue in issues)


def test_a_valid_submission_reaches_submitted_and_no_further() -> None:
    """The positive control, and the boundary in one test.

    If nothing could ever be submitted the refusals above would prove nothing; and
    submission reaching ACCEPTED would make the second act decorative.
    """
    gate = ingest_submission(_payload(), gate=_gate(), expected_source_references=REFERENCES)
    assert gate.status is DecisionStatus.SUBMITTED
    assert not gate.is_resolved
    assert gate.blocks_production


def test_acceptance_by_the_submitter_is_refused() -> None:
    """It collapses two acts into one and removes the only check on the first."""
    gate = ingest_submission(_payload(), gate=_gate(), expected_source_references=REFERENCES)
    with pytest.raises(IngestError, match="both submitted and accepted"):
        accept_decision(gate, {"accepted_by": "reviewer-1", "accepted_at": "2026-09-02"})


def test_acceptance_cannot_predate_the_submission_it_accepts() -> None:
    gate = ingest_submission(_payload(), gate=_gate(), expected_source_references=REFERENCES)
    with pytest.raises(IngestError, match="cannot predate"):
        accept_decision(gate, {"accepted_by": "maintainer", "accepted_at": "2026-08-31"})


def test_acceptance_without_submission_is_refused() -> None:
    with pytest.raises(IngestError, match="cannot accept a PENDING"):
        accept_decision(_gate(), {"accepted_by": "maintainer", "accepted_at": "2026-09-02"})


def test_a_second_submission_over_a_decided_gate_is_refused() -> None:
    """A later answer supersedes rather than overwrites."""
    gate = ingest_submission(_payload(), gate=_gate(), expected_source_references=REFERENCES)
    issues = validate_submission(_payload(), gate=gate, expected_source_references=REFERENCES)
    assert any("already SUBMITTED" in issue.problem for issue in issues)


def test_a_properly_attributed_decision_can_be_accepted() -> None:
    """The end-to-end positive control. Two acts, two identities."""
    gate = ingest_submission(_payload(), gate=_gate(), expected_source_references=REFERENCES)
    accepted = accept_decision(gate, {"accepted_by": "maintainer", "accepted_at": "2026-09-02"})
    assert accepted.status is DecisionStatus.ACCEPTED
    assert accepted.is_resolved
    assert not accepted.blocks_production


def test_no_single_function_turns_a_payload_into_an_accepted_gate() -> None:
    """`ingest_submission` takes a payload; `accept_decision` takes a gate.

    So there is no signature in this module that accepts external data and returns
    an accepted decision.
    """
    assert "payload" in inspect.signature(ingest_submission).parameters
    accept_params = list(inspect.signature(accept_decision).parameters)
    assert accept_params[0] == "gate"


# ---------------------------------------------------------------------------
# Production gate
# ---------------------------------------------------------------------------


def _gate_over(tmp_path: Path, *, decision: dict[str, Any], admissibility: dict[str, Any]):  # type: ignore[no-untyped-def]
    (tmp_path / "decision.json").write_text(json.dumps(decision))
    (tmp_path / "adm.json").write_text(json.dumps(admissibility))
    return ProductionGate(
        admissibility_report=tmp_path / "adm.json",
        decision_records=((tmp_path / "decision.json"),),
    ).evaluate()


READY_ADM = {
    "status": "READY",
    "designated_slice": "REGULATION:42 CFR 410.32:2026-08-13",
    "admissible": ["REGULATION:42 CFR 410.32:2026-08-13"],
    "assessment": [
        {
            "policy_identity": "REGULATION:42 CFR 410.32:2026-08-13",
            "checks": {"production_semantics_executable": True},
        }
    ],
}
ACCEPTED = {"focus_id": "FOCUS-001", "status": "ACCEPTED", "is_resolved": True}
PENDING = {"focus_id": "FOCUS-001", "status": "PENDING", "is_resolved": False}


def test_a_pending_decision_blocks_production(tmp_path: Path) -> None:
    """Even with everything else green."""
    decision = _gate_over(tmp_path, decision=PENDING, admissibility=READY_ADM)
    assert decision.status is ProductionStatus.BLOCKED
    assert not decision.permits_inference
    assert any("PENDING" in blocker for blocker in decision.blockers)


def test_an_inadmissible_policy_blocks_production(tmp_path: Path) -> None:
    blocked = {
        "status": "BLOCKED",
        "designated_slice": None,
        "admissible": [],
        "nearest_candidate": "REGULATION:42 CFR 410.32:2026-08-13",
        "nearest_candidate_blockers": ["no_unresolved_dependency"],
        "assessment": [],
    }
    decision = _gate_over(tmp_path, decision=ACCEPTED, admissibility=blocked)
    assert decision.status is ProductionStatus.BLOCKED
    assert any("no policy version is admissible" in b for b in decision.blockers)


def test_both_conditions_together_permit_inference(tmp_path: Path) -> None:
    """The positive control. If the gate could never open, the blocks prove nothing."""
    decision = _gate_over(tmp_path, decision=ACCEPTED, admissibility=READY_ADM)
    assert decision.status is ProductionStatus.READY
    assert decision.permits_inference
    assert decision.blockers == ()
    decision.require()


def test_an_unreadable_artefact_fails_closed(tmp_path: Path) -> None:
    """The gate could not check is not the gate found nothing wrong."""
    (tmp_path / "decision.json").write_text(json.dumps(ACCEPTED))
    result = ProductionGate(
        admissibility_report=tmp_path / "does-not-exist.json",
        decision_records=((tmp_path / "decision.json"),),
    ).evaluate()
    assert result.status is ProductionStatus.BLOCKED
    assert any("unreadable" in b for b in result.blockers)


def test_an_internally_inconsistent_report_is_refused(tmp_path: Path) -> None:
    """A report claiming READY with no designated slice is half-believed otherwise."""
    inconsistent = {**READY_ADM, "status": "READY", "designated_slice": None, "admissible": []}
    result = _gate_over(tmp_path, decision=ACCEPTED, admissibility=inconsistent)
    assert result.status is ProductionStatus.BLOCKED
    assert any("internally inconsistent" in b for b in result.blockers)


def test_require_raises_when_blocked(tmp_path: Path) -> None:
    """A boolean a caller can ignore is not a gate."""
    result = _gate_over(tmp_path, decision=PENDING, admissibility=READY_ADM)
    with pytest.raises(PermissionError, match="BLOCKED"):
        result.require()


def test_the_real_repository_gate_is_blocked() -> None:
    """Against the committed artefacts, not a fixture."""
    result = ProductionGate(
        admissibility_report=REPO / "data/review/slice_admissibility.json",
        decision_records=((REPO / "data/review/focus_001_decision.json"),),
    ).evaluate()
    assert result.status is ProductionStatus.BLOCKED
    assert result.policy_identity is None


# ---------------------------------------------------------------------------
# gold_v2 migration planning
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def gold() -> tuple[dict[str, Any], ...]:
    return tuple(
        json.loads(line) for line in GOLD.read_text(encoding="utf-8").splitlines() if line.strip()
    )


def test_planning_cannot_modify_gold_v1(gold: tuple[dict[str, Any], ...]) -> None:
    """The regression Part D asks for, against the real frozen corpus."""
    before = hashlib.sha256(GOLD.read_bytes()).hexdigest()
    for outcome in FocusOutcome:
        plan_migration(outcome, gold_cases=gold)
    assert hashlib.sha256(GOLD.read_bytes()).hexdigest() == before


def test_the_planner_has_no_write_path() -> None:
    """Stated as a property of the module, not of one call.

    A planner that could write is a planner that will, the first time someone is in
    a hurry.
    """
    import ast

    source = (REPO / "app/review/migration.py").read_text(encoding="utf-8")
    for forbidden in ("write_text", "open(", "Path(", "os.", "shutil", "mkdir"):
        assert forbidden not in source, f"the migration planner references {forbidden!r}"

    # And the precursor: a filesystem import is harmless on its own and is the
    # first line of any write that follows. Checked over the AST so a mention in
    # prose does not trip it.
    tree = ast.parse(source)
    imported = {
        alias.name.split(".")[0]
        for node in ast.walk(tree)
        if isinstance(node, ast.Import)
        for alias in node.names
    } | {
        node.module.split(".")[0]
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom) and node.module
    }
    assert not imported & {"pathlib", "os", "io", "shutil", "tempfile"}, (
        f"the migration planner imports {sorted(imported & {'pathlib', 'os', 'io', 'shutil', 'tempfile'})}"
    )


def test_every_outcome_is_planned(gold: tuple[dict[str, Any], ...]) -> None:
    """Including the two that require nothing.

    Returning nothing for those would make "no plan" and "not yet planned"
    indistinguishable.
    """
    for outcome in FocusOutcome:
        plan = plan_migration(outcome, gold_cases=gold)
        assert plan.outcome is outcome
        assert plan.summary
        assert plan.is_additive


def test_only_outcomes_changing_c03_require_a_migration(gold: tuple[dict[str, Any], ...]) -> None:
    plans = {o: plan_migration(o, gold_cases=gold) for o in FocusOutcome}
    assert plans[FocusOutcome.NARROW_C03_TO_BASELINE].required
    assert plans[FocusOutcome.SPLIT_C03].required
    assert not plans[FocusOutcome.LEAVE_C03_NOT_ADJUDICABLE].required
    assert not plans[FocusOutcome.OTHER].required


def test_a_migration_carries_unaffected_cases_forward_unchanged(
    gold: tuple[dict[str, Any], ...],
) -> None:
    """23 of 156 change. The other 133 are copied, not regenerated differently."""
    plan = plan_migration(FocusOutcome.NARROW_C03_TO_BASELINE, gold_cases=gold)
    assert plan.cases_total == len(gold)
    assert plan.cases_unchanged == len(gold) - len(plan.cases_migrated)
    assert plan.cases_unchanged > 0


def test_the_plan_names_what_it_must_not_modify(gold: tuple[dict[str, Any], ...]) -> None:
    """Enumerated so the guarantee is checkable rather than a promise in a docstring."""
    plan = plan_migration(FocusOutcome.SPLIT_C03, gold_cases=gold)
    assert "data/gold/cases/gold_v1.jsonl" in plan.must_not_modify
    assert "eval/reports/**" in plan.must_not_modify
    assert any("retrieval_v2" in path for path in plan.must_not_modify)


def test_the_plan_reproduces_the_split_rule_exactly(gold: tuple[dict[str, Any], ...]) -> None:
    """A regenerated set with a different split is a different dataset."""
    steps = " ".join(plan_migration(FocusOutcome.SPLIT_C03, gold_cases=gold).steps)
    assert "sha256(case_id)[:8]" in steps
    assert "0.18" in steps and "0.10" in steps
    assert "supersedes_reason" in steps


# ---------------------------------------------------------------------------
# Slice contract shapes
# ---------------------------------------------------------------------------


def test_an_assessment_cannot_name_an_outcome() -> None:
    """Three states, and no case-level decision among them.

    A successful injection cannot emit an approval because no approval token exists
    in the schema being filled.
    """
    states = {state.value for state in AssessmentState}
    assert states == {"SATISFIED", "NOT_SATISFIED", "UNKNOWN"}
    assert not states & {"APPROVE", "DENY", "APPROVE_RECOMMENDED", "DENY_RECOMMENDED"}


def test_the_slice_vocabulary_narrows_the_adjudication_vocabulary_totally() -> None:
    """Two enums both call themselves "the entire vocabulary". Pin the relationship.

    `Verdict` (four members) is what `decide()` consumes and what gold_v1 labels were
    computed against. `AssessmentState` (three) is what the slice permits a model to
    return. The narrowing is deliberate, and it is only safe if it is TOTAL - a slice
    state with no `Verdict` to map onto would be a value `decide()` cannot receive,
    discovered at the first slice run rather than here.

    `NOT_APPLICABLE` is unreachable in the other direction on purpose: whether a
    criterion applies is answered by `When` in the declared logic, not by the model.
    """
    mapping = {
        AssessmentState.SATISFIED: Verdict.SATISFIED,
        AssessmentState.NOT_SATISFIED: Verdict.NOT_SATISFIED,
        AssessmentState.UNKNOWN: Verdict.INSUFFICIENT_EVIDENCE,
    }
    assert set(mapping) == set(AssessmentState), "a slice state maps nowhere"
    assert len(set(mapping.values())) == len(mapping), "two states collapse into one verdict"
    assert Verdict.NOT_APPLICABLE not in set(mapping.values())

    # Neither vocabulary may grow an outcome, at either boundary.
    tokens = {"APPROVE", "DENY", "APPROVE_RECOMMENDED", "DENY_RECOMMENDED"}
    assert not {v.value for v in Verdict} & tokens
    assert not {s.value for s in AssessmentState} & tokens


def test_a_hedged_assessment_state_is_refused() -> None:
    """`PROBABLY_SATISFIED` is exactly the hedge a model reaches for."""
    with pytest.raises(ValidationError):
        CriterionAssessment(
            criterion_id="C01",
            assessment="PROBABLY_SATISFIED",  # type: ignore[arg-type]
            evidence_ids=("E1",),
            rationale_summary="hedged",
        )


def test_a_decided_assessment_must_cite_evidence() -> None:
    """Only UNKNOWN may be reached without citing something."""
    with pytest.raises(ValidationError, match="with no evidence"):
        CriterionAssessment(
            criterion_id="C01",
            assessment=AssessmentState.SATISFIED,
            evidence_ids=(),
            rationale_summary="satisfied on the basis of nothing",
        )
    unknown = CriterionAssessment(
        criterion_id="C01",
        assessment=AssessmentState.UNKNOWN,
        evidence_ids=(),
        rationale_summary="the note does not address it",
    )
    assert unknown.assessment is AssessmentState.UNKNOWN


def test_an_asserting_mapping_must_cite_both_a_fact_and_a_span() -> None:
    """An unsupported free-text claim has nowhere to live."""
    reference = EvidenceReference(
        evidence_id="E1",
        chunk_id="c1",
        policy_identity="REGULATION:42 CFR 410.32:2026-08-13",
        section_path="Ordering diagnostic tests",
        quote="must be ordered",
    )
    with pytest.raises(ValidationError, match="no policy evidence"):
        EvidenceMapping(
            criterion_id="C01",
            clinical_fact_ids=("F1",),
            evidence=(),
            support_state=SupportState.SUPPORTED,
            provenance="retrieved",
        )
    with pytest.raises(ValidationError, match="no clinical fact"):
        EvidenceMapping(
            criterion_id="C01",
            clinical_fact_ids=(),
            evidence=(reference,),
            support_state=SupportState.SUPPORTED,
            provenance="retrieved",
        )
    missing = EvidenceMapping(
        criterion_id="C01",
        clinical_fact_ids=(),
        evidence=(),
        support_state=SupportState.MISSING,
        provenance="retrieved",
    )
    assert missing.support_state is SupportState.MISSING


def test_missing_and_uncertain_are_distinct() -> None:
    """ "The note does not address this" and "the reading is unclear" send a reviewer
    to different places."""
    assert SupportState.MISSING is not SupportState.UNCERTAIN
    assert {s.value for s in SupportState} == {"SUPPORTED", "CONTRADICTED", "MISSING", "UNCERTAIN"}


def test_intake_has_no_field_for_an_outcome() -> None:
    """Extraction only. There is nowhere to put a recommendation."""
    fields = set(IntakeResult.model_fields) | set(ClinicalFact.model_fields)
    assert not fields & {"outcome", "recommendation", "coverage", "decision", "approved"}


def test_a_clinical_fact_must_locate_in_the_note() -> None:
    """A fact that cannot be located is a claim about the note, not a reading of it."""
    with pytest.raises(ValidationError):
        ClinicalFact(
            fact_id="F1",
            kind="order",
            value="x",
            span_start=5,
            span_end=5,
            extraction_prompt_id="intake.v1",
        )


def test_duplicate_fact_ids_are_refused() -> None:
    """Two facts sharing an id makes a citation ambiguous about what it rests on."""
    fact = ClinicalFact(
        fact_id="F1",
        kind="order",
        value="x",
        span_start=0,
        span_end=3,
        extraction_prompt_id="intake.v1",
    )
    with pytest.raises(ValidationError, match="duplicate fact ids"):
        IntakeResult(
            case_id="c",
            diagnoses=(fact,),
            procedures=(fact,),
            prompt_id="intake.v1",
            model_id="m",
        )


def test_an_audit_event_has_no_field_for_clinical_text() -> None:
    """The rule is structural: there is nowhere a note could be put."""
    fields = set(AuditEvent.model_fields)
    assert not fields & {"note", "clinical_note", "text", "quote", "payload"}
    assert {"fact_ids", "chunk_ids", "criterion_ids"} <= fields


def test_a_slice_input_requires_a_date_of_service() -> None:
    """Version selection is by date of service, never "latest" (ADR-004).

    A default would silently make every undated request resolve against today.
    """
    assert SliceInput.model_fields["date_of_service"].is_required()
    with pytest.raises(ValidationError):
        SliceInput(  # type: ignore[call-arg]
            case_id="c",
            clinical_note="n",
            procedure_code="R0070",
            code_system=CodeSystem.HCPCS,
        )


def test_the_contract_models_refuse_unexpected_fields() -> None:
    """An unexpected field is a refusal, not a silently-dropped value."""
    with pytest.raises(ValidationError):
        EvidenceReference(
            evidence_id="E1",
            chunk_id="c1",
            policy_identity="p",
            section_path="s",
            quote="q",
            source_url="https://example.invalid",  # type: ignore[call-arg]
        )


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def fixtures() -> list[dict[str, Any]]:
    return [
        json.loads(path.read_text(encoding="utf-8")) for path in sorted(FIXTURES.glob("*.json"))
    ]


def test_all_eight_scenarios_exist(fixtures: list[dict[str, Any]]) -> None:
    scenarios = {f["scenario"] for f in fixtures}
    assert scenarios == {
        "ALL_EVIDENCE_PRESENT",
        "ONE_MISSING_CRITERION",
        "CONTRADICTORY_EVIDENCE",
        "INVALID_CITATION",
        "RETRIEVAL_FAILURE",
        "UNRESOLVED_POLICY_SEMANTICS",
        "MODEL_SCHEMA_FAILURE",
        "NO_APPLICABLE_POLICY",
    }


def test_no_fixture_depends_on_an_unresolved_criterion(fixtures: list[dict[str, Any]]) -> None:
    """C03's dependency is open. A fixture asserting a verdict on it would encode an
    answer to the question a reviewer has not been asked yet."""
    for fixture in fixtures:
        referenced = {m["criterion_id"] for m in fixture["evidence_mappings"]} | {
            a["criterion_id"] for a in fixture["criterion_assessments"]
        }
        assert "42_CFR_410_32_2026_08_13_C03" not in referenced, fixture["fixture"]


def test_every_expected_abstention_is_a_real_state(fixtures: list[dict[str, Any]]) -> None:
    valid = {reason.value for reason in AbstentionReason}
    for fixture in fixtures:
        expected = fixture["expected_abstention"]
        if expected is not None:
            assert expected in valid, fixture["fixture"]


def test_the_positive_control_fixture_reaches_no_abstention(fixtures: list[dict[str, Any]]) -> None:
    """Without one, every abstention fixture would pass on a pipeline that never
    decides anything."""
    complete = next(f for f in fixtures if f["scenario"] == "ALL_EVIDENCE_PRESENT")
    assert complete["expected_abstention"] is None
    assert complete["criterion_assessments"]


def test_valid_fixtures_parse_through_the_real_contract_shapes(
    fixtures: list[dict[str, Any]],
) -> None:
    """The fixtures are checked against the schemas, not against a copy of them.

    The schema-failure fixture is expected NOT to parse — that is what it is for.
    """
    for fixture in fixtures:
        SliceInput(
            **{**fixture["input"], "code_system": CodeSystem(fixture["input"]["code_system"])}
        )
        for fact in fixture["intake"]["clinical_facts"]:
            ClinicalFact(**fact)
        for mapping in fixture["evidence_mappings"]:
            EvidenceMapping(
                **{
                    **mapping,
                    "evidence": tuple(EvidenceReference(**e) for e in mapping["evidence"]),
                }
            )
        if fixture["scenario"] == "MODEL_SCHEMA_FAILURE":
            with pytest.raises(ValidationError):
                for assessment in fixture["criterion_assessments"]:
                    CriterionAssessment(**assessment)
        else:
            for assessment in fixture["criterion_assessments"]:
                CriterionAssessment(**assessment)


def test_fixtures_are_not_gold_data(fixtures: list[dict[str, Any]]) -> None:
    """They carry no expected clinical outcome and must never be scored."""
    for fixture in fixtures:
        assert "NOT gold data" in fixture["note"]
        assert "expected_decision" not in fixture
        assert fixture["why_this_fixture_exists"].strip()


def test_fixtures_require_no_model_inference(fixtures: list[dict[str, Any]]) -> None:
    """Assessments are supplied, so the contract can be exercised offline."""
    for fixture in fixtures:
        assert fixture["intake"]["model_id"] == "abstract-structured-model"
