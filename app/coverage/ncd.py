"""National Coverage Determinations from the CMS Coverage (MCIM) API.

A coverage determination is not a regulation. 42 CFR states the statutory
conditions of payment; an NCD states whether Medicare covers a particular item or
service nationally. They are stored as separate `document_type`s, retrieved through
separate scopes, and never merged - ADR-022 made that non-negotiable and Phase 5
turns it into a database constraint and a query predicate.

## What the source actually provides

Verified by live probe, not assumed. `GET /v1/data/ncd?ncdid=<id>` returns 19
fields. Four properties of that payload shape everything below:

**There is no procedure-code field.** Not one of the 19. So NCD applicability
cannot come from the document, and the linkage stays curated - exactly as it is for
42 CFR, and for the same reason. Nothing here may claim CMS supplies it.

**`effective_date` is often prose.** 14 of 24 records sampled carried "This is a
longstanding national coverage determination. The effective date of this version
has not been posted." Such a version is stored, indexed and provenance-preserved,
and is **unreachable by date of service**. Encoding the unknown as a sentinel would
convert "we do not know when this took effect" into "it has always been in effect".

**`effective_end_date` is not a version window.** For NCD 30.4 it is identical
across all three versions and *precedes* their effective dates. It is a
document-level retirement date; treating it as a window would manufacture an
interval the source does not establish.

**A non-existent version returns HTTP 200 with an empty `data` array**, not 404. So
version history is read from `/ncd/other-versions`, never by probing 1, 2, 3… until
empty - that would silently truncate at the first gap and report a partial history
as a complete one.

## Temporal derivation, and its asymmetry

**Ends may be inferred. Starts never are.** Inferring an end *narrows*
applicability; inferring a start *widens* it. A dated version runs until the day
before the next dated version begins, and `window_derivation` records that the end
was derived so a reviewer is never shown an inferred date as a published one.
"""

from __future__ import annotations

import html
import json
import re
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Iterator
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta
from enum import StrEnum
from typing import Any

from app.core.errors import MedauthError
from app.core.hashing import content_hash
from app.policy.models import TemporalStatus, WindowDerivation

__all__ = [
    "BASE_URL",
    "NcdAcquisitionError",
    "NcdDocument",
    "NcdRefusal",
    "NcdSource",
    "NcdVersion",
    "VersionDataStatus",
    "derive_windows",
    "parse_cms_date",
    "strip_html",
    "version_from_record",
]

BASE_URL = "https://api.coverage.cms.gov/v1/data"
USER_AGENT = "medauth-ai/0.1 (research; coverage policy ingestion)"

#: The API publishes dates in this format and nothing else. Anything that does not
#: match is treated as prose - never scraped for a date-shaped substring, because a
#: regex over "not been posted" is how a fabricated date gets into a citation.
_CMS_DATE = re.compile(r"^\s*(\d{2})/(\d{2})/(\d{4})\s*$")

#: Tags that end a block of text. Replaced with a newline so paragraph structure
#: survives into chunking; every other tag becomes a space, because an inline tag
#: like <strong> sits INSIDE a sentence and turning it into a newline would split
#: that sentence in two. An earlier version did exactly that and produced
#: "Covered\nwhen documented." from "<strong>Covered</strong> when documented."
_BLOCK_TAG = re.compile(r"</?(?:p|div|br|li|ul|ol|tr|table|h[1-6]|blockquote)\b[^>]*>", re.I)
_TAG = re.compile(r"<[^>]+>")
_WHITESPACE = re.compile(r"[ \t]+")
_BLANK_LINES = re.compile(r"\n{3,}")


class NcdAcquisitionError(MedauthError):
    """Acquisition failed. Never recovered from by substituting a default."""


class VersionDataStatus(StrEnum):
    """What the source returned for a version the version list named.

    `NO_VERSION_DATA` exists so an empty response is never read as
    `END_OF_HISTORY`. The API returns 200-with-no-rows for a version that does not
    exist, so the two are indistinguishable at the transport layer and must be
    distinguished by what asked for them: a version the authoritative list named
    must have a record, and its absence is a source defect.
    """

    PRESENT = "PRESENT"
    NO_VERSION_DATA = "NO_VERSION_DATA"


