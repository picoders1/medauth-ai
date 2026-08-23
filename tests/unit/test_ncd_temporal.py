"""NCD temporal resolution and coverage semantics.

Every hazard tested here was observed in the live CMS Coverage API during Phase 5
planning, not imagined. The counts are recorded in
`data/coverage/ncd_selection.yaml` and `data/coverage/registry.yaml`.

The rule the whole file exists to pin: **never choose "latest" because temporal
resolution failed.** A determination whose start date the source never published is
stored, indexed and unreachable by date of service - and the tests below prove that
the unreachability is real rather than incidental.
"""

from __future__ import annotations

import itertools
import json
from datetime import UTC, date, datetime
from pathlib import Path

import pytest

from app.coverage.ncd import (
    NcdVersion,
    VersionDataStatus,
    derive_windows,
    parse_cms_date,
    strip_html,
    version_from_record,
)
from app.coverage.resolve import (
    CoverageStatus,
    TemporalResolution,
    resolve_coverage,
    select_version,
)
from app.policy.models import TemporalStatus, WindowDerivation

pytestmark = pytest.mark.unit

#: The exact string the API returns for an undated determination.
LONGSTANDING = (
    "This is a longstanding national coverage determination. The effective date of "
    "this version has not been posted."
)


def _version(
    number: int,
    effective: date | None,
    *,
    raw: str = "",
    end: date | None = None,
    status: TemporalStatus | None = None,
) -> NcdVersion:
    resolved = status or (TemporalStatus.DATED if effective is not None else TemporalStatus.UNDATED)
    return NcdVersion(
        ncdid=1,
        version=number,
        display_id="220.6",
        title="Test Determination",
        effective_date=effective,
        effective_date_source=raw or (effective.strftime("%m/%d/%Y") if effective else ""),
        effective_end_date_source="",
        temporal_status=resolved,
        end_date=end,
    )


# ---------------------------------------------------------------------------
# Date parsing: prose is never mined for a date
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("05/27/2024", date(2024, 5, 27)),
        ("  05/27/2024  ", date(2024, 5, 27)),
        ("N/A", None),
        ("", None),
        (None, None),
        (LONGSTANDING, None),
        ("2024-05-27", None),  # ISO is not the published format
        ("13/01/2024", None),  # month 13
        ("02/30/2024", None),  # no such day
        ("Effective 05/27/2024 per transmittal", None),  # embedded, not the field
    ],
)
def test_only_a_bare_cms_date_parses(raw: object, expected: date | None) -> None:
    """Anything that is not exactly `MM/DD/YYYY` is prose, and prose yields None.

    The last case is the important one. A regex that scraped a date out of
    surrounding words would eventually mine one out of a sentence explaining that no
    date exists, and that fabricated date would then appear in a citation.
    """
    assert parse_cms_date(raw) == expected


def test_the_longstanding_string_yields_no_date() -> None:
    """The literal payload from the API, 14 of 24 records in the planning sample."""
    assert parse_cms_date(LONGSTANDING) is None


# ---------------------------------------------------------------------------
# HTML
# ---------------------------------------------------------------------------


def test_double_escaped_html_is_reduced_to_text() -> None:
    """The API double-escapes: the payload contains `&lt;p&gt;` for `<p>`."""
    raw = "&lt;p&gt;&lt;strong&gt;Covered&lt;&sol;strong&gt; when documented.&lt;&sol;p&gt;"
    assert strip_html(raw) == "Covered when documented."


def test_stripping_happens_at_acquisition_not_retrieval() -> None:
    """Text that reaches a hash must be the text a reviewer reads.

    Hashing markup would make `text_sha256` detect reformatting rather than
    tampering.
    """
    assert "<" not in strip_html("&lt;div&gt;a&lt;&sol;div&gt;")
    assert strip_html(None) == ""


# ---------------------------------------------------------------------------
# Window derivation
# ---------------------------------------------------------------------------


def test_ends_are_derived_from_the_next_version_and_labelled_as_derived() -> None:
    """A reviewer must never be shown an inferred date as a published one."""
    windowed = derive_windows(
        (
            _version(1, date(2000, 9, 19)),
            _version(2, date(2007, 7, 9)),
            _version(3, date(2024, 5, 27)),
        )
    )
    assert [v.end_date for v in windowed] == [date(2007, 7, 8), date(2024, 5, 26), None]
    assert [v.window_derivation for v in windowed] == [
        WindowDerivation.DERIVED_FROM_SEQUENCE,
        WindowDerivation.DERIVED_FROM_SEQUENCE,
        WindowDerivation.POSTED,
    ]


