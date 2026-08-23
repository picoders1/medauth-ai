# Open Decisions

Genuinely unsettled questions. An item leaves this list only with the artefact or decision that
resolved it — not by being forgotten.

Settled decisions live in [adr/](adr/). If something here is decided, it becomes or amends an ADR
and the row is marked `Resolved` with a pointer.

---

| ID | Question | Why it is open | Resolved by | Phase |
|---|---|---|---|---|
| ~~**OD-1**~~ | ~~Does the configured model support `response_format: json_schema`, `json_object`, or tool calling?~~ | **RESOLVED (Phase 0).** Measured through the firewall: the primary model supports `json_schema` at 5/5 schema-valid; the long-context model is served with speculative decoding and rejects every grammar-constrained mode, but supports `tool_choice: auto`. Routing is by task. | `eval/reports/20260823T091726Z__model-capabilities/report.md`; ADR-008 amended | **0 — done** |
| **OD-2** | Is self-hosted vLLM ever validated for this project? | The reference machine has 4 GB VRAM and cannot serve a useful model at the required context. vLLM is a documented deployment target with no evidence behind it. | A served model with measured latency on adequate hardware, or permanent deferral | 9+ |
| **OD-3** | Should MEDAUTH enable the firewall's provenance overlay? | The capability exists in the firewall but ships **off and uncalibrated** (its OD-3). MEDAUTH would be its first real consumer. | A calibrated threshold and an ADR **in the firewall repository** first | 8+ |
| **OD-4** | May a `DRAFT` (unreviewed) criteria tree produce recommendations outside evaluation? | Human review does not scale to a large corpus, but an unreviewed tree is an unvalidated rule set driving clinical recommendations. | ADR-007 amendment; likely `criteria_tree_reviewed` stays a hard gate feature | 2 |
| **OD-5** | Does `self_consistency` (k independent adjudications per criterion) add signal over `criteria_coverage` and `rerank_margin`? | It multiplies adjudication cost by k. Worth it only if it improves the coverage/safety frontier. | Measured on dev in Phase 6 before adoption | 6 |
| **OD-6** | Is Presidio adopted? | All data here is synthetic, so it would detect nothing real while adding spaCy, a model download and startup cost; the firewall already redacts on the model path. Shipping it would be a compliance gesture, not a control. | A real-data deployment decision. Deferred, not rejected | — |
| **OD-7** | Will a pilot with real clinical reviewers happen? | Override rate, human/AI agreement and review-time claims are **refused** without one. This is the largest gap between what the system does and what can be said about it. | A pilot with participants and a protocol | — |
| **OD-8** | What are the abstention thresholds, and what are the unsafe-rate ceilings? | Cannot be chosen before calibration data exists. Ceilings must be **pre-registered** in ADR-011 before the sweep is run. | ADR-011 amendment before Phase 6 step 2 | 6 |
| **OD-9** | Will the Kubernetes manifests ever run on a real cluster? | No cluster exists on the reference machine — no `kubectl`, `kind`, `minikube` or `helm`. Until one does, "runs on Kubernetes" is a refused claim and `kubeconform` validation is the permitted one. | A cluster run producing an artefact | 9+ |
| **OD-10** | Which embedding model and reranker? | `BAAI/bge-base-en-v1.5` and `BAAI/bge-reranker-base` are **defaults, not choices**. Coverage policy is a narrow, templated, jargon-dense domain and general-purpose retrieval quality may not transfer. | The Phase 1 retrieval comparison report; ADR-006 amended | 1 |
| **OD-11** | How many procedures should the initial corpus cover? | Too few and the evaluation measures nothing general; too many and Phase 1 never finishes. Starting point is 5–8, spanning national and jurisdictional coverage with at least one superseded version. | Phase 1 selection record, written before download | 1 |
| **OD-12** | Should the optional LLM faithfulness check be enabled by default? | It costs a call per case and can only withhold, never release. Whether it catches anything the deterministic guardrail misses is unmeasured. | Phase 6 measurement of its marginal catch rate | 6 |
| **OD-13** | How are conflicting LCDs across jurisdictions handled beyond routing to a human? | Currently row 2 → `HUMAN_REVIEW`, which is safe but may be common enough to be unhelpful. | Frequency measured in Phase 1; revisit only if material | 1, 6 |
| **OD-14** | Should MEDAUTH expose an OpenAI-compatible surface of its own? | It would make the system embeddable in other tools, but MEDAUTH is not a chat system and forcing its outputs into that shape would misrepresent them. | Deferred; no requirement exists | — |
