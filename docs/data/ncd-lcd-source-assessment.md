# NCD / LCD Source Assessment (OD-20)

**Finding: National Coverage Determinations are openly accessible through an
official CMS API. Local Coverage Determinations are not — they sit behind an
AMA/ADA/AHA licence gate.**

---

## 1. What was found

`api.coverage.cms.gov` — the MCIM API, operated by CMS — **is reachable from this
network**, unlike every other CMS property. It was found by probing systematically
rather than assuming: it returns **400** where `cms.gov` returns **403**, and a 400
means the request arrived.

| Endpoint | Result |
|---|---|
| `/v1/data/contractor` | **200** — open |
| `/v1/data/ncd?ncdid=N` | **200** — open, full NCD record |
| `/v1/data/ncd?ncdid=N&ncdver=V` | **200** — **historical versions retrievable** |
| `/v1/data/lcd` | **401** — licence token required |
| `/v1/data/article` | **401** — licence token required |

The API states the gate plainly:

> "some endpoints require a license agreement token for access. This token is
> obtained by accepting the AMA, ADA, and AHA license agreements"

That is the CPT copyright boundary ADR-003 anticipated, appearing exactly where
expected: LCDs and Articles are dense with CPT codes; NCDs largely are not.

**No access control was circumvented.** The 401 endpoints were not pursued, and no
licence agreement was accepted — accepting one on the operator's behalf would commit
them to redistribution terms that are theirs to weigh.

## 2. What an NCD actually contains

Sampled 15 NCDs. Example, NCD 310.1 *Routine Costs in Clinical Trials*:

| Field | Value |
|---|---|
| `document_display_id` | 310.1 |
| `document_version` | **3** |
| `effective_date` | 05/27/2024 |
| `indications_limitations` | **10,549 characters**, 35 obligation markers |
| `benefit_category`, `cross_reference`, `transmittal_number` | present |

8 of 15 sampled NCDs carry substantial `indications_limitations` text. Version
history is real: NCD 20.29 (Hyperbaric Oxygen) is at v4, NCD 30.3 (Acupuncture) at
v2.

**A real limitation, found by sampling rather than assumed:** many NCDs are
"longstanding" and carry no posted effective date — the field literally reads *"This
is a longstanding national coverage determination. The effective date of this
version has not been posted."* Temporal resolution over those is impossible, and
they are a substantial share of the corpus (7 of 15 sampled).

---

## 3. Comparison against the current eCFR corpus

| Dimension | eCFR (42 CFR) | NCD (MCIM API) | LCD |
|---|---|---|---|
| Authority for coverage decisions | Regulation — the layer *above* | **Coverage determination itself** | Coverage determination, local |
| Medical-necessity specificity | Conditions of payment, general | **Procedure-specific indications** | Most specific |
| Procedure code linkage | **None** — must be curated | Partial | **Yes, in source** |
| Diagnosis code linkage | None | Partial | **Yes, in source** |
| Documentation requirements | Yes, strong | Varies | Yes |
| Temporal versioning | **Excellent** — any date, real amendments | **Good**, but absent for longstanding NCDs | Behind licence |
| Retrieval feasibility | **Excellent** — structured XML | Good — JSON, HTML in one field | Not accessible |
| Provenance | **Excellent** — OFR, public domain | **Good** — CMS official | n/a |
| Reproducibility | **Excellent** — date-addressable | Good — id + version addressable | n/a |
| Engineering effort | Done | Moderate — new adapter, HTML parsing | Blocked |
| Legal/usage constraints | **None** — public domain | **None** for NCD endpoints | **AMA/ADA/AHA licence** |
| Evaluation usefulness | Good, but wrong layer | **High — the right layer** | Highest, unavailable |

### The decisive points

**eCFR's weakness is structural, not incidental.** A regulation enumerates no
procedure codes, which is why `data/linkage/` exists at all and why **zero** of its
16 links can be `AUTHORITATIVE`. NCDs carry indications tied to specific procedures,
so a meaningful part of that curated layer would stop being curated.

**NCD's weakness is temporal coverage**, and it is real: longstanding NCDs cannot
support date-of-service resolution at all. 42 CFR is *better* on temporal
versioning, which is the property this architecture is built around.

They are complementary rather than competing, and that is what decides it.

---

## 4. Decision

**OPTION C — eCFR and NCD as separate policy layers, LCD deferred.**

| Layer | Type | Status |
|---|---|---|
| 42 CFR | `REGULATION` | **Retained.** Best temporal versioning; conditions of payment |
| NCD | `NCD` | **Adopt** as a distinct layer, in the next phase |
| LCD / Article | `LCD`, `ARTICLE` | **Deferred** — licence gate is the operator's decision (OD-21) |
| 42 CFR 411.15 | `EXCLUSION_OVERLAY` | Retained as an overlay |

Rejected:

- **Option A (eCFR only)** — leaves procedure linkage permanently curated and the
  corpus permanently one layer above where coverage criteria live.
- **Option B (NCD as primary, replacing eCFR)** — would lose the temporal
  versioning that the resolution architecture exists to exercise, and longstanding
  NCDs cannot supply it.
- **Option D (defer entirely)** — was the expected answer before probing, and the
  evidence does not support it. NCDs are open, official, versioned and reachable.

### Non-negotiable: the layers never merge

`DocumentType` already distinguishes `REGULATION`, `NCD`, `LCD`, `ARTICLE`. A
regulation must never silently become a coverage determination — they carry
different authority, and conflating them would misstate what the system is citing.
Adding NCDs must extend the enum's use, not blur it. A test asserts the separation.

---

## 5. What adopting NCDs would and would not fix

**Would fix:** the corpus reaching the coverage-determination layer; some curated
code linkage becoming source-derived; procedure-specific indications instead of
general conditions of payment.

**Would not fix:** completeness (OD-19) — someone still has to decide which
provisions of an NCD are decision-relevant, and that is the same unverified
judgement. Nor clinical review. Nor the constructed clinical notes.

**Adopting NCDs improves the corpus. It does not resolve the ground-truth gate.**

Sources: [MCIM API](https://api.coverage.cms.gov/) · [CMS MCD Downloads](https://www.cms.gov/medicare-coverage-database/downloads/downloads.aspx) · [CMS Local Coverage Determinations](https://www.cms.gov/medicare/coverage/determination-process/local)