def test_derived_windows_are_contiguous_and_never_overlap() -> None:
    """Overlapping windows would make two versions in force at once."""
    windowed = derive_windows(tuple(_version(i, date(2000 + i, 1, 1)) for i in range(1, 5)))
    dated = [v for v in windowed if v.temporal_status is TemporalStatus.DATED]
    for earlier, later in itertools.pairwise(dated):
        assert earlier.end_date is not None
        assert earlier.effective_date is not None
        assert later.effective_date is not None
        assert earlier.end_date < later.effective_date
        assert (later.effective_date - earlier.end_date).days == 1


def test_a_start_is_never_inferred() -> None:
    """An undated version stays undated however much context surrounds it.

    Inferring an end narrows applicability; inferring a start widens it. An undated
    v1 between two dated versions could be given a start by interpolation, and that
    start would be fabricated.
    """
    windowed = derive_windows(
        (
            _version(1, None, raw=LONGSTANDING),
            _version(2, date(2010, 1, 1)),
            _version(3, date(2020, 1, 1)),
        )
    )
    undated = next(v for v in windowed if v.version == 1)
    assert undated.effective_date is None
    assert undated.end_date is None
    assert undated.temporal_status is TemporalStatus.UNDATED


def test_an_undated_version_does_not_break_the_chain() -> None:
    """Dated versions still close against each other across an undated one."""
    windowed = derive_windows(
        (
            _version(1, date(2010, 1, 1)),
            _version(2, None, raw=LONGSTANDING),
            _version(3, date(2020, 1, 1)),
        )
    )
    first = next(v for v in windowed if v.version == 1)
    assert first.end_date == date(2019, 12, 31)


def test_two_versions_sharing_an_effective_date_become_ambiguous() -> None:
    """Picking one would be choosing a winner the source does not name."""
    windowed = derive_windows((_version(1, date(2010, 1, 1)), _version(2, date(2010, 1, 1))))
    assert {v.temporal_status for v in windowed} == {TemporalStatus.AMBIGUOUS}
    assert all(v.effective_date is None for v in windowed)
    assert all("share effective date" in v.effective_date_source for v in windowed)


# ---------------------------------------------------------------------------
# Version selection
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("as_of", "expected_version", "expected_status"),
    [
        (date(2005, 1, 1), 1, TemporalResolution.RESOLVED),
        (date(2007, 7, 8), 1, TemporalResolution.RESOLVED),  # last day of v1
        (date(2007, 7, 9), 2, TemporalResolution.RESOLVED),  # first day of v2
        (date(2024, 5, 26), 2, TemporalResolution.RESOLVED),
        (date(2024, 5, 27), 3, TemporalResolution.RESOLVED),
        (date(2030, 1, 1), 3, TemporalResolution.RESOLVED),  # open-ended
        (date(1999, 1, 1), None, TemporalResolution.NO_APPLICABLE_VERSION),
    ],
)
def test_boundary_dates_select_the_right_version(
    as_of: date, expected_version: int | None, expected_status: TemporalResolution
) -> None:
    """Both sides of every boundary, including the day before the first version."""
    versions = derive_windows(
        (
            _version(1, date(2000, 9, 19)),
            _version(2, date(2007, 7, 9)),
            _version(3, date(2024, 5, 27)),
        )
    )
    status, chosen, _ = select_version(versions, as_of)
    assert status is expected_status
    assert (chosen.version if chosen else None) == expected_version


def test_an_undated_determination_is_never_selected() -> None:
    """The central fail-closed property of the coverage layer.

    Three versions, none placeable in time. There is a "most recent" one and it is
    not chosen, because recency is not applicability.
    """
    versions = (
        _version(1, None, raw=LONGSTANDING),
        _version(2, None, raw=LONGSTANDING),
        _version(3, None, raw=LONGSTANDING),
    )
    status, chosen, notes = select_version(versions, date(2024, 1, 1))
    assert status is TemporalResolution.TEMPORALLY_UNRESOLVABLE
    assert chosen is None
    assert any("cannot be placed in time" in n for n in notes)


