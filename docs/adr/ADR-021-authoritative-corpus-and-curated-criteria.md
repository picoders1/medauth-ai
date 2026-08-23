# ADR-021: Authoritative Corpus, Curated Criteria, and the Verification Gate

**Status:** Accepted · **Date:** 2026-08-23 · **Phase:** 2B
**Amends:** [ADR-003](ADR-003-policy-corpus.md) (corpus), [ADR-007](ADR-007-ingest-time-criteria-extraction.md) (criteria extraction)

## Context

ADR-003 chose the CMS Medicare Coverage Database. It is unreachable: every CMS
property returns 403 at an Akamai edge, `robots.txt` included, while other US
government sites answer normally from the same host. A geographic edge block, not a
crawl policy, and not something to be worked around.

ADR-007 decided criteria would be extracted at ingest by a model, human-reviewed
before evaluation use. That was written when the corpus was going to be real. With
a corpus this project authored, model extraction would have completed a closed
loop: we write the policy, a model extracts criteria from it, cases are built from
those criteria, and labels are computed from the cases. Everything agrees with
everything because it all came from one place.

## Problem

Two questions, and the second is the one that matters.

1. Where does authoritative policy text come from, given CMS is unreachable?
2. **How do criteria come to exist without the process being circular or
   unverifiable?**

## Options

### Corpus

| # | Option | Assessment |
|---|---|---|
| A | Keep CMS-shaped fixtures | Everything downstream inherits "not authoritative". No claim survives. |
| B | Obtain NCD/LCD via US egress | Real and the right layer. Requires routing around a geographic control; not this project's call to make unilaterally. |
| C | **42 CFR via the official eCFR API** | Real, public domain, versioned, freely accessible. A *different* layer of the hierarchy. |

### Criteria

| # | Option | Assessment |
|---|---|---|
| D | Model extraction (ADR-007 as written) | Scales. Circular here, and the extraction itself is unverifiable. |
| E | Human transcription, unchecked | Non-circular. Nothing detects drift, a typo, or a misattribution. |
| F | **Human transcription, mechanically span-verified against the source** | Non-circular *and* checkable. Does not scale. |

## Decision

**C and F.**

**Corpus:** 42 CFR Parts 410 and 411, retrieved from the eCFR API. Documents are
typed `REGULATION` - a new document type - because 42 CFR sits *above* NCDs and
LCDs, and labelling a regulation as either would misstate its authority and scope.

**Criteria:** a person reads the regulation and transcribes the operative
requirements into `data/criteria/transcriptions/`, recording for each the
**verbatim authoritative text** and, separately, a normalized interpretation.
`scripts/verify_criteria.py` then locates that verbatim text in the section it
cites, using the same normalizer that verifies citations at runtime.

The gate **fails the pipeline**. It never repairs a span, re-anchors to a nearer
section, or accepts a close match.

**Code linkage** is a third, clearly separated artefact. A regulation states
conditions of payment and enumerates no procedure codes, so
`data/linkage/policy_code_links.yaml` is labelled
`HUMAN_CURATED_ENGINEERING_LINKAGE`, carries a rationale and confidence per entry,
and is authoritative for nothing. Code *existence* is verified against NLM, which
is authoritative for exactly that and nothing more.

## Rationale

**Transcription and verification are different jobs, and both are needed.**
Transcription is a human judgement about which requirements matter - a model cannot
make it credibly and a model making it here would close the loop. Verification is a
mechanical check that the transcription did not drift from the text - a human cannot
make it reliably, and a human making it is exactly the review that gets skipped
under deadline. Splitting them gives each to whichever is actually good at it.

**Verification is genuinely non-vacuous**, which is the point. Four corruption paths
were exercised and all four are refused: text absent from the document, text present
but in a *different* section, a section that does not exist, and a duplicate fact
key. The second is the interesting one - the quote is real, so a human spot-check
passes it.

**It caught a real amendment.** 42 CFR 410.38's criteria were transcribed against
the 2026 revision. Verified against 2022 they hold; against 2019 they **fail**,
because that text was restructured. So the 2019 revision has no transcription and
generates no cases. Carrying criteria across an amendment without re-verifying would
silently attribute requirements to a text that never contained them - and nothing
downstream would have noticed.

**Keeping the interpretation beside the authoritative text, never instead of it**,
matters more than it looks. A normalized reading is what a reviewer will actually
read. If it ever stood in for the regulation, the interpretation would quietly
become the policy, and the citation would point at text nobody consulted.

## Consequences

**Positive.** The first link of the credibility chain is authoritative. Temporal
versioning is real amendment history rather than constructed pairs. Every criterion
carries section, page, character span and document hash. Curated artefacts are
labelled as curated and asserted so by test.

**Negative.** Transcription does not scale - 33 criteria took a person, and a full
corpus would take many. 42 CFR is the wrong *layer*: procedure-level coverage
criteria and real code linkage live in NCDs and LCDs, which remain unreachable
(OD-20). Code linkage is now an artefact requiring its own review that a real LCD
would have supplied for free.

**Neutral, and the largest remaining gap.** Verification proves each transcription
is **faithful**. It says nothing about **completeness** - whether the material
requirements were chosen, or whether any was missed - and a non-clinician chose
them. That is recorded as R-50 and OD-19, and only review by someone qualified to
read coverage regulation resolves it.

## Rejected alternatives

| Alternative | Rejected because |
|---|---|
| **A - keep fixtures** | Nothing downstream could be claimed. Real text was obtainable, so this was a choice not to look. |
| **B - NCD/LCD via US egress** | The right layer, and it means routing around a geographic access control. That is the operator's decision, not something to build in. Recorded as OD-20. |
| **D - model extraction** | Closes the loop: the same system authoring the policy would author the criteria and then be evaluated against them. Also unverifiable - there is nothing to check an extraction against except the extractor. |
| **E - unchecked transcription** | Indistinguishable from invention after the fact. A criterion whose source cannot be located is exactly as good as one that was made up. |
| Inferring code linkage from semantic similarity | Would make "this policy applies" a similarity judgement - the specific failure ADR-004 exists to prevent. |
