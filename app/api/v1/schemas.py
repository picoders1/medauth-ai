"""Request and response models. **No ORM row ever crosses this boundary.**

Returning a `CaseRow` would publish the schema as the contract: a column rename becomes
a breaking API change, and a column added for internal bookkeeping becomes a field
callers start depending on. Every response here is built explicitly from a row.

## The recommendation is a typed object, never raw model output

`RecommendationResponse` carries the outcome, the rule that produced it, the policy
identity, the abstention state and the provider-failure state. It does not carry a
model rationale, a free-form conclusion or anything the model wrote in prose. The
system's answer is what `decide()` computed; the model produced per-criterion verdicts
and nothing else, and the API is the last place that distinction could be lost.

`confidence_state` is a **string state**, not a number. `UNCALIBRATED` is the honest
value and a float here would be read as a probability by every consumer.
"""

from __future__ import annotations

from datetime import date, datetime

from pydantic import BaseModel, ConfigDict, Field

from app.audit.models import HumanReviewAction, ReviewOutcome
from app.case.lifecycle import CaseState

__all__ = [
    "AcceptRequest",
    "AuditEventResponse",
    "CaseResponse",
    "CaseStatusResponse",
    "EvidenceResponse",
    "OverrideRequest",
    "RecommendationResponse",
    "RequestInformationRequest",
    "ReviewCaseResponse",
    "ReviewRequest",
    "ReviewResponse",
    "SubmitCaseRequest",
]


class _Strict(BaseModel):
    """Unknown fields are refused everywhere, as they are in the model contracts."""

    model_config = ConfigDict(extra="forbid", frozen=True)


class SubmitCaseRequest(_Strict):
    case_id: str = Field(min_length=1, max_length=64)
    #: Synthetic only. **No real PHI, ever.** Hashed on receipt; never persisted.
    clinical_note: str = Field(min_length=1)
    procedure_code: str = Field(min_length=1, max_length=16)
    code_system: str = Field(min_length=1, max_length=16)
    #: Required, and no default. Version selection is by date of service, never
    #: "latest" - a default would silently resolve every undated request against today.
    date_of_service: date
    diagnosis_codes: tuple[str, ...] = ()
    #: Absent means jurisdictional policies do NOT apply - never that they do.
    jurisdiction: str = ""


class CaseResponse(_Strict):
    case_id: str
    case_version: int
    state: CaseState
    procedure_code: str
    code_system: str
    jurisdiction: str
    date_of_service: date
    #: The digest of what was submitted. The submission itself is not stored.
    input_sha256: str
    created_at: datetime
    updated_at: datetime
    request_id: str


class CaseStatusResponse(_Strict):
    case_id: str
    state: CaseState
    #: What may legally happen next. Published so a client need not hardcode the graph.
    allowed_next: tuple[CaseState, ...]
    awaiting_human_review: bool
    updated_at: datetime
    request_id: str


class RecommendationResponse(_Strict):
    """What the engine concluded. Never raw model output - see the module docstring."""

    case_id: str
    outcome: str
    decision_rule: str
    abstention_reason: str | None = None
    resolution_state: str | None = None
    resolution_reason: str | None = None
    policy_type: str | None = None
    policy_id: str | None = None
    policy_version: str | None = None
    #: Present when the provider path broke. A broken response path is not a wrong
    #: answer, and this field exists so a consumer cannot conflate them.
    provider_failure_kind: str | None = None
    provider_failure_attribution: str | None = None
    #: A state, not a number. See the module docstring.
    confidence_state: str
    human_review_required: bool
    model_calls: int
    run_seq: int
    created_at: datetime
    request_id: str


class EvidenceItem(_Strict):
    """One retrieved passage, by reference. The text is joined for display elsewhere."""

    chunk_id: str
    policy_type: str | None = None
    policy_id: str | None = None
    policy_version: str | None = None
    section: str | None = None
    criterion_ids: tuple[str, ...] = ()


class EvidenceResponse(_Strict):
    case_id: str
    items: tuple[EvidenceItem, ...]
    #: True when the run recorded no evidence - a different fact from "none was relevant".
    empty_because_not_assessed: bool
    request_id: str


class AcceptRequest(_Strict):
    """Accept the engine's recommendation as the disposition.

    No rationale is required: agreeing with a recorded, cited, rule-derived
    recommendation adds no information a later reader lacks. Disagreeing does, which is
    why `OverrideRequest` requires one.
    """

    comment: str | None = Field(default=None, max_length=2000)
    stated_qualification: str = Field(default="", max_length=512)


class OverrideRequest(_Strict):
    """Decide against the engine. **Rationale required, and it must say what to.**"""

    override_outcome: ReviewOutcome
    rationale: str = Field(min_length=1, max_length=4000)
    stated_qualification: str = Field(default="", max_length=512)


class RequestInformationRequest(_Strict):
    """Ask the submitter for something. **What is being asked is required.**

    A request for information with no statement of what is wanted returns the case to
    the submitter with no way to satisfy it, which is a loop rather than a workflow.
    """

    requested_information: str = Field(min_length=1, max_length=4000)
    stated_qualification: str = Field(default="", max_length=512)