def test_a_service_before_the_first_version_selects_nothing() -> None:
    """Not the earliest version. A determination cannot apply retroactively."""
    versions = derive_windows((_version(1, date(2010, 1, 1)),))
    status, chosen, _ = select_version(versions, date(2009, 12, 31))
    assert status is TemporalResolution.NO_APPLICABLE_VERSION
    assert chosen is None


def test_a_future_version_is_not_in_force_yet() -> None:
    versions = derive_windows((_version(1, date(2030, 1, 1)),))
    status, chosen, _ = select_version(versions, date(2026, 1, 1))
    assert status is TemporalResolution.NO_APPLICABLE_VERSION
    assert chosen is None


def test_a_retired_determination_stops_applying_after_its_end() -> None:
    versions = (_version(1, date(2010, 1, 1), end=date(2015, 12, 31)),)
    assert select_version(versions, date(2015, 12, 31))[0] is TemporalResolution.RESOLVED
    assert select_version(versions, date(2016, 1, 1))[0] is TemporalResolution.NO_APPLICABLE_VERSION


def test_a_mix_of_dated_and_undated_reports_what_could_not_be_considered() -> None:
    """Silently ignoring undated versions would hide part of the corpus."""
    versions = derive_windows((_version(1, date(2020, 1, 1)), _version(2, None, raw=LONGSTANDING)))
    _, _, notes = select_version(versions, date(2019, 1, 1))
    assert any("could not be considered" in n for n in notes)


def test_no_versions_at_all_is_unknown_not_a_selection() -> None:
    status, chosen, _ = select_version((), date(2024, 1, 1))
    assert status is TemporalResolution.UNKNOWN
    assert chosen is None


# ---------------------------------------------------------------------------
# Coverage semantics
# ---------------------------------------------------------------------------


def test_no_ncd_is_not_established_and_is_never_not_covered() -> None:
    """The most damaging error available in this layer, refused explicitly.

    Absence of a national determination generally means contractor discretion. A
    system that read silence as refusal would deny nationally on the basis of CMS
    having said nothing.
    """
    resolution = resolve_coverage((), date(2024, 1, 1))
    assert resolution.status is CoverageStatus.NOT_ESTABLISHED
    assert resolution.status is not CoverageStatus.NOT_COVERED
    assert not resolution.establishes_coverage
    assert any("does NOT establish non-coverage" in n for n in resolution.notes)


def test_an_unresolvable_determination_is_unknown_not_not_established() -> None:
    """A determination that exists but cannot be placed is a different thing.

    `NOT_ESTABLISHED` means nobody ruled nationally. `UNKNOWN` means somebody did
    and we cannot say which ruling governs. Collapsing them would lose the
    distinction between an absent policy and an unreadable one.
    """
    resolution = resolve_coverage((_version(1, None, raw=LONGSTANDING),), date(2024, 1, 1))
    assert resolution.temporal is TemporalResolution.TEMPORALLY_UNRESOLVABLE
    assert resolution.status is CoverageStatus.UNKNOWN
    assert resolution.status is not CoverageStatus.NOT_ESTABLISHED
    assert resolution.version is None


def test_coverage_status_is_never_inferred_from_the_document() -> None:
    """A governing version with no recorded status is UNKNOWN, not COVERED.

    Classifying `indications_limitations` prose by keyword would be exactly the
    unreviewed inference this project refuses everywhere else.
    """
    versions = derive_windows((_version(1, date(2010, 1, 1)),))
    resolution = resolve_coverage(versions, date(2024, 1, 1))
    assert resolution.temporal is TemporalResolution.RESOLVED
    assert resolution.version is not None
    assert resolution.status is CoverageStatus.UNKNOWN
    assert any("has not been recorded by a reviewer" in n for n in resolution.notes)


def test_a_recorded_status_is_reported_for_the_governing_version_only() -> None:
    versions = derive_windows((_version(1, date(2000, 1, 1)), _version(2, date(2020, 1, 1))))
    recorded = {1: CoverageStatus.NOT_COVERED, 2: CoverageStatus.COVERED}

    early = resolve_coverage(versions, date(2010, 1, 1), status_of=recorded)
    assert early.status is CoverageStatus.NOT_COVERED

    late = resolve_coverage(versions, date(2024, 1, 1), status_of=recorded)
    assert late.status is CoverageStatus.COVERED


def test_conditional_coverage_does_not_establish_coverage() -> None:
    """ "Covered if X" is not "covered". Whether X holds is adjudication."""
    versions = derive_windows((_version(1, date(2010, 1, 1)),))
    resolution = resolve_coverage(
        versions, date(2024, 1, 1), status_of={1: CoverageStatus.CONDITIONAL}
    )
    assert resolution.status is CoverageStatus.CONDITIONAL
    assert not resolution.establishes_coverage


