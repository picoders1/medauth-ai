# Dataset Card — MEDAUTH Data Foundation

**Version:** 2 · **Date:** 2026-08-23
**Provenance:** authoritative policy · curated criteria · synthetic cases

---

## Purpose

To evaluate an evidence-grounded prior-authorization decision-support system at the
level its architecture operates on: policy resolution, evidence retrieval,
criterion-level adjudication, decision derivation, citation grounding and
abstention - each measured separately, so a failure can be attributed rather than
averaged away.

It exists so that a later agentic system is measured against a stable, inspectable
ground truth instead of against examples chosen after the fact.

---

## Composition

| Artefact | Count | Location |
|---|---|---|
| Policy documents | 6 | `tests/fixtures/cms/` |
| Policy versions with criteria | 5 | — |
| Criteria | 27 | `data/criteria/inventory.jsonl` |
| Synthetic authorization cases | 210 | `data/synthetic/cases/cases.jsonl` |
| Gold cases (frozen) | 155 | `data/gold/cases/gold_v1.jsonl` |
| Development cases | 40 | `data/synthetic/cases/development.jsonl` |
| Validation cases | 15 | `data/synthetic/cases/validation.jsonl` |
| Retrieval queries | 21 | `eval/datasets/retrieval/questions.yaml` |

---

## Sources and provenance — five categories, never blurred

Each artefact belongs to exactly one. Conflating them is how a project ends up
claiming authority it does not have.

### 1. Authoritative source data — eCFR

