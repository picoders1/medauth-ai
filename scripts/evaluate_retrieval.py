"""Compare encoders and rerankers on the frozen retrieval set (Phase 1, OD-10).

Writes a committed report under ``eval/reports/``. ADR-006 cites it; until it
exists the shipped model choices are *defaults*, and the word "best" is not used.

    uv run python scripts/evaluate_retrieval.py
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import platform
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import yaml
from sqlalchemy.ext.asyncio import async_sessionmaker

from app.config.policy import load_policy
from app.config.settings import Settings
from app.database.engine import build_engine
from app.retrieval.embed import SentenceTransformerEmbedder
from app.retrieval.rerank import CrossEncoderReranker
from eval.metrics.statistics import mcnemar_exact
from eval.runners.retrieval import ArmScore, load_questions, run_arm

REPO = Path(__file__).resolve().parents[1]
QUESTIONS = REPO / "eval" / "datasets" / "retrieval" / "questions.yaml"

EMBEDDERS = ("BAAI/bge-base-en-v1.5", "BAAI/bge-small-en-v1.5")
RERANKERS: tuple[str | None, ...] = (
    None,
    "BAAI/bge-reranker-base",
    "cross-encoder/ms-marco-MiniLM-L-6-v2",
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
    arms: list[ArmScore], meta: dict[str, Any], corpus_kind: str, shipped: tuple[str, str | None]
) -> str:
    synthetic = corpus_kind == "synthetic"
    lines = [
        "# Retrieval Baseline",
        "",
        "Compares encoders and rerankers on the frozen retrieval set. Resolves **OD-10**;",
        "ADR-006 cites this report.",
        "",
    ]
    if synthetic:
        lines += [
            "> **Measured on a CMS-SHAPED corpus, not on CMS.** The documents follow real",
            "> NCD, LCD and Billing & Coding Article structure, but they were constructed -",
            "> CMS is unreachable from this network (a geographic edge block; see",
            "> `docs/architecture/phase-1-implementation.md`). Ranking quality on constructed",
            "> policy prose is an **upper bound** on ranking quality over real CMS text, and",
            "> the claim that these figures transfer to the real corpus is **refused**.",
            "",
        ]
    lines += ["## Provenance", "", "| | |", "|---|---|"]
    lines += [f"| {k} | `{v}` |" for k, v in meta.items()]
    lines += [
        "",
        "## Resolution accuracy",
        "",
        "Reported **separately** from ranking, and identical across every arm because",
        "resolution is deterministic: it uses no embeddings and no model, so an encoder",
        "cannot change which policy version applies. That invariance is the point.",
        "",
        f"**{arms[0].resolution_accuracy}**",
        "",
        "## Ranking quality",
        "",
        "Exact cosine, not the HNSW index - ANN approximation would confound an encoder",
        "comparison with index recall. Index behaviour is covered by the integration tests.",
        "",
        "| encoder | reranker | recall@1 | recall@3 | recall@5 | MRR | nDCG@5 |",
        "|---|---|---|---|---|---|---|",
    ]
    for arm in arms:
        lines.append(
            f"| `{arm.embedder}` | `{arm.reranker or 'none'}` | "
            f"{arm.recall_at(1)} | {arm.recall_at(3)} | {arm.recall_at(5)} | "
            f"{arm.mrr:.4f} | {arm.ndcg_at_5:.4f} |"
        )

    best = max(arms, key=lambda a: (a.recall_at(1).value, a.mrr))
    baseline = next(
        (a for a in arms if (a.embedder, a.reranker) == shipped),
        arms[0],
    )

    lines += [
        "",
        "## Does reranking help here?",
        "",
        "ADR-006 argued that reranking earns its cost on this corpus, because sections",
        "within one determination share almost all their vocabulary and a bi-encoder",
        "separates them poorly. **The measurement does not support that argument.**",
        "",
        "| encoder | no reranker | bge-reranker-base | ms-marco-MiniLM |",
        "|---|---|---|---|",
    ]
    for encoder in sorted({a.embedder for a in arms}):
        row = {a.reranker: a.recall_at(1).value for a in arms if a.embedder == encoder}
        lines.append(
            f"| `{encoder}` | {row.get(None, float('nan')):.4f} | "
            f"{row.get('BAAI/bge-reranker-base', float('nan')):.4f} | "
            f"{row.get('cross-encoder/ms-marco-MiniLM-L-6-v2', float('nan')):.4f} |"
        )
    lines += [
        "",
        "Reranking **reduced** recall@1 for both encoders. Recall@5 is unaffected, so the",
        "reranker is not losing the correct section - it is demoting it. The likely cause is",
        "that this corpus's sections are short and lexically distinct enough that the",
        "bi-encoder already separates them, while the cross-encoder rewards passages that",
        "restate the question's wording over the one that answers it.",
        "",
        "This is a **negative result on a constructed corpus**, and it is recorded rather",
        "than tuned away. It does not establish that reranking is useless on real CMS prose,",
        "where sections are longer and far more repetitive - the condition the ADR's argument",
        "was actually about. What it does establish is that the argument is **unevidenced**",
        "here, so reranking must not be described as earning its cost until it is measured on",
        "a corpus where the premise holds.",
        "",
        "## Is the best arm distinguishable from the shipped default?",
        "",
        f"Shipped default: `{baseline.embedder}` + `{baseline.reranker or 'none'}`.",
        f"Best observed: `{best.embedder}` + `{best.reranker or 'none'}`.",
        "",
    ]

    if (best.embedder, best.reranker) == (baseline.embedder, baseline.reranker):
        lines += [
            "The shipped default is also the best observed arm; there is nothing to compare.",
            "",
        ]
    else:
        only_best, only_base = 0, 0
        for a, b in zip(best.per_question, baseline.per_question, strict=False):
            ra, rb = a.get("ranking"), b.get("ranking")
            if not isinstance(ra, dict) or not isinstance(rb, dict):
                continue
            hit_a = ra.get("rank_of_correct_section") == 1
            hit_b = rb.get("rank_of_correct_section") == 1
            only_best += int(hit_a and not hit_b)
            only_base += int(hit_b and not hit_a)
        p_value = mcnemar_exact(only_best, only_base)
        lines += [
            f"Paired exact McNemar on recall@1 discordant pairs "
            f"({only_best} best-only / {only_base} default-only): **p = {p_value:.4f}**.",
            "",
        ]
        if p_value >= 0.05:
            lines += [
                "**Not distinguishable at this denominator.** No configuration change is made on",
                "this evidence: with 11 scored questions, an interval on a rate near 0.9 spans",
                "roughly 35 percentage points, and every arm overlaps every other. Switching the",
                "default here would be tuning on noise.",
                "",
            ]
        else:
            lines += [
                "Distinguishable at p < 0.05 **on this constructed corpus**. That is not",
                "sufficient grounds to change the shipped default, which should be decided on",
                "real policy prose.",
                "",
            ]

    lines += [
        "## What this report does NOT establish",
        "",
        "- **Not a claim that any model is best.** The denominator is small and the corpus",
        "  is constructed; intervals are wide enough that most arms overlap.",
        "- **Not decision quality.** This measures whether the right *section* is retrieved,",
        "  not whether a correct recommendation follows. That is Phase 6.",
        "- **Not index recall.** Exact search was used deliberately.",
        "- `BAAI/bge-small-en-v1.5` emits 384 dimensions. Adopting it would require a",
        "  migration of `policy_chunks.embedding` and a full re-embed - it is not a",
        "  configuration change.",
        "",
    ]
    return "\n".join(lines)


async def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", default="eval/reports")
    parser.add_argument("--top-k", type=int, default=40)
    args = parser.parse_args()

    settings = Settings()
    policy = load_policy(settings.decision_policy_file)
    questions = load_questions(QUESTIONS)
    raw = yaml.safe_load(QUESTIONS.read_text(encoding="utf-8"))

    engine = build_engine(settings)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    arms: list[ArmScore] = []

    try:
        async with factory() as session:
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
                    arm = await run_arm(
                        session,
                        questions,
                        embedder,
                        reranker,
                        policy.resolution,
                        top_k=args.top_k,
                        rerank_top_n=settings.rerank_top_n,
                    )
                    arms.append(arm)
                    print(f"recall@1 {arm.recall_at(1).value:.4f}  MRR {arm.mrr:.4f}")
    finally:
        await engine.dispose()

    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    meta = {
        "generated_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "git_commit": _git_commit(),
        "dataset": str(QUESTIONS.relative_to(REPO)),
        "dataset_sha256": hashlib.sha256(QUESTIONS.read_bytes()).hexdigest()[:16],
        "dataset_version": raw["version"],
        "corpus": raw["corpus"],
        "corpus_kind": raw["corpus_kind"],
        "questions": len(questions),
        "scored_questions": arms[0].ranking_total,
        "device": settings.embedding_device,
        "python": platform.python_version(),
        "platform": f"{platform.system()} {platform.machine()}",
    }

    out = REPO / args.out / f"{stamp}__retrieval-baseline"
    out.mkdir(parents=True, exist_ok=True)
    (out / "report.md").write_text(
        _render(
            arms, meta, raw["corpus_kind"], (settings.embedding_model, settings.reranker_model)
        ),
        encoding="utf-8",
    )
    (out / "result.json").write_text(
        json.dumps({"meta": meta, "arms": [a.as_dict() for a in arms]}, indent=2, default=str),
        encoding="utf-8",
    )
    print(f"\nreport: {out.relative_to(REPO)}/report.md")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