def test_coverage_status_has_no_approve_or_deny_member() -> None:
    """The invariant, at the coverage layer.

    `CoverageStatus` is the vocabulary a future adjudication layer will map FROM.
    An outcome token here would let coverage resolution decide a case directly,
    which is the same structural error as an outcome token in a model schema.
    """
    members = {member.value for member in CoverageStatus}
    assert not members & {"APPROVE_RECOMMENDED", "DENY_RECOMMENDED", "APPROVE", "DENY"}


# ---------------------------------------------------------------------------
# Empty responses are not end-of-history
# ---------------------------------------------------------------------------


def test_no_version_data_is_distinct_from_end_of_history() -> None:
    """The API returns 200-with-no-rows for a version that does not exist.

    Reading that as "history ends here" is what makes probing 1, 2, 3… truncate
    silently. The status has its own name so the distinction survives.
    """
    assert VersionDataStatus.NO_VERSION_DATA.value == "NO_VERSION_DATA"
    assert {s.value for s in VersionDataStatus} == {"PRESENT", "NO_VERSION_DATA"}
    assert "END_OF_HISTORY" not in {s.value for s in VersionDataStatus}


# ---------------------------------------------------------------------------
# The parsing path itself, against recorded API responses
# ---------------------------------------------------------------------------
#
# The tests above build `NcdVersion` directly, so they exercise derivation and
# selection but NOT the code that decides `temporal_status` from a raw record. An
# injection that made every parsed record DATED with a sentinel date left every one
# of them green - which is exactly the defect this section exists to catch.

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "coverage"


def _record(name: str) -> dict:
    payload = json.loads((FIXTURES / name).read_text(encoding="utf-8"))
    return payload["data"][0]


def test_a_recorded_undated_record_parses_as_undated() -> None:
    """The real payload, not a hand-built one.

    NCD 150.1 publishes the longstanding-determination sentence where a date
    belongs. Parsing it must yield no date and `UNDATED` - and the raw string must
    survive, so the row can explain why it is unreachable.
    """
    version = version_from_record(
        _record("ncd-3-undated.json"),
        ncdid=3,
        source_url="https://api.coverage.cms.gov/v1/data/ncd?ncdid=3",
        retrieved_at=datetime(2026, 8, 23, tzinfo=UTC),
    )
    assert version.effective_date is None
    assert version.temporal_status is TemporalStatus.UNDATED
    assert "has not been posted" in version.effective_date_source
    assert not version.is_resolvable


def test_a_recorded_dated_record_parses_as_dated() -> None:
    """The positive control. Without it, "everything is UNDATED" would pass."""
    version = version_from_record(
        _record("ncd-1-dated.json"),
        ncdid=1,
        source_url="https://api.coverage.cms.gov/v1/data/ncd?ncdid=1",
        retrieved_at=datetime(2026, 8, 23, tzinfo=UTC),
    )
    assert version.effective_date == date(2024, 5, 27)
    assert version.temporal_status is TemporalStatus.DATED
    assert version.is_resolvable


def test_a_parsed_record_carries_its_provenance() -> None:
    version = version_from_record(
        _record("ncd-1-dated.json"),
        ncdid=1,
        source_url="https://api.coverage.cms.gov/v1/data/ncd?ncdid=1",
        retrieved_at=datetime(2026, 8, 23, tzinfo=UTC),
    )
    assert version.source_url.startswith("https://api.coverage.cms.gov/")
    assert version.retrieved_at is not None
    assert version.content_sha256
    assert version.policy_id.startswith("NCD ")


def test_a_parsed_record_never_carries_a_sentinel_date() -> None:
    """The specific mutation: `effective_date or date.min`.

    A sentinel would make an undated determination in force for every date of
    service - the widest-applicability direction, and the one that would print a
    fabricated date to a reviewer.
    """
    for name in ("ncd-3-undated.json", "ncd-1-dated.json"):
        version = version_from_record(
            _record(name), ncdid=1, source_url="x", retrieved_at=datetime(2026, 8, 23, tzinfo=UTC)
        )
        assert version.effective_date != date.min
        assert (version.effective_date is None) == (
            version.temporal_status is not TemporalStatus.DATED
        )
