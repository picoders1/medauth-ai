"""PostgreSQL actually refuses to mutate the audit trail.

`tests/unit/test_audit_schema.py` asserts the migration *says* the trail is
append-only. This asserts the database *behaves* that way, which is a different claim
and the one that matters. Both are needed: the unit test runs on a laptop with no
server, and this one is the only thing that would have caught the defect below.

## What this found

The first version of migration 0005 enforced append-only with `REVOKE UPDATE, DELETE`.
Applied cleanly. Correct in `information_schema`. And completely inert - PostgreSQL does
not enforce grants against a table's **owner**, and the application user owns its own
schema. UPDATE, DELETE and TRUNCATE all still succeeded.

The second version added a `FOR EACH ROW` trigger. UPDATE and DELETE were refused;
**TRUNCATE still went straight through**, because a row-level trigger never fires on a
statement that removes rows without visiting them.

Neither of those was caught by reading. Both were caught here.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

pytestmark = [pytest.mark.integration, pytest.mark.security]

INSERT_EVENT = text(
    "INSERT INTO audit_events (id, request_id, case_id, event, stage, payload, created_at) "
    "VALUES (:id, :request_id, :case_id, 'decided', 'decide', '{}', :created_at)"
)


async def insert_event(engine: AsyncEngine, case_id: str) -> None:
    async with engine.begin() as connection:
        await connection.execute(
            INSERT_EVENT,
            {
                "id": uuid.uuid4(),
                "request_id": f"req-{uuid.uuid4().hex[:8]}",
                "case_id": case_id,
                "created_at": datetime.now(UTC),
            },
        )


async def count_events(engine: AsyncEngine, case_id: str) -> int:
    async with engine.connect() as connection:
        result = await connection.execute(
            text("SELECT count(*) FROM audit_events WHERE case_id = :c"), {"c": case_id}
        )
        return int(result.scalar() or 0)


async def refuses(engine: AsyncEngine, statement: str, **params: object) -> bool:
    """Whether PostgreSQL rejects this statement.

    Parameterised rather than interpolated - not because a uuid-derived case id could
    be hostile, but because a security lint that has to be silenced in test code is a
    security lint people learn to silence.
    """
    try:
        async with engine.begin() as connection:
            await connection.execute(text(statement), params)
    except Exception:  # the driver wraps the PostgreSQL error; the type is not the point
        return True
    return False


@pytest.mark.asyncio
async def test_the_trail_can_grow(engine: AsyncEngine) -> None:
    """The positive control. A table nothing can write to would pass every refusal
    test below and be useless."""
    case_id = f"CASE-{uuid.uuid4().hex[:8]}"
    await insert_event(engine, case_id)
    assert await count_events(engine, case_id) == 1


@pytest.mark.asyncio
async def test_an_audit_row_cannot_be_updated(engine: AsyncEngine) -> None:
    case_id = f"CASE-{uuid.uuid4().hex[:8]}"
    await insert_event(engine, case_id)
    assert await refuses(
        engine, "UPDATE audit_events SET event = 'tampered' WHERE case_id = :c", c=case_id
    )
    assert await count_events(engine, case_id) == 1


@pytest.mark.asyncio
async def test_an_audit_row_cannot_be_deleted(engine: AsyncEngine) -> None:
    case_id = f"CASE-{uuid.uuid4().hex[:8]}"
    await insert_event(engine, case_id)
    assert await refuses(engine, "DELETE FROM audit_events WHERE case_id = :c", c=case_id)
    assert await count_events(engine, case_id) == 1


@pytest.mark.asyncio
async def test_the_trail_cannot_be_truncated(engine: AsyncEngine) -> None:
    """**The one a row-level trigger misses.**

    TRUNCATE removes every row without visiting any, so `FOR EACH ROW` never fires. It
    is also the most complete erasure available - the whole table in one statement -
    which makes it the first thing an attacker with SQL access would reach for.
    """
    case_id = f"CASE-{uuid.uuid4().hex[:8]}"
    await insert_event(engine, case_id)
    assert await refuses(engine, "TRUNCATE audit_events")
    assert await count_events(engine, case_id) == 1


@pytest.mark.asyncio
async def test_a_human_review_event_cannot_be_rewritten(engine: AsyncEngine) -> None:
    """An override must never be editable after the fact - that is the point of
    recording it beside the recommendation rather than on it.

    A row is inserted first, and that is not incidental. The first version of this
    test asserted refusal against an empty table and failed: a `FOR EACH ROW` trigger
    has nothing to fire on, so the UPDATE "succeeded" by touching zero rows. An
    assertion about a guard has to be made against something the guard can guard.
    """
    case_id = f"CASE-{uuid.uuid4().hex[:8]}"
    async with engine.begin() as connection:
        await connection.execute(
            text(
                "INSERT INTO human_review_events (id, request_id, case_id, reviewer_id, "
                "reviewer_qualification, action, outcome, rationale, created_at) "
                "VALUES (:id, :rq, :c, 'reviewer-1', 'test fixture', 'OVERRIDE', "
                "'DENIED', 'recorded so the trigger has a row to refuse', :t)"
            ),
            {
                "id": uuid.uuid4(),
                "rq": f"req-{uuid.uuid4().hex[:8]}",
                "c": case_id,
                "t": datetime.now(UTC),
            },
        )

    assert await refuses(
        engine,
        "UPDATE human_review_events SET action = 'APPROVE' WHERE case_id = :c",
        c=case_id,
    )
    assert await refuses(engine, "DELETE FROM human_review_events WHERE case_id = :c", c=case_id)
    assert await refuses(engine, "TRUNCATE human_review_events")

    async with engine.connect() as connection:
        surviving = (
            await connection.execute(
                text("SELECT action FROM human_review_events WHERE case_id = :c"),
                {"c": case_id},
            )
        ).scalar()
    assert surviving == "OVERRIDE", "the override was rewritten"

    async with engine.begin() as connection:
        await connection.execute(
            text("SELECT purge_audit_before(:before)"),
            {"before": datetime.now(UTC) + timedelta(days=1)},
        )


@pytest.mark.asyncio
async def test_retention_can_delete_by_created_at_and_restores_the_guard(
    engine: AsyncEngine,
) -> None:
    """The one legitimate deletion, and proof it does not leave the door open.

    The restoration is checked against a **non-empty** table. An earlier version of
    this check ran after a successful TRUNCATE and reported the guard broken when the
    table was simply empty - a row-level trigger has nothing to fire on.
    """
    case_id = f"CASE-{uuid.uuid4().hex[:8]}"
    await insert_event(engine, case_id)

    async with engine.begin() as connection:
        removed = (
            await connection.execute(
                text("SELECT purge_audit_before(:before)"),
                {"before": datetime.now(UTC) + timedelta(days=1)},
            )
        ).scalar()
    assert removed is not None and removed >= 1
    assert await count_events(engine, case_id) == 0

    # And the guard is back. Against a row that exists.
    await insert_event(engine, case_id)
    assert await refuses(engine, "DELETE FROM audit_events WHERE case_id = :c", c=case_id)
    assert await count_events(engine, case_id) == 1

    async with engine.begin() as connection:
        await connection.execute(
            text("SELECT purge_audit_before(:before)"),
            {"before": datetime.now(UTC) + timedelta(days=1)},
        )


@pytest.mark.asyncio
async def test_the_case_projection_is_still_mutable(engine: AsyncEngine) -> None:
    """`cases` advances through states, so it must remain writable. The record is the
    event stream; this is a projection, and confusing the two would either freeze the
    lifecycle or unfreeze the trail."""
    async with engine.connect() as connection:
        result = await connection.execute(
            text(
                "SELECT privilege_type FROM information_schema.role_table_grants "
                "WHERE table_name = 'cases' AND grantee = current_user"
            )
        )
        granted = {row[0] for row in result}
    assert {"INSERT", "SELECT", "UPDATE"} <= granted
