"""The temporal predicate. Defined once, used by resolution *and* retrieval.

A policy version is selected by **date of service**, never by "latest". Retrieving a
version that was retired before the service occurred, or that took effect after it,
is a silent correctness failure of exactly the kind a fluent, well-cited answer
hides: the citation verifies, the quote is real, and the policy does not apply.

This module exists so that resolution and retrieval cannot drift apart. A second
copy of the date filter inside the retrieval query is a defect waiting for a corpus
refresh - it would pass every test written against today's corpus and start
returning out-of-scope chunks the moment a version is superseded. Both call
:func:`in_force_on`, and a test asserts the two produce identical SQL.
"""

from __future__ import annotations

from datetime import date

from sqlalchemy import ColumnElement, and_, or_

from app.policy.models import PolicyVersion, TemporalStatus

__all__ = ["applies_in_jurisdiction", "in_force_on"]


def in_force_on(as_of: date) -> ColumnElement[bool]:
    """Was this ``policy_version`` in force on ``as_of``?

    ``end_date IS NULL`` means *currently in force* - it does not mean *most
    recent*. A version with a future ``effective_date`` is not yet in force even
    though it is the newest row, which is precisely the case a "latest" query gets
    wrong.

    The ``temporal_status`` conjunct is not redundant, and it is worth being precise
    about what it does. Deleting it alone changes nothing: ``NULL <= as_of`` is
    NULL, so an undated version is already excluded by three-valued logic, and every
    test still passes. Measured, not assumed.

    What it protects against is the *next* edit. Making the date comparison
    NULL-tolerant - ``or_(effective_date.is_(None), effective_date <= as_of)`` -
    looks like a reasonable accommodation for nullable dates and would make every
    undated version in force for **every** date of service. With this conjunct that
    mutation is caught; without it, both undated-unreachability tests fail. So the
    conjunct is what stops the date clause's NULL behaviour from being load-bearing,
    and it states the intent where a reader making that edit will see it.
    """
    return and_(
        PolicyVersion.temporal_status == TemporalStatus.DATED.value,
        PolicyVersion.effective_date <= as_of,
        or_(PolicyVersion.end_date.is_(None), PolicyVersion.end_date >= as_of),
    )


def applies_in_jurisdiction(jurisdiction: str | None) -> ColumnElement[bool]:
    """Does this version's scope cover ``jurisdiction``?

    National coverage applies everywhere. Jurisdictional coverage applies only where
    it is stated - and when the caller supplies no jurisdiction, jurisdictional
    policies are **excluded** rather than assumed to apply. Guessing here would
    silently widen applicability, which is the failure direction that produces
    confident answers from policies that do not govern the case.
    """
    national = PolicyVersion.scope == "NATIONAL"
    if jurisdiction is None:
        return national
    return or_(national, PolicyVersion.jurisdiction == jurisdiction)
