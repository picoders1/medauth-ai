"""Does the designated policy actually govern this request? (R-93, ADR-004)

Phase 14 ran 26 cases through a slice that was *handed* a `PolicyIdentity` and then
asserted `ResolutionState(RESOLVED)` on the strength of having been handed one. The
decision table's row 1 - the row that refuses to decide when no policy applies - was
therefore unreachable from the live runtime for the whole of Phases 11 to 14, and
CASE-0073 produced `DENY_RECOMMENDED` with **seven verified citations and zero
citation failures** against a policy the case's own gold record says does not govern
it. Every grounding metric passed that case, because the citations were genuine. It
is precisely the failure ADR-004 was written to prevent, and it happened on a live
run.

This module is the missing stage. It is deliberately split in two:

**Discovery and filtering are SQL** (`app/policy/live_applicability.py`), reusing
`in_force_on` and `applies_in_jurisdiction` so there is still exactly one temporal
predicate in this system. A second copy in Python would pass every test written
against today's corpus and start disagreeing the moment a version is superseded -
which is the defect `app/policy/temporal.py` exists to prevent.

**Classification is pure** (here). It receives counts and identities, never a
session, so all six states are exercisable as a truth table with no database. It
imports no encoder and no model: applicability is decided by rules over
`policy_code_links`, and the moment similarity influences it the ADR-004 guarantee
is gone.

## The one thing this module will not do

It will not read the clinical note. CASE-0073's note says "unlisted procedure
99199"; its structured `requested_procedure.code` says `R0075`, which the corpus
genuinely links to 42 CFR 410.33. A resolver that reached into the narrative to
recover the "intended" answer would be a semantic resolver wearing a deterministic
one's clothes, and it would resolve differently for the same structured request
depending on prose. The disagreement is a **dataset** defect (R-97), and it is
reported as one.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from enum import StrEnum

from app.core.identity import PolicyIdentity
from app.core.types import CodeSystem, ResolutionStatus

__all__ = [
    "ApplicabilityFinding",
    "ApplicabilityReason",
    "ApplicabilityRequest",
    "CandidateCensus",
    "classify",
    "designated_without_resolution",
]


class ApplicabilityReason(StrEnum):
    """*Why* applicability came out the way it did, in a reviewer's words.

    Finer-grained than `ResolutionStatus` on purpose. "No policy lists this
    procedure" and "policies list it, but none in your jurisdiction" are the same
    state - the request is not covered by anything this system holds - and they are
    completely different sentences to put in front of a human. A state without a
    reason produces an abstention that says only "no".
    """

    #: The designated policy version governs. The only reason that permits a model
    #: call, and the only one paired with `ResolutionStatus.RESOLVED`.
    DESIGNATED_POLICY_APPLIES = "DESIGNATED_POLICY_APPLIES"

    # -- NOT_APPLICABLE ------------------------------------------------------
    #: Nothing in the corpus lists this procedure code as covered, ever, anywhere.
    NO_POLICY_LISTS_THE_PROCEDURE = "NO_POLICY_LISTS_THE_PROCEDURE"
    #: Policies list it, and none of them reaches the request's jurisdiction. A
    #: jurisdiction the caller did not state excludes jurisdictional policies rather
    #: than admitting them, so this is reachable from an absent jurisdiction too.
    NO_POLICY_IN_THIS_JURISDICTION = "NO_POLICY_IN_THIS_JURISDICTION"
    #: Versions are in force, and versions reach the jurisdiction, and no single
    #: version does both. Kept apart from the two above because it is the one that
    #: usually means the corpus is incomplete rather than the request uncovered.
    NO_POLICY_APPLIES_ON_THESE_FACTS = "NO_POLICY_APPLIES_ON_THESE_FACTS"

    # -- MULTIPLE_CANDIDATES -------------------------------------------------
    #: Two or more distinct policies could govern. Which one does is a judgement.
    SEVERAL_POLICIES_COULD_GOVERN = "SEVERAL_POLICIES_COULD_GOVERN"
    #: One document has overlapping in-force versions - a corpus defect, surfaced
    #: as a candidate conflict rather than resolved by picking one.
    CORPUS_VERSIONS_OVERLAP = "CORPUS_VERSIONS_OVERLAP"

    # -- TEMPORALLY_UNRESOLVED -----------------------------------------------
    #: A policy lists the procedure; no version of it was in force on the date of
    #: service. Version selection is by date of service, never "latest".
    NO_VERSION_IN_FORCE_ON_THAT_DATE = "NO_VERSION_IN_FORCE_ON_THAT_DATE"

    # -- INSUFFICIENT_INFORMATION --------------------------------------------
    #: No procedure code. Applicability has nothing to key on.
    NO_PROCEDURE_CODE = "NO_PROCEDURE_CODE"
    #: A bare code string with no code system. `93000` is a CPT code and an ICD-10
    #: code and they name different things; guessing picks a policy by coincidence.
    CODE_SYSTEM_NOT_STATED = "CODE_SYSTEM_NOT_STATED"
    #: No date of service, so no version window can be applied at all.
    NO_DATE_OF_SERVICE = "NO_DATE_OF_SERVICE"

    # -- RESOLUTION_ERROR ----------------------------------------------------
    #: Resolution raised. Infrastructure, not coverage.
    RESOLVER_FAILED = "RESOLVER_FAILED"
    #: Resolution succeeded and named a policy this runtime is not wired to
    #: adjudicate. Adjudicating the designated one anyway is exactly CASE-0073.
    RESOLVED_POLICY_IS_NOT_THE_DESIGNATED_ONE = "RESOLVED_POLICY_IS_NOT_THE_DESIGNATED_ONE"
    #: Same, where the disagreement is the layer of authority: a regulation states
    #: statutory conditions, an NCD makes a coverage determination, and a runtime
    #: holding one must not adjudicate a case the other governs.
    RESOLVED_POLICY_TYPE_DIFFERS = "RESOLVED_POLICY_TYPE_DIFFERS"
    #: Same, where the disagreement is the version. "Close enough" is how a case is
    #: decided against a revision that was not in force when the service happened.
    RESOLVED_VERSION_IS_NOT_THE_DESIGNATED_ONE = "RESOLVED_VERSION_IS_NOT_THE_DESIGNATED_ONE"

    # -- REPLAY --------------------------------------------------------------
    #: No resolution was performed; a policy was designated by the harness. Never
    #: produced in `RunMode.PRODUCTION`, and it exists so that a replay result can
    #: never be read as a resolved one - the record says which it was.
    DESIGNATED_WITHOUT_RESOLUTION = "DESIGNATED_WITHOUT_RESOLUTION"


@dataclass(frozen=True, slots=True)
class ApplicabilityRequest:
    """The structured facts applicability is allowed to see. No free text.

    Every field is optional in the type and required in effect: an absent one
    produces `INSUFFICIENT_INFORMATION` rather than a default. `SliceInput` makes
    all three mandatory at its own boundary, so the absent cases arrive from API
    callers and from tests - both of which must be refused, not guessed at.
    """

    procedure_code: str
    code_system: CodeSystem | None
    as_of: date | None
    jurisdiction: str | None = None
    diagnosis_codes: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class CandidateCensus:
    """How many policy versions survive each filter, counted in SQL.

    Three counts rather than three lists, and rather than one list filtered in
    Python. The point is that `classify()` performs no temporal or jurisdictional
    reasoning of its own: it reads counts that `in_force_on` and
    `applies_in_jurisdiction` produced, so this system still has exactly one
    implementation of "in force on".

    Each count is over versions whose `policy_code_links` row lists the request's
    procedure code as a covered procedure under an admissible link provenance.
    """

    #: Versions listing the code at all - no date filter, no jurisdiction filter.
    total: int = 0
    #: ... and in force on the date of service.
    in_force: int = 0
    #: ... and reaching the request's jurisdiction.
    in_jurisdiction: int = 0

    def __post_init__(self) -> None:
        if min(self.total, self.in_force, self.in_jurisdiction) < 0:
            raise ValueError("a census count cannot be negative")
        if self.in_force > self.total or self.in_jurisdiction > self.total:
            raise ValueError(
                f"census subsets exceed the total ({self.in_force}, "
                f"{self.in_jurisdiction} of {self.total}); the filters are not "
                "being applied to the same candidate set"
            )


@dataclass(frozen=True, slots=True)
class ApplicabilityFinding:
    """What the applicability stage concluded, and everything a reviewer needs.

    `permits_adjudication` is read straight off the state rather than stored, so a
    finding cannot be constructed that refuses in its state and permits in its flag.
    """

    state: ResolutionStatus
    reason: ApplicabilityReason
    designated: PolicyIdentity
    selected: PolicyIdentity | None = None
    applicable: tuple[PolicyIdentity, ...] = ()
    census: CandidateCensus = field(default_factory=CandidateCensus)
    notes: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        resolved = self.state is ResolutionStatus.RESOLVED
        if resolved and self.selected is None:
            raise ValueError(
                f"{self.designated}: RESOLVED with no selected version. A resolution "
                "that cannot name what it resolved to is the Phase-14 defect exactly"
            )
        if resolved and self.selected != self.designated:
            raise ValueError(
                f"RESOLVED selected {self.selected} but the runtime is wired for "
                f"{self.designated}; adjudicating one against the other is R-93"
            )

    @property
    def permits_adjudication(self) -> bool:
        """Whether retrieval and the model may run. True for RESOLVED alone."""
        return self.state.permits_adjudication

    @property
    def version_count(self) -> int:
        """What `ResolutionState` records - versions found applicable, not candidates."""
        return len(self.applicable)

    @property
    def summary(self) -> str:
        """One line, for a console and for an audit note. No clinical text."""
        where = f" -> {self.selected}" if self.selected else ""
        return f"{self.state.value}/{self.reason.value}{where} (candidates {self.census.total})"


def classify(
    request: ApplicabilityRequest,
    *,
    designated: PolicyIdentity,
    applicable: tuple[PolicyIdentity, ...] = (),
    census: CandidateCensus | None = None,
    conflicts: tuple[str, ...] = (),
    error: str | None = None,
) -> ApplicabilityFinding:
    """Six states from structured facts. Total, pure, and never raising on data.

    The order below is the safety property. Every refusing branch is checked before
    the admitting one, so `RESOLVED` is reachable only by falling through all of
    them - a state arrived at by elimination, never by default. An early `return
    RESOLVED` inserted anywhere above would be visible as exactly that.
    """
    census = census or CandidateCensus()

    def finding(
        state: ResolutionStatus,
        reason: ApplicabilityReason,
        *,
        selected: PolicyIdentity | None = None,
        note: str = "",
    ) -> ApplicabilityFinding:
        return ApplicabilityFinding(
            state=state,
            reason=reason,
            designated=designated,
            selected=selected,
            applicable=applicable if state is ResolutionStatus.RESOLVED else (),
            census=census,
            notes=(note,) if note else (),
        )

    # 1 - The resolver itself failed. Says nothing about coverage, so it must not
    #     be reported as a coverage answer.
    if error is not None:
        return finding(
            ResolutionStatus.RESOLUTION_ERROR,
            ApplicabilityReason.RESOLVER_FAILED,
            note=f"policy resolution failed: {error}",
        )

    # 2 - The request cannot key applicability. Checked before anything is counted,
    #     because a census taken on a missing code is a census of nothing.
    if not request.procedure_code.strip():
        return finding(
            ResolutionStatus.INSUFFICIENT_INFORMATION,
            ApplicabilityReason.NO_PROCEDURE_CODE,
            note="the request names no procedure code",
        )
    if request.code_system is None:
        return finding(
            ResolutionStatus.INSUFFICIENT_INFORMATION,
            ApplicabilityReason.CODE_SYSTEM_NOT_STATED,
            note=f"{request.procedure_code} was supplied without a code system",
        )
    if request.as_of is None:
        return finding(
            ResolutionStatus.INSUFFICIENT_INFORMATION,
            ApplicabilityReason.NO_DATE_OF_SERVICE,
            note="no date of service, so no version window can be applied",
        )

    # 3 - The corpus disagrees with itself, or several policies could govern.
    #     Checked before "nothing applies" so an overlap is never reported as an
    #     absence, and before the admitting branch so ambiguity never resolves.
    if conflicts:
        return finding(
            ResolutionStatus.MULTIPLE_CANDIDATES,
            ApplicabilityReason.CORPUS_VERSIONS_OVERLAP,
            note="; ".join(conflicts),
        )
    if len(applicable) > 1:
        named = ", ".join(sorted(str(i) for i in applicable))
        return finding(
            ResolutionStatus.MULTIPLE_CANDIDATES,
            ApplicabilityReason.SEVERAL_POLICIES_COULD_GOVERN,
            note=f"{len(applicable)} versions apply: {named}",
        )

    # 4 - Nothing applies. Which *kind* of nothing is the useful part.
    if not applicable:
        if census.total == 0:
            return finding(
                ResolutionStatus.NOT_APPLICABLE,
                ApplicabilityReason.NO_POLICY_LISTS_THE_PROCEDURE,
                note=(
                    f"no policy version lists {request.code_system.value} "
                    f"{request.procedure_code} as a covered procedure. Absence of a "
                    "determination is contractor discretion, not non-coverage"
                ),
            )
        if census.in_force == 0:
            return finding(
                ResolutionStatus.TEMPORALLY_UNRESOLVED,
                ApplicabilityReason.NO_VERSION_IN_FORCE_ON_THAT_DATE,
                note=(
                    f"{census.total} version(s) list {request.procedure_code} and "
                    f"none was in force on {request.as_of}"
                ),
            )
        if census.in_jurisdiction == 0:
            return finding(
                ResolutionStatus.NOT_APPLICABLE,
                ApplicabilityReason.NO_POLICY_IN_THIS_JURISDICTION,
                note=(
                    f"{census.total} version(s) list {request.procedure_code}; none "
                    f"reaches jurisdiction {request.jurisdiction or '(unstated)'}. An "
                    "unstated jurisdiction excludes jurisdictional policies"
                ),
            )
        return finding(
            ResolutionStatus.NOT_APPLICABLE,
            ApplicabilityReason.NO_POLICY_APPLIES_ON_THESE_FACTS,
            note=(
                f"{census.in_force} version(s) in force and {census.in_jurisdiction} "
                "in jurisdiction, and no single version is both"
            ),
        )

    # 5 - Exactly one applies. It still has to be the one this runtime holds
    #     criteria and a criteria tree for.
    selected = applicable[0]
    if selected != designated:
        if selected.policy_type is not designated.policy_type:
            reason = ApplicabilityReason.RESOLVED_POLICY_TYPE_DIFFERS
        elif selected.scope_key == designated.scope_key:
            reason = ApplicabilityReason.RESOLVED_VERSION_IS_NOT_THE_DESIGNATED_ONE
        else:
            reason = ApplicabilityReason.RESOLVED_POLICY_IS_NOT_THE_DESIGNATED_ONE
        return finding(
            ResolutionStatus.RESOLUTION_ERROR,
            reason,
            note=(
                f"resolution selected {selected}; this runtime adjudicates "
                f"{designated}. Adjudicating one against the other is R-93"
            ),
        )

    # 6 - The designated policy governs. Reached only by elimination.
    return finding(
        ResolutionStatus.RESOLVED,
        ApplicabilityReason.DESIGNATED_POLICY_APPLIES,
        selected=selected,
    )


def designated_without_resolution(designated: PolicyIdentity) -> ApplicabilityFinding:
    """The replay finding. **Never reachable from `RunMode.PRODUCTION`.**

    A historical replay reproduces gold_v1's labels, which were computed against a
    designated policy before this stage existed. It is admitted, and it is stamped:
    the state says `RESOLVED` because the harness designated a policy, and the
    reason says `DESIGNATED_WITHOUT_RESOLUTION` so that no reader and no report can
    mistake it for a resolution that ran.
    """
    return ApplicabilityFinding(
        state=ResolutionStatus.RESOLVED,
        reason=ApplicabilityReason.DESIGNATED_WITHOUT_RESOLUTION,
        designated=designated,
        selected=designated,
        applicable=(designated,),
        notes=(
            "REPLAY: no applicability resolution was performed. This finding is not "
            "evidence that the policy governs the case.",
        ),
    )
