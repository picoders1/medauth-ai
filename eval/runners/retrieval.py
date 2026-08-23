"""Retrieval evaluation: resolution accuracy and ranking quality, reported apart.

The two are measured separately and never averaged, because they fail differently
and are fixed differently. A resolution error is a rule or data defect - the wrong
policy version was selected, and no amount of better ranking recovers from it. A
ranking error is a model defect within a correctly-scoped set. Folding them into
one number would let a corpus gap masquerade as an encoder problem.

Ranking is scored with **exact** cosine similarity rather than through the pgvector
HNSW index. That is deliberate: the question here is which encoder separates this
corpus best, and ANN approximation would confound the comparison with index recall.
Index behaviour is exercised separately, by the integration tests.
"""

from __future__ import annotations

import math
import time
from dataclasses import asdict, dataclass, field
from datetime import date
from pathlib import Path
from typing import Any

import yaml
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config.policy import ResolutionPolicy
from app.core.types import CodeSystem
from app.policy.models import PolicyChunk, PolicyDocument, PolicyVersion
from app.policy.resolve import ResolutionRequest, resolve
from app.retrieval.embed import Embedder
from app.retrieval.rerank import Reranker
from eval.metrics.statistics import Rate, wilson_interval

__all__ = ["ArmScore", "Question", "load_questions", "run_arm"]


@dataclass(frozen=True, slots=True)
class Question:
    id: str
    text: str
    procedure_code: str
    code_system: CodeSystem
    as_of: date
    jurisdiction: str | None
    expect_policy_id: str
    expect_revision_id: str
    expect_section_path: str
    #: Which policy requirement this query targets. Lets a retrieval failure be
    #: attributed to a specific criterion instead of to "the corpus".
    expect_criterion_id: str | None = None
    unreachable_by_resolution: bool = False
    note: str = ""


def load_questions(path: Path | str) -> tuple[Question, ...]:
    raw = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    questions = []
    for entry in raw["questions"]:
        expect = entry["expect"]
        as_of = entry["as_of"]
        questions.append(
            Question(
                id=entry["id"],
                text=entry["text"],
                procedure_code=str(entry["procedure_code"]),
                code_system=CodeSystem(entry["code_system"]),
                as_of=as_of if isinstance(as_of, date) else date.fromisoformat(str(as_of)),
                jurisdiction=entry.get("jurisdiction"),
                expect_policy_id=str(expect["policy_id"]),
                expect_revision_id=expect["revision_id"],
                expect_section_path=expect["section_path"],
                expect_criterion_id=expect.get("criterion_id"),
                unreachable_by_resolution=bool(entry.get("unreachable_by_resolution", False)),
                note=entry.get("note", ""),
            )
        )
    return tuple(questions)


