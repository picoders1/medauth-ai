"""The four mandatory temporal tests (ADR-004), plus the resolver's contract.

Coverage policy is temporal, and a system that retrieves by similarity alone will
happily cite a version that was retired before the service occurred. The citation
verifies, the quote is real, the metadata is consistent - and the policy does not
govern the case. Every grounding metric passes it. These tests are the only thing
that catches it.
"""

from __future__ import annotations

from datetime import date

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.config.policy import ResolutionPolicy
from app.core.types import CodeSystem, ResolutionStatus
from app.policy.models import DocumentType, LinkType, PolicyScope
from app.policy.resolve import ResolutionRequest, resolve
from tests.integration.conftest import CorpusBuilder

pytestmark = [pytest.mark.integration, pytest.mark.asyncio]

KNEE = ("27447", "HCPCS", LinkType.COVERED_PROCEDURE)
POLICY = ResolutionPolicy()


async def _knee_lcd_with_two_revisions(corpus: CorpusBuilder) -> None:
    """L34567 rev 3 in force 2022-01-01..2023-06-30, superseded by rev 4 from 2023-07-01."""
    document = await corpus.document(
        "L34567", DocumentType.LCD, title="Major Joint Replacement", contractor="MAC J6"
    )
    await corpus.version(
        document,
        "R3",
        date(2022, 1, 1),
        end_date=date(2023, 6, 30),
        scope=PolicyScope.JURISDICTIONAL,
        jurisdiction="J6",
        codes=(KNEE,),
    )
    await corpus.version(
        document,
        "R4",
        date(2023, 7, 1),
        scope=PolicyScope.JURISDICTIONAL,
        jurisdiction="J6",
        codes=(KNEE,),
    )
    await corpus.commit()


def _request(as_of: date) -> ResolutionRequest:
    return ResolutionRequest(
        procedure_code="27447", code_system=CodeSystem.HCPCS, as_of=as_of, jurisdiction="J6"
    )


# ------------------------------------------------------------------ MANDATORY 1
async def test_a_date_before_effective_date_does_not_resolve(
    session: AsyncSession, corpus: CorpusBuilder
) -> None:
    """A version that had not taken effect yet must not govern the case.

    This is the failure a "latest version" query makes: the newest row is not the
    one in force.
    """
    await _knee_lcd_with_two_revisions(corpus)

    result = await resolve(session, _request(date(2021, 6, 1)), POLICY)

    assert result.status is ResolutionStatus.NONE_APPLICABLE
    assert result.versions == ()
    assert "not non-coverage" in " ".join(result.notes)


# ------------------------------------------------------------------ MANDATORY 2
async def test_a_past_date_resolves_to_the_version_in_force_then(
    session: AsyncSession, corpus: CorpusBuilder
) -> None:
    """Not the current revision - the one that governed on the date of service."""
    await _knee_lcd_with_two_revisions(corpus)

    historical = await resolve(session, _request(date(2023, 3, 15)), POLICY)
    current = await resolve(session, _request(date(2024, 3, 15)), POLICY)

    assert historical.status is ResolutionStatus.RESOLVED
    assert [v.revision_id for v in historical.versions] == ["R3"], (
        "a 2023-03-15 date of service resolved to the wrong revision; "
        "selection must be by date of service, never by 'latest'"
    )
    assert [v.revision_id for v in current.versions] == ["R4"]


async def test_the_boundary_days_belong_to_the_right_revision(
    session: AsyncSession, corpus: CorpusBuilder
) -> None:
    """Inclusive on both ends. An off-by-one here silently mis-resolves a whole day."""
    await _knee_lcd_with_two_revisions(corpus)

    for as_of, expected in [
        (date(2022, 1, 1), "R3"),  # first day effective
        (date(2023, 6, 30), "R3"),  # last day in force
        (date(2023, 7, 1), "R4"),  # first day of the successor
    ]:
        result = await resolve(session, _request(as_of), POLICY)
        assert [v.revision_id for v in result.versions] == [expected], f"{as_of} -> {expected}"


