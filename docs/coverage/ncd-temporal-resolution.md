# NCD Temporal Resolution

Which version of a coverage determination governs a date of service — and when the
honest answer is *none*.

**The rule: never choose "latest" because temporal resolution failed.**

---

## Version enumeration

Read from `/v1/data/ncd/other-versions?ncdid=<id>`, which returns the authoritative
list. **Never by probing `ncdver=1,2,3…` until empty.**

A version that does not exist returns **HTTP 200 with an empty `data` array**, not a
404. So probing cannot distinguish "no such version" from "empty record", and would
stop at the first gap — reporting a truncated history as a complete one. That is why
`VersionDataStatus` names `NO_VERSION_DATA` and does not name `END_OF_HISTORY`: an
empty response is a fact about one request, not a statement about a document's
history.

A version the list names whose record comes back empty is a **hard refusal**: the
source disagrees with itself, and that is a corpus defect rather than a missing
version.

## Window derivation, and its asymmetry

> **Ends are inferred. Starts never are.**

Inferring an end *narrows* applicability. Inferring a start *widens* it. That
asymmetry is the whole rule, and it matches the direction-of-error reasoning used at
`applies_in_jurisdiction()` and `leaf_value()`.

A dated version runs until the day before the next **dated** version begins.
`window_derivation` records `DERIVED_FROM_SEQUENCE`, so `ResolvedVersion.why` can
tell a reviewer the end was derived — presenting a derived date as a published one
is the same class of error as a sentinel, one field over.

Undated versions do not participate and do not break the chain. An undated v1
followed by a dated v2 leaves v1 permanently unreachable (its start is unknown)
while v2 is perfectly well defined.

Two dated versions sharing an effective date become `AMBIGUOUS` — both unreachable.
Picking one would be choosing a winner the source does not name.

### `effective_end_date` is never a version end

Settled by probe: for NCD 30.4 it is `01/01/2021` on all three versions while their
effective dates run to `04/10/2023`. Identical across versions ⇒ document-level;
preceding the start ⇒ not a window.

It is stored as `policy_documents.retirement_date_raw` and may only ever **close** a
window, never open one. Where it precedes the newest version's start, the document
is **refused** — there is no coherent window to build, and building one would mean
choosing which of two contradictory published values to believe.

## Resolution outcomes

| `TemporalResolution` | means |
|---|---|
| `RESOLVED` | exactly one version was in force. The only outcome yielding a version |
| `NO_APPLICABLE_VERSION` | versions are dated, none covers this date — service predates the earliest, or falls in a gap |
| `TEMPORALLY_UNRESOLVABLE` | versions exist and none can be placed in time. The determination is real; when it applied is unknown |
| `AMBIGUOUS` | more than one dated version claims this date. Derivation should make this impossible, so the corpus is inconsistent |
| `UNKNOWN` | nothing was supplied |

`TEMPORALLY_UNRESOLVABLE` maps to `CoverageStatus.UNKNOWN`, **not**
`NOT_ESTABLISHED`. A determination that exists but cannot be placed is a different
thing from no determination existing, and collapsing them would lose the distinction
between an absent policy and an unreadable one.

## Enforcement in SQL

`in_force_on()` names `temporal_status = 'DATED'` explicitly, and it is worth being
precise about why, because the honest answer is not "otherwise undated rows leak".

Deleting the conjunct alone changes nothing — `NULL <= as_of` is NULL, so undated
rows are already excluded and every test still passes. **Measured, not assumed.**

What it protects against is the next edit. Making the date comparison NULL-tolerant
— `or_(effective_date.is_(None), effective_date <= as_of)` — looks like a reasonable
accommodation for a nullable column and would put every undated version in force for
**every** date of service. With the conjunct that mutation is caught; without it,
both undated-unreachability tests fail. Both mutations were run.

The same predicate is used by resolution *and* retrieval, so an undated version is
unreachable as evidence as well as unreachable as policy. A version whose text could
be cited with an effective date the citation cannot show would be worse than not
storing it at all.

## Measured on the acquired corpus

| | |
|---|---|
| versions acquired | 19 |
| `DATED` | 16 |
| `UNDATED` | 3 |
| documents refused for an incoherent retirement date | 1 |

Derived windows across the 16 dated versions are contiguous and non-overlapping —
each ends exactly one day before the next begins — and the newest version of each
document is open-ended.

**No claim is made about NCD temporal completeness.** Where CMS publishes no
effective date, this system does not have one, and says so.
