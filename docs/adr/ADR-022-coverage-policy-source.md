# ADR-022 — Coverage Policy Source: 42 CFR, NCDs, and the Deferred LCD Layer

**Status:** Accepted (2026-08-23)
**Supersedes:** nothing. **Amends:** ADR-003 (CMS policy corpus & licensing), ADR-021.
**Resolves:** OD-20. **Opens:** OD-21.

---

## Context

ADR-003 assumed the corpus would be NCDs and LCDs downloaded from CMS. It cannot be:
every `cms.gov` property returns **403 at an Akamai edge from this location**, including
`robots.txt` itself, while other US-government hosts answer normally. This is a
geographic access restriction, not a crawl policy.

Circumventing it — user-agent spoofing, proxying, or any access-control evasion — was
refused and is out of bounds permanently.

Phase 2B therefore built the corpus from **42 CFR** via the official eCFR API: real
regulation, public domain, date-addressable, with genuine amendment history. That
produced 8 documents, 7 versions, 33 span-verified criteria.

But 42 CFR is one layer *above* coverage determinations. It states the statutory
conditions for payment; it does not state whether a specific procedure is covered for
a specific diagnosis in a specific jurisdiction. That is what an NCD or LCD does, and
it is what a prior-authorization system actually reasons over.

**OD-20 asked: can NCD/LCD content be obtained legitimately?**

## Investigation

The Medicare Coverage Information Model (MCIM) API at `api.coverage.cms.gov` is a
different host from `cms.gov` and is **not behind the same edge restriction**:

| Endpoint | Result | Interpretation |
|---|---|---|
| `cms.gov/*` | `403` (Akamai) | Geographically blocked |
| `api.coverage.cms.gov/v1/data/ncd?ncdid=N` | **`200`** | Openly accessible |
| `.../ncd?ncdid=N&ncdver=V` | **`200`** | Version history available |
| `.../lcd?...` | **`401`** | Behind a licence token |
| `.../article?...` | **`401`** | Behind a licence token |

The `401` is a licence gate, not an access block. LCDs and Billing & Coding Articles
embed **CPT® (AMA), CDT® (ADA) and ICD-10-PCS/CPT-assistant (AHA)** content, and CMS
requires acceptance of those licence agreements before serving them.

**No licence agreement was accepted and no `401` endpoint was pursued.** Accepting a
copyright licence on the user's behalf is not a decision this project makes
unilaterally, and ADR-003 already forbids redistributing AMA descriptor text.

## Options

**A — 42 CFR only.** Keep the current corpus. Honest and authoritative, but the
system never reasons over an actual coverage determination, which is the whole
premise. Retrieval stays too small to be evaluable (13 sections).

**B — Adopt NCDs and LCDs.** Maximum realism. Requires accepting the AMA/ADA/AHA
licence terms, and creates a redistribution hazard the repository is explicitly
structured to avoid.

**C — 42 CFR + NCDs as separate layers; LCDs deferred behind an explicit gate.**
NCDs are openly served, are the *national* coverage layer, and carry versioned
history matching the temporal model already built. LCDs stay out until the licence
question is answered deliberately.

**D — Synthesise policy documents.** Rejected outright. A fabricated coverage policy
makes every downstream metric meaningless, and ADR-021 exists precisely because an
earlier iteration did this.

## Decision

**Option C.**

1. **42 CFR remains the statutory layer** — unchanged, authoritative, public domain.
2. **NCDs are adopted as a second, separately-typed layer.** `policy_type` already
   distinguishes them; resolution, temporal versioning and retrieval scoping apply
   identically. NCDs are **not** merged into the CFR corpus and are never presented
   as interchangeable with it.
3. **LCDs and Billing & Coding Articles are deferred** behind **OD-21**, which cannot
   be closed by engineering — it requires a decision about accepting AMA/ADA/AHA
   licence terms and a plan for keeping descriptor text out of the repository.
4. **CPT® descriptor text is never committed**, from any source. Code *values* are
   fine; descriptor prose is not redistributed here (ADR-003, unchanged).
5. **The limitation is stated wherever coverage claims are made**, not buried: this
   system reasons over statutory conditions and national coverage determinations, and
   **not** over local contractor policy — which is where a large share of real prior
   authorization actually lives.

## Consequences

**Positive.** The corpus grows toward a real coverage layer without a licence
compromise. NCD version history exercises the temporal model against documents it was
designed for. Retrieval gains enough volume that ranking becomes a measurable problem
(see the Part G assessment — the current corpus is too small to discriminate between
encoders).

**Negative.** NCD adoption is *decided*, not *implemented* — the corpus is still 42
CFR only, so Q10 of the readiness gate remains `PARTIAL`. Jurisdictional resolution
stays untested against real MAC-level policy, because national determinations have no
jurisdiction axis to test. Any claim about local coverage remains **refused** in
`docs/evidence-and-claims.md`.

**Neutral.** No change to resolution, retrieval, guardrail or decision code. This ADR
adds a source, not a mechanism.

## Rejected alternatives, recorded

- **Scraping CMS through a proxy or with a spoofed user agent.** Refused. Access-control
  circumvention is out of bounds regardless of the value of the data.
- **Accepting the AMA licence to unlock LCDs.** Not refused on principle — deferred, as
  OD-21, because it is the user's decision and carries a redistribution obligation the
  repository must be restructured to honour first.
- **Using a third-party mirror of CMS coverage data.** Rejected: provenance cannot be
  verified, which defeats the purpose of an authoritative corpus.
