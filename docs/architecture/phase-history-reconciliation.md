# Phase history, reconciled

**One canonical chronology.** Historical reports are *not* renamed — renaming them would
break every cross-reference in the ADRs, the risk register and the commit messages, and
a traceability chain that has to be re-derived is worse than a mapping table.

---

## 1. Why the numbering is confused

Four separate causes, none of them a mistake anybody made twice:

**Briefs restarted numbering.** More than one work request arrived labelled "Phase 16"
or "Phase 17" describing work the repository had already delivered under those numbers.
The label a request carries is not evidence about the repository's own history.

**Some commits carry several phases.** `1015216` is "Phases 13-15"; `fe394d9` squashed
five (5–9) into one. A regression inside either cannot be bisected to a phase, and the
roadmap already says so.

**Some phases carry no commit of their own.** Phase 1's artefacts landed inside
`41a9ac2`, which is Phase 2B's commit.

**Several tracks were never numbered at all.** The closure audit, the R-86 attribution
work, the parallel engineering track and the application layer are substantial, are
committed, and have no phase number — because they were responses to findings rather
than planned phases.

## 2. The canonical chronology

`FORMAL` = a planned phase with exit criteria. `EMERGENT` = a track that exists because
something was found.

| canonical id | title | commit(s) | kind | status |
|---|---|---|---|---|
| P0 | Foundation | — | FORMAL | Complete |
| P1 | Policy corpus & RAG | `41a9ac2` (inside P2B) | FORMAL | Complete |
| P2B | Data foundation | `41a9ac2` | FORMAL | Complete — P2A never existed separately |
| P3 | Ground-truth authority | `17434a6` | FORMAL | Complete |
| P4 | Policy logic + retrieval eval | `04c0657` | FORMAL | Complete |
| P5–P9 | Fail-closed semantics → slice contracts | `fe394d9` | FORMAL | Complete — five phases, one commit |
| P10 | Reviewer-packet hardening | `987080e` | FORMAL | Complete |
| E-1 | External decision (FOCUS-001) | `e814e61`, `4d9630a` | EMERGENT | Complete |
| E-2 | OD-19 / 410.33 logic declared | `8fbc46a`, `4e61b74` | EMERGENT | Complete |
| P11 | First AI vertical slice | `3c921a9` | FORMAL | Complete — **zero model calls** |
| E-3 | Pre-P12 remediation | `bf8ba18` | EMERGENT | Complete |
| P12 | Real model activation | `9c2f424` | FORMAL | **IN PROGRESS** — acceptance criteria deliberately not all attempted |
| P13–P15 | Guardrail closure → applicability resolution | `1015216` | FORMAL | Complete — **R-93 resolved** |
| P16 | Measurement recovery | `41dd237` | FORMAL | Complete — gold_v2, retrieval_v4, `phase16-evaluation-001` frozen and **not run** |
| P17 | Provider-gate closure attempt | `ba06f71` | FORMAL | Complete; **the gate did not open** |
| P18 | R-86 handoff + evaluation hold | `01d624f` | FORMAL | Complete |
| P19 | Freeze verification | `ded0e9b` | FORMAL | Complete |
| E-4 | Final engineering closure audit | `fa799c4` | EMERGENT | Complete — found R-103, R-104, R-105 |
| E-5 | R-86 provider-side attribution | `778aca5` | EMERGENT | Complete — found R-106 |
| E-6 | R-86 root-cause narrowing | `67dac1c` | EMERGENT | Complete — hypotheses narrowed, none selected |
| E-7 | Sendable escalation package | `5976178` | EMERGENT | Complete |
| E-8 | Parallel engineering track (audit schema) | `2aaa19b` | EMERGENT | Complete |
| E-9 | Application runtime layer | `4d66c07` | EMERGENT | Complete |
| E-10 | Application lifecycle closure | `d8dd3a8` | EMERGENT | Complete |
| E-11 | R-86 disposition + this reconciliation | *this commit* | EMERGENT | Complete |

Predecessor/successor is the table's own order; every row's predecessor is the row above
it, because the repository has a linear history with no merges.

## 3. Numbers that mean two things — read carefully

| the label | the repository's meaning | what a later brief also called it |
|---|---|---|
| **Phase 15** | applicability resolution, R-93 resolved (`1015216`) | a re-request for the same work |
| **Phase 16** | measurement recovery, gold_v2 (`41dd237`) | a re-request for slice revalidation |
| **Phase 17** | provider-gate closure attempt (`ba06f71`) | a re-request for R-86 disposition |
| **Phase 20–23** | *no repository phase exists* | several briefs; all stopped at the R-86 gate without spending budget |

**Briefs labelled Phase 20 and later produced no numbered phase** because each one
correctly stopped at the R-86 gate before spending anything. Their outputs are the
`E-*` tracks above, which is where the work actually went.

## 4. Historical reports are preserved as-is

`docs/architecture/phase12-model-activation.md`, `docs/evaluation/phase16-*.md`,
`docs/evaluation/r86-gate-recheck.md` and the rest keep their names and their contents.
They are records of what was believed and measured **at the time**, and this document is
the index onto them — not a replacement for them.

The same principle as the sealed reproducer: a record that gets rewritten whenever the
world moves is a document about today rather than evidence about a moment.