@dataclass(frozen=True, slots=True)
class NcdRefusal:
    """A document the adapter declined to ingest, and why.

    Refusals are returned rather than raised so one incoherent document does not
    abort a corpus, and are recorded rather than dropped so the corpus can say what
    it does not contain.
    """

    ncdid: int
    display_id: str
    reason: str
    observed: dict[str, str] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class NcdVersion:
    """One published version of an NCD, normalised.

    Field names mirror the source. Nothing is invented: every value is either
    copied, parsed strictly, or derived with `window_derivation` saying so.
    """

    ncdid: int
    version: int
    display_id: str
    title: str
    #: None when `temporal_status` is not DATED.
    effective_date: date | None
    effective_date_source: str
    #: The document-level `effective_end_date` exactly as published. NOT this
    #: version's end date - for NCD 30.4 it is identical across all three versions
    #: and precedes their effective dates. Kept per version because that is where
    #: the API returns it, and because being identical across versions is the
    #: evidence that it is document-level.
    effective_end_date_source: str
    temporal_status: TemporalStatus
    end_date: date | None = None
    window_derivation: WindowDerivation = WindowDerivation.POSTED
    benefit_category: str = ""
    item_service_description: str = ""
    indications_limitations: str = ""
    reasons_for_denial: str = ""
    cross_reference: str = ""
    transmittal_number: str = ""
    transmittal_url: str = ""
    revision_history: str = ""
    other_text: str = ""
    ama_statement: str = ""
    source_url: str = ""
    retrieved_at: datetime | None = None
    content_sha256: str = ""

    @property
    def policy_id(self) -> str:
        """`NCD 220.6.5`, mirroring the `42 CFR 410.32` convention.

        Prefixed so a bare policy id in a log line or a citation is unambiguous
        about which layer of authority it names.
        """
        return f"NCD {self.display_id}"

    @property
    def is_resolvable(self) -> bool:
        return self.temporal_status.is_resolvable


@dataclass(frozen=True, slots=True)
class NcdDocument:
    """An NCD and every version of it the source lists."""

    ncdid: int
    display_id: str
    title: str
    versions: tuple[NcdVersion, ...]
    retirement_date_raw: str = ""

    @property
    def policy_id(self) -> str:
        return f"NCD {self.display_id}"

    @property
    def resolvable_versions(self) -> tuple[NcdVersion, ...]:
        return tuple(v for v in self.versions if v.is_resolvable)


# ---------------------------------------------------------------------------
# Parsing
# ---------------------------------------------------------------------------


def parse_cms_date(raw: object) -> date | None:
    """`MM/DD/YYYY` or nothing. Prose returns None; no substring is scraped.

    `"N/A"`, an empty string and a paragraph of explanation all return None, and
    they are all the same answer: the source did not publish a date here.
    """
    if raw is None:
        return None
    match = _CMS_DATE.match(str(raw))
    if match is None:
        return None
    month, day, year = (int(g) for g in match.groups())
    try:
        return date(year, month, day)
    except ValueError:
        return None


def strip_html(raw: object) -> str:
    """Unescape entities, drop tags, normalise whitespace.

    Done at acquisition, never at retrieval: `text_sha256` must hash the text a
    reviewer reads, or tamper detection degrades into formatting detection.

    Entities are unescaped twice because the API double-escapes - the payload
    contains `&lt;p&gt;`, which is the escaped form of `<p>`.
    """
    if raw is None:
        return ""
    text = html.unescape(html.unescape(str(raw)))
    text = _BLOCK_TAG.sub("\n", text)
    text = _TAG.sub(" ", text)
    text = _WHITESPACE.sub(" ", text)
    text = "\n".join(line.strip() for line in text.splitlines())
    return _BLANK_LINES.sub("\n\n", text).strip()


def version_from_record(
    record: dict[str, Any], *, ncdid: int, source_url: str, retrieved_at: datetime
) -> NcdVersion:
    raw_effective = str(record.get("effective_date") or "")
    effective = parse_cms_date(raw_effective)

    body = "\n\n".join(
        part
        for part in (
            strip_html(record.get("item_service_description")),
            strip_html(record.get("indications_limitations")),
            strip_html(record.get("reasons_for_denial")),
        )
        if part
    )

    return NcdVersion(
        ncdid=ncdid,
        version=int(record.get("document_version") or 0),
        display_id=str(record.get("document_display_id") or ""),
        title=str(record.get("title") or ""),
        effective_date=effective,
        effective_date_source=raw_effective,
        effective_end_date_source=str(record.get("effective_end_date") or ""),
        temporal_status=(TemporalStatus.DATED if effective is not None else TemporalStatus.UNDATED),
        benefit_category=strip_html(record.get("benefit_category")),
        item_service_description=strip_html(record.get("item_service_description")),
        indications_limitations=strip_html(record.get("indications_limitations")),
        reasons_for_denial=strip_html(record.get("reasons_for_denial")),
        cross_reference=strip_html(record.get("cross_reference")),
        transmittal_number=str(record.get("transmittal_number") or ""),
        transmittal_url=str(record.get("transmittal_url") or ""),
        revision_history=strip_html(record.get("revision_history")),
        other_text=strip_html(record.get("other_text")),
        ama_statement=strip_html(record.get("ama_statement")),
        source_url=source_url,
        retrieved_at=retrieved_at,
        content_sha256=content_hash(body) if body else "",
    )


