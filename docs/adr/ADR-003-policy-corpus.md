# ADR-003: CMS Medicare Coverage Database as the Initial Policy Corpus

**Status:** Accepted · **Date:** 2026-08-23 · **Phase:** Planning

## Context

The system needs an authoritative corpus of coverage-policy criteria to reason against. The corpus
determines what can be evaluated, what can be published, and what the architecture must accommodate
in structure, versioning and jurisdiction.

## Problem

Which corpus, and how does the architecture avoid being shaped by it so that a different payer's
policy set can replace it later?

## Options

| # | Option | Assessment |
|---|---|---|
| A | CMS Medicare Coverage Database — NCDs, LCDs, Billing & Coding Articles | Public, authoritative, versioned, jurisdiction-aware, freely usable as US Government work. |
| B | A commercial payer's medical policy | Closer to commercial prior authorization. Copyrighted, not redistributable, often behind login. Results could not be published. |
| C | Synthetic policy documents | Full control over structure and difficulty. Proves nothing about real policy language, which is the hard part. |
| D | Clinical guidelines (specialty societies) | Clinically rich, but they are not coverage criteria. Wrong document class for this task. |

## Decision

**Option A**, with the policy layer built payer-agnostic.

- Corpus: NCDs, LCDs, and the **Billing & Coding Articles attached to LCDs** — the last because much
  of the operative code-level criteria live there rather than in the LCD body.
- Corpus is **downloaded, never committed**. `data/cms/registry.yaml` *is* committed and records per
  document: source URL, type, policy id, retrieval date, content hash, licence note, and
  contamination risk relative to the evaluation corpus.
- Nothing above `policy_documents` / `policy_versions` knows the corpus is CMS. Swapping payers is a
  new loader populating the same schema.

**This is CMS Medicare coverage policy.** It is not, and must never be described as, any commercial
payer's medical policy.

## Rationale

**Authoritative and inspectable.** A reviewer can open the cited source URL and read the same text
the system cited. That is a precondition for the citation contract meaning anything at all.

**It has the properties the architecture must handle anyway**, and which would otherwise have to be
simulated: national versus jurisdictional scope, effective and end dates, revision histories,
superseded versions, and code-level linkage by HCPCS/CPT and ICD-10. Building against a corpus that
genuinely has these avoids discovering them after the schema is fixed.

**It is publishable.** Evaluation reports can quote the policy text they were scored against, which
matters because every number in this project must be traceable to an artefact someone else can read.

**Payer-agnosticism here is real rather than aspirational**, because of ADR-004: applicability is
expressed as rows in `policy_code_links`, not as code. Another payer's applicability rules are
different rows in the same table.

## Licensing

CMS documents are US Government works. **CPT® codes and their descriptors, embedded in those
documents, are copyrighted by the American Medical Association.** Consequences, enforced by
`.gitignore` and by test:

- No CMS document is committed to this repository.
- Code *values* (e.g. `27447`) are stored and may appear in fixtures. CPT descriptor *text* is not
  redistributed here.
- `registry.yaml` carries a licence note per document.

## Consequences

**Positive.** Authoritative, free, publishable, and structurally realistic. Reviewers can verify
citations against the public source. Evaluation is reproducible by anyone holding the registry.

**Negative.** Medicare coverage language differs from commercial prior authorization in tone and
structure, so results do not automatically transfer and no claim is made that they do. CMS layouts
vary, so ingestion must fail loudly on unrecognised structure rather than silently flatten it. The
corpus changes over time, which is why versions are added and never edited (ADR-004).

**Neutral.** Corpus scope is bounded to 5–8 procedures initially (OD-11). This limits generality and
is reported as a denominator, not hidden.

## Rejected alternatives

| Alternative | Rejected because |
|---|---|
| **B — commercial payer policy** | Copyrighted and not redistributable. Results could not be published and the corpus could not be shared with anyone reviewing the work. |
| **C — synthetic policy** | Removes the difficulty that makes the problem interesting. Real policy prose is ambiguous, cross-referential and inconsistently structured; a synthetic corpus would validate a parser against itself. |
| **D — clinical guidelines** | Guidelines state what is clinically indicated; coverage policy states what is covered. Conflating the two is precisely the error this system must not make. |
| **Both CMS and a commercial payer** | Doubles ingestion work before either is validated. The architecture supports it; Phase 1 does not attempt it. |
