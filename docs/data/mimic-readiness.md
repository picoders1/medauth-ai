# MIMIC-IV-Note Readiness

**Status: NOT ACCESSED. No MIMIC data is present in this repository, and none has
been requested.** This document exists so that the decision to use it is made
deliberately, with its obligations understood in advance.

---

## 1. Why real clinical text matters here

Every clinical note in this project is constructed. That is not a small caveat.

A constructed note states each fact once, unambiguously, in a section a reader
expects. Realism has been added deliberately - facts reordered across headed
sections, clinically plausible distractors interleaved, one fact restated in
different words - but that is *controlled* messiness, generated from a seed, and it
cannot simulate what real documentation does:

| Real submissions | Constructed cases |
|---|---|
| The same fact stated twice with different values | One value, stated once |
| Relevant detail buried in an unrelated section | Deliberate misplacement only |
| Hedged language ("possible", "cannot exclude") | Definite statements |
| Copy-forward text years out of date | No history |
| Abbreviations, typos, dictation artefacts | Abbreviations in distractors only |
| Facts implied but never stated | Explicit or absent |

The last row is the one that matters most. Constructed `UNKNOWN` is a clean
omission. Real `UNKNOWN` is a note that *gestures* at a fact without documenting it,
and distinguishing those is the actual difficulty of medical-necessity review.

**Consequence:** measured performance on constructed cases is an **upper bound**,
and the claim that it transfers to real documentation is refused (R-22, R-38).

---

## 2. MIMIC-IV-Note as a candidate

[MIMIC-IV-Note](https://physionet.org/content/mimic-iv-note/2.2/) (PhysioNet) is
the strongest candidate reachable from this project: real de-identified discharge
summaries and radiology reports from a single US academic centre.

It is a candidate, not a plan. Its fit is partial, and the gaps are recorded in §6.

---

## 3. Access requirements - none of which are satisfied

| Requirement | Status |
|---|---|
| PhysioNet account | not created |
| CITI "Data or Specimens Only Research" training, completed and current | **not completed** |
| Credentialed status granted by PhysioNet | **not held** |
| Data Use Agreement signed for this specific dataset | **not signed** |
| Reference/supervisor attestation | not provided |

Credentialing is a review by people, not a form: it takes days to weeks, and it can
be declined.

### What must not happen

- **No download, no mirror, no cached copy** before credentialing completes.
- **No third-party re-host.** Copies appearing on model hubs or in scraped corpora
  do not carry the DUA, and using one would breach the agreement the data is
  released under regardless of how it was obtained.
- **No claim that MIMIC "is available"** to this project. It is not.
- **No re-identification attempt**, including "just checking" whether a record
  matches a public source. The DUA prohibits it and so does this project.
- **No redistribution** of MIMIC text through this repository, its artefacts, its
  reports, or any prompt sent to a third-party model endpoint.

That last point has teeth here: MEDAUTH sends clinical text to a model through the
LLM Firewall to an external provider. **Sending MIMIC text to a third-party API is
redistribution** and is not permitted under the DUA without separate consideration
of where that endpoint runs and what it retains. Resolving that is a precondition,
not a detail - see §5.

---

## 4. Intended use, if access is ever granted

Narrow and stated in advance, so scope cannot drift after the fact:

1. **Realism calibration.** Measure how far constructed notes differ from real ones
   - length, section structure, redundancy, hedging - and use the difference to
   improve the generator. No MIMIC text enters a case.
2. **A held-out realism check.** A small number of cases whose *note* is real text
   annotated against existing criteria, used once to test whether performance on
   constructed notes overstates performance on real ones.

**Not** intended for: training, fine-tuning, prompt libraries, few-shot examples, or
any artefact that leaves this repository.

---

## 5. Integration boundary (designed, not built)

```
  MIMIC-IV-Note (PhysioNet, credentialed)
        |
        v  authorised acquisition        credentials outside the repo; nothing cached
  data/clinical/real/                    GITIGNORED, never committed, never in a report
        |
        v  de-identification verification  scan for identifier patterns; refuse on any hit
        |
        v  normalisation                  section detection, whitespace, encoding
        |
        v  ClinicalNote                   SAME representation as a synthetic note
        |
        v  dataset class: REAL_DEIDENTIFIED   never merged with SYNTHETIC
```

Two boundaries are load-bearing:

**Dataset classes never merge.** A record is `SYNTHETIC` or `REAL_DEIDENTIFIED`,
carried on every case and into every report. A mixed corpus reported as one number
would make it impossible to say afterwards which result came from which - and the
two have completely different standing.

**The model path is a redistribution boundary.** Before any real note reaches
`app/llm`, this project must establish whether the configured endpoint retains
prompts and whether the DUA permits sending text to it. Until then, real notes may
be used for *measurement about the corpus* but not sent to a model. The
architecture already isolates that decision to one place, which is why it can be
gated rather than audited after the fact.

De-identification verification runs even though MIMIC is already de-identified.
Trusting an upstream claim is not the same as checking it, and the check costs
nothing.

---

## 6. Limitations that would remain even with access

1. **Not prior-authorization submissions.** MIMIC holds discharge summaries and
   radiology reports. A PA packet is a different document with different content and
   a different purpose. Real *notes* would not make the cases real *submissions*.
2. **One institution.** Documentation practice is highly local.
3. **Labels would still be ours.** Criterion states would be annotated against the
   same criteria by the same non-clinician. Real text does not confer clinical
   validation on the labels.
4. **Population mismatch.** MIMIC is heavily critical-care; this corpus concerns
   DMEPOS, outpatient imaging and rehabilitation.

**What real notes would fix:** whether the system degrades on realistic prose.
**What they would not fix:** whether its clinical judgements are correct.

---

## 7. Current position

Documentation stops here, as it should. The synthetic corpus is the working dataset,
its ceiling is recorded, and nothing in the pipeline assumes real text will arrive.

If credentialing is completed, the next step is §5's ingestion boundary and the
redistribution question - **not** dropping MIMIC text into the existing dataset.
