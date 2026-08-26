"""The case record and its append-only trail.

R-16 (audit tampering, **Critical**) has recorded its mitigation since Phase 0 as:

> Append-only grants; retention deletes by `created_at` and nothing else, asserted
> against the compiled SQL.

None of it existed. `AuditEvent` was an in-memory contract that the slice produced
correctly and the process discarded on return. R-17 ("schema-level assertion that no
column holds a prompt or completion") had no schema to assert over. This module is
those two rows becoming true.

## Append-only is a grant, not a convention

`UPDATE` and `DELETE` on `audit_events` and `human_review_events` are revoked from the
application role in migration `0005`. A future ORM call that tries to mutate a row
fails in PostgreSQL, not in a code review - which is the difference between a property
and an intention. `tests/unit/test_audit_schema.py` asserts the revocations against the
compiled SQL, exactly as R-16's wording promises.

The two mutable tables are `cases` and `case_recommendations`: a case advances through
states and its latest recommendation is a projection. **Neither is the record.** The
record is the event stream, and it only ever grows.

## No column can hold clinical text

Every column here is an identifier, a digest, an enum, a count or a timestamp. There is
no `TEXT` column a note, a prompt or a completion could be put in, and
`test_no_audit_column_can_hold_free_text` walks the metadata to keep it that way. The
one free-text column in the whole module is `HumanReviewEvent.rationale`, which is
written by a named reviewer about their own decision - a different thing from clinical
narrative, and required by Part F.

## Retention deletes by `created_at` and by nothing else

`retention_delete()` compiles to a `DELETE ... WHERE created_at < :before` with no other
predicate available. A purge that can be aimed at a case id, a reviewer or an outcome is
a mechanism for erasing the record of one particular recommendation, which is the attack
R-16 names.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from enum import StrEnum

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PgUUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.case.lifecycle import CaseState
from app.database.base import Base, utc_now_column, uuid_pk

__all__ = [
    "APPEND_ONLY_TABLES",
    "AuditEventRow",
    "CaseRecommendationRow",
    "CaseRow",
    "CaseState",
    "HumanReviewAction",
    "HumanReviewEventRow",
    "ReviewOutcome",
]

#: `CaseState` lives in `app.case.lifecycle` and is imported, not redefined. It was
#: briefly declared here too - two vocabularies for one thing, which disagree the moment
#: somebody adds a state to one of them. The machine owns the states; this module owns
#: the rows they are written into.

#: Tables the application role may INSERT and SELECT, and nothing else. Named here so
#: the migration, the grant test and the ORM all read the same list rather than three
#: hand-kept copies that drift.
APPEND_ONLY_TABLES: tuple[str, ...] = ("audit_events", "human_review_events")


class HumanReviewAction(StrEnum):
    """What a reviewer did. Part F's four, and no fifth that means "nothing"."""

    APPROVE = "APPROVE"
    DENY = "DENY"
    REQUEST_INFO = "REQUEST_INFO"
    #: The reviewer's decision differs from the engine's recommendation. Recorded as
    #: its own action rather than as an APPROVE/DENY with a flag, so an override is
    #: countable without parsing anything.
    OVERRIDE = "OVERRIDE"


class ReviewOutcome(StrEnum):
    """The reviewer's clinical conclusion, kept separate from the *action*.

    An `OVERRIDE` needs to say what it overrode *to*; an `APPROVE` does not need a
    second field to say "approved". Splitting them means the audit can answer "how
    often do reviewers disagree with the engine, and in which direction" without
    inference.
    """

    APPROVED = "APPROVED"
    DENIED = "DENIED"
    INFORMATION_REQUESTED = "INFORMATION_REQUESTED"


