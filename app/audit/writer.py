"""The only thing that writes the audit trail.

Migration 0005 made `audit_events` append-only and proved it against a real server.
Nothing wrote to it. This is that gap closed, and it is deliberately the *single* way in:
a service that needed "just one INSERT here" would be the beginning of a trail whose
shape depends on which call site wrote the row.

## Lifting, not re-deriving

`SliceOutcome` already carries per-stage `AuditEvent`s, produced by the runtime that
actually did the work. `record_slice()` **lifts** them. It does not re-derive events from
the outcome's fields, because two descriptions of one run disagree eventually and the
persisted one would be the one nobody checked.

## Every write is an append

There is no `update`, no `delete`, no `amend` and no `correct` on this class. A
correction to the record is a new event that says so; the original stays. That is not
politeness, it is what makes the earlier event worth having - and the database enforces
it independently, so a method added here would fail at the trigger rather than succeed
quietly.

## What cannot be put in an event

`payload` is JSONB and this module writes only identifiers, counts and digests into it.
`payload_hash` is recorded so a caller *can* prove what it held without the trail holding
it. `_REJECTED_KEYS` refuses the field names a clinical note actually arrives under, so
"we needed somewhere to put it" fails loudly instead of becoming a habit.

R-17's stated mitigation is the schema having no text column. This is the runtime half:
the schema cannot hold prose, and the writer will not try.
"""

from __future__ import annotations

import hashlib
import json
import uuid
from collections.abc import Iterable, Mapping
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.audit.models import AuditEventRow
from app.contracts.slice import AuditEvent
from app.core.errors import MedauthError

__all__ = ["ActorType", "AuditWriter", "EventType", "UnsafeAuditPayload"]


class EventType(StrEnum):
    """The lifecycle vocabulary. Closed, so a typo is not a new event type."""

    CASE_RECEIVED = "CASE_RECEIVED"
    CASE_VALIDATED = "CASE_VALIDATED"
    APPLICABILITY_RESOLVED = "APPLICABILITY_RESOLVED"
    APPLICABILITY_REJECTED = "APPLICABILITY_REJECTED"
    RETRIEVAL_STARTED = "RETRIEVAL_STARTED"
    RETRIEVAL_COMPLETED = "RETRIEVAL_COMPLETED"
    EVIDENCE_SELECTED = "EVIDENCE_SELECTED"
    MODEL_REQUESTED = "MODEL_REQUESTED"
    MODEL_RESPONSE_RECEIVED = "MODEL_RESPONSE_RECEIVED"
    PROVIDER_FAILURE = "PROVIDER_FAILURE"
    ABSTENTION = "ABSTENTION"
    RECOMMENDATION_CREATED = "RECOMMENDATION_CREATED"
    HUMAN_REVIEW_REQUESTED = "HUMAN_REVIEW_REQUESTED"
    HUMAN_DECISION_RECORDED = "HUMAN_DECISION_RECORDED"
    CASE_FINALIZED = "CASE_FINALIZED"
    CASE_FAILED = "CASE_FAILED"
    #: A stage event lifted verbatim from the runtime's own trail.
    RUNTIME_STAGE = "RUNTIME_STAGE"


class ActorType(StrEnum):
    """Who caused this event. `SYSTEM` and `HUMAN` must never be confusable.

    An audit trail that cannot distinguish a decision the engine reached from one a
    person made is an audit trail that cannot answer the only question anyone will ask
    of it after a bad outcome.
    """

    SYSTEM = "SYSTEM"
    HUMAN = "HUMAN"
    CALLER = "CALLER"


#: Field names a clinical note, prompt or completion actually arrives under. Refused
#: rather than filtered - silently dropping them would let a caller believe the value
#: was recorded.
_REJECTED_KEYS = frozenset(
    {
        "clinical_note",
        "note",
        "note_text",
        "text",
        "prompt",
        "completion",
        "content",
        "narrative",
        "messages",
        "raw",
        "body",
        "response",
    }
)

#: Long enough to be prose. Identifiers, codes and digests are all well under this.
_MAX_VALUE_CHARS = 200


class UnsafeAuditPayload(MedauthError):
    """A payload carried something the trail must not hold."""


