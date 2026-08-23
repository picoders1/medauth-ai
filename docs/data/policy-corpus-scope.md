# Policy Corpus Scope

**Status: AUTHORITATIVE.** 42 CFR, retrieved from the official eCFR API, public
domain, with real amendment history.

---

## 1. Selection criteria

The corpus is deliberately small. "Ingest all of CMS" produces a large corpus that
exercises nothing in particular; what is needed is a set that stresses the specific
mechanisms this system is built on.

A section was included only if it supplies criteria that are **enumerable,
checkable against a submission, and varied in kind**:

| Requirement | Why | Where satisfied |
|---|---|---|
| Explicit conditions with "must" | Criterion-level ground truth needs them | 410.32, 410.33, 410.38, 410.61 |
| Documentation-content criteria | The `NEEDS_INFO` path is a first-class outcome | 410.38 order elements, 410.61 plan content |
| Timing criteria | Exercises numeric comparison | 410.38 face-to-face 6 months |
| Numeric thresholds | Borderline cases need a threshold to sit on | 410.38 months, 410.33 site limit |
| Personnel / eligibility | A different criterion shape from documentation | 410.33 supervision, qualification |
| Categorical exclusions | Decision-table row 7 needs a positively-evidenced exclusion | 410.38, 410.33, 411.15 |
| Multiple real revisions | Temporal resolution is untestable without them | 410.38, 410.61 |

Deliberately excluded, with reasons:

| Excluded | Reason |
|---|---|
| 42 CFR 410.43 (partial hospitalisation) | Structure yields too few headed paragraphs to anchor criteria reliably |
| 42 CFR 414.x (payment) | Payment methodology, not coverage criteria |
| Bulk ingestion of Title 42 | Out of proportion to a development corpus; nothing is gained by volume |
| Commercial payer policy | Copyrighted, not redistributable |
| Clinical guidelines | State what is clinically indicated, not what is covered. Conflating them is the error this system must not make |

---

## 2. Included policies

All retrieved from `https://www.ecfr.gov/api/versioner/v1/full/{date}/title-42.xml`
on **2026-08-23**. Checksums per document are recorded in `data/cms/registry.yaml`;
the criterion inventory carries `document_sha256` per criterion.

| Policy | Title | Rev | Effective | Ends | Criteria | Extraction | Verification |
|---|---|---|---|---|---|---|---|
| 42 CFR 410.32 | Diagnostic tests: Conditions | 2026-08-13 | 2026-08-13 | in force | 4 | OK | **PASS** |
| 42 CFR 410.33 | Independent diagnostic testing facility | 2026-08-13 | 2026-08-13 | in force | 5 | OK | **PASS** |
| 42 CFR 410.38 | DMEPOS: Scope and conditions | 2022-01-01 | 2022-01-01 | 2026-08-12 | 5 | OK | **PASS** |
| 42 CFR 410.38 | DMEPOS: Scope and conditions | 2026-08-13 | 2026-08-13 | in force | 5 | OK | **PASS** |
| 42 CFR 410.61 | Plan of treatment, outpatient rehab | 2019-01-01 | 2019-01-01 | 2026-08-12 | 5 | OK | **PASS** |
| 42 CFR 410.61 | Plan of treatment, outpatient rehab | 2026-08-13 | 2026-08-13 | in force | 5 | OK | **PASS** |
| 42 CFR 411.15 | Particular services excluded | 2026-08-13 | 2026-08-13 | in force | 4 | OK | **PASS** (overlay) |
| 42 CFR 410.43 | Partial hospitalisation | 2026-08-13 | 2026-08-13 | in force | 0 | OK | not transcribed |

**Authority:** Office of the Federal Register. **Source authority for codes:** NLM
Clinical Tables (existence only).

### Why these, specifically

**410.38 is the corpus's centre of gravity.** It is the closest analogue here to a
prior-authorization workflow: a written order with named elements, a timing
requirement, a setting condition and an institutional exclusion — all checkable
against a submission. It also has two usable revisions.

**410.32 and 410.33** supply a different criterion shape: who may order a test,
whether the result informs management, and what supervision applied. Those are the
questions imaging authorisation turns on.

**410.61** contributes documentation-content criteria — a plan that must state four
parameters plus diagnosis and goals — and a second revision pair.

**411.15** is the exclusions layer. It is marked `EXCLUSION_OVERLAY` because it
declares no required criteria and cannot support a standalone decision (§4).

---

## 3. Accessibility status

| Status | Meaning | Count |
|---|---|---|
| `AUTOMATICALLY_ACQUIRED` | Fetched from the official API by `scripts/acquire_ecfr.py` | **8** |
| `MANUALLY_ACQUIRED` | Placed on disk by an operator | 0 |
| `SYNTHETIC` | Written for this project | 0 (retired) |
| `NOT_ACCESSIBLE` | Identified and unobtainable here | NCDs, LCDs — see below |

**CMS NCD/LCD material remains unreachable.** Every CMS property returns 403 at an
Akamai edge, `robots.txt` included, while `healthdata.gov` and `api.fda.gov` answer
normally from the same host: a geographic edge block, not a crawl policy. A search of
all 20,470 HHS catalogue datasets found no NCD or LCD documents — the Coverage
Database is a separate application, not open data.

**Nothing is done to work around it.** No user-agent substitution, no proxy, no
headless browser. The data being public does not make circumventing a geographic
control the right thing to do.

---

## 4. Known limitations

1. **Regulation, not determinations.** 42 CFR is the layer *above* NCDs and LCDs.
   Its criteria are real coverage conditions, but a criterion here is not a coverage
   determination, and documents are typed `REGULATION` so this cannot be blurred.
2. **No code linkage in the source.** A regulation does not enumerate procedure
   codes. `data/linkage/` is a **human-curated engineering artefact** and is
   authoritative for nothing.
3. **411.15 is not decidable alone.** Only exclusions, no required criteria;
   standalone cases drove every decision to the table's totality guard. Marked as an
   overlay — a real, authoritative policy that is still not a basis for a decision.
4. **410.38 rev 2019-01-01 has no transcription.** The section was restructured and
   the 2026 criteria do not locate in it. Refusing to carry them across is correct.
5. **Transcription completeness is unverified.** Span verification proves each
   transcribed criterion is faithful. Nothing checks that the *right* criteria were
   chosen, or that none was missed.
6. **No clinician has reviewed any criterion.**

---

## 5. Reproducing the corpus

```bash
uv run python scripts/acquire_ecfr.py --as-of 2026-08-13 \
    --sections 410.32 410.33 410.38 410.61 411.15
uv run python scripts/acquire_ecfr.py --as-of 2022-01-01 --end-date 2026-08-12 --sections 410.38
uv run python scripts/acquire_ecfr.py --as-of 2019-01-01 --end-date 2026-08-12 --sections 410.61
uv run python scripts/verify_criteria.py
```

The eCFR API serves any date, so the corpus is reproducible from the manifest on any
machine with network access — which is the reproducibility that matters, rather than
pretending every environment has identical reach.
