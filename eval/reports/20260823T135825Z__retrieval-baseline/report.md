# Retrieval Baseline

Compares encoders and rerankers on the frozen retrieval set. Resolves **OD-10**;
ADR-006 cites this report.

## Provenance

| | |
|---|---|
| generated_at | `2026-08-23T13:58:25+00:00` |
| git_commit | `038d1b2` |
| dataset | `eval/datasets/retrieval/questions.yaml` |
| dataset_sha256 | `0026a812276a3e2e` |
| dataset_version | `3` |
| corpus | `data/cms` |
| corpus_kind | `authoritative` |
| questions | `23` |
| scored_questions | `21` |
| device | `cpu` |
| python | `3.12.3` |
| platform | `Linux x86_64` |

## Resolution accuracy

Reported **separately** from ranking, and identical across every arm because
resolution is deterministic: it uses no embeddings and no model, so an encoder
cannot change which policy version applies. That invariance is the point.

**1.0000 [0.8454, 1.0000] n=21**

## Ranking quality

Exact cosine, not the HNSW index - ANN approximation would confound an encoder
comparison with index recall. Index behaviour is covered by the integration tests.

| encoder | reranker | recall@1 | recall@3 | recall@5 | MRR | nDCG@5 |
|---|---|---|---|---|---|---|
| `BAAI/bge-base-en-v1.5` | `none` | 0.7619 [0.5491, 0.8937] n=21 | 0.9524 [0.7733, 0.9915] n=21 | 1.0000 [0.8454, 1.0000] n=21 | 0.8429 | 0.8403 |
| `BAAI/bge-base-en-v1.5` | `BAAI/bge-reranker-base` | 0.5714 [0.3655, 0.7553] n=21 | 0.9524 [0.7733, 0.9915] n=21 | 0.9524 [0.7733, 0.9915] n=21 | 0.7528 | 0.7561 |
| `BAAI/bge-base-en-v1.5` | `cross-encoder/ms-marco-MiniLM-L-6-v2` | 0.8095 [0.6000, 0.9233] n=21 | 0.9524 [0.7733, 0.9915] n=21 | 1.0000 [0.8454, 1.0000] n=21 | 0.8825 | 0.8756 |
| `BAAI/bge-small-en-v1.5` | `none` | 0.7143 [0.5004, 0.8619] n=21 | 0.9524 [0.7733, 0.9915] n=21 | 1.0000 [0.8454, 1.0000] n=21 | 0.8349 | 0.8478 |
| `BAAI/bge-small-en-v1.5` | `BAAI/bge-reranker-base` | 0.5714 [0.3655, 0.7553] n=21 | 0.9524 [0.7733, 0.9915] n=21 | 0.9524 [0.7733, 0.9915] n=21 | 0.7528 | 0.7561 |
| `BAAI/bge-small-en-v1.5` | `cross-encoder/ms-marco-MiniLM-L-6-v2` | 0.8095 [0.6000, 0.9233] n=21 | 0.9524 [0.7733, 0.9915] n=21 | 1.0000 [0.8454, 1.0000] n=21 | 0.8825 | 0.8756 |

## Does reranking help here?

ADR-006 argued that reranking earns its cost on this corpus, because sections
within one determination share almost all their vocabulary and a bi-encoder
separates them poorly. **The measurement does not support that argument.**

| encoder | no reranker | bge-reranker-base | ms-marco-MiniLM |
|---|---|---|---|
| `BAAI/bge-base-en-v1.5` | 0.7619 | 0.5714 | 0.8095 |
| `BAAI/bge-small-en-v1.5` | 0.7143 | 0.5714 | 0.8095 |

Reranking **reduced** recall@1 for both encoders. Recall@5 is unaffected, so the
reranker is not losing the correct section - it is demoting it. The likely cause is
that this corpus's sections are short and lexically distinct enough that the
bi-encoder already separates them, while the cross-encoder rewards passages that
restate the question's wording over the one that answers it.

This is a **negative result on a constructed corpus**, and it is recorded rather
than tuned away. It does not establish that reranking is useless on real CMS prose,
where sections are longer and far more repetitive - the condition the ADR's argument
was actually about. What it does establish is that the argument is **unevidenced**
here, so reranking must not be described as earning its cost until it is measured on
a corpus where the premise holds.

## Is the best arm distinguishable from the shipped default?

Shipped default: `BAAI/bge-base-en-v1.5` + `BAAI/bge-reranker-base`.
Best observed: `BAAI/bge-base-en-v1.5` + `cross-encoder/ms-marco-MiniLM-L-6-v2`.

Paired exact McNemar on recall@1 discordant pairs (6 best-only / 1 default-only): **p = 0.1250**.

**Not distinguishable at this denominator.** No configuration change is made on
this evidence: with 11 scored questions, an interval on a rate near 0.9 spans
roughly 35 percentage points, and every arm overlaps every other. Switching the
default here would be tuning on noise.

## What this report does NOT establish

- **Not a claim that any model is best.** The denominator is small and the corpus
  is constructed; intervals are wide enough that most arms overlap.
- **Not decision quality.** This measures whether the right *section* is retrieved,
  not whether a correct recommendation follows. That is Phase 6.
- **Not index recall.** Exact search was used deliberately.
- `BAAI/bge-small-en-v1.5` emits 384 dimensions. Adopting it would require a
  migration of `policy_chunks.embedding` and a full re-embed - it is not a
  configuration change.