# ------------------------------------------------------------------ MANDATORY 3
async def test_a_corpus_refresh_does_not_change_a_historical_resolution(
    session: AsyncSession, corpus: CorpusBuilder
) -> None:
    """Adding a newer revision must not retroactively rewrite a settled case.

    This is what makes a recommendation issued last year still defensible: the
    version it cited is still the version that resolves for its date of service.
    """
    await _knee_lcd_with_two_revisions(corpus)
    as_of = date(2023, 3, 15)

    before = await resolve(session, _request(as_of), POLICY)

    # Corpus refresh: a new revision arrives. Versions are ADDED, never edited.
    document = (await corpus.document("L34567", DocumentType.LCD)) if False else None
    from sqlalchemy import select

    from app.policy.models import PolicyDocument, PolicyVersion

    existing = (
        await session.execute(select(PolicyDocument).where(PolicyDocument.policy_id == "L34567"))
    ).scalar_one()
    current = (
        await session.execute(
            select(PolicyVersion).where(
                PolicyVersion.document_id == existing.id, PolicyVersion.revision_id == "R4"
            )
        )
    ).scalar_one()
    current.end_date = date(2025, 3, 31)
    await corpus.version(
        existing,
        "R5",
        date(2025, 4, 1),
        scope=PolicyScope.JURISDICTIONAL,
        jurisdiction="J6",
        codes=(KNEE,),
    )
    await corpus.commit()

    after = await resolve(session, _request(as_of), POLICY)

    assert [v.revision_id for v in after.versions] == [v.revision_id for v in before.versions]
    assert [v.version_id for v in after.versions] == [v.version_id for v in before.versions], (
        "a corpus refresh changed which version governs a historical date of service"
    )
    assert document is None  # keeps the unused binding honest


# ------------------------------------------------------------------- contract
async def test_no_applicable_policy_is_not_a_denial(
    session: AsyncSession, corpus: CorpusBuilder
) -> None:
    """Absence of an NCD/LCD means contractor discretion, not non-coverage."""
    await _knee_lcd_with_two_revisions(corpus)

    result = await resolve(
        session,
        ResolutionRequest(
            procedure_code="99999", code_system=CodeSystem.HCPCS, as_of=date(2024, 1, 1)
        ),
        POLICY,
    )

    assert result.status is ResolutionStatus.NONE_APPLICABLE
    assert result.status is not ResolutionStatus.CONFLICTING
    assert result.version_ids == ()


async def test_jurisdiction_is_not_assumed(session: AsyncSession, corpus: CorpusBuilder) -> None:
    """A jurisdictional policy must not apply to a request from elsewhere, and must
    not apply when no jurisdiction was supplied. Guessing widens applicability."""
    await _knee_lcd_with_two_revisions(corpus)
    as_of = date(2024, 1, 1)

    wrong = await resolve(
        session,
        ResolutionRequest("27447", CodeSystem.HCPCS, as_of, jurisdiction="J15"),
        POLICY,
    )
    unstated = await resolve(session, ResolutionRequest("27447", CodeSystem.HCPCS, as_of), POLICY)

    assert wrong.status is ResolutionStatus.NONE_APPLICABLE
    assert unstated.status is ResolutionStatus.NONE_APPLICABLE


async def test_a_national_policy_applies_everywhere(
    session: AsyncSession, corpus: CorpusBuilder
) -> None:
    ncd = await corpus.document("220.1", DocumentType.NCD, title="Computed Tomography")
    await corpus.version(
        ncd,
        "R1",
        date(2020, 1, 1),
        scope=PolicyScope.NATIONAL,
        codes=(("70551", "HCPCS", LinkType.COVERED_PROCEDURE),),
    )
    await corpus.commit()

    for jurisdiction in ("J6", "J15", None):
        result = await resolve(
            session,
            ResolutionRequest("70551", CodeSystem.HCPCS, date(2024, 1, 1), jurisdiction),
            POLICY,
        )
        assert result.status is ResolutionStatus.RESOLVED, f"jurisdiction={jurisdiction}"


async def test_an_ncd_governs_when_an_lcd_also_applies(
    session: AsyncSession, corpus: CorpusBuilder
) -> None:
    """Normal, not a conflict: both are recorded and the national policy governs."""
    ncd = await corpus.document("220.1", DocumentType.NCD)
    await corpus.version(ncd, "R1", date(2020, 1, 1), scope=PolicyScope.NATIONAL, codes=(KNEE,))
    lcd = await corpus.document("L34567", DocumentType.LCD, contractor="MAC J6")
    await corpus.version(
        lcd,
        "R4",
        date(2023, 7, 1),
        scope=PolicyScope.JURISDICTIONAL,
        jurisdiction="J6",
        codes=(KNEE,),
    )
    await corpus.commit()

    result = await resolve(session, _request(date(2024, 1, 1)), POLICY)

    assert result.status is ResolutionStatus.RESOLVED
    assert len(result.versions) == 2
    assert result.governing is not None
    assert result.governing.document_type is DocumentType.NCD
    assert "governs" in " ".join(result.notes)


