"""Retrieval evaluation v2: graded relevance, negative queries, correct nDCG.

v1 could not fail. 21 of 33 criteria covered, no negative and no ambiguous
queries, and Recall@3 of 0.9524 across every arm - six configurations tying is
not a measurement of any of them. This runner scores a set built to discriminate.

Three things are different, and each is a correctness fix rather than a feature:

**Graded relevance.** A query whose answer spans two sections is badly described
by one binary target. Labels are RELEVANT (2), PARTIALLY_RELEVANT (1) and
NOT_RELEVANT (0), and the gain is the label - so a retriever that surfaces
context above the answer scores below one that gets the order right.

**Negative queries.** Some questions have no answer in the corpus. A vector search
always returns something, so the measurement is not "did it find the answer" but
"how confidently did it offer a non-answer". Scored as a false-retrieval rate with
its own denominator, never folded into recall.

**nDCG that cannot exceed 1.** The ideal ranking is the actual labels sorted
descending, truncated at k. The v1 bug - assuming exactly one relevant chunk when a
target section spans several - produced nDCG above 1.0, which is impossible, and
that impossibility was the only reason it was noticed. Here the ideal is computed
from the same label multiset that produced the gains, so the bound holds by
construction and is asserted by test.

Resolution and ranking stay reported apart, as in v1: a resolution error is a rule
or data defect that no amount of better ranking recovers from.
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

__all__ = ["ArmScoreV2", "QuestionV2", "dcg", "load_questions_v2", "ndcg", "run_arm_v2"]

#: Graded gains. The spacing is deliberate: a partially relevant section is worth
#: having, and worth less than the answer.
GAIN = {"RELEVANT": 2, "PARTIALLY_RELEVANT": 1, "NOT_RELEVANT": 0}


@dataclass(frozen=True, slots=True)
class QuestionV2:
    id: str
    category: str
    text: str
    reason_for_inclusion: str
    procedure_code: str
    code_system: CodeSystem
    as_of: date
    jurisdiction: str | None
    #: section_path -> label. Sections absent from this map are NOT_RELEVANT.
    relevance: dict[str, str] = field(default_factory=dict)
    expect_policy_id: str | None = None
    expect_revision_id: str | None = None
    expect_criterion_id: str | None = None
    #: No chunk in the corpus answers this. Scored as false retrieval, not recall.
    expect_no_relevant: bool = False
    #: Structurally unreachable from a procedure code (411.15 declares none).
    unreachable_by_resolution: bool = False
    note: str = ""

    def gain_for(self, section_path: str) -> int:
        return GAIN[self.relevance.get(section_path, "NOT_RELEVANT")]


def load_questions_v2(path: Path | str) -> tuple[QuestionV2, ...]:
    raw = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    questions: list[QuestionV2] = []
    for entry in raw["questions"]:
        expect = entry.get("expect") or {}
        relevance = {str(r["section_path"]): str(r["label"]) for r in expect.get("relevance", [])}
        for label in relevance.values():
            if label not in GAIN:
                raise ValueError(f"{entry['id']}: unknown relevance label {label!r}")
        if entry.get("expect_no_relevant") and relevance:
            raise ValueError(
                f"{entry['id']}: a negative query cannot also declare relevant sections"
            )
        if not entry.get("reason_for_inclusion", "").strip():
            raise ValueError(f"{entry['id']}: every query must state why it exists")
        questions.append(
            QuestionV2(
                id=str(entry["id"]),
                category=str(entry["category"]),
                text=str(entry["text"]),
                reason_for_inclusion=str(entry["reason_for_inclusion"]).strip(),
                procedure_code=str(entry["procedure_code"]),
                code_system=CodeSystem(str(entry["code_system"])),
                as_of=entry["as_of"]
                if isinstance(entry["as_of"], date)
                else date.fromisoformat(str(entry["as_of"])),
                jurisdiction=entry.get("jurisdiction"),
                relevance=relevance,
                expect_policy_id=expect.get("policy_id"),
                expect_revision_id=str(expect["revision_id"])
                if expect.get("revision_id")
                else None,
                expect_criterion_id=expect.get("criterion_id"),
                expect_no_relevant=bool(entry.get("expect_no_relevant", False)),
                unreachable_by_resolution=bool(entry.get("unreachable_by_resolution", False)),
                note=str(
                    entry.get("temporal_note")
                    or entry.get("ambiguity_note")
                    or entry.get("distractor_note")
                    or entry.get("cross_policy_note")
                    or ""
                ),
            )
        )
    ids = [q.id for q in questions]
    if len(set(ids)) != len(ids):
        raise ValueError("duplicate question ids")
    return tuple(questions)


def dcg(gains: list[int], k: int) -> float:
    return sum(g / math.log2(i + 2) for i, g in enumerate(gains[:k]))


def ndcg(gains: list[int], k: int) -> float:
    """nDCG@k over graded gains. Cannot exceed 1.

    The ideal is *this query's own labels* sorted descending and truncated at k.
    Because the gains list and the ideal list are the same multiset, no ranking can
    score above the ideal - the bound holds by construction rather than by
    remembering to clamp it. v1 assumed a single relevant item and produced values
    above 1.0; a `test_ndcg_never_exceeds_one` fuzz test pins this.
    """
    ideal = dcg(sorted(gains, reverse=True), k)
    return dcg(gains, k) / ideal if ideal else 0.0


@dataclass
class ArmScoreV2:
    embedder: str
    reranker: str | None
    resolution_correct: int = 0
    resolution_total: int = 0
    ranking_total: int = 0
    hit_at_1: int = 0
    hit_at_3: int = 0
    hit_at_5: int = 0
    reciprocal_ranks: list[float] = field(default_factory=list)
    ndcg_at_5: list[float] = field(default_factory=list)
    precision_at_3: list[float] = field(default_factory=list)
    #: Negative queries: a "false retrieval" is a top-1 result the query's own
    #: labels say is not relevant - which for a negative query is every chunk.
    negative_total: int = 0
    negative_false_retrievals: int = 0
    negative_top_scores: list[float] = field(default_factory=list)
    latencies_ms: list[float] = field(default_factory=list)
    per_question: list[dict[str, Any]] = field(default_factory=list)
    by_category: dict[str, dict[str, int]] = field(default_factory=dict)

    def resolution_accuracy(self) -> Rate:
        return wilson_interval(self.resolution_correct, self.resolution_total)

    def recall_at(self, k: int) -> Rate:
        hits = {1: self.hit_at_1, 3: self.hit_at_3, 5: self.hit_at_5}[k]
        return wilson_interval(hits, self.ranking_total)

    def false_retrieval_rate(self) -> Rate:
        return wilson_interval(self.negative_false_retrievals, self.negative_total)

    @staticmethod
    def _mean(values: list[float]) -> float:
        return round(sum(values) / len(values), 4) if values else 0.0

    def _percentile(self, p: float) -> float:
        if not self.latencies_ms:
            return 0.0
        ordered = sorted(self.latencies_ms)
        return round(ordered[min(int(p * len(ordered)), len(ordered) - 1)], 2)

    def as_dict(self) -> dict[str, Any]:
        return {
            "embedder": self.embedder,
            "reranker": self.reranker,
            "resolution_accuracy": asdict(self.resolution_accuracy()),
            "recall_at_1": asdict(self.recall_at(1)),
            "recall_at_3": asdict(self.recall_at(3)),
            "recall_at_5": asdict(self.recall_at(5)),
            "mrr": self._mean(self.reciprocal_ranks),
            "ndcg_at_5": self._mean(self.ndcg_at_5),
            "precision_at_3": self._mean(self.precision_at_3),
            "false_retrieval_rate_on_negatives": asdict(self.false_retrieval_rate()),
            "negative_mean_top_score": self._mean(self.negative_top_scores),
            "latency_p50_ms": self._percentile(0.50),
            "latency_p95_ms": self._percentile(0.95),
            "ranking_denominator": self.ranking_total,
            "resolution_denominator": self.resolution_total,
            "negative_denominator": self.negative_total,
            "by_category": self.by_category,
        }


def _cosine(a: list[float], b: list[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b, strict=True))
    na = math.sqrt(sum(x * x for x in a)) or 1.0
    nb = math.sqrt(sum(y * y for y in b)) or 1.0
    return dot / (na * nb)


async def run_arm_v2(
    session: AsyncSession,
    questions: tuple[QuestionV2, ...],
    embedder: Embedder,
    reranker: Reranker | None,
    policy: ResolutionPolicy,
    *,
    top_k: int = 40,
    rerank_top_n: int = 5,
) -> ArmScoreV2:
    """Score one configuration. `top_k` and `rerank_top_n` are fixed across arms."""
    score = ArmScoreV2(embedder=embedder.model_id, reranker=reranker.model_id if reranker else None)

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
            "category": question.category,
            "text": question.text,
            "criterion_id": question.expect_criterion_id,
        }
        bucket = score.by_category.setdefault(
            question.category, {"scored": 0, "hit_at_1": 0, "hit_at_3": 0, "excluded": 0}
        )

        if question.unreachable_by_resolution:
            entry["excluded"] = "not reachable by resolution from a procedure code"
            bucket["excluded"] += 1
            score.per_question.append(entry)
            continue

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
        resolved = {(v.policy_id, v.revision_id) for v in resolution.versions}

        if not question.expect_no_relevant:
            score.resolution_total += 1
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
                entry["ranking"] = "not scored - resolution was wrong"
                score.per_question.append(entry)
                continue
        else:
            entry["resolution"] = {"status": resolution.status.value, "negative_query": True}
            if not resolution.versions:
                entry["ranking"] = "not scored - negative query did not resolve"
                score.per_question.append(entry)
                continue

        scope = {v.version_id for v in resolution.versions}
        candidates = [
            (chunk, version, document, corpus_vectors[i])
            for i, (chunk, version, document) in enumerate(rows)
            if str(version.id) in scope
        ]
        if not candidates:
            entry["ranking"] = "not scored - empty scope"
            score.per_question.append(entry)
            continue

        started = time.perf_counter()
        query_vector = embedder.encode_query(question.text)
        scored_candidates = [(c, _cosine(query_vector, c[3])) for c in candidates]
        ranked = [c for c, _ in sorted(scored_candidates, key=lambda p: -p[1])[:top_k]]
        top_score = max(s for _, s in scored_candidates)

        if reranker is not None and ranked:
            rerank_scores = reranker.score(question.text, [c[0].text for c in ranked])
            ranked = [
                c for _, c in sorted(zip(rerank_scores, ranked, strict=True), key=lambda p: -p[0])
            ][:rerank_top_n]
        score.latencies_ms.append((time.perf_counter() - started) * 1000)

        gains = [question.gain_for(chunk.section_path) for chunk, _, _, _ in ranked]

        if question.expect_no_relevant:
            # Every chunk is NOT_RELEVANT by construction, so any confident top-1
            # is a false retrieval. The similarity score is kept alongside it: a
            # near-miss surfaced at 0.31 is a different failure from one at 0.82.
            score.negative_total += 1
            score.negative_false_retrievals += 1
            score.negative_top_scores.append(top_score)
            entry["negative"] = {
                "top_section": ranked[0][0].section_path if ranked else None,
                "top_similarity": round(top_score, 4),
            }
            score.per_question.append(entry)
            continue

        score.ranking_total += 1
        bucket["scored"] += 1
        rank = next((i + 1 for i, g in enumerate(gains) if g == GAIN["RELEVANT"]), None)
        score.hit_at_1 += int(rank is not None and rank <= 1)
        score.hit_at_3 += int(rank is not None and rank <= 3)
        score.hit_at_5 += int(rank is not None and rank <= 5)
        bucket["hit_at_1"] += int(rank is not None and rank <= 1)
        bucket["hit_at_3"] += int(rank is not None and rank <= 3)
        score.reciprocal_ranks.append(1 / rank if rank else 0.0)
        score.ndcg_at_5.append(ndcg(gains, 5))
        score.precision_at_3.append(sum(1 for g in gains[:3] if g > 0) / 3)

        entry["ranking"] = {
            "rank_of_relevant_section": rank,
            "top_sections": [
                (c[0].section_path, question.relevance.get(c[0].section_path, "NOT_RELEVANT"))
                for c in ranked[:3]
            ],
            "ndcg_at_5": round(ndcg(gains, 5), 4),
        }
        score.per_question.append(entry)

    return score
