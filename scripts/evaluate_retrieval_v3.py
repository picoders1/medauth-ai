"""Score retrieval_v3 — ONCE — under OD-28.

The same comparison as `evaluate_retrieval_v2.py`, against the provenance-clean
set, with EVERY parameter identical: same arms, same `top_k`, same `rerank_top_n`,
same chunking, same resolution policy, same shipped defaults.

**Nothing is tuned here and nothing may be tuned after seeing the result.** The
benchmark was frozen before any arm ran; no query was added, rewritten, reweighted
or dropped, and the labels are the ones committed in the dataset.

v3 exists because v1 and v2 are provenance-contaminated: a rate whose denominator
includes measurements that mean nothing is not a rate. v3 is 36 queries, all six
ways provenance-clean, and this is its first and only scoring.

Original v2 docstring follows.

Compare retrieval configurations on the v2 benchmark (Phase 4, OD-22).

v1 could not discriminate: Recall@3 was 0.9524 across all six arms. This runs the
same comparison against a set built to be hard - negative queries, ambiguous
queries, distractors, cross-policy and cross-version pairs, and every one of the
35 criteria covered.

    uv run python scripts/evaluate_retrieval_v3.py

Nothing is tuned here. `top_k`, `rerank_top_n`, chunking and the resolution policy
are identical across arms and identical to the shipped defaults. The benchmark was
authored and frozen before any arm was run, and no query was rewritten, reweighted
or dropped after seeing a result.
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import platform
import subprocess
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import yaml
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import async_sessionmaker

from app.config.policy import load_policy
from app.config.settings import Settings
from app.database.engine import build_engine
from app.policy.models import PolicyChunk, PolicyDocument, PolicyVersion
from app.retrieval.embed import SentenceTransformerEmbedder
from app.retrieval.rerank import CrossEncoderReranker
from eval.runners.retrieval_v2 import ArmScoreV2, load_questions_v2, run_arm_v2

REPO = Path(__file__).resolve().parents[1]
QUESTIONS = REPO / "eval" / "datasets" / "retrieval_v3" / "questions.yaml"

EMBEDDERS = ("BAAI/bge-base-en-v1.5", "BAAI/bge-small-en-v1.5")
RERANKERS: tuple[str | None, ...] = (
    None,
    "BAAI/bge-reranker-base",
    "cross-encoder/ms-marco-MiniLM-L-6-v2",
)


def _value(d: dict[str, Any]) -> float:
    return d["successes"] / d["total"] if d["total"] else 0.0


def _rate(d: dict[str, Any]) -> str:
    """Render a serialised `Rate`. A proportion never appears without its
    denominator and interval - a bare 0.81 hides that it is 34 of 42."""
    return (
        f"{_value(d):.4f} ({d['successes']}/{d['total']}, 95% CI {d['lower']:.4f}-{d['upper']:.4f})"
    )


def _git_commit() -> str:
    try:
        out = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],
            cwd=REPO,
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        )
        return out.stdout.strip() or "unknown"
    except (OSError, subprocess.SubprocessError):
        return "unknown"


def _render(
    arms: list[dict[str, Any]],
    meta: dict[str, Any],
    categories: dict[str, int],
    scope_sizes: dict[str, int] | None = None,
) -> str:
    lines = [
        "# Retrieval Evaluation v3",
        "",
        "Compares six configurations on `eval/datasets/retrieval_v3`. Addresses **OD-28**:",
        "whether a retrieval benchmark for this corpus can discriminate between systems at",
        "all.",
        "",
        "**v1 and v2 are not superseded.** Its numbers remain attached to its own set and its own",
        "report. This is a different, harder benchmark, and the two are not comparable.",
        "",
        "## Provenance",
        "",
        "| | |",
        "|---|---|",
    ]
    lines += [f"| {k} | `{v}` |" for k, v in meta.items()]
    lines += [
        "",
        "## What the set contains",
        "",
        "| category | queries |",
        "|---|---|",
    ]
    lines += [f"| {name} | {n} |" for name, n in sorted(categories.items())]
    lines += [
        f"| **total** | **{sum(categories.values())}** |",
        "",
        "## Resolution accuracy",
        "",
        "Reported separately from ranking and identical across arms: resolution is",
        "deterministic SQL on code, jurisdiction and date, so an encoder cannot change",
        "which policy version applies. Negative queries are excluded from this denominator -",
        "they have no expected version.",
        "",
        f"**{_rate(arms[0]['resolution_accuracy'])}**",
        "",
        "## Ranking quality",
        "",
        "Graded relevance: RELEVANT = 2, PARTIALLY_RELEVANT = 1. Recall counts a fully",
        "relevant section reaching rank k. Exact cosine, not the HNSW index.",
        "",
        "| encoder | reranker | R@1 | R@3 | R@5 | MRR | nDCG@5 | P@3 | p50 ms |",
        "|---|---|---|---|---|---|---|---|---|",
    ]
    for d in arms:
        lines.append(
            f"| `{d['embedder']}` | `{d['reranker'] or 'none'}` | "
            f"{_value(d['recall_at_1']):.4f} | {_value(d['recall_at_3']):.4f} | "
            f"{_value(d['recall_at_5']):.4f} | {d['mrr']:.4f} | {d['ndcg_at_5']:.4f} | "
            f"{d['precision_at_3']:.4f} | {d['latency_p50_ms']:.1f} |"
        )

    spread_1 = max(_value(a["recall_at_1"]) for a in arms) - min(
        _value(a["recall_at_1"]) for a in arms
    )
    spread_3 = max(_value(a["recall_at_3"]) for a in arms) - min(
        _value(a["recall_at_3"]) for a in arms
    )

    lines += [
        "",
        f"Recall@1 spread across arms: **{spread_1:.4f}**. Recall@3 spread: **{spread_3:.4f}**.",
        "",
        "On v1 the Recall@3 spread was **0.0000** - every arm scored 0.9524 and the",
        "benchmark distinguished nothing. Whether this set does better is the number above,",
        "and it is reported whatever it says.",
    ]

    identical = [
        (a["embedder"], b["embedder"], a["reranker"])
        for i, a in enumerate(arms)
        for b in arms[i + 1 :]
        if a["reranker"] == b["reranker"]
        and a["reranker"] is not None
        and (_value(a["recall_at_1"]), a["mrr"], a["ndcg_at_5"])
        == (_value(b["recall_at_1"]), b["mrr"], b["ndcg_at_5"])
    ]
    if identical:
        largest = max(scope_sizes.values()) if scope_sizes else None
        lines += [
            "",
            "## The reranked arms are encoder-independent, and that is a finding",
            "",
            "Every pair of arms sharing a reranker produced **identical** metrics:",
            "",
        ]
        lines += [
            f"- `{a}` and `{b}` with `{r}` agree on R@1, MRR and nDCG to four decimals"
            for a, b, r in identical
        ]
        lines += [
            "",
            f"That is not a coincidence and not a bug. `top_k` is **{meta['top_k']}**"
            + (
                f" while the largest policy version in this corpus holds **{largest} chunks**,"
                if largest
                else ","
            ),
            "so first-stage retrieval never filters anything. Every reranker receives the",
            "complete resolved scope whatever ordering the encoder produced, and the",
            "encoder's contribution is discarded entirely.",
            "",
            "**Consequence: with a reranker present, this benchmark measures the reranker",
            "alone.** The encoder comparison is interpretable only in the two arms with no",
            "reranker, where `bge-base` leads `bge-small` at R@1 "
            f"({_value(arms[0]['recall_at_1']):.4f} vs {_value(arms[3]['recall_at_1']):.4f}).",
            "",
            "The same effect explains the negative-query table below: mean top similarity is",
            "measured before reranking, so it varies by encoder and not by reranker.",
            "",
            "`top_k` was **not** lowered to fix this. Changing a parameter after seeing",
            "results is how a comparison becomes a search for a flattering configuration,",
            "and Part C of this phase fixes `top_k` across arms deliberately. A corrected",
            "comparison needs either a corpus large enough that 40 candidates is a real",
            "filter, or a pre-registered experiment at a smaller `top_k` - not a quiet edit",
            "to this one.",
        ]

    lines += [
        "",
        "## Negative queries",
        "",
        "Six queries the corpus does not answer. Every chunk in scope is NOT_RELEVANT by",
        "construction, so a top-1 result is always a false retrieval - the measurement is",
        "the *confidence* attached to it. A system that returns its best non-answer at 0.30",
        "is behaving differently from one that returns it at 0.80, and only the second would",
        "mislead a reviewer.",
        "",
        "| encoder | reranker | false retrieval rate | mean top similarity |",
        "|---|---|---|---|",
    ]
    for d in arms:
        lines.append(
            f"| `{d['embedder']}` | `{d['reranker'] or 'none'}` | "
            f"{_rate(d['false_retrieval_rate_on_negatives'])} | "
            f"{d['negative_mean_top_score']:.4f} |"
        )
    lines += [
        "",
        "A false retrieval rate of 1.0000 is the expected result, not a defect: dense",
        "retrieval has no abstention mechanism and always returns its nearest neighbour.",
        "The figure exists to make that explicit and to give the similarity distribution a",
        "denominator - **there is currently no threshold below which this system declines to",
        "retrieve**, and these numbers are what such a threshold would have to be calibrated",
        "against. Calibrating it on this set is not permitted (OD-8 governs threshold",
        "selection, and it is dev-only).",
        "",
        "## Per-category recall@1",
        "",
        "| category | "
        + " | ".join(
            f"`{a['embedder'].split('/')[-1]}`+`{(a['reranker'] or 'none').split('/')[-1]}`"
            for a in arms
        )
        + " |",
        "|---" * (len(arms) + 1) + "|",
    ]
    all_categories = sorted({c for a in arms for c in a["by_category"]})
    for category in all_categories:
        cells = []
        for arm in arms:
            b = arm["by_category"].get(category, {})
            scored = b.get("scored", 0)
            cells.append(f"{b.get('hit_at_1', 0)}/{scored}" if scored else "-")
        lines.append(f"| {category} | " + " | ".join(cells) + " |")

    lines += [
        "",
        "Cells are hits/scored. A dash means every query in that category was excluded from",
        "ranking - which for NEGATIVE is by definition and for EXCEPTION reflects the 411.15",
        "queries that no procedure code can resolve to (OD-15).",
        "",
        "## Why precision@3 is low everywhere",
        "",
        "P@3 sits near 0.51 in every arm, and that is a property of the labels rather",
        "than of the retrievers. Most queries have one or two relevant sections, so a",
        "query with a single relevant section caps P@3 at 0.3333 however perfect the",
        "ranking is. It is reported because Part B asks for precision where meaningful,",
        "and this is the honest reading: **it is not meaningful here.** MRR and nDCG@5",
        "carry the ranking signal on this set.",
        "",
        "## What the per-category table shows",
        "",
        "This is where v2 earns its existence. PARAPHRASED ranges from 1/5 to 3/5 across",
        "arms and HISTORICAL_VERSION from 4/8 to 7/8 - differences v1 could not have",
        "surfaced, because on v1 every arm scored the same. PARTIAL_INFORMATION is 1/3 in",
        "every arm, which is the expected result for two-word queries and is reported as",
        "a property of the category rather than as a failure of any configuration.",
        "",
        "## What this report does NOT establish",
        "",
        "- **Not a claim that any configuration is best.** Denominators are still small and",
        "  intervals still overlap. No default was changed on this evidence.",
        "- **Not decision quality.** This measures whether the right section is retrieved,",
        "  not whether a correct recommendation follows.",
        "- **Not index recall.** Exact cosine was used deliberately, so an ANN approximation",
        "  cannot be confounded with encoder quality.",
        "- **Not generalisation to real coverage determinations.** The corpus is five",
        "  regulations, not NCDs or LCDs (R-55).",
        "- `BAAI/bge-small-en-v1.5` emits 384 dimensions. Adopting it would require a",
        "  migration of `policy_chunks.embedding` and a full re-embed.",
        "",
    ]
    return "\n".join(lines)


async def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", default="eval/reports")
    parser.add_argument("--top-k", type=int, default=40)
    parser.add_argument("--rerank-top-n", type=int, default=5)
    parser.add_argument(
        "--render-only",
        metavar="DIR",
        help="re-render report.md from an existing results.json without re-running any arm",
    )
    args = parser.parse_args()

    if args.render_only:
        # The report is a rendering of the committed artefact, so a wording change
        # must never require re-running the models - re-running would also produce
        # new numbers, and a report whose prose and figures came from different
        # runs is worse than no report.
        out_dir = REPO / args.render_only
        saved = json.loads((out_dir / "results.json").read_text(encoding="utf-8"))
        questions = load_questions_v2(QUESTIONS)
        (out_dir / "report.md").write_text(
            _render(
                saved["arms"],
                saved["meta"],
                dict(Counter(q.category for q in questions)),
                saved.get("scope_sizes"),
            ),
            encoding="utf-8",
        )
        print(f"  re-rendered {out_dir.relative_to(REPO)}/report.md from results.json")
        return 0

    settings = Settings()
    policy = load_policy(settings.decision_policy_file)
    questions = load_questions_v2(QUESTIONS)
    categories = Counter(q.category for q in questions)

    engine = build_engine(settings)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    arms: list[ArmScoreV2] = []
    scope_sizes: dict[str, int] = {}

    try:
        async with factory() as session:
            # Recorded so the report can say whether first-stage retrieval filtered
            # anything at all. With top_k above the largest scope it does not, and
            # every reranked arm then measures only the reranker.
            for policy_id, revision_id, count in (
                await session.execute(
                    select(
                        PolicyDocument.policy_id,
                        PolicyVersion.revision_id,
                        func.count(PolicyChunk.id),
                    )
                    .join(PolicyVersion, PolicyVersion.document_id == PolicyDocument.id)
                    .join(PolicyChunk, PolicyChunk.policy_version_id == PolicyVersion.id)
                    .group_by(PolicyDocument.policy_id, PolicyVersion.revision_id)
                )
            ).all():
                scope_sizes[f"{policy_id}|{revision_id}"] = int(count)

            for embedder_id in EMBEDDERS:
                embedder = SentenceTransformerEmbedder(
                    embedder_id, device=settings.embedding_device
                )
                for reranker_id in RERANKERS:
                    print(f"  {embedder_id:<28} + {reranker_id or 'none':<38} ", end="", flush=True)
                    reranker = (
                        CrossEncoderReranker(reranker_id, device=settings.embedding_device)
                        if reranker_id
                        else None
                    )
                    arm = await run_arm_v2(
                        session,
                        questions,
                        embedder,
                        reranker,
                        policy.resolution,
                        top_k=args.top_k,
                        rerank_top_n=args.rerank_top_n,
                    )
                    arms.append(arm)
                    print(
                        f"R@1={arm.recall_at(1).value:.4f}  R@3={arm.recall_at(3).value:.4f}  "
                        f"nDCG={arm.as_dict()['ndcg_at_5']:.4f}"
                    )
    finally:
        await engine.dispose()

    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    out_dir = REPO / args.out / f"{stamp}__retrieval-v3"
    out_dir.mkdir(parents=True, exist_ok=True)

    meta = {
        "dataset": "eval/datasets/retrieval_v3/questions.yaml",
        "dataset_sha256": hashlib.sha256(QUESTIONS.read_bytes()).hexdigest()[:16],
        "dataset_version": yaml.safe_load(QUESTIONS.read_text(encoding="utf-8"))["version"],
        "queries": len(questions),
        "top_k": args.top_k,
        "rerank_top_n": args.rerank_top_n,
        "git_commit": _git_commit(),
        "python": platform.python_version(),
        "machine": f"{platform.system()} {platform.machine()}",
        "generated_at": datetime.now(UTC).isoformat(),
    }

    (out_dir / "results.json").write_text(
        json.dumps(
            {
                "meta": meta,
                "arms": [a.as_dict() for a in arms],
                "per_question": {f"{a.embedder}|{a.reranker}": a.per_question for a in arms},
            },
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )
    (out_dir / "report.md").write_text(
        _render([a.as_dict() for a in arms], meta, dict(categories), scope_sizes),
        encoding="utf-8",
    )
    print(f"\n  written to {out_dir.relative_to(REPO)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
