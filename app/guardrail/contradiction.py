"""Do the assessments disagree with each other, or with the facts they cite?

Decision-table row 5 has always existed and, until now, has never been reachable:
the slice passed `GuardrailState.PASSED` unconditionally, so `CONTRADICTION` and the
`CONTRADICTORY_EVIDENCE` abstention were decoration (R-89). An abstention state that
nothing can produce is worse than no state at all - it reads as coverage.

## What this may and may not conclude

It reads **structured evidence only**: per-criterion assessments, the evidence ids
they cite, and the clinical facts intake located with spans. It never re-reads the
note and never asks a model. A contradiction detector that inferred new clinical
content would be adjudicating, and the thing it would be adjudicating is the output
of the component that is supposed to adjudicate.

One correction worth recording: the first version of this module compared
`evidence_ids` across criteria. Those are assigned **per criterion** - `E1` in one
criterion's set is a different passage from `E1` in another's - so it was comparing
labels rather than sources, and fired on every ordinary case. It compares chunk ids
now, which are global.

So it detects **structural** disagreement - two verdicts that cannot both hold given
the same evidence - and reports `UNDETERMINED` for everything else. That is a narrow
capability and the docstring says so rather than the report implying more.

## Why UNDETERMINED is not CONTRADICTION

`UNDETERMINED` means the analysis could not tell. It must stay **non-decisive**: it
neither routes to a human nor clears the way to a decision, it simply says nothing,
and the rest of the pipeline proceeds on the evidence it has. Collapsing it into
`CONTRADICTION` would make every thin case look like a conflict; collapsing it into
`NO_CONTRADICTION` would claim a check ran that did not.

Pure: no I/O, no model, no clock.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from enum import StrEnum

from app.contracts.slice import AssessmentState, ClinicalFact, CriterionAssessment
from app.decision.table import GuardrailState

__all__ = [
    "ContradictionFinding",
    "ContradictionReport",
    "ContradictionState",
    "analyse_contradictions",
    "guardrail_state_for",
]


class ContradictionState(StrEnum):
    """Three states, and the third is not a hedge.

    `UNDETERMINED` is a real answer: the evidence available to this analysis does not
    settle the question. It is kept apart from `NO_CONTRADICTION` because "checked
    and clean" and "could not check" send a reviewer to different places.
    """

    NO_CONTRADICTION = "NO_CONTRADICTION"
    CONTRADICTION = "CONTRADICTION"
    UNDETERMINED = "UNDETERMINED"


@dataclass(frozen=True, slots=True)
class ContradictionFinding:
    """One conflict, with everything a reviewer needs to check it themselves.

    Every field is required rather than optional. A finding that cannot say which
    facts, which evidence and why is an assertion, and an assertion is what the whole
    citation apparatus exists to make impossible.
    """

    kind: str
    reason: str
    criterion_ids: tuple[str, ...]
    fact_ids: tuple[str, ...] = ()
    evidence_ids: tuple[str, ...] = ()
    conflicting_values: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not self.reason.strip():
            raise ValueError(f"{self.kind}: a finding with no reason cannot be checked")
        if not self.criterion_ids:
            raise ValueError(f"{self.kind}: a finding that names no criterion is not locatable")


@dataclass(frozen=True, slots=True)
class ContradictionReport:
    """What the analysis concluded, and what it could not reach."""

    state: ContradictionState
    findings: tuple[ContradictionFinding, ...] = ()
    notes: tuple[str, ...] = field(default_factory=tuple)

    def __post_init__(self) -> None:
        if self.state is ContradictionState.CONTRADICTION and not self.findings:
            raise ValueError(
                "CONTRADICTION with no findings. A conflict nobody can point at is "
                "an assertion, and it would route a case to a human with nothing to read."
            )
        if self.state is not ContradictionState.CONTRADICTION and self.findings:
            raise ValueError(
                f"{self.state.value} carrying {len(self.findings)} finding(s). A "
                "finding that does not change the state is a conflict being reported "
                "and ignored."
            )

    @property
    def is_decisive(self) -> bool:
        """Whether this report should stop the case. Only `CONTRADICTION` does."""
        return self.state is ContradictionState.CONTRADICTION

    @property
    def audit_payload(self) -> dict[str, object]:
        """Ids and reasons. **No clinical text** - `conflicting_values` carries the
        fact ids' values only where they are already structured, and the audit event
        that consumes this carries ids alone."""
        return {
            "contradiction_state": self.state.value,
            "finding_count": len(self.findings),
            "criterion_ids": sorted({c for f in self.findings for c in f.criterion_ids}),
            "fact_ids": sorted({i for f in self.findings for i in f.fact_ids}),
            "evidence_ids": sorted({e for f in self.findings for e in f.evidence_ids}),
            "kinds": sorted({f.kind for f in self.findings}),
        }


def _same_evidence_opposite_verdicts(
    assessments: Sequence[CriterionAssessment],
    cited_chunks: Mapping[str, frozenset[str]],
) -> list[ContradictionFinding]:
    """Two criteria resting on the SAME evidence and reaching opposite verdicts.

    The clearest structural conflict available without reading anything: one passage
    cannot simultaneously establish and refute, and if two criteria disagree while
    citing only it, one of the two readings is wrong. Which one is not a question this
    layer answers.
    """
    findings: list[ContradictionFinding] = []
    decided = [
        a for a in assessments if a.assessment is not AssessmentState.UNKNOWN and a.evidence_ids
    ]
    for i, first in enumerate(decided):
        for second in decided[i + 1 :]:
            if first.assessment is second.assessment:
                continue
            # CHUNK ids, not evidence ids. Evidence ids are assigned per criterion -
            # `E1` in one criterion's set and `E1` in another's are different
            # passages. Comparing them across criteria compares labels, not sources,
            # and made this detector fire on every ordinary fixture case.
            first_chunks = cited_chunks.get(first.criterion_id, frozenset())
            second_chunks = cited_chunks.get(second.criterion_id, frozenset())
            if not first_chunks or not second_chunks:
                continue
            shared = first_chunks & second_chunks
            # Only when the sources are IDENTICAL, not merely overlapping. Two
            # criteria legitimately share a passage while testing different things,
            # and flagging that would make the detector fire on ordinary cases - which
            # is how a check gets switched off.
            if shared and first_chunks == second_chunks:
                findings.append(
                    ContradictionFinding(
                        kind="SAME_EVIDENCE_OPPOSITE_VERDICTS",
                        reason=(
                            f"{first.criterion_id} is {first.assessment.value} and "
                            f"{second.criterion_id} is {second.assessment.value}, both "
                            f"resting on exactly {sorted(shared)}. One passage cannot "
                            "both establish and refute."
                        ),
                        criterion_ids=(first.criterion_id, second.criterion_id),
                        evidence_ids=tuple(sorted(shared)),  # chunk ids
                        conflicting_values=(
                            first.assessment.value,
                            second.assessment.value,
                        ),
                    )
                )
    return findings


def _duplicate_criterion_verdicts(
    assessments: Sequence[CriterionAssessment],
) -> list[ContradictionFinding]:
    """The same criterion assessed twice, differently.

    Should be impossible - the slice assesses each criterion once - which is exactly
    why it is checked. An invariant nobody verifies is an assumption, and this one
    would silently pick whichever verdict happened to be last.
    """
    findings: list[ContradictionFinding] = []
    seen: dict[str, CriterionAssessment] = {}
    for assessment in assessments:
        previous = seen.get(assessment.criterion_id)
        if previous is not None and previous.assessment is not assessment.assessment:
            findings.append(
                ContradictionFinding(
                    kind="DUPLICATE_CRITERION_DISAGREEMENT",
                    reason=(
                        f"{assessment.criterion_id} was assessed twice, as "
                        f"{previous.assessment.value} and {assessment.assessment.value}."
                    ),
                    criterion_ids=(assessment.criterion_id,),
                    evidence_ids=tuple(
                        sorted(set(previous.evidence_ids) | set(assessment.evidence_ids))
                    ),
                    conflicting_values=(
                        previous.assessment.value,
                        assessment.assessment.value,
                    ),
                )
            )
        seen[assessment.criterion_id] = assessment
    return findings


def _conflicting_facts(facts: Sequence[ClinicalFact]) -> list[ContradictionFinding]:
    """Two facts of the same kind covering the SAME SPAN with different values.

    Span overlap is the only structural signal available here. Two facts about
    different sentences may legitimately differ - a note can record a verbal order and
    later a written one - and calling that a contradiction would flag ordinary clinical
    documentation. **Semantic disagreement is deliberately NOT detected**: judging
    whether "two sites" and "five sites" conflict requires reading, and reading is the
    thing this layer refuses to do.
    """
    findings: list[ContradictionFinding] = []
    by_span: dict[tuple[str, int, int], list[ClinicalFact]] = {}
    for fact in facts:
        by_span.setdefault((fact.kind, fact.span_start, fact.span_end), []).append(fact)

    for (kind, start, end), group in sorted(by_span.items()):
        values = {f.value for f in group}
        if len(group) > 1 and len(values) > 1:
            findings.append(
                ContradictionFinding(
                    kind="SAME_SPAN_DIFFERENT_VALUES",
                    reason=(
                        f"{len(group)} {kind} facts were extracted from the same span "
                        f"[{start}:{end}] with different values. The same words cannot "
                        "carry both readings."
                    ),
                    criterion_ids=("<intake>",),
                    fact_ids=tuple(sorted(f.fact_id for f in group)),
                    conflicting_values=tuple(sorted(values)),
                )
            )
    return findings


def analyse_contradictions(
    assessments: Sequence[CriterionAssessment],
    facts: Sequence[ClinicalFact] = (),
    cited_chunks: Mapping[str, frozenset[str]] | None = None,
) -> ContradictionReport:
    """Structural contradiction analysis over what the pipeline already produced.

    Returns `UNDETERMINED` when there is not enough decided, evidenced material to
    conclude anything - which is honest rather than convenient. A case where every
    criterion came back `UNKNOWN` has not been checked for contradictions; saying
    `NO_CONTRADICTION` would claim otherwise.
    """
    findings = (
        _same_evidence_opposite_verdicts(assessments, cited_chunks or {})
        + _duplicate_criterion_verdicts(assessments)
        + _conflicting_facts(facts)
    )
    if findings:
        return ContradictionReport(state=ContradictionState.CONTRADICTION, findings=tuple(findings))

    evidenced = [
        a for a in assessments if a.assessment is not AssessmentState.UNKNOWN and a.evidence_ids
    ]
    # UNDETERMINED whenever the VERDICT comparison could not run, even if the fact
    # comparison did. Two evidenced verdicts are what that check needs, and reporting
    # NO_CONTRADICTION on the strength of a clean fact scan would claim a check that
    # never happened - the exact overstatement this state exists to prevent.
    if len(evidenced) < 2:
        return ContradictionReport(
            state=ContradictionState.UNDETERMINED,
            notes=(
                f"only {len(evidenced)} evidenced verdict(s): the verdict comparison "
                "did not run. Not a clean bill of health.",
                f"the fact comparison ran over {len(facts)} located fact(s) and found "
                "no same-span conflict, which is a narrower statement.",
            ),
        )

    return ContradictionReport(
        state=ContradictionState.NO_CONTRADICTION,
        notes=(
            f"compared {len(evidenced)} evidenced verdict(s) and {len(facts)} fact(s); "
            "no structural conflict. Semantic disagreement is out of scope here.",
        ),
    )


def guardrail_state_for(report: ContradictionReport) -> GuardrailState:
    """Map an analysis result onto what the decision table consumes.

    A named rule rather than an inline ternary at the call site. Two reasons, and
    the second is the one that mattered: a mapping with a name can be tested
    directly, and an inline conditional inside a long argument list was
    demonstrably hard to prove sensitive to mutation - the slice-level test kept
    passing when the branch was removed, and chasing why through the pipeline cost
    more than extracting it.

    **`UNDETERMINED` maps to `PASSED`, and that is not the same as saying it is
    clean.** It means this analysis has no basis to stop the case; the report still
    carries `UNDETERMINED` and says so where a reviewer reads it. Encoding "could
    not check" as a guardrail state would need a table row that does not exist, and
    inventing one to hold an unknown is how an unknown becomes a verdict.
    """
    return (
        GuardrailState.CONTRADICTION
        if report.state is ContradictionState.CONTRADICTION
        else GuardrailState.PASSED
    )