class CaseRow(Base):
    """One prior-authorization request. **Mutable by design; not the record.**

    The audit trail is the record. This is a projection that lets the API answer
    "where is case X" without replaying events, and every transition it makes also
    writes an immutable event.
    """

    __tablename__ = "cases"
    __table_args__ = (
        UniqueConstraint("case_id"),
        Index("ix_cases_state_created_at", "state", "created_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(PgUUID(as_uuid=True), primary_key=True, default=uuid_pk)
    #: The caller's identifier for this case. Not a patient identifier.
    case_id: Mapped[str] = mapped_column(String(64), nullable=False)
    #: Bumped when a case is re-run or amended. The recommendation rows carry their own
    #: `run_seq`; this is the case's version, so "which submission" and "which run" stay
    #: separable questions.
    case_version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    state: Mapped[CaseState] = mapped_column(String(24), nullable=False, default=CaseState.RECEIVED)

    #: The caller that submitted this case. **The authorization boundary.** Ownership is
    #: checked in the service, not the route, so a future second entry point cannot
    #: reach a case by skipping a decorator.
    submitted_by: Mapped[str] = mapped_column(String(64), nullable=False)

    #: sha256 of the submitted payload. The payload itself is NOT stored here - this
    #: is what lets a later reader prove which input produced which recommendation
    #: without the clinical note living in the audit database.
    input_sha256: Mapped[str] = mapped_column(String(64), nullable=False)

    procedure_code: Mapped[str] = mapped_column(String(16), nullable=False)
    code_system: Mapped[str] = mapped_column(String(16), nullable=False)
    jurisdiction: Mapped[str] = mapped_column(String(16), nullable=False)
    date_of_service: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utc_now_column
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utc_now_column, onupdate=utc_now_column
    )

    recommendations: Mapped[list[CaseRecommendationRow]] = relationship(
        back_populates="case", cascade="all, delete-orphan"
    )


class CaseRecommendationRow(Base):
    """What the engine produced. One row per completed run.

    Kept beside the case rather than on it because a case can be re-run - after a
    corpus refresh, or after a provider outage clears - and the earlier
    recommendation must not be overwritten by the later one. `run_seq` orders them.
    """

    __tablename__ = "case_recommendations"
    __table_args__ = (
        UniqueConstraint("case_uuid", "run_seq"),
        # An outcome and the rule that produced it travel together or not at all.
        CheckConstraint(
            "(outcome IS NULL) = (decision_rule IS NULL)",
            name="outcome_and_rule_agree",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(PgUUID(as_uuid=True), primary_key=True, default=uuid_pk)
    case_uuid: Mapped[uuid.UUID] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("cases.id", ondelete="CASCADE"), nullable=False
    )
    run_seq: Mapped[int] = mapped_column(Integer, nullable=False, default=1)

    #: `APPROVE_RECOMMENDED`, `DENY_RECOMMENDED`, `NEEDS_INFO`, `HUMAN_REVIEW`,
    #: `NO_DECISION`. NULL where the run failed before deciding.
    outcome: Mapped[str | None] = mapped_column(String(32))
    decision_rule: Mapped[str | None] = mapped_column(String(48))
    abstention_reason: Mapped[str | None] = mapped_column(String(48))

    #: Applicability, as resolved. Two fields, because the state routes the case and
    #: the reason is what a reviewer is owed.
    resolution_state: Mapped[str | None] = mapped_column(String(32))
    resolution_reason: Mapped[str | None] = mapped_column(String(48))

    policy_type: Mapped[str | None] = mapped_column(String(16))
    policy_id: Mapped[str | None] = mapped_column(String(64))
    policy_version: Mapped[str | None] = mapped_column(String(64))

    #: Provider failure kind where one occurred, from the taxonomy. NULL means the
    #: provider path was healthy - a different fact from "the model was right".
    provider_failure_kind: Mapped[str | None] = mapped_column(String(40))
    provider_failure_attribution: Mapped[str | None] = mapped_column(String(32))

    model_id: Mapped[str | None] = mapped_column(String(128))
    model_calls: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    prompt_tokens: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    completion_tokens: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    latency_ms: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    #: Confidence is UNCALIBRATED and says so. A numeric score here would be read as
    #: a probability by every consumer, and this project has not earned one.
    confidence_state: Mapped[str] = mapped_column(
        String(24), nullable=False, default="UNCALIBRATED"
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utc_now_column
    )

    case: Mapped[CaseRow] = relationship(back_populates="recommendations")


class AuditEventRow(Base):
    """One append-only event. **INSERT and SELECT only** — see the module docstring.

    Ids, digests, enums and counts. `payload` is JSONB and is asserted by test to
    carry no free-text key, so "we needed somewhere to put the note" cannot quietly
    become a column.
    """

    __tablename__ = "audit_events"
    __table_args__ = (
        Index("ix_audit_events_case_id_created_at", "case_id", "created_at"),
        Index("ix_audit_events_created_at", "created_at"),
        Index("ix_audit_events_request_id", "request_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(PgUUID(as_uuid=True), primary_key=True, default=uuid_pk)
    #: Correlates every event of one HTTP request, including across stages.
    request_id: Mapped[str] = mapped_column(String(64), nullable=False)
    case_id: Mapped[str] = mapped_column(String(64), nullable=False)

    event: Mapped[str] = mapped_column(String(48), nullable=False)
    stage: Mapped[str] = mapped_column(String(32), nullable=False)

    outcome: Mapped[str | None] = mapped_column(String(32))
    abstention_reason: Mapped[str | None] = mapped_column(String(48))
    resolution_state: Mapped[str | None] = mapped_column(String(32))
    resolution_reason: Mapped[str | None] = mapped_column(String(48))
    contradiction_state: Mapped[str | None] = mapped_column(String(32))
    provider_failure_kind: Mapped[str | None] = mapped_column(String(40))

    #: Identifiers only: fact ids, chunk ids, criterion ids, spans. Never text.
    payload: Mapped[dict[str, object]] = mapped_column(JSONB, nullable=False, default=dict)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utc_now_column
    )


class HumanReviewEventRow(Base):
    """A named person's decision. **Append-only, and never edits the AI's.**

    An override does not update `case_recommendations`. It inserts here, beside the
    recommendation it disagreed with, so the trail always shows both what the system
    proposed and what the human did about it. That is the property Part F asks for and
    it is a schema property, not a service-layer convention.
    """

    __tablename__ = "human_review_events"
    __table_args__ = (
        Index("ix_human_review_events_case_id_created_at", "case_id", "created_at"),
        Index("ix_human_review_events_created_at", "created_at"),
        # A rationale is required for the two actions where a later reader will ask
        # "why". Enforced in the database because the API is not the only writer a
        # deployment might ever have.
        CheckConstraint(
            "action NOT IN ('DENY', 'OVERRIDE') OR (rationale IS NOT NULL AND length(rationale) > 0)",
            name="denial_and_override_require_a_rationale",
        ),
        # An authenticated review without a principal is the defect OD-43 exists to
        # close, so the database refuses it. Legacy rows are exempt by naming their
        # identity model, not by being old.
        CheckConstraint(
            "identity_model <> 'AUTHENTICATED_HUMAN' "
            "OR (principal_id IS NOT NULL AND principal_type = 'HUMAN' "
            "AND authentication_method IS NOT NULL)",
            name="authenticated_review_names_its_principal",
        ),
        Index("ix_human_review_events_principal_id", "principal_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(PgUUID(as_uuid=True), primary_key=True, default=uuid_pk)
    request_id: Mapped[str] = mapped_column(String(64), nullable=False)
    case_id: Mapped[str] = mapped_column(String(64), nullable=False)

    #: Which recommendation this decision is *about*. An override with no referent is
    #: a decision nobody can audit against what the system actually said.
    recommendation_id: Mapped[uuid.UUID | None] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("case_recommendations.id", ondelete="RESTRICT")
    )

    reviewer_id: Mapped[str] = mapped_column(String(64), nullable=False)
    #: Free text on purpose: this project cannot enumerate clinical credentials, and
    #: a dropdown would imply it had.
    reviewer_qualification: Mapped[str] = mapped_column(Text, nullable=False)

    action: Mapped[HumanReviewAction] = mapped_column(String(16), nullable=False)
    outcome: Mapped[ReviewOutcome | None] = mapped_column(String(24))

    #: The reviewer's own words about their own decision. NOT clinical narrative, and
    #: the only free-text column in this module that a person writes.
    rationale: Mapped[str | None] = mapped_column(Text)

    # -- authenticated identity (OD-43) ----------------------------------------
    #: `AUTHENTICATED_HUMAN` or `LEGACY_CALLER_SUPPLIED`. Per row, so a reader can tell
    #: how much the identity on it is worth. Historical rows are labelled, never
    #: back-filled with a principal that did not exist at the time.
    identity_model: Mapped[str] = mapped_column(
        String(24), nullable=False, default="LEGACY_CALLER_SUPPLIED"
    )
    #: The authenticated subject. `reviewer_id` above is what the person called
    #: themselves; THIS is what the system verified. Both are kept - they should agree,
    #: and a row where they do not is worth seeing rather than silently reconciling.
    principal_id: Mapped[str | None] = mapped_column(String(128))
    principal_type: Mapped[str | None] = mapped_column(String(16))
    authentication_method: Mapped[str | None] = mapped_column(String(16))
    #: Which identity provider vouched for them. Part of "who decided", and not
    #: reconstructible later.
    identity_issuer: Mapped[str | None] = mapped_column(Text)

    #: What the engine had recommended when the reviewer acted. Denormalised on
    #: purpose: it makes "did the human agree" answerable from this row alone, and
    #: immune to anything that later happens to the recommendation table.
    recommended_outcome_at_review: Mapped[str | None] = mapped_column(String(32))

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utc_now_column
    )
