# The human-in-the-loop review workflow

**Read model:** `app/case/review_view.py` · **Actions:** `app/case/review.py` ·
**API:** `app/api/v1/routes.py` · **UI:** `app/api/reviewer_ui.py`
**Tests:** `tests/api/test_reviewer_workflow.py` (19) · **Mutations:** 4

---

## 1. The workflow

```
case → engine → HUMAN_REVIEW → reviewer opens it
                                   ↓
                   why it is here · evidence · criteria · citations
                   AI draft · abstention · contradiction · provider state
                                   ↓
        ACCEPT ─────────────────► FINALIZED
        OVERRIDE (rationale) ───► FINALIZED
        REQUEST_INFORMATION ────► NEEDS_INFO
```

A reviewer cannot finalise a case from any state but `HUMAN_REVIEW`. Enforced in the
service, not the route — a route-only check is one a second entry point can miss.

## 2. Three endpoints, not one with an `action` field

Accepting a recommendation and overriding it need different inputs and carry different
authority. A single endpoint would validate *"rationale required unless action ==
ACCEPT"* in prose; here the requirement is the request model's shape.

| endpoint | requires | permission |
|---|---|---|
| `POST …/review/accept` | nothing | `REVIEW_CASE` + `FINALIZE_CASE` |
| `POST …/review/override` | `override_outcome` **and** `rationale` | + `OVERRIDE_RECOMMENDATION` |
| `POST …/review/request-info` | `requested_information` | `REVIEW_CASE` |

**Accept requires no rationale.** Agreeing with a recorded, cited, rule-derived
recommendation adds nothing a later reader lacks. Disagreeing does.

**`request-info` must say what is wanted.** A request with nothing asked returns the
case to the submitter with no way to satisfy it — a loop rather than a workflow.

## 3. Nothing is re-run when a reviewer opens a case

Evidence comes from the audit events the original run emitted. Re-running retrieval
would return **today's** corpus for **yesterday's** decision, under a heading saying
"supporting evidence" — and the failure would be invisible: the citations would verify,
the passages would look relevant, and the reviewer would be judging a different case
from the one the engine decided.

## 4. Why it is here comes before what was proposed

`routing_explanation` turns an abstention reason into a sentence a reviewer can act on,
and the UI renders it **above** the recommendation.

That ordering is an anti-anchoring measure. R-04 (automation bias, High) says the
system's own interface can cause reviewers to rubber-stamp; showing the proposed answer
before the question is how an interface does that. A test asserts the order.

Every routed reason gets a sentence. A reason the table does not know says so, rather
than rendering a bare enum name and letting a reviewer guess.

## 5. Identity, qualification, competence — three things

| concept | question | what MEDAUTH has |
|---|---|---|
| identity | who is this? | a validated OIDC subject — **established** |
| qualification | what are they credentialed to do? | a sentence they typed — **`SELF_ASSERTED`** |
| competence | can they decide *this* case? | **nothing. Not modelled.** |

**A qualification grants nothing.** There is no function mapping one to a permission and
no call site that could pass one — the separation is an absence, asserted structurally
as well as behaviourally. A reviewer stating *"Chief of Radiology, 30 years"* and holding
only `READ_CASE` is refused every review action.

`VERIFIED_BY_REGISTRY` exists in the vocabulary and is **unreachable**: no registry is
integrated. The state is there so the record can distinguish "checked and qualified"
from "nobody checked" if one ever is — and it still would not grant a permission.

**The qualification is optional.** It was required until this phase, inherited from
before OD-43 when it was the only identity there was. A mandatory field that grants
nothing and cannot be verified gets filled with `"n/a"`, and the trail then records
`"n/a"` as though it meant something. `NOT_STATED` is the truthful record of a reviewer
who did not say.

## 6. History is append-only, and a later decision references the earlier one

Every action inserts. `recommended_outcome_at_review` is denormalised onto each row, so
"did this person agree with the engine, and with what" is answerable from that row alone
— immune to anything that later happens to the recommendation table.

Each entry renders its `identity_model`, so a reader can tell a
`LEGACY_CALLER_SUPPLIED` decision (self-declared, pre-OD-43) from an
`AUTHENTICATED_HUMAN` one at a glance.

## 7. Reviewer assignment — deliberately minimal

**Not implemented.** The workflow does not need it: a case in `HUMAN_REVIEW` is
reviewable by any authorised human whose integrator can see it, and that is the honest
description of the current model.

Adding a `CaseAssignment` table with `UNASSIGNED`/`ASSIGNED`/`COMPLETED` before anything
assigns anything would be a schema nobody writes to and a status nobody reads — and the
brief's own instruction ("keep it optional if not necessary") is the right call. When a
real queue needs it, it arrives with the code that uses it.

**There is no default assignee**, hidden or otherwise.

## 8. What this does not establish

- **No clinical validation**, and a reviewer workflow is not one.
- **No verified credentials.** See §5.
- **No enterprise SSO deployed.** A *non-production* Keycloak is now integrated and
  verified end to end with real tokens (`docs/security/nonproduction-idp.md`), which is
  a different claim from a deployed production provider - that one is still refused.
- **No review metrics.** `docs/evaluation/human-review-metrics.md` defines them; none
  can be reported until real review activity exists, and inventing a turnaround time
  would be the fabrication this project refuses.
