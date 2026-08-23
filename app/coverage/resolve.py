"""Coverage resolution: which NCD version governs, and what it establishes.

**This module produces no recommendation.** It answers two narrow questions -
*which version of a coverage determination applies to this date of service*, and
*what does that determination establish about coverage* - and stops. Mapping a
coverage state onto `APPROVE_RECOMMENDED` or `DENY_RECOMMENDED` belongs to the
adjudication layer, which is not built yet.

That separation is not tidiness. Two conflations are the failure modes here, and
both are one careless mapping away:

**The absence of an NCD is not a denial.** No national determination generally
means the question is left to contractor discretion or case-by-case adjudication -
it does *not* mean non-coverage. `NOT_ESTABLISHED` exists so that "nobody has ruled
nationally" has a name of its own and cannot be typed as `NOT_COVERED`.

**Satisfying a regulation is not coverage.** 42 CFR states conditions of payment;
an NCD states whether an item is covered at all. A case can satisfy every statutory
condition and still not be covered, and can be covered while failing one. Nothing
here reads the regulation layer, and nothing in the regulation layer reads this.

Pure: no I/O, no clock. `as_of` is an argument. Versions arrive already resolved
from the database by the caller, so this module can be exercised as a truth table.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from enum import StrEnum

from app.coverage.ncd import NcdVersion
from app.policy.models import TemporalStatus

__all__ = [
    "CoverageResolution",
    "CoverageStatus",
    "TemporalResolution",
    "resolve_coverage",
    "select_version",
]


class TemporalResolution(StrEnum):
    """Whether a governing version could be selected for a date of service."""

    #: Exactly one version was in force. The only outcome that yields a version.
    RESOLVED = "RESOLVED"

    #: Versions exist and are dated, but none covers this date - the service
    #: predates the earliest, or falls in a gap the source leaves.
    NO_APPLICABLE_VERSION = "NO_APPLICABLE_VERSION"

    #: Versions exist and none can be placed in time. The source published prose
    #: where a date belongs, or two versions claim the same effective date. The
    #: determination is real; when it applied is unknown.
    TEMPORALLY_UNRESOLVABLE = "TEMPORALLY_UNRESOLVABLE"

    #: More than one dated version claims this date, which the derivation should
    #: make impossible. Reaching it means the corpus is inconsistent.
    AMBIGUOUS = "AMBIGUOUS"

    #: Nothing was supplied to resolve.
    UNKNOWN = "UNKNOWN"


class CoverageStatus(StrEnum):
    """What a coverage determination establishes. **Never a recommendation.**

    Deliberately NOT mapped to `Outcome` anywhere in this phase. The mapping is a
    clinical policy decision, and writing it before the adjudication layer exists
    would bake in the two conflations this module is built to prevent.
    """

    #: The determination establishes national coverage.
    COVERED = "COVERED"

    #: The determination establishes national non-coverage. A positive finding,
    #: made by CMS - not an inference from silence.
    NOT_COVERED = "NOT_COVERED"

    #: Covered subject to conditions the determination states. Most NCDs are this,
    #: and whether a given case meets those conditions is adjudication, not
    #: resolution.
    CONDITIONAL = "CONDITIONAL"

    #: No national determination governs. **This is not NOT_COVERED.** Absence of
    #: an NCD generally means contractor discretion, and the single most damaging
    #: error available in this layer would be to read silence as refusal.
    NOT_ESTABLISHED = "NOT_ESTABLISHED"

    #: A determination exists but does not address this request.
    NOT_APPLICABLE = "NOT_APPLICABLE"

    #: A determination governs and what it establishes could not be determined -
    #: including every case where the governing version could not be selected.
    UNKNOWN = "UNKNOWN"


@dataclass(frozen=True, slots=True)
class CoverageResolution:
    """What coverage resolution concluded, and why.

    `temporal` and `status` are separate because they fail separately: a version
    that cannot be placed in time and a version that says nothing useful are
    different problems with different fixes, and a reviewer needs to know which.
    """

    temporal: TemporalResolution
    status: CoverageStatus
    version: NcdVersion | None = None
    candidates_considered: int = 0
    notes: tuple[str, ...] = field(default_factory=tuple)

    @property
    def establishes_coverage(self) -> bool:
        """True only for an unconditional, positively established coverage finding.

        `CONDITIONAL` is excluded: whether the conditions are met is adjudication,
        and treating "covered if X" as "covered" is how a condition disappears.
        """
        return self.status is CoverageStatus.COVERED


def select_version(
    versions: tuple[NcdVersion, ...], as_of: date
) -> tuple[TemporalResolution, NcdVersion | None, tuple[str, ...]]:
    """Pick the version in force on `as_of`. Never "the latest".

    A version whose effective date the source never published is not a candidate,
    however recent it looks. Falling back to the newest row when temporal
    resolution fails is the specific error this function exists to refuse - it is
    how a determination that took effect after the service gets applied to it.
    """
    if not versions:
        return TemporalResolution.UNKNOWN, None, ("no versions supplied",)

    dated = [v for v in versions if v.temporal_status is TemporalStatus.DATED]
    if not dated:
        return (
            TemporalResolution.TEMPORALLY_UNRESOLVABLE,
            None,
            (
                f"{len(versions)} version(s) exist and none carries a published "
                "effective date; the determination is real but cannot be placed in "
                "time. Selecting the most recent would apply a version whose start "
                "is unknown.",
            ),
        )

    in_force = [
        v
        for v in dated
        if v.effective_date is not None
        and v.effective_date <= as_of
        and (v.end_date is None or v.end_date >= as_of)
    ]

    if len(in_force) == 1:
        return TemporalResolution.RESOLVED, in_force[0], ()
    if len(in_force) > 1:
        return (
            TemporalResolution.AMBIGUOUS,
            None,
            (
                f"{len(in_force)} versions are in force on {as_of}; window "
                "derivation should make this impossible, so the corpus is "
                "inconsistent",
            ),
        )

    undated = len(versions) - len(dated)
    note = f"no version of this determination was in force on {as_of}"
    if undated:
        note += (
            f"; {undated} further version(s) carry no published effective date and "
            "could not be considered"
        )
    return TemporalResolution.NO_APPLICABLE_VERSION, None, (note,)


def resolve_coverage(
    versions: tuple[NcdVersion, ...],
    as_of: date,
    *,
    status_of: dict[int, CoverageStatus] | None = None,
) -> CoverageResolution:
    """Resolve which determination governs, and what it establishes.

    `status_of` maps a version number to what a reviewer determined that version
    establishes. **It is not derived from the document text**, and there is no
    default: an NCD's `indications_limitations` is prose, and classifying it
    COVERED or NOT_COVERED by keyword would be exactly the unreviewed inference
    this project refuses everywhere else. Absent an entry, the status is `UNKNOWN` -
    the determination governs and what it establishes is not yet recorded.

    An empty `versions` means no national determination governs, which is
    `NOT_ESTABLISHED` and **never** `NOT_COVERED`.
    """
    if not versions:
        return CoverageResolution(
            temporal=TemporalResolution.UNKNOWN,
            status=CoverageStatus.NOT_ESTABLISHED,
            candidates_considered=0,
            notes=(
                "no national coverage determination governs this request. Absence "
                "of an NCD generally means contractor discretion or case-by-case "
                "adjudication - it does NOT establish non-coverage.",
            ),
        )

    temporal, version, notes = select_version(versions, as_of)

    if version is None:
        return CoverageResolution(
            temporal=temporal,
            # A determination exists; which one governs is unknown. That is not the
            # same as no determination existing, so it is UNKNOWN rather than
            # NOT_ESTABLISHED - and it is certainly not NOT_COVERED.
            status=CoverageStatus.UNKNOWN,
            candidates_considered=len(versions),
            notes=notes,
        )

    recorded = (status_of or {}).get(version.version)
    if recorded is None:
        return CoverageResolution(
            temporal=temporal,
            status=CoverageStatus.UNKNOWN,
            version=version,
            candidates_considered=len(versions),
            notes=(
                f"{version.policy_id} version {version.version} governs on {as_of}, "
                "and what it establishes has not been recorded by a reviewer. It is "
                "not inferred from the document text.",
            ),
        )

    return CoverageResolution(
        temporal=temporal,
        status=recorded,
        version=version,
        candidates_considered=len(versions),
        notes=notes,
    )
