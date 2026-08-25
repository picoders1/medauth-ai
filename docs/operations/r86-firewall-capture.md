# R-86 — firewall-side upstream capture

**Evidence:** `data/escalations/r86-firewall-capture.json` (`r86-firewall-capture-001`)
**Answers:** [r86-provider-escalation.md](r86-provider-escalation.md) §10, **check 2** — *"the request as
forwarded and the response as received, before any proxy transformation"* — which that
document records as decisive on its own.

**Result:** the firewall is exonerated. R-86 is **not** fixed and the official
evaluation stays blocked.

---

## 1. Why this took four phases

Phases 15 through 19 recorded R-86's attribution as `INDETERMINATE` and called it
`OUTSIDE_ENGINEERING_CONTROL`, on the correct reasoning that MEDAUTH observes exactly
one hop and holds no provider credential. From where MEDAUTH stands,
`PROVIDER_DECODER` and `FIREWALL_PROXY` are indistinguishable, and no amount of code
in this repository changes that.

What went unexamined is who *else* was standing there. The firewall is operated by the
same team, its append-only audit trail was already recording every hop, and check 2
had been sitting behind the word "external" without anybody testing whether it was.

The word was right about MEDAUTH and wrong about the deployment. **A dependency being
outside one component's control is not the same as it being outside anyone's.** That
distinction is the finding here, and it cost four phases of hold.

## 2. Method

Run by the firewall operator against the firewall's own records. **MEDAUTH holds no
connection to this database and grew none** — the rows were handed over exactly as
they would have been by any other owner, which is what keeps MEDAUTH's boundary at the
HTTP contract where the architecture puts it.

```sql
-- The twelve trials of the registered revalidation, one row per HTTP exchange.
SELECT t.created_at, t.request_id, t.upstream_host, t.model, t.status_code,
       t.decision, t.input_chars, t.output_chars, round(t.upstream_latency_ms)
FROM   request_traces t
WHERE  t.created_at >= '2026-08-25 15:56:20+00'
  AND  t.created_at <  '2026-08-25 15:57:20+00'
ORDER  BY t.created_at;

-- Whether anything the firewall does could have altered the body.
SELECT t.created_at, t.decision, t.input_chars, t.output_chars,
       count(d.id)                             AS detectors,
       count(*) FILTER (WHERE d.detected)      AS detected,
       count(*) FILTER (WHERE d.errored)       AS errored
FROM   request_traces t
LEFT   JOIN detector_results d ON d.trace_id = t.id
WHERE  t.created_at >= '2026-08-25 15:56:20+00'
  AND  t.created_at <  '2026-08-25 15:57:20+00'
GROUP  BY 1, 2, 3, 4 ORDER BY 1;
```

`output_chars` is counted in the firewall's output-inspection stage, immediately after
the HTTP read from the provider and **before** anything is returned to MEDAUTH. That
is precisely the observation point check 2 asks for.

No prompt text, note text or completion text is read, quoted or committed. The audit
trail stores counts and metadata; the deployment's model name and upstream host appear
in the artefact only as digests, under the convention the sealed manifest already uses.

## 3. Identity

The traces are the registered configuration, verified rather than assumed:

| | |
|---|---|
| model digest | `sha256:31d69bc24c21367e` — **identical to the seal's** |
| trials in window | 12, against 12 registered |
| structure | two cells of six, matching `intake/gold_note/{long,short}` |
| upstream host | `sha256:334329af9cb116de` — the real provider, not the mock |

That last row matters more than it looks. The firewall ships with a mock upstream and
it was running on the same machine. The audit records the host **per request**, so
"these trials really went to the provider" is a fact read off the record rather than
inferred from a configuration file that could have changed since.

## 4. What the capture shows

| | production cell | control cell |
|---|---|---|
| trials | 6 | 6 |
| firewall `input_chars` | 1058 | 532 |
| firewall `output_chars` | **2389** | 1211 |
| status / decision | 200 / `allow` | 200 / `allow` |
| detectors run · detected | 4 · **0** | 4 · **0** |
| upstream latency | 6323–6447 ms | 2101–2586 ms |
| identical across trials | yes | yes |

Three things follow.

**The padding was already there.** The firewall received 2389 characters of completion
content. MEDAUTH measured that same response at 92.05% whitespace, which puts roughly
2199 whitespace characters and a ~190-character JSON prefix on the wire *from the
provider*.

**The firewall did nothing to it.** `decision=allow`, four detectors run, none
detected, none errored. The only code path in the firewall that mutates a response
body is `set_response_text()` under `Action.REDACT`, and it requires a detector to
fire. None did — and redaction replaces text, it does not pad with whitespace.

**Three times the latency for content that never terminates.** 6.3 s against 2.1 s on
the control, consistent with decoding to the ceiling rather than stopping.

## 5. The two records agree to the character

The decisive part is not either record. It is that two independent measurements were
taken on opposite sides of the proxy and match exactly:

| | firewall side | MEDAUTH side |
|---|---|---|
| production response | `output_chars` **2389** | `body_chars` **2389** |
| production request | `input_chars` **1058** | `payload_chars` **1058** |
| control response | `output_chars` **1211** | `body_chars` **1211** |
| control request | `input_chars` **532** | `payload_chars` **532** |

Nothing changed across the hop, and this is established by measurement rather than by
reading the proxy's source and believing it.

MEDAUTH's own record of the same exchange adds `finish_reason: "length"`,
`parsed_as_json: false`, `completion_tokens: 1536` — a response that ran to the
ceiling and never closed its document.

## 6. Classification

```
STILL_FAILING          the defect is present, reproduced 6/6
attribution            PROVIDER_SIDE   (was INDETERMINATE)
FIREWALL_PROXY         eliminated
```

**What this does not claim.** It localises the defect to the provider side of the
proxy hop. It does **not** identify which component inside the provider's serving stack
produces the padding — decoder, grammar implementation or sampler — and no such claim
is made here. One layer is ruled out; the other is not resolved further.

**What it does not do.** It does not lift anything. Attribution is not a fix. The
production cell still fails 6/6, the gate still reads 6/12 = 0.5000 against the
pre-registered ceiling of 0.10, and R-86 remains a `VERIFIED FAILURE`. This evidence is
not grounds for a revalidation either: revalidation asks whether the defect is gone,
and this says it is present.

**The seal is not rewritten.** `r86-reproducer.manifest.json` still records
`attribution: INDETERMINATE`, and two tests assert that it does. That was true when the
seal was taken, and a seal that gets updated whenever the world moves is a document
about today rather than a record of a moment. The new attribution lives beside it —
the same separation Phase 17 used to keep an authorisation out of the manifest it
decided about.

## 7. What changes for the escalation

The escalation can now go to the **model provider** specifically, carrying the
firewall's own records rather than an assertion that the firewall is probably fine.

Checks 1, 3, 4 and 5 in §10 are no longer needed — they exist to separate the two
layers, and the layers are separated. The one still worth asking is **check 6**:

> Does the constrained decoder's grammar admit whitespace after a structurally
> complete document?

That is now a question with a single addressee and no ambiguity about which system it
is about.