class ReviewRequest(_Strict):
    """What a reviewer submits. **It cannot name the reviewer.**

    `reviewer_id`, `accepted_by` and `finalized_by` are absent, and their absence is the
    mechanism (OD-43). The model is `extra="forbid"`, so a client that sends one gets a
    422 naming the field rather than having it silently ignored - a silently-dropped
    identity field is worse than a rejected one, because the caller believes it worked.

    The reviewer's identity comes from the authenticated principal and from nowhere
    else.
    """

    action: HumanReviewAction
    #: Required for DENY and OVERRIDE. Enforced in the service and in the database.
    rationale: str | None = None
    #: An override must say what it overrode TO.
    override_outcome: ReviewOutcome | None = None
    #: Free text on purpose: this project cannot enumerate clinical credentials, and a
    #: dropdown would imply it had. It states the basis for a decision, NOT who made it -
    #: the authenticated identity answers that and this cannot override it.
    stated_qualification: str = Field(default="", max_length=512)


class ReviewResponse(_Strict):
    case_id: str
    action: HumanReviewAction
    outcome: ReviewOutcome | None
    #: The authenticated subject. Echoed so a caller can see whose identity was
    #: actually recorded, which will not be a value they supplied.
    reviewer_id: str
    principal_type: str
    authentication_method: str
    identity_model: str
    #: What the engine had recommended when the reviewer acted, so agreement is
    #: readable from the response alone.
    recommended_outcome_at_review: str | None
    case_state: CaseState
    created_at: datetime
    request_id: str


class AuditEventResponse(_Strict):
    event: str
    stage: str
    outcome: str | None = None
    abstention_reason: str | None = None
    resolution_state: str | None = None
    provider_failure_kind: str | None = None
    actor_type: str | None = None
    correlation_id: str | None = None
    created_at: datetime


class AuditTrailResponse(_Strict):
    case_id: str
    events: tuple[AuditEventResponse, ...]
    request_id: str


class EvidenceRefResponse(_Strict):
    chunk_id: str
    criterion_ids: tuple[str, ...] = ()
    stage: str = ""


class ReviewHistoryResponse(_Strict):
    action: str
    outcome: str | None
    reviewer_principal_id: str | None
    #: `AUTHENTICATED_HUMAN` or `LEGACY_CALLER_SUPPLIED`. Rendered so a reader can tell
    #: how much the identity on a past decision is worth.
    identity_model: str
    authentication_method: str | None
    rationale: str | None
    recommended_outcome_at_review: str | None
    created_at: datetime


class ReviewCaseResponse(_Strict):
    """The reviewer's whole picture.

    `ai_recommendation` and `human_disposition` are **separate fields**. A single
    `outcome` would let a consumer render the engine's draft as the answer, which is the
    one thing this architecture exists to prevent.
    """

    case_id: str
    state: CaseState
    procedure_code: str
    code_system: str
    jurisdiction: str
    date_of_service: date
    input_sha256: str

    # -- the engine's draft --------------------------------------------------
    ai_recommendation: str | None
    ai_recommendation_label: str = "AI-generated recommendation - not a decision"
    decision_rule: str | None
    abstention_reason: str | None
    #: Why this case is in front of a person, in a sentence.
    routing_explanation: str
    policy_type: str | None
    policy_id: str | None
    policy_version: str | None
    resolution_state: str | None
    resolution_reason: str | None
    contradiction_state: str | None
    provider_failure_kind: str | None
    confidence_state: str
    recommended_at: datetime | None

    # -- the human's decision, if one exists yet ------------------------------
    human_disposition: str | None
    human_disposition_label: str = "Human disposition"
    disposition_by: str | None
    disposition_at: datetime | None

    # -- the reviewer looking at it -------------------------------------------
    reviewer_principal_id: str
    reviewer_qualification: str
    #: `SELF_ASSERTED` or `NOT_STATED`. Never `VERIFIED_BY_REGISTRY` - none exists.
    qualification_state: str
    qualification_notice: str

    evidence: tuple[EvidenceRefResponse, ...]
    history: tuple[ReviewHistoryResponse, ...]
    #: What the case's **state** permits, from `allowed_next`. Not an authorization
    #: answer: a case in HUMAN_REVIEW publishes all three regardless of who is asking.
    available_actions: tuple[str, ...]

    # -- what this reviewer may do (OD-43) ------------------------------------
    #
    # State and authority are two different gates and the API reports them
    # separately, because a client that had only `available_actions` would have to
    # *infer* authority - and the only inference available is the wrong one.
    #
    # These mirror the flags `app/api/reviewer_ui.py` already passes to the Jinja
    # template; the same `Principal.has()` reads the same granted permissions. They
    # are **informational**, and nothing here enforces: `HumanReviewService.record`
    # calls `Principal.require()` on every action, so a client that ignored these
    # fields entirely is refused by the service exactly as before.
    may_review: bool
    may_override: bool
    may_finalize: bool

    audit_event_count: int
    request_id: str
