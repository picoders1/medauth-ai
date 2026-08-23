# LLM Firewall Integration

**Status:** Planning phase. No integration code exists.
**Sibling project:** `/home/piai/Music/llm-firewall` — a release-candidate OpenAI-compatible
security gateway, separately deployed and separately versioned.

---

## 1. The boundary

```
   MEDAUTH  ──── OpenAI HTTP contract ────▶  llm-firewall :8005/v1  ────▶  provider
   (caller key)                              (holds provider key)      OpenAI-compatible
                                                                       endpoint + model id,
                                                                       both from .env
```

The brief proposed a bespoke *LLM Gateway Interface* abstraction between MEDAUTH and the firewall.
It is not built, deliberately.

The firewall **is** the OpenAI API — that is its entire adoption argument (its ADR-004). Wrapping
an OpenAI-compatible endpoint in a custom interface would add a translation layer whose only
function is to convert a standard contract into a private one, and would give MEDAUTH a second
thing to keep in sync on every provider feature. Provider portability, the reason such an
abstraction is usually built, is already provided by the contract itself: vLLM, Ollama, Together,
Groq, OpenRouter and most self-hosted servers speak it.

**The abstraction is `base_url`.** Pointing MEDAUTH at a different endpoint — including a bare
provider, for a controlled comparison — is a configuration change, not a code change.

Recorded in [ADR-016](../adr/ADR-016-llm-firewall-integration.md).

---

## 2. Credential placement

The firewall's ADR-024 establishes that a caller's credential never becomes the gateway's: the
upstream key is bound at client construction, and the forwarding method has nowhere to put a
header. MEDAUTH is built to sit on the correct side of that property.

| Credential | Held by | Never held by |
|---|---|---|
| Provider key | **llm-firewall** — `FIREWALL_UPSTREAM_API_KEY` | MEDAUTH |
| Firewall caller key | **MEDAUTH** — `MEDAUTH_LLM_API_KEY`, `SecretStr` | anything else |
| SHA-256 digest of the caller key | llm-firewall — `FIREWALL_CALLER_API_KEYS` | — |

Consequences:

- **MEDAUTH holds no model-provider credential at all.** Compromising MEDAUTH does not yield
  provider access; it yields a revocable caller key scoped to one gateway.
- The caller key is minted with the firewall's `scripts/generate_caller_key.py medauth-ai`. The raw
  key goes into MEDAUTH's `.env`; the digest goes into the firewall's configuration. The gateway
  never stores the raw key.
- Revoking MEDAUTH's access is a firewall-side change requiring no MEDAUTH deployment.

Neither credential appears in `.env.example`, in `config/*.yaml` (keys matching `*_key`,
`*secret*`, `*token*`, `*password*` are structurally rejected there), in any log, or in any
container image. `gitleaks` runs over full history in CI.

---

## 3. Request flow

```
  app/llm/schema_call.py
        │  build messages:
        │    system  = versioned prompt template            (TRUSTED, never from data)
        │    user    = task + fenced data block             (UNTRUSTED content lives here)
        │  response_format per the Phase 0 capability probe
        │  stream = false  (always)
        ▼
  POST http://localhost:8005/v1/chat/completions
       Authorization: Bearer <firewall caller key>
       X-Medauth-Request-Id: <request_id>          ← correlates both audit trails
        ▼
  firewall: admission → caller auth → normalise → detectors → policy → forward
        ▼
  the configured OpenAI-compatible provider
```

Notes:

- **Streaming is never requested.** The firewall refuses `stream: true` with `400
  unsupported_feature` rather than faking inspected streaming (its ADR-004). MEDAUTH does not want
  it anyway: every call returns a schema-validated object, and a partially-streamed verdict has no
  meaning. `MEDAUTH_LLM_STREAMING_ENABLED=false` exists as a guard, and `stream=True` is rejected
  in code before a request is built.
- **Embeddings do not traverse the firewall.** It exposes no `/v1/embeddings` (deferred there), and
  inspecting a policy-corpus embedding request would serve no security purpose. `sentence-transformers`
  runs in-process.
- The shared request id lets a MEDAUTH audit row and a firewall audit row be joined during an
  investigation, without either system storing the other's data.

---

## 4. Response and failure handling

| Firewall response | MEDAUTH behaviour | Case outcome |
|---|---|---|
| `200` | Validate against the schema; bounded repair on failure | continues |
| `400 unsupported_feature` | Configuration defect. Fail loudly at startup, not per request | — |
| **`403` security_block** | **Never retried.** Category and request id recorded in the audit trail | `HUMAN_REVIEW` |
| `429` | Retry honouring `Retry-After`, within the attempt ceiling | continues, else `HUMAN_REVIEW` |
| **`503` detector_failure** | The firewall failed closed. Retry with backoff within the ceiling | `HUMAN_REVIEW` |
| Connection error / timeout | Counts as an attempt | `HUMAN_REVIEW` |

