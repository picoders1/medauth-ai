# R-86 — remediation classes, and what does not count

**Closure is defined in** [../evaluation/r86-closure-gate.md](../evaluation/r86-closure-gate.md).
This document is about what kind of change could satisfy it — none of which is
implemented here, and none of which MEDAUTH can perform.

---

## 1. Remediations that could close R-86

All provider-side. Listed as classes, not as recommendations — MEDAUTH has no basis to
prefer one, and [r86-provider-root-cause.md](r86-provider-root-cause.md) deliberately
selects no hypothesis.

| class | what it would change |
|---|---|
| **decoder / runtime fix** | the serving stack stops generating past a structurally complete state |
| **grammar termination fix** | the grammar stops admitting whitespace once the document is complete |
| **EOS handling fix** | EOS becomes reachable after the schema is satisfied |
| **model-runtime change** | the same model on a runtime whose constrained path terminates |
| **constrained-decoding implementation change** | a different implementation of the same contract |
| **provider configuration correction** | a setting on the existing stack, changed to a terminating one |

Any of these keeps the **registered request shape** intact, which is what makes them
candidates for closure rather than for a new experiment. The reproducer re-runs
unchanged and either passes or does not.

## 2. What is *not* a fix to this configuration

If the provider's answer is:

- use a **different model**
- use a **different schema**
- use a **different API mode** (`tool_call`, `json_object`, unconstrained)
- use a **different runtime**

then R-86 is **not closed**. The defect in the registered configuration is exactly as
present as it was; a different configuration has merely been proposed alongside it.

That is not a refusal to adopt the advice — it may well be the right engineering
answer. It is a statement about what may be recorded. Such a change is:

```
NEW_SYSTEM_CONFIGURATION
```

and it requires, before anything is scored:

1. a **new configuration digest**;
2. a **new experiment identity**;
3. a **new pre-registration** — hypothesis, success criteria with denominators and
   direction, failure modes, in advance;
4. a **new baseline**.

**The existing experiment is not overwritten.** `phase16-evaluation-001`, its frozen
manifest and its `AUTHORISATION.json` stay exactly as they are. An experiment quietly
re-pointed at a different system is the most expensive kind of wrong number, because
everything about it looks correct except what it is about.

R-86 in that world stays open against the configuration it was raised against, with a
note that the deployment moved away from it. A defect does not stop existing because
something else is now in use.

## 3. What is not a fix at all (Part H)

None of these may be implemented as a response to R-86:

- whitespace stripping to manufacture validity
- forced JSON repair
- repeated retries until success
- completion-limit increases
- schema simplification solely to bypass R-86
- prompt shortening
- clinical-note truncation

Each makes the symptom go away while the provider path still fails to terminate. Two
of them are worse than cosmetic: **retry-until-success** turns a deterministic 100%
failure into a latency-and-cost multiplier that reports as healthy, and **clinical-note
truncation** discards patient evidence to make a decoder finish — a clinical safety
change dressed as an engineering workaround.

Any of them may be investigated later as a separate, **pre-registered containment
experiment**, with its own manifest and its own claim. Containment and closure are
different things:

> **Containment** limits what the failure costs us. **Closure** means the failure is
> gone. R-86 is already contained — every occurrence fails to a human and never to a
> recommendation. It is not closed, and containment must never be reported as though
> it were.

The closure rule is written so these cannot pass: conditions 3 and 4 are about the
provider's generation, not about what we can salvage from it afterwards.

## 4. Evidence a remediation must arrive with

Not a message saying it is fixed. The revalidation runs against the live path, so what
is needed is only that the path has actually changed:

- **what changed**, in the classes of §1, and on which component;
- **whether the registered request shape is untouched** — if not, §2 applies;
- **when it was deployed**, so the revalidation runs against the fixed path and not
  ahead of it.

Then, and only then:

```bash
MEDAUTH_LIVE_MODEL=1 uv run python scripts/r86_revalidate.py --write
```

The runner re-verifies the live configuration against the seal field by field before
it makes a single call, so a fix that also moved the model, the schema, the ceiling or
the temperature is reported as `INCONCLUSIVE` — configuration drift — rather than
being scored as a pass.
