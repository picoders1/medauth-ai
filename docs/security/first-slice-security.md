# First Slice — Security

**Containment is structural. It holds whether or not an injection is detected.**

---

## The threat this system actually has

The firewall classifies the **user's turn**. This is a RAG application whose
untrusted surface is content the user never wrote: a policy chunk that has been
tampered with looks exactly like one that has not.

Its own committed evidence refuses the claim that it protects RAG applications —
indirect-injection recall **0.1423**, planted-content recall **0.0938**. So every
control below is designed to hold at recall zero.

## Four structural properties

**1 · No outcome token reaches the model.** `AssessmentState` has three members. A
successful injection cannot emit an approval because no approval token exists in the
instructions, the evidence block, or the JSON schema. Asserted by test over all three.

**2 · Retrieved text is fenced, framed and neutralised.** One chokepoint,
[evidence_block.py](../../app/adjudication/evidence_block.py). The framing tells the
model what to do with an instruction found inside *before* it meets one. A chunk
containing the fence delimiter has it replaced — replaced rather than rejected,
because refusing the chunk would let anyone who can write to the corpus delete an
inconvenient passage from every future evidence set.

**3 · Span verification, four checks, any failure stops the case.** Quote located
under normalisation · chunk was in **that criterion's** evidence set · stored hash
still matches · chunk belongs to the resolved policy and version. Failures are kept
apart rather than collapsed into "invalid" — a missing quote is a model problem, an
unretrieved chunk is a retrieval problem, a hash mismatch is a corpus-integrity
problem, and one label would send all three to the same wrong fix.

**4 · Per-criterion isolation.** A tampered chunk influences only the criterion that
retrieved it.

## Fail closed means fail toward the human

| | routes to | retried |
|---|---|---|
| `BLOCKED` (403) | `HUMAN_REVIEW` | **never** |
| `DETECTOR_UNAVAILABLE` (503) | `HUMAN_REVIEW` | no |
| `TIMEOUT` / `UNREACHABLE` | `HUMAN_REVIEW` | may re-run |
| `SCHEMA_INVALID` | `HUMAN_REVIEW` | after bounded repair |

Parameterised over the whole enum: **every failure routes to a human, none to a
denial.** A non-retryable failure is asserted to produce exactly **one** call.

That last assertion was strengthened after a mutation exposed it: the original test
checked that the remedy text said "never retried", and a mutation that changed the
prose while leaving a retry loop intact passed it. The test was reading a sentence
rather than counting calls.

## No clinical text in the audit trail

`AuditEvent` carries ids and spans. There is no field a note could be put in, so the
rule is structural rather than a convention. Asserted by searching the serialised
events for note content.

## Ten mutations, each confirmed failing, all restored

```
citation failure no longer stops the case      a tampered chunk is accepted
policy and version checks removed              invented evidence ids are trusted
corpus text can close the fence                evidence merged into instructions
facts with impossible spans are kept           a wrong criterion id is kept
the slice retries a non-retryable failure      retryable/blocked remedies collapse
```

## What is not tested here

No live firewall call. The gateway is a protocol and the slice runs against a
double, so **what is verified is the slice's behaviour given a firewall response**,
not the firewall's behaviour. Those are different claims and only the first is made.
