# ADR-020: Reviewer Console — Next.js

**Status:** Accepted · **Date:** 2026-08-23 · **Phase:** Planning

## Context

Reviewers must inspect a case in full: the note with fact spans highlighted, resolved policy
versions with the reason they resolved, the criteria tree with per-criterion verdicts, each citation
as an exact quote highlighted inside its stored chunk, guardrail results, and the recommendation
with the decision-table row that fired.

This is a dense, stateful, cross-referencing interface. Its design directly affects whether human
oversight is real (ADR-012, T-26).

## Problem

Which rendering technology, given that the interface is the mechanism by which the safety property
"a human decides" either holds or does not?

## Options

| # | Option | Assessment |
|---|---|---|
| A | Streamlit | Fastest to a working reviewer flow. Weak for dense cross-referenced layouts, auth and routing; a heavy Python runtime dependency; re-runs the script on interaction. |
| B | Vanilla HTML/CSS/JS, no build step | No npm surface, no build. Consistent with the sibling project's console. Substantial hand-written code for highlighting and linked state. |
| C | **Next.js** | Best fit for the interaction model; strong client state; typed API contract. Adds Node toolchain and npm supply-chain surface. |

## Decision

**Option C — Next.js**, in `ui/`, built and served from its own container on **:3100**.

Constraints, enforced by test and by CI:

- **Renders only backend data.** No hard-coded metric, no placeholder value in the frontend source —
  asserted per file, including the classic placeholder numbers.
- **No runtime CDN.** All assets bundled; the CSP forbids external origins.
- **Lockfile committed**; `npm audit` in CI.
- **Reviewer identity is derived server-side**, never asserted by the client (ADR-012).
- **Null is never rendered as zero.** A missing latency or absent score displays as "no data", not
  `0` — a false zero in a clinical review interface is a wrong fact, not a formatting issue.
- Evidence renders **before** the recommendation, in the order given by ADR-012.

## Rationale

**The interaction model is the deciding factor.** A reviewer needs to click a criterion and see its
citations highlight inside the policy chunk; click a fact and see it highlight in the note; compare
two policy versions. That is linked client-side state across several panels. Streamlit's re-run
model fights this directly, and vanilla JS means hand-writing the highlighting, span mapping and
selection state that a component model provides.

**The UI is a safety surface, not a demo.** Automation bias (T-26, R-04) is a real harm this
system's own interface can cause. Mitigating it needs deliberate control over ordering, prominence
and framing — `NEEDS_INFO` and `NO_DECISION` rendered as prominently as decisions, denial framed as
a draft rationale. Streamlit's layout model does not give that control; hand-written HTML gives it
at high cost.

**Divergence from the sibling project is deliberate.** That console is six read-only views over
audit rows — vanilla HTML/CSS/JS with no build step is exactly right there, and its ADR-022 says so.
MEDAUTH's console is an interactive review workstation. Same reasoning, different requirements,
different answer. Copying the choice rather than the reasoning would be cargo-culting.

**The npm supply chain is the real cost**, and it is accepted with mitigations rather than waved
past: committed lockfile, `npm audit` in CI, no runtime CDN, and a UI that holds no secrets and
makes no decisions — it renders backend data and posts reviewer actions.

## Consequences

**Positive.** The interface can be built to actually support careful review rather than merely
display results. Typed API contract between console and backend. Independent deployment and scaling.
Strong control over ordering and prominence, which is a safety property here.

**Negative.** Node toolchain, build step and an npm dependency surface in a healthcare project
(R-31). A second language and test framework. More work than Streamlit for the same first
functionality. A separate container and its own security scanning.

**Neutral.** Server-side rendering versus client-side is deferred to Phase 7; either satisfies the
constraints above.

## Rejected alternatives

| Alternative | Rejected because |
|---|---|
| **A — Streamlit** | Fastest to a demo, and this is not a demo. The re-run model fights linked cross-panel state, and layout control is too weak for the ordering and prominence decisions that mitigate automation bias. |
| **B — vanilla, no build step** | Right for the sibling project's read-only console; here it means hand-writing span highlighting, linked selection and diffing — the exact work a component model removes. Reconsidered if npm surface proves unacceptable. |
| **Server-rendered templates (Jinja)** | No build step, but every interaction becomes a round trip; evidence exploration would be slow enough to discourage the careful review the design depends on. |
| **A component library with heavy theming** | Deferred. The requirement is clarity and control, not visual polish. |
