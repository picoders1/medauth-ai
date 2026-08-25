"""Score retrieval_v4 ONCE, under the frozen configuration. Part C2/C3.

    uv run python scripts/score_retrieval_v4_baseline.py --write

## One arm, on purpose

`scripts/evaluate_retrieval_v3.py` sweeps two encoders across three rerank options.
This runs the **single configuration the system currently ships** and reports what it
does. That is the whole deliverable: a baseline, not a winner.

Nothing here is a variable. Chunking, `top_k`, `rerank_top_n`, the encoder and the
reranker are read from the same constants the Phase-15 evaluation froze, and the
report records `ENGINEERING_DEFAULT_UNRESOLVED` beside every number so no reader can
mistake "this is what it scores" for "this is what was chosen".

Selecting a configuration on this set is forbidden until OD-35/36's pre-registered
protocol runs (ADR-027). A 36-query benchmark cannot separate arms - `retrieval_v3`
proved that arithmetically at n=31 - and sweeping it anyway would produce a winner
whose margin is noise.

## The metrics are borrowed, deliberately

`eval/runners/retrieval_v2.py` computes them, unchanged: nDCG's ideal is the query's
own labels sorted descending, so it cannot exceed 1 **by construction** rather than
by a clamp somebody remembered; negatives are excluded from the Recall denominator
and scored separately as a false-retrieval rate; single rates carry Wilson intervals.
Re-implementing any of that here would give this project two metric definitions that
agree until they do not.
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import platform
import subprocess
import sys
from collections import Counter
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
from eval.runners.retrieval_v2 import load_questions_v2, run_arm_v2
from eval.schema import ScoringBudgetExhausted, require_scoring_budget

REPO = Path(__file__).resolve().parents[1]
QUESTIONS = REPO / "eval/datasets/retrieval_v4/questions.yaml"
PROVENANCE = REPO / "data/review/retrieval_v4_provenance.json"
OUT = REPO / "eval/reports/retrieval-v4-baseline"

# -- FROZEN. Identical to the Phase-15 evaluation manifest. ---------------------
ENCODER = "BAAI/bge-base-en-v1.5"
RERANKER = "cross-encoder/ms-marco-MiniLM-L-6-v2"
TOP_K = 40
RERANK_TOP_N = 5
CONFIGURATION_STATUS = "ENGINEERING_DEFAULT_UNRESOLVED"


def _git_commit() -> str:
    try:
        return subprocess.run(
            ["git", "rev-parse", "HEAD"], cwd=REPO, capture_output=True, text=True, check=True
        ).stdout.strip()
    except (OSError, subprocess.CalledProcessError):  # pragma: no cover
        return "unknown"


def _check_metrics(arm: dict[str, Any]) -> list[str]:
    """Arithmetic sanity, asserted rather than assumed.

    Every one of these has been wrong in a retrieval report somewhere: an nDCG above
    1 from a single-relevant-item ideal, a recall computed over the wrong
    denominator, a rate with no denominator at all. Checking them here means a
    broken metric fails the run rather than reaching a document.
    """
    problems: list[str] = []
    if not 0.0 <= arm["ndcg_at_5"] <= 1.0:
        problems.append(f"nDCG@5 = {arm['ndcg_at_5']} is outside [0, 1]")
    if not 0.0 <= arm["mrr"] <= 1.0:
        problems.append(f"MRR = {arm['mrr']} is outside [0, 1]")
    for k in (1, 3, 5):
        rate = arm[f"recall_at_{k}"]
        if not 0.0 <= rate["successes"] / max(rate["total"], 1) <= 1.0:
            problems.append(f"Recall@{k} is outside [0, 1]")
        if rate["total"] != arm["ranking_denominator"]:
            problems.append(f"Recall@{k} denominator {rate['total']} != ranking denominator")
    if arm["recall_at_1"]["successes"] > arm["recall_at_3"]["successes"]:
        problems.append("Recall@1 exceeds Recall@3, which is impossible")
    if arm["recall_at_3"]["successes"] > arm["recall_at_5"]["successes"]:
        problems.append("Recall@3 exceeds Recall@5, which is impossible")
    negatives = arm["false_retrieval_rate_on_negatives"]
    if negatives["total"] + arm["ranking_denominator"] == 0:
        problems.append("no query was scored on either denominator")
    return problems


async def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--write", action="store_true")
    args = parser.parse_args()

    provenance = json.loads(PROVENANCE.read_text(encoding="utf-8"))
    if provenance["counts"]["invalid_for_scoring"]:
        # A benchmark scored before its provenance is clean is a benchmark whose
        # numbers describe an unknown corpus.
        print(
            f"  REFUSING: {provenance['counts']['invalid_for_scoring']} queries are "
            "INVALID_FOR_SCORING; fix the audit before scoring",
            file=sys.stderr,
        )
        return 1

    dataset = yaml.safe_load(QUESTIONS.read_text(encoding="utf-8"))
    # Read through the library boundary rather than re-implementing the comparison.
    # The line this replaces was `dataset.get("scoring_budget", 1)` - a **default of
    # one**, so a benchmark that declared no budget silently acquired a free scoring.
    # `eval.schema` has no default: an undeclared allowance is zero (R-103).
    try:
        require_scoring_budget(QUESTIONS, experiment="retrieval_v4-baseline")
    except ScoringBudgetExhausted as spent:
        print(f"  REFUSING: {spent}", file=sys.stderr)
        return 1

    questions = load_questions_v2(QUESTIONS)
    settings = Settings()
    policy = load_policy(settings.decision_policy_file)
    engine = build_engine(settings)
    maker = async_sessionmaker(engine, expire_on_commit=False)

    print(f"  dataset      retrieval_v4, {len(questions)} queries")
    print(f"  encoder      {ENCODER}")
    print(f"  reranker     {RERANKER}")
    print(f"  top_k        {TOP_K}   rerank_top_n {RERANK_TOP_N}")
    print(f"  status       {CONFIGURATION_STATUS}\n")

    try:
        async with maker() as session:
            score = await run_arm_v2(
                session,
                questions,
                policy=policy.resolution,
                embedder=SentenceTransformerEmbedder(ENCODER),
                reranker=CrossEncoderReranker(RERANKER),
                top_k=TOP_K,
                rerank_top_n=RERANK_TOP_N,
            )
    finally:
        await engine.dispose()

    arm = score.as_dict()
    problems = _check_metrics(arm)
    if problems:
        print(f"  REFUSING: the metrics are not arithmetically sound: {problems}", file=sys.stderr)
        return 1

    report = {
        "experiment": "retrieval-v4-baseline",
        "ran_at": datetime.now(UTC).isoformat(),
        "git_commit": _git_commit(),
        "python": platform.python_version(),
        "dataset": {
            "version": "retrieval_v4",
            "path": "eval/datasets/retrieval_v4/questions.yaml",
            "sha256": hashlib.sha256(QUESTIONS.read_bytes()).hexdigest(),
            "queries": len(questions),
            "categories": dict(sorted(Counter(q.category for q in questions).items())),
            "provenance_audit": "data/review/retrieval_v4_provenance.json",
            "invalid_for_scoring": provenance["counts"]["invalid_for_scoring"],
        },
        "configuration": {
            "status": CONFIGURATION_STATUS,
            "embedding_model": ENCODER,
            "reranker_model": RERANKER,
            "top_k": TOP_K,
            "rerank_top_n": RERANK_TOP_N,
            "chunking": "section-aware, never crossing a section boundary (Phase 1)",
            "note": (
                "FROZEN and identical to the Phase-15 evaluation manifest. Nothing "
                "here was selected on evidence; this run measures it, and no claim "
                "about it may be drawn from the result."
            ),
        },
        "arm": arm,
        "metric_definitions": {
            "recall_at_k": (
                "a RELEVANT section appears in the top k. Denominator excludes "
                "NEGATIVE queries, which have no relevant section to recall."
            ),
            "ndcg_at_5": (
                "graded gains, ideal = this query's own labels sorted descending. "
                "Bounded by 1 BY CONSTRUCTION, not by a clamp."
            ),
            "false_retrieval_rate_on_negatives": (
                "top-1 result on a NEGATIVE query that the query's labels call not "
                "relevant. Reported separately, with its own denominator."
            ),
            "implementation": "eval/runners/retrieval_v2.py, unchanged",
        },
        "arithmetic_checks": "passed: nDCG and MRR in [0,1], recall monotone in k, denominators consistent",
        "interpretation": {
            "claim_permitted": (
                "The retrieval baseline of the currently frozen configuration on a "
                "provenance-clean 36-query benchmark, with denominators and intervals."
            ),
            "claims_refused": [
                "that this configuration is best, or better than any other",
                "that a difference from retrieval_v2 or v3 is attributable to the "
                "configuration - the benchmarks differ",
                "that 36 queries can separate arms (retrieval_v3 established they cannot at n=31)",
                "anything about clinical accuracy",
            ],
        },
    }

    print(
        f"  Recall@1 {arm['recall_at_1']['successes']}/{arm['recall_at_1']['total']} = "
        f"{arm['recall_at_1']['successes'] / max(arm['recall_at_1']['total'], 1):.4f}"
    )
    print(
        f"  Recall@3 {arm['recall_at_3']['successes']}/{arm['recall_at_3']['total']}   "
        f"Recall@5 {arm['recall_at_5']['successes']}/{arm['recall_at_5']['total']}"
    )
    print(
        f"  MRR      {arm['mrr']:.4f}   nDCG@5 {arm['ndcg_at_5']:.4f}   P@3 {arm['precision_at_3']:.4f}"
    )
    print(
        f"  negatives false-retrieval "
        f"{arm['false_retrieval_rate_on_negatives']['successes']}/"
        f"{arm['false_retrieval_rate_on_negatives']['total']}"
    )
    print(f"  latency  p50 {arm['latency_p50_ms']:.1f} ms   p95 {arm['latency_p95_ms']:.1f} ms")

    if args.write:
        OUT.mkdir(parents=True, exist_ok=True)
        (OUT / "results.json").write_text(
            json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )
        # The dataset records its own spend, so a second scoring has to be a
        # deliberate act against a visible counter rather than a re-run.
        dataset["scorings_spent"] = 1
        dataset["scored"] = True
        dataset["scored_at"] = report["ran_at"]
        dataset["scored_by"] = "scripts/score_retrieval_v4_baseline.py"
        QUESTIONS.write_text(
            yaml.safe_dump(dataset, sort_keys=False, allow_unicode=True, width=100),
            encoding="utf-8",
        )
        print(f"\n  written to {(OUT / 'results.json').relative_to(REPO)}")
        print("  retrieval_v4 scoring budget now 1/1 - spent")
    else:
        print("\n  (dry run; pass --write)")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
