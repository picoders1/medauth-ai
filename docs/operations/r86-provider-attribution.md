# R-86 — provider-side attribution

**Artefact:** `data/escalations/r86-provider-attribution.json`
(`r86-provider-attribution-001`)
**Evidence:** [r86-firewall-capture.md](r86-firewall-capture.md) ·
`data/escalations/r86-firewall-capture.json`

```
status                 VERIFIED_FAILURE
attribution            PROVIDER_SIDE
firewall_hypothesis    RULED_OUT_BY_UPSTREAM_CAPTURE
provider_component     UNKNOWN
resolution             UNRESOLVED
official_evaluation    BLOCKED
```

**Nothing here is a fix, and nothing here lifts anything.** Attribution says where to
look. The production cell still fails 6/6, the gate still reads 6/12 = 0.5000 against
the pre-registered ceiling of 0.10.

---

## 1. What is established

One claim, and it is narrow:

> The provider response observed **upstream** of the proxy is identical, in every
> measured characteristic, to the provider response observed by MEDAUTH
> **downstream** of it.

| | firewall side | MEDAUTH side |
|---|---|---|
| production response | `output_chars` **2389** | `body_chars` **2389** |
| production request | `input_chars` **1058** | `payload_chars` **1058** |
| control response | `output_chars` **1211** | `body_chars` **1211** |
| control request | `input_chars` **532** | `payload_chars` **532** |

With `decision=allow`, four detectors executed and **zero detected** on every trial —
so the only body-mutating path in the firewall (`set_response_text()` under
`Action.REDACT`) was never entered.

The whitespace-dominated, non-terminating response was therefore already present when
the firewall received it from the provider.

## 2. What is explicitly *not* established

**Which provider component.** `provider_component: UNKNOWN`. This localises the defect
to the provider side of one hop. It does not name a decoder, a grammar
implementation, a sampler, a runtime or a configuration, and no such claim is made
anywhere in this package. The candidate causes are listed — deliberately without one
being chosen — in [r86-provider-root-cause.md](r86-provider-root-cause.md).

**Root cause.** `NOT_ESTABLISHED`. Attribution and root cause are different questions
and only the first has an answer.

## 3. The firewall hypothesis, retired precisely

The exact statement, and it is the only one this package makes:

> The firewall-side response transformation hypothesis is ruled out for the registered
> R-86 reproducer based on matching upstream and downstream response lengths/content
> characteristics.

**Not claimed:**

- ~~The firewall can never corrupt responses.~~
- ~~The firewall is correct in general.~~
- ~~Any other firewall failure mode has been tested or excluded.~~

The scope is this reproducer, these twelve trials, this configuration. A single
negative result about one path is not a clean bill of health for a component, and
writing it as though it were is how a retired hypothesis becomes an assumption nobody
re-examines.

## 4. The seal is not rewritten

`r86-reproducer.manifest.json` still records `attribution: INDETERMINATE`, still
hashes to `sha256:271127edace3d94d`, and two tests still assert both.

That was true when the seal was taken. A seal updated whenever the world moves is a
document about today rather than a record of a moment, and the whole value of sealing
the reproducer was that a later reader can see what was known *then*. The new
attribution lives beside it — the same separation Phase 17 used to keep an
authorisation out of the manifest it decided about.

`r86-handoff-status.json` **is** updated, because it is a status file rather than a
record, and a status that contradicts current evidence is worse than no status.

## 5. Why this took four phases

Phases 15–19 recorded R-86 as `OUTSIDE_ENGINEERING_CONTROL` on correct reasoning:
MEDAUTH observes exactly one hop and holds no provider credential, so `PROVIDER_DECODER`
and `FIREWALL_PROXY` are indistinguishable *from here*.

What went unexamined is who else was standing there. The firewall is operated by the
same team, its append-only audit had been recording every hop since Phase 12, and the
decisive check had been sitting behind the word "external" without anybody testing
whether it was.

**A dependency outside one component's control is not the same as one outside
anyone's.** That is the transferable lesson, and it is recorded in the risk register
against R-86 rather than left in a commit message.