def derive_windows(versions: tuple[NcdVersion, ...]) -> tuple[NcdVersion, ...]:
    """Close each dated version the day before the next dated one opens.

    **Ends are inferred; starts are not.** Inferring an end narrows applicability,
    which is the safe direction; inferring a start widens it, which is not.

    Undated versions do not participate and do not break the chain: a dated
    version's end still comes from the next *dated* version. So an undated v1
    followed by a dated v2 leaves v1 permanently unreachable (its start is unknown)
    while v2 is perfectly well defined.

    Two dated versions sharing an effective date make the ordering unknowable, so
    both become `AMBIGUOUS` - stored, and unreachable. Picking one would be
    choosing a winner the source does not name.
    """
    dated = sorted(
        (v for v in versions if v.temporal_status is TemporalStatus.DATED),
        # `effective_date` is not None for DATED versions - the filter above
        # guarantees it, and `date.min` is never used as a sort key because it would
        # be the same sentinel this module exists to avoid.
        key=lambda v: (v.effective_date or date(1, 1, 1), v.version),
    )

    collisions = {
        v.effective_date
        for i, v in enumerate(dated[:-1])
        if v.effective_date == dated[i + 1].effective_date
    }

    resolved: dict[int, NcdVersion] = {}
    for index, version in enumerate(dated):
        if version.effective_date in collisions:
            resolved[version.version] = _as_unresolvable(
                version,
                TemporalStatus.AMBIGUOUS,
                f"two versions share effective date {version.effective_date}; the "
                "source does not establish which governs",
            )
            continue

        end: date | None = None
        derivation = WindowDerivation.POSTED
        for later in dated[index + 1 :]:
            if later.effective_date in collisions or later.effective_date is None:
                continue
            end = later.effective_date - timedelta(days=1)
            derivation = WindowDerivation.DERIVED_FROM_SEQUENCE
            break

        resolved[version.version] = NcdVersion(
            **{
                **{f: getattr(version, f) for f in version.__slots__},
                "end_date": end,
                "window_derivation": derivation,
            }
        )

    for version in versions:
        resolved.setdefault(version.version, version)
    return tuple(resolved[v.version] for v in versions)


def _as_unresolvable(version: NcdVersion, status: TemporalStatus, reason: str) -> NcdVersion:
    """Strip the dates and record why, so the row explains its own unreachability."""
    return NcdVersion(
        **{
            **{f: getattr(version, f) for f in version.__slots__},
            "temporal_status": status,
            "effective_date": None,
            "end_date": None,
            "effective_date_source": (
                f"{version.effective_date_source} [{reason}]"
                if version.effective_date_source
                else f"[{reason}]"
            ),
        }
    )