Two properties matter here.

**A `403` is not retried.** Retrying a blocked request is an attempt to evade a security control.
If a legitimate clinical note is blocked, that is a finding about detector false positives —
recorded in both repositories — not something to be worked around by the application.

**Fail closed means fail toward the human, never toward a denial.** Every firewall failure routes
the case to `HUMAN_REVIEW` via row 4 of the decision table. A security failure must not be able to
manufacture a clinical outcome in either direction. `MEDAUTH_LLM_FAIL_CLOSED=false` exists for
local experimentation and is **refused at startup in production**.

---

## 5. What the firewall does and does not do for MEDAUTH

### Provides

| Capability | Value here |
|---|---|
| Caller-turn injection screening | Its strongest measured case (user-requested recall 0.7250) — covers T-01 |
| PII redaction on the model path | Defence in depth; all data here is synthetic |
| Upstream credential isolation | MEDAUTH holds no provider key |
| Fail-closed detector semantics | A detector failure blocks rather than silently forwarding |
| Rate limiting and admission control | Bounds cost and abuse on the model path |
| Independent audit of every model call | A second, separately-owned record |
| Provider portability | `base_url` is the only coupling |

### Does not provide

**Protection against injection delivered through retrieved policy text.** The firewall's own
committed evidence establishes this:

| Measurement | Value | Source |
|---|---|---|
| Indirect-injection recall | **0.1423** (n=520) | `eval/results/20260817T130736Z__indirect-delivery-shape/report.md` |
| Recall on *planted* content | 0.0938 (n=480) | same |
| Recall on *user-requested* content | 0.7250 (n=40) | same |
| `system_marker` shape | recall 0.5667 at FPR 0.2000 | same |
| Baseline through-socket recall | 0.4706 | R-102 |
| **"The firewall protects RAG applications"** | **claim refused; must not be made** | `docs/22-evidence-and-claims.md` |

The detector classifies the **user's turn**. MEDAUTH's threat is content the user never wrote — a
poisoned or adversarial passage inside a retrieved policy chunk. That is precisely the 0.0938 case.

**Therefore MEDAUTH does not delegate this threat.** Containment is structural and lives in
MEDAUTH: fenced delivery, closed output schemas with no decision token, span-verified quotes, a
decision computed by code, per-criterion isolation, and corpus content hashing. See
[threat-model.md](threat-model.md) T-05/T-06 and
[system-architecture.md](../architecture/system-architecture.md) §9.

This is the single most important sentence in this document: **the firewall is a valuable layer,
and it is not the layer that protects this system's primary attack surface.**

---

## 6. Provenance signalling

The firewall can carry content provenance and apply a monotone policy overlay that may only tighten
a decision (its ADR-017). MEDAUTH marks retrieved policy content as untrusted when it appears in a
request.

**This capability ships off and uncalibrated in the firewall (its OD-3).** MEDAUTH therefore treats
it as defence-in-depth and **not** as a control it relies on or claims. If it is ever enabled,
enabling it requires a calibrated threshold and an ADR in the firewall repository first. MEDAUTH
would be that capability's first real consumer, which is interesting but is not evidence.

---

## 7. Operational coupling

| Concern | Position |
|---|---|
| Deployment | The firewall is deployed and versioned **separately**. MEDAUTH consumes it; MEDAUTH's compose stack does not start it. |
| Readiness | Firewall reachability is an **advisory** check on `/ready`. A firewall outage stops new recommendations but must not make the reviewer console — where humans work existing cases — unavailable. |
| Versioning | MEDAUTH depends on the OpenAI contract subset, not on a firewall version. |
| Local development | Firewall on `:8005` with caller auth disabled (its development default). Production requires a caller key on both sides. |
| CI | Model-calling tests are marked and **skipped by default**. CI must pass from a clean clone with no key and no firewall. |
| Testing | Unit tests use a stub client. Integration tests may run against the firewall with its mock upstream on `:8081`, which needs no provider key and no egress. |

---

## 8. Observability interaction

Both systems record every model call, from different vantage points and for different purposes:

| | MEDAUTH audit | Firewall audit |
|---|---|---|
| Records | Case provenance: verdicts, citations, decision rule, prompt/model versions | Security decision: action, category, detector outcomes |
| Contains prompts or completions | **No** | **No** |
| Contains clinical text | No | No |
| Joined by | `X-Medauth-Request-Id` | same |
| Write path | **On** the request path — an unauditable recommendation is not issued | **Off** the request path, drops under load (its ADR-029) |

That last row is a deliberate divergence. The firewall's audit records a security decision that has
already been enforced, so dropping a row under load loses a record, not a control. MEDAUTH's audit
records the provenance of a clinical recommendation — the artefact a reviewer will later be asked
to justify. A recommendation that cannot be audited has no value here, so MEDAUTH pays the latency
instead. Recorded in [ADR-013](../adr/ADR-013-audit-architecture.md).
