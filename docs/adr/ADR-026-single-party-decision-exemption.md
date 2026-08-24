# ADR-026 — Single-Party Acceptance of a Domain Decision, Recorded

**Status:** Accepted (2026-08-24)
**Amends:** ADR-025 (slice admissibility). **Resolves:** OD-29.
**Weakens, deliberately and visibly:** the separation-of-duties control introduced
in Phase 8.

---

## Context

FOCUS-001 requires two acts by two people: a reviewer submits a decision, and a
second, differently-named person accepts it. `accept_decision()` refuses an
acceptance recorded by the identity that submitted it.

That rule was written for a system with a reviewer pool. **This project does not
have one.** It is a single-author portfolio system evaluated exclusively on
synthetic patient data, with no clinical use and no second reviewer to call on. The
rule is therefore not protecting a decision from a colluding pair; it is preventing
the only available person from recording an answer at all.

Three responses were available, and only one of them is honest.

**Wait for a second person.** Legitimate, and it stops the project indefinitely on a
control that is not defending against anything present here.

**Route around it** — a `--force` flag, a second identity invented for the purpose,
a hand-edited record. Each produces a record that *looks* two-party. This is the
outcome the whole gate exists to prevent, and it would be worse than never having
built the control, because the record would now assert something false.

**Relax it, narrowly, and say so in the record.** A control that is deliberately
relaxed and visibly marked is weaker than a control that holds. It is much stronger
than a control that was quietly bypassed, because every downstream reader can see
exactly what was and was not checked.

## Decision

### 1. Single-party acceptance is permitted, and is never the default

`accept_decision()` continues to refuse same-identity acceptance **unless** the
acceptance payload carries all three of:

| field | why |
|---|---|
| `single_party_acceptance: true` | explicit opt-in. The exemption is never inferred from the identities matching — that inference is exactly how a control erodes |
| `single_party_authority: "ADR-026"` | the amendment that permits it, checked against a constant. An invented or mistyped authority is refused, so the exemption cannot be claimed on an ADR that does not say this |
| `single_party_justification` | ≥ 12 words stating why no second party is available. A later reader must be able to judge whether the circumstance still holds |

Any one missing ⇒ the original refusal, unchanged.

### 2. The relaxation is recorded on the decision itself, permanently

`DecisionGate` gains:

```python
class SeparationOfDuties(StrEnum):
    TWO_PARTY = "TWO_PARTY"  # the default
    SINGLE_PARTY_EXEMPTED = "SINGLE_PARTY_EXEMPTED"  # ADR-026
```

`TWO_PARTY` is the default and the enum has no third member. A gate whose
`accepted_by` equals its reviewer while still claiming `TWO_PARTY` is **refused at
construction** — the marker cannot be dropped to make the record look stronger than
it is.

The justification is appended to the gate's `notes`, so the reason travels with the
decision rather than living only in this document.

### 3. Nothing else changes

The production gate, the admissibility conditions and every other refusal are
untouched. A single-party acceptance still requires a valid decision, a rationale, a
cited packet, `accepted_at >= submitted_at`, and a `SUBMITTED` gate to accept. The
exemption removes exactly one check and marks that it did.

## Consequences

**The decision record carries a visible weaker-control marker.** Anyone reading it
sees `separation_of_duties: SINGLE_PARTY_EXEMPTED` beside the answer. That is the
point: the marker is the cost, and paying it in the open is what makes the exemption
acceptable.

**This does not scale to real use.** If MEDAUTH ever adjudicates a real
authorization request, `SINGLE_PARTY_EXEMPTED` must not appear on any decision
governing it. This ADR is scoped to a synthetic-data portfolio system and says so;
extending it would need a new ADR that argues the case on its own facts, not an
appeal to this one.

**The claim ledger changes.** *"FOCUS-001 was accepted under separation of duties"*
becomes refused for any decision carrying the marker. The permitted claim is
narrower and true: *a qualified reviewer's decision was recorded, and the
independent-acceptance control was deliberately exempted under ADR-026.*

**A test asserts the exemption cannot widen.** It is available only where an
explicit opt-in, this ADR by name, and a written justification are all present, and
only on the acceptance step. It is not a general same-identity permission.

## Alternatives rejected

**A `--force` flag or a config setting.** Both make the exemption reachable without
saying why, and neither leaves a trace on the decision. A flag is not an amendment.

**Silently permitting it when the reviewer pool is size one.** The system cannot
know the pool size, and inferring the exemption from circumstances is how a control
becomes decorative.

**A second identity created for the purpose.** This is the failure mode, not an
alternative. It produces a record asserting an independent acceptance that did not
happen — a fabricated attribution in the one artefact whose entire value is
attribution.