# ---------------------------------------------------------------------------
# Acquisition
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class NcdSource:
    """Fetches NCDs by id. No discovery, no crawling, no gated endpoints.

    Only the two documented NCD paths are ever requested. LCD and Article endpoints
    return 401 behind an AMA/ADA/AHA licence gate and are not called - not retried,
    not probed, not worked around (ADR-022, OD-21).
    """

    base_url: str = BASE_URL
    timeout_seconds: float = 30.0

    def _get(self, path: str, params: dict[str, Any]) -> dict[str, Any]:
        url = f"{self.base_url}{path}?{urllib.parse.urlencode(params)}"
        request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})  # noqa: S310
        try:
            with urllib.request.urlopen(request, timeout=self.timeout_seconds) as response:  # noqa: S310
                payload = json.loads(response.read().decode("utf-8"))
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            # Fail closed. A network failure must never yield a partial corpus that
            # looks complete - the caller decides what to do about a missing NCD.
            raise NcdAcquisitionError(f"{url}: unreachable ({exc})") from exc
        except json.JSONDecodeError as exc:
            raise NcdAcquisitionError(f"{url}: response was not JSON ({exc})") from exc

        if not isinstance(payload, dict) or "data" not in payload:
            raise NcdAcquisitionError(f"{url}: malformed payload, no `data` key")
        return payload

    def version_list(self, ncdid: int) -> tuple[int, ...]:
        """Version numbers from the authoritative list, descending.

        Never inferred by probing. A missing version returns 200 with no rows, so
        probing 1, 2, 3… until empty would stop at the first gap and report a
        truncated history as a complete one.
        """
        payload = self._get("/ncd/other-versions", {"ncdid": ncdid})
        rows = payload.get("data") or []
        if not rows:
            raise NcdAcquisitionError(
                f"ncdid={ncdid}: the version list is empty. Treating this as "
                "'one version' would be inferring history from an absence."
            )
        return tuple(sorted({int(r["document_version"]) for r in rows}, reverse=True))

    def fetch_version(
        self, ncdid: int, version: int
    ) -> tuple[VersionDataStatus, NcdVersion | None]:
        params = {"ncdid": ncdid, "ncdver": version}
        payload = self._get("/ncd", params)
        rows = payload.get("data") or []
        if not rows:
            return VersionDataStatus.NO_VERSION_DATA, None
        url = f"{self.base_url}/ncd?{urllib.parse.urlencode(params)}"
        return VersionDataStatus.PRESENT, version_from_record(
            rows[0], ncdid=ncdid, source_url=url, retrieved_at=datetime.now(UTC)
        )

    def fetch_document(self, ncdid: int) -> NcdDocument | NcdRefusal:
        """Every listed version of one NCD, with windows derived and coherence checked.

        Returns a refusal rather than raising when the *source* is internally
        inconsistent, so one bad document does not abort a corpus and the reason is
        recorded rather than lost.
        """
        versions: list[NcdVersion] = []
        retirement = ""
        for number in self.version_list(ncdid):
            status, version = self.fetch_version(ncdid, number)
            if status is VersionDataStatus.NO_VERSION_DATA:
                # The list named it and the record is absent: the source disagrees
                # with itself. Not silently skipped - that would report a partial
                # history as complete.
                return NcdRefusal(
                    ncdid=ncdid,
                    display_id="",
                    reason=(
                        f"version {number} appears in /ncd/other-versions but its "
                        "record is empty; the source disagrees with itself"
                    ),
                    observed={"version": str(number), "status": status.value},
                )
            if version is None:  # pragma: no cover - PRESENT always carries a record
                raise NcdAcquisitionError(f"ncdid={ncdid} version {number}: PRESENT with no record")
            versions.append(version)

        if not versions:
            return NcdRefusal(ncdid=ncdid, display_id="", reason="no versions returned")

        licensed = [v for v in versions if v.ama_statement]
        if licensed:
            # NCDs carried an empty `ama_statement` in every record sampled, but the
            # field exists. A populated one means AMA-licensed descriptor text, which
            # this repository does not redistribute (ADR-003).
            return NcdRefusal(
                ncdid=ncdid,
                display_id=versions[0].display_id,
                reason="record carries an AMA statement; licensed content is not ingested",
                observed={"versions": ",".join(str(v.version) for v in licensed)},
            )

        windowed = derive_windows(tuple(versions))
        retirement = str(_raw_retirement(versions))
        document = NcdDocument(
            ncdid=ncdid,
            display_id=windowed[0].display_id,
            title=windowed[0].title,
            versions=windowed,
            retirement_date_raw=retirement,
        )

        refusal = _check_retirement_coherence(document)
        return refusal if refusal is not None else document


def _raw_retirement(versions: list[NcdVersion]) -> str:
    """The document-level retirement string, if the source publishes a coherent one.

    `effective_end_date` appears on every version's record and is identical across
    them - that identity is how it was identified as document-level rather than as
    a version window.

    Returns "" when the versions disagree. Disagreement would mean the value is
    version-scoped after all, and this function's premise would be wrong; picking
    one anyway would be asserting a document-level fact from version-level data.
    """
    published = {
        v.effective_end_date_source.strip()
        for v in versions
        if v.effective_end_date_source.strip() not in {"", "N/A"}
    }
    return published.pop() if len(published) == 1 else ""


def _check_retirement_coherence(document: NcdDocument) -> NcdRefusal | None:
    """Refuse a document whose retirement date precedes its own last start.

    NCD 30.4 is the case: `effective_end_date` of 01/01/2021 against an effective
    date of 04/10/2023, identical across all three versions. There is no coherent
    window to build from that, and building one anyway would mean choosing which of
    two contradictory published values to believe.
    """
    retirement = parse_cms_date(document.retirement_date_raw)
    if retirement is None:
        return None
    dated = document.resolvable_versions
    if not dated:
        return None
    latest = max(v.effective_date for v in dated if v.effective_date is not None)
    if retirement < latest:
        return NcdRefusal(
            ncdid=document.ncdid,
            display_id=document.display_id,
            reason=(
                "the published retirement date precedes the newest version's "
                "effective date; the source does not establish a coherent window"
            ),
            observed={
                "retirement_date": str(retirement),
                "latest_effective_date": str(latest),
            },
        )
    return None


def iter_documents(
    source: NcdSource, ncdids: tuple[int, ...]
) -> Iterator[NcdDocument | NcdRefusal]:
    """Fetch each selected NCD in order. Order is the selection record's order."""
    for ncdid in ncdids:
        yield source.fetch_document(ncdid)
