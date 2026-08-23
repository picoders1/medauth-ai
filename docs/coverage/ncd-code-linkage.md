# NCD Code Linkage

**The CMS Coverage API publishes no procedure-code field for NCDs.** Nineteen
fields, none of them codes — verified by live probe. So an NCD cannot be resolved
from a procedure code unless someone supplies the mapping, and the only someone
available is us.

`data/linkage/ncd_code_links.yaml`. Loaded by `scripts/load_code_links.py`.

---

## Three levels of authority

They are not a quality scale. They are three different **kinds of claim**, and only
the first is a claim about the source rather than about us.

| | means | authoritative | production |
|---|---|---|---|
| `SOURCE_STATED` | the source document states the relationship | **yes** | resolves |
| `HUMAN_CURATED` | a person judged the code falls within the policy's subject matter | no | resolves |
| `ENGINEERING_INFERRED` | the link rests on resemblance rather than a judgement about the text | no | **refused** |

**No link in this corpus is `SOURCE_STATED`, and none can be** from the present
sources. 42 CFR enumerates no procedure codes; the MCIM NCD record carries no code
field. The member exists so that a future source which *does* supply linkage is
distinguishable from the judgement calls made here.

## Why `HUMAN_CURATED` resolves and `ENGINEERING_INFERRED` does not

`admissible_in_production` and `is_authoritative` answer different questions, and
conflating them would break the system in one direction or make it unsafe in the
other.

Refusing `HUMAN_CURATED` as well would leave the corpus with **no resolvable link at
all** — disabling the system rather than making it safer. Admitting
`ENGINEERING_INFERRED` would let applicability rest on similarity, which is
precisely what ADR-004 exists to prevent.

`ResolutionPolicy.admit_engineering_inferred_links` is `False` and must stay false in
production. Evaluation may set it true explicitly — the retrieval sets were authored
against links that predate this distinction — but that is a declared choice in a
versioned policy file, not a default anyone inherits.

## Review status is a separate axis

Verifying a curated link confirms a reading; it does not make the reviewer the
source. So `LinkReviewStatus` (`PENDING · IN_REVIEW · VERIFIED · REJECTED ·
INTERPRETATION_REQUIRED`) is its own column, and `VERIFIED` never appears among
provenance values.

## Current state

| corpus | links | `HUMAN_CURATED` | `ENGINEERING_INFERRED` | `SOURCE_STATED` |
|---|---|---|---|---|
| 42 CFR | 16 | 14 | 2 | 0 |
| NCD | 6 | 4 | 2 | 0 |

All 22 are `PENDING` review.

The two CFR `ENGINEERING_INFERRED` links were recorded in Phase 3 under the older
`evidence_class: INFERRED` vocabulary. The loader **translates** rather than
rewriting the file: `policy_code_links.yaml` records a curation decision made on a
date, and editing its wording now would restate a past judgement in today's terms.

An unrecognised provenance value is **refused**, not defaulted — the default is
admissible, so a typo would otherwise silently promote a refused link into one that
establishes applicability.

## What a link does and does not mean

A link means *"this determination is about this kind of item, so a request for it
should surface this determination for a human to read"*.

It does **not** mean the item is covered. Every acquired NCD currently establishes
`UNKNOWN` (OD-26). **A link makes a determination reachable, not applied.**

## What is deliberately absent

The three undated determinations carry no links: they cannot be temporally resolved
at all, so a link to them could never fire, and adding one would create linkage that
looks like coverage and behaves like nothing.

Two further determinations carry none because their subject matter is coded largely
in CPT, which is AMA-copyrighted and not redistributed here (ADR-003).