**42 CFR (Code of Federal Regulations, Title 42)**, retrieved from the
[eCFR API](https://www.ecfr.gov/) published by the Office of the Federal Register.

| | |
|---|---|
| Authority | **Authoritative.** US federal regulation |
| Licence | Public domain (US Government work) |
| Versioning | Real amendment history; any date retrievable |
| Retrieved | 2026-08-23 |
| Coverage | 5 sections, 8 documents, 3 revision dates |

**What it is not:** an NCD or an LCD. 42 CFR sits *above* those in the coverage
hierarchy — statute, then regulation, then national determinations, then local ones.
Documents are typed `REGULATION` so the distinction survives into the data.

CMS's Medicare Coverage Database, which holds NCDs and LCDs, is **unreachable** from
this network: every CMS property returns 403 at an Akamai edge, `robots.txt`
included, while other US government sites answer normally. A geographic edge block,
not a crawl policy. Nothing was done to work around it.

### 2. Reference code data — NLM Clinical Tables

**HCPCS Level II** and **ICD-10-CM** metadata from the
[NLM Clinical Tables API](https://clinicaltables.nlm.nih.gov/).

| | |
|---|---|
| Authoritative for | Code **existence and description**, and nothing else |
| **Not** authoritative for | Whether any code is covered by any policy |

The copyright boundary is enforced by the source rather than by this project: HCPCS
Level II codes are CMS-maintained and public domain and the API returns their
descriptors; AMA-copyrighted CPT codes are simply **absent** from it, so a CPT
descriptor cannot be redistributed here even by accident (ADR-003).

### 3. Human-curated engineering mappings

`data/linkage/policy_code_links.yaml` and the criterion transcriptions in
`data/criteria/transcriptions/`.

| | |
|---|---|
| Authority | **None.** Engineering judgement |
| Curator | Software engineer — **not a clinician, not a certified coder** |
| Labelled | `HUMAN_CURATED_ENGINEERING_LINKAGE`, asserted by test |

A regulation states conditions of payment; it does not enumerate procedure codes the
way a determination does. The code mapping exists so deterministic resolution has
something to resolve on, and every link records a rationale and a confidence —
including entries marked `low`, which exist deliberately so the corpus contains
linkage the system should be sceptical of.

Criterion transcriptions are also curated, but with one mechanical guarantee the
code mapping does not have: every transcribed criterion is **span-verified against
the authoritative text**, and a transcription that does not locate is refused.
Verification proves the transcription is faithful. It does not prove the criterion
set is complete or the interpretation clinically correct.

### 4. Synthetic patient data

Cases in `data/synthetic/` and `data/gold/`. Generated from a pinned seed
(`20260823`), constructed **from criteria** rather than from patients.

| | |
|---|---|
| Real patient data used | **None.** None was available to this project |
| Provenance | `synthetic`, carried on every record |
| Reproducible | Byte-identical from the same seed and corpus |

**Synthea was evaluated and not used** (OD-17). It generates patients first, which
reverses the required policy-to-case order; its FHIR output carries none of the
decision-relevant facts; and what it would contribute is exactly the demographics
that must not affect the outcome. Patient records are therefore deliberately thin —
age, sex, and a synthetic flag.

### 5. Potential future real de-identified clinical text

**MIMIC-IV-Note is NOT present, NOT downloaded, and NOT accessible to this
project.** No PhysioNet credentialing has been completed and no Data Use Agreement
has been signed.

It is documented as a *candidate* in
[mimic-readiness.md](mimic-readiness.md), including the obligations that would apply
and the redistribution question that must be resolved before any real note could
reach a third-party model endpoint. Were it ever acquired, it would carry the
dataset class `REAL_DEIDENTIFIED` and would never be merged with synthetic records.

## Generation methodology

```
policy -> criteria (span-verified) -> case template -> synthetic facts
       -> clinical note -> criterion states -> expected decision
```

Criteria are **declared** in each policy document with a section anchor and the
exact source text, and ingestion verifies that text occurs in that section using the
same normalizer that verifies citations. A declaration that cannot be located is
rejected at parse time. No model invents criteria.

Everything derives from seed `20260823`. The same seed and corpus rebuild both
artefacts byte-for-byte.

---

## Labelling methodology

Criterion-level labels are **primary**; the case-level decision is derived from them
by `app.decision.table.decide` - the same function the system uses. A test recomputes
every stored decision from its criterion states, so the two levels cannot disagree.

**No human labelled any case.** No clinician has reviewed any case, criterion or
label. See [gold-set-labeling-protocol.md](../evaluation/gold-set-labeling-protocol.md).

---

## Intended use

Measuring MEDAUTH's mechanisms: does it resolve the right policy version for a date
of service, retrieve the section that answers a query, adjudicate criteria against a
stated pattern, derive the decision the policy's own logic implies, and decline when
evidence is absent.

## Out-of-scope use

- Any claim about clinical accuracy or real-world performance
- Training a model
- Evidence that the system is safe to deploy
- Any statement beginning "clinically validated"

---

## Limitations

1. **Not authoritative.** The defining limitation; everything else follows from it.
2. **Constructed cases are cleaner than real submissions.** Each fact appears once,
   unambiguously, in the section a reader expects. Measured performance is an
   **upper bound**, and the claim that it transfers is refused.
3. **Small.** 27 criteria, 5 policy versions, 155 gold cases. At these denominators
   a 95% Wilson interval on a rate near 0.9 spans roughly 10 percentage points, and
   per-category intervals are far wider.
4. **Single labeller, and it is a program.** Inter-annotator agreement was **not
   measured** - there is nothing to measure it between. It is not reported as
   pending; it does not exist.
5. **Self-consistent by construction.** The same author wrote the policies, declared
   the criteria and built the cases. Internal consistency is guaranteed and is
   therefore not evidence of anything.
6. **One jurisdiction (J6).** Cross-jurisdiction behaviour is tested against
   synthetic negatives only.
7. **Billing & Coding Articles are unreachable by resolution** (OD-15). Affected
   queries are excluded from the denominator with the reason recorded.

## Known biases

- Category proportions were chosen by the generator plan, not observed from real
  authorization traffic. The real-world mix is unknown to this project.
- `NEEDS_INFO` is over-represented relative to a plausible real distribution. That
  is deliberate - it is a first-class outcome and the hardest to get right - but it
  means aggregate accuracy is not comparable to any external figure.
- Clinical vocabulary comes from one author, so lexical variety is far below real
  clinical documentation. Retrieval results benefit from this.

## Known gaps

- No real CMS document (R-33)
- No clinician review
- No inter-annotator agreement
- No real-note evaluation, and none planned
- Articles unreachable by resolution (OD-15)

---

## Privacy

Every record is synthetic and generated from a seed. No real patient data was used
at any point, and none was available to this project.

Automated checks assert the absence of SSN, email, phone, MRN and date-of-birth
patterns across the entire corpus, and that patient records carry nothing beyond
age, sex and a synthetic flag. These run whether or not they can currently fail:
the controls must be correct for a real deployment, and building the habit on
synthetic data is how they survive into one.

No compliance claim is made. The system is designed with healthcare privacy and
security considerations and evaluated exclusively using synthetic patient data.

---

## Versioning

| Dataset | Version | Hash recorded in |
|---|---|---|
| Criteria inventory | 1 | `data/synthetic/manifests/cases.manifest.json` |
| Case corpus | 1 (schema 1, seed 20260823) | same |
| Gold set | 1 (frozen) | `data/gold/manifests/gold_v1.manifest.json` |
| Retrieval set | 2 | in-file |
| Case templates | 1 | in-file |

Every evaluation report must cite the versions and hashes it used. A report whose
hashes no longer match describes a dataset that no longer exists.