async def test_two_local_determinations_are_a_conflict(
    session: AsyncSession, corpus: CorpusBuilder
) -> None:
    """Which local policy controls is a human judgement, not a ranking problem."""
    for policy_id in ("L34567", "L99999"):
        document = await corpus.document(policy_id, DocumentType.LCD, contractor="MAC J6")
        await corpus.version(
            document,
            "R1",
            date(2023, 1, 1),
            scope=PolicyScope.JURISDICTIONAL,
            jurisdiction="J6",
            codes=(KNEE,),
        )
    await corpus.commit()

    result = await resolve(session, _request(date(2024, 1, 1)), POLICY)

    assert result.status is ResolutionStatus.CONFLICTING
    assert len(result.versions) == 2
    assert any("human judgement" in c for c in result.conflicts)


async def test_overlapping_versions_of_one_document_are_surfaced_as_a_defect(
    session: AsyncSession, corpus: CorpusBuilder
) -> None:
    """A corpus whose temporal ranges overlap is wrong. Route to a human rather
    than silently picking one."""
    document = await corpus.document("L34567", DocumentType.LCD, contractor="MAC J6")
    await corpus.version(
        document,
        "R3",
        date(2022, 1, 1),
        end_date=date(2024, 12, 31),
        scope=PolicyScope.JURISDICTIONAL,
        jurisdiction="J6",
        codes=(KNEE,),
    )
    await corpus.version(
        document,
        "R4",
        date(2023, 7, 1),
        scope=PolicyScope.JURISDICTIONAL,
        jurisdiction="J6",
        codes=(KNEE,),
    )
    await corpus.commit()

    result = await resolve(session, _request(date(2024, 1, 1)), POLICY)

    assert result.status is ResolutionStatus.CONFLICTING
    assert any("overlapping in-force versions" in c for c in result.conflicts)


async def test_supporting_diagnoses_are_reported_but_do_not_decide_applicability(
    session: AsyncSession, corpus: CorpusBuilder
) -> None:
    """A policy applies because it covers the procedure. Whether the diagnosis
    supports necessity is a criterion question, adjudicated later."""
    document = await corpus.document("L34567", DocumentType.LCD, contractor="MAC J6")
    await corpus.version(
        document,
        "R4",
        date(2023, 7, 1),
        scope=PolicyScope.JURISDICTIONAL,
        jurisdiction="J6",
        codes=(KNEE, ("M17.11", "ICD10CM", LinkType.SUPPORTING_DIAGNOSIS)),
    )
    await corpus.commit()

    with_diagnosis = await resolve(
        session,
        ResolutionRequest("27447", CodeSystem.HCPCS, date(2024, 1, 1), "J6", ("M17.11",)),
        POLICY,
    )
    without = await resolve(session, _request(date(2024, 1, 1)), POLICY)
    unsupported = await resolve(
        session,
        ResolutionRequest("27447", CodeSystem.HCPCS, date(2024, 1, 1), "J6", ("Z00.00",)),
        POLICY,
    )

    assert with_diagnosis.versions[0].supporting_diagnoses == ("M17.11",)
    assert without.versions[0].supporting_diagnoses == ()
    # Applicability is identical in all three cases.
    assert unsupported.status is ResolutionStatus.RESOLVED
    assert with_diagnosis.version_ids == without.version_ids == unsupported.version_ids


async def test_resolution_explains_itself(session: AsyncSession, corpus: CorpusBuilder) -> None:
    """A reviewer must be able to see WHY a policy applied (ADR-012)."""
    await _knee_lcd_with_two_revisions(corpus)

    result = await resolve(session, _request(date(2024, 1, 1)), POLICY)
    why = result.versions[0].why

    for expected in ("L34567", "R4", "27447", "covered_procedure", "J6", "effective"):
        assert expected in why, f"{expected!r} missing from explanation: {why}"