@dataclass
class ArmScore:
    """One (embedder, reranker) configuration scored on the frozen set."""

    embedder: str
    reranker: str | None
    resolution_correct: int = 0
    resolution_total: int = 0
    hit_at_1: int = 0
    hit_at_3: int = 0
    hit_at_5: int = 0
    ranking_total: int = 0
    reciprocal_ranks: list[float] = field(default_factory=list)
    ndcg_scores: list[float] = field(default_factory=list)
    #: Per-query wall time for the ranking stage only, in milliseconds. Encoding the
    #: corpus is excluded: it happens once per arm, not once per query.
    latencies_ms: list[float] = field(default_factory=list)
    per_question: list[dict[str, Any]] = field(default_factory=list)

    @property
    def resolution_accuracy(self) -> Rate:
        return wilson_interval(self.resolution_correct, self.resolution_total)

    def recall_at(self, k: int) -> Rate:
        hits = {1: self.hit_at_1, 3: self.hit_at_3, 5: self.hit_at_5}[k]
        return wilson_interval(hits, self.ranking_total)

    @property
    def mrr(self) -> float:
        return (
            round(sum(self.reciprocal_ranks) / len(self.reciprocal_ranks), 4)
            if self.reciprocal_ranks
            else 0.0
        )

    @property
    def latency_p50_ms(self) -> float:
        ordered = sorted(self.latencies_ms)
        return round(ordered[len(ordered) // 2], 2) if ordered else 0.0

    @property
    def latency_p95_ms(self) -> float:
        ordered = sorted(self.latencies_ms)
        return round(ordered[int(len(ordered) * 0.95)], 2) if ordered else 0.0

    @property
    def ndcg_at_5(self) -> float:
        return round(sum(self.ndcg_scores) / len(self.ndcg_scores), 4) if self.ndcg_scores else 0.0

    def as_dict(self) -> dict[str, Any]:
        return {
            "embedder": self.embedder,
            "reranker": self.reranker,
            "resolution_accuracy": asdict(self.resolution_accuracy),
            "recall_at_1": asdict(self.recall_at(1)),
            "recall_at_3": asdict(self.recall_at(3)),
            "recall_at_5": asdict(self.recall_at(5)),
            "mrr": self.mrr,
            "ndcg_at_5": self.ndcg_at_5,
            "latency_p50_ms": self.latency_p50_ms,
            "latency_p95_ms": self.latency_p95_ms,
            "per_question": self.per_question,
        }


def _cosine(a: list[float], b: list[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b, strict=True))
    na = math.sqrt(sum(x * x for x in a)) or 1.0
    nb = math.sqrt(sum(y * y for y in b)) or 1.0
    return dot / (na * nb)


def _ndcg(relevance: list[int], k: int = 5) -> float:
    """Binary-relevance nDCG@k.

    The ideal ranking puts every relevant item first, and a target *section*
    typically spans several chunks - so the ideal DCG sums over as many relevant
    items as exist, capped at k. Assuming exactly one relevant item made the ideal
    too small and produced nDCG above 1.0, which is impossible and was the signal
    that the metric was wrong.
    """
    gains = sum(rel / math.log2(i + 2) for i, rel in enumerate(relevance[:k]))
    relevant = min(sum(relevance), k)
    ideal = sum(1 / math.log2(i + 2) for i in range(relevant))
    return gains / ideal if ideal else 0.0


async def run_arm(
    session: AsyncSession,
    questions: tuple[Question, ...],
    embedder: Embedder,
    reranker: Reranker | None,
    policy: ResolutionPolicy,
    *,
    top_k: int = 40,
    rerank_top_n: int = 5,
) -> ArmScore:
    """Score one configuration over the frozen question set."""
    score = ArmScore(embedder=embedder.model_id, reranker=reranker.model_id if reranker else None)

    # Embed the whole corpus once per encoder; ranking is exact cosine (see module
    # docstring), so the pgvector index is not exercised here.
    rows = (
        await session.execute(
            select(PolicyChunk, PolicyVersion, PolicyDocument)
            .join(PolicyVersion, PolicyVersion.id == PolicyChunk.policy_version_id)
            .join(PolicyDocument, PolicyDocument.id == PolicyVersion.document_id)
        )
    ).all()
    corpus_vectors = embedder.encode_passages([chunk.text for chunk, _, _ in rows])

    for question in questions:
        entry: dict[str, Any] = {
            "id": question.id,
            "text": question.text,
            "criterion_id": question.expect_criterion_id,
        }

        resolution = await resolve(
            session,
            ResolutionRequest(
                procedure_code=question.procedure_code,
                code_system=question.code_system,
                as_of=question.as_of,
                jurisdiction=question.jurisdiction,
            ),
            policy,
        )

        if question.unreachable_by_resolution:
            # Excluded from both denominators, and the reason is recorded rather
            # than the question being quietly dropped.
            entry["excluded"] = "not reachable by resolution from a procedure code"
            score.per_question.append(entry)
            continue

        score.resolution_total += 1
        resolved = {(v.policy_id, v.revision_id) for v in resolution.versions}
        expected = (question.expect_policy_id, question.expect_revision_id)
        resolution_ok = expected in resolved
        score.resolution_correct += int(resolution_ok)
        entry["resolution"] = {
            "status": resolution.status.value,
            "expected": list(expected),
            "resolved": sorted(list(r) for r in resolved),
            "correct": resolution_ok,
        }

        if not resolution_ok:
            # Ranking is not scored on a wrongly-scoped set: it would measure the
            # encoder against evidence that could never be right.
            entry["ranking"] = "not scored - resolution was wrong"
            score.per_question.append(entry)
            continue

        scope = {v.version_id for v in resolution.versions}
        candidates = [
            (chunk, version, document, corpus_vectors[i])
            for i, (chunk, version, document) in enumerate(rows)
            if str(version.id) in scope
        ]
        started = time.perf_counter()
        query_vector = embedder.encode_query(question.text)
        ranked = sorted(candidates, key=lambda c: _cosine(query_vector, c[3]), reverse=True)[:top_k]

        if reranker is not None and ranked:
            scores = reranker.score(question.text, [c[0].text for c in ranked])
            ranked = [c for _, c in sorted(zip(scores, ranked, strict=True), key=lambda p: -p[0])][
                :rerank_top_n
            ]
        score.latencies_ms.append((time.perf_counter() - started) * 1000)

        relevance = [
            int(
                chunk.section_path == question.expect_section_path
                and document.policy_id == question.expect_policy_id
            )
            for chunk, _, document, *_ in ranked
        ]
        score.ranking_total += 1
        rank = next((i + 1 for i, rel in enumerate(relevance) if rel), None)
        score.hit_at_1 += int(bool(rank) and rank <= 1)
        score.hit_at_3 += int(bool(rank) and rank <= 3)
        score.hit_at_5 += int(bool(rank) and rank <= 5)
        score.reciprocal_ranks.append(1 / rank if rank else 0.0)
        score.ndcg_scores.append(_ndcg(relevance))

        entry["ranking"] = {
            "rank_of_correct_section": rank,
            "top_sections": [c[0].section_path for c in ranked[:3]],
        }
        score.per_question.append(entry)

    return score
