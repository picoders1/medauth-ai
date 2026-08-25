# Failure taxonomy: what broke, and whose it was

**Module:** `app/llm/failure_taxonomy.py` · **Coverage:** `eval/coverage.py`
**Tests:** `tests/unit/test_provider_failure_taxonomy.py`

---

## The rule

> **A bad answer is not a provider failure. A broken response path is.**

`classify_provider_failure` takes an exception, a status code and a response *shape*.
It has **no parameter through which correctness could reach it**, and a test asserts
that over the signature. A model that returns a well-formed, schema-valid, entirely
wrong verdict classifies as `NONE`.

The inverse matters more. Phase 14 reported "MODEL_ASSESSMENT: 16" for a run in which
ten cases never reached a model. One name covered both, and a provider outage read as
a model that could not think.

## Two vocabularies, on purpose

| | answers | members | consumed by |
|---|---|---|---|
| `GatewayOutcome` | what this case does next | 7, all routing to a human | routing |
| `ProviderFailureKind` | whose defect this was | 11 | reliability reporting |

They travel together on `GatewayFailure` and are never collapsed. Merging them would
make routing depend on diagnostic detail — a case routed differently because a status
code happened to be more specific.

## The kinds

| kind | what it is | attribution | counts toward reliability |
|---|---|---|---|
| `NONE` | the path worked | NONE | — |
| `TIMEOUT` | exceeded the client timeout on every attempt | INDETERMINATE | yes |
| `UPSTREAM_CLIENT_ERROR` | 4xx that is not 403/429 — usually **our** malformed request | MEDAUTH | **no** |
| `UPSTREAM_BLOCKED` | 403; a security control **working** | FIREWALL | **no** |
| `UPSTREAM_SERVER_ERROR` | 5xx | INDETERMINATE | yes |
| `RATE_LIMITED` | 429; ours to pace | MEDAUTH | yes |
| `PROXY_TRANSFORMATION` | 503; the firewall answered about itself | FIREWALL | yes |
| `MALFORMED_RESPONSE` | 200, terminated, body unusable | INDETERMINATE | yes |
| `SCHEMA_GRAMMAR_FAILURE` | invalid after bounded repair — **R-86 lands here** | INDETERMINATE | yes |
| `CONNECTION_FAILURE` | the socket never opened, or died | INDETERMINATE | yes |
| `UNKNOWN_PROVIDER_FAILURE` | reached the boundary, matched nothing | INDETERMINATE | yes |

**Two exclusions from the reliability rate, and only two.** A firewall refusing a
request is not an outage — counting it as one would give whoever reads the number a
reason to want the control switched off. A 400 means we sent something wrong.
The exclusion set is asserted as an exact set, so widening it is a visible edit.

**`INDETERMINATE` is the commonest attribution and that is honest.** MEDAUTH sees one
hop. Naming the provider or the proxy without evidence is how an escalation gets
closed against the wrong team.

## The bug this taxonomy had

The first version tested *"did the body parse?"* before *"is this a whitespace
runaway?"*. A decoder that pads to the ceiling never closes its document and
therefore never parses — so **every R-86 occurrence was reported as
`MALFORMED_RESPONSE` with `is_r86_signature: False`.** `r86-factorial-001` produced
five textbook runaways and the instrument hid all five.

Found by running the experiment. The ordering was corrected, the matrix re-executed
unchanged, and both facts are recorded in the artefact — a measuring device was
repaired, no hypothesis or threshold moved.

## At case level

`AbstentionReason.PROVIDER_LIMITATION` splits what `MODEL_SCHEMA_FAILURE` used to
cover. Both route to `HUMAN_REVIEW` through rule 4; **no routing changed**. What
differs is what the case says about itself:

    MODEL_SCHEMA_FAILURE   the model answered and the answer was refused
    PROVIDER_LIMITATION    there was no answer to refuse

## At run level

`eval/coverage.py` gives six dispositions — `ASSESSED`, `PROVIDER_FAILURE`,
`DATASET_DEFECT`, `CONTRADICTION`, `SYSTEM_FAILURE`, `RETRIEVAL_FAILURE`. There is
deliberately **no `MODEL_WRONG`**, and a test asserts no kind is named for one: a
wrong answer from an assessed case is a decision-quality fact, not a coverage bucket.

`SYSTEM_FAILURE` is kept apart from `PROVIDER_FAILURE` so an outage cannot absorb a
bug of ours — a case that reached no verdict with no bucket explaining why is
attributed to MEDAUTH until proven otherwise.