def _check_payload(payload: Mapping[str, Any]) -> dict[str, Any]:
    """Refuse prose. Raise rather than strip - see the module docstring."""
    offenders = sorted(k for k in payload if k.lower() in _REJECTED_KEYS)
    if offenders:
        raise UnsafeAuditPayload(
            f"audit payload keys {offenders} name clinical or model text. The trail "
            "carries identifiers, counts and digests; pass a digest instead."
        )
    for key, value in payload.items():
        if isinstance(value, str) and len(value) > _MAX_VALUE_CHARS:
            raise UnsafeAuditPayload(
                f"audit payload key {key!r} holds {len(value)} characters, which is "
                "long enough to be text rather than an identifier"
            )
    return dict(payload)


def payload_hash(value: object) -> str:
    """A stable digest of anything, so the trail can prove *what* without holding it."""
    encoded = json.dumps(value, sort_keys=True, default=str).encode()
    return f"sha256:{hashlib.sha256(encoded).hexdigest()}"


class AuditWriter:
    """Append-only, and holds a session it never commits.

    Committing is the **caller's** decision, because the case-state change and its event
    must land in one transaction or neither (Part H). A writer that committed on its own
    would make that impossible and would produce exactly the inconsistency the boundary
    exists to prevent: a case that reads `RECOMMENDATION_READY` with no event saying how.
    """

    __slots__ = ("_case_id", "_correlation_id", "_request_id", "_session")

    def __init__(
        self,
        session: AsyncSession,
        *,
        case_id: str,
        request_id: str,
        correlation_id: str | None = None,
    ) -> None:
        self._session = session
        self._case_id = case_id
        self._request_id = request_id
        #: Defaults to the request id rather than to None: an event that cannot be
        #: correlated with anything is an event nobody can follow.
        self._correlation_id = correlation_id or request_id

    def record(
        self,
        event: EventType,
        *,
        stage: str,
        actor: ActorType = ActorType.SYSTEM,
        actor_id: str | None = None,
        outcome: str | None = None,
        abstention_reason: str | None = None,
        resolution_state: str | None = None,
        resolution_reason: str | None = None,
        contradiction_state: str | None = None,
        provider_failure_kind: str | None = None,
        payload: Mapping[str, Any] | None = None,
    ) -> AuditEventRow:
        """Append one event. Never updates anything, by absence of any method that could."""
        body = _check_payload(payload or {})
        body.setdefault("actor_type", actor.value)
        if actor_id:
            body.setdefault("actor_id", actor_id)
        body.setdefault("correlation_id", self._correlation_id)
        body.setdefault("payload_hash", payload_hash(body))
        body.setdefault("schema_version", "audit.v1")

        row = AuditEventRow(
            id=uuid.uuid4(),
            request_id=self._request_id,
            case_id=self._case_id,
            event=event.value,
            stage=stage[:32],
            outcome=outcome,
            abstention_reason=abstention_reason,
            resolution_state=resolution_state,
            resolution_reason=resolution_reason,
            contradiction_state=contradiction_state,
            provider_failure_kind=provider_failure_kind,
            payload=body,
            created_at=datetime.now(UTC),
        )
        self._session.add(row)
        return row

    def record_slice(self, events: Iterable[AuditEvent]) -> list[AuditEventRow]:
        """Lift the runtime's own stage events verbatim.

        Not re-derived from the outcome. The runtime produced these while doing the
        work; anything reconstructed afterwards is a second description of one run, and
        the two disagree eventually.
        """
        rows: list[AuditEventRow] = []
        for event in events:
            rows.append(
                self.record(
                    EventType.RUNTIME_STAGE,
                    stage=event.stage,
                    outcome=event.outcome,
                    abstention_reason=event.abstention_reason,
                    resolution_state=event.resolution_state,
                    resolution_reason=event.resolution_reason,
                    contradiction_state=event.contradiction_state,
                    payload={
                        "runtime_event": event.event,
                        "fact_ids": list(event.fact_ids),
                        "chunk_ids": list(event.chunk_ids),
                        "criterion_ids": list(event.criterion_ids),
                    },
                )
            )
        return rows
