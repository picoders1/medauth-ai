"""Cross-encoder reranking over the ANN candidates.

Reranking earns its cost more here than in general RAG. The candidate pool is small
and lexically homogeneous - within one LCD, "Coverage Indications", "Limitations"
and "Documentation Requirements" share almost all their vocabulary, and a
bi-encoder separates them poorly. A cross-encoder reads the criterion and the
passage together, which is the distinction that matters.

The rerank score margin is also reused as a deterministic feature of the abstention
gate (ADR-011), so this contributes to safety and not only to relevance.

Like the encoder, the model is loaded lazily from the optional ``retrieval`` extra
and its choice stays provisional until the comparison report exists (OD-10).
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import replace
from typing import Protocol, runtime_checkable

import structlog

from app.retrieval.evidence import EvidenceChunk

__all__ = ["CrossEncoderReranker", "Reranker", "rerank", "rerank_margin"]

log = structlog.get_logger(__name__)


@runtime_checkable
class Reranker(Protocol):
    @property
    def model_id(self) -> str: ...

    def score(self, query: str, passages: Sequence[str]) -> list[float]: ...


class CrossEncoderReranker:
    """`sentence-transformers` CrossEncoder, loaded lazily."""

    def __init__(
        self,
        model_id: str = "BAAI/bge-reranker-base",
        *,
        device: str = "cpu",
        batch_size: int = 16,
    ) -> None:
        self._model_id = model_id
        self._device = device
        self._batch_size = batch_size
        self._model: object | None = None

    @property
    def model_id(self) -> str:
        return self._model_id

    def _load(self) -> object:
        if self._model is None:
            try:
                from sentence_transformers import CrossEncoder
            except ImportError as exc:  # pragma: no cover - environment dependent
                raise ImportError(
                    "sentence-transformers is not installed. It lives in the optional "
                    "`retrieval` extra: `uv sync --extra retrieval`"
                ) from exc
            log.info("loading_reranker", model=self._model_id, device=self._device)
            self._model = CrossEncoder(self._model_id, device=self._device)
        return self._model

    def score(self, query: str, passages: Sequence[str]) -> list[float]:
        if not passages:
            return []
        model = self._load()
        scores = model.predict(  # type: ignore[attr-defined]
            [(query, passage) for passage in passages],
            batch_size=self._batch_size,
            show_progress_bar=False,
        )
        return [float(s) for s in scores]


def rerank(
    reranker: Reranker,
    query: str,
    candidates: Sequence[EvidenceChunk],
    *,
    top_n: int,
) -> tuple[EvidenceChunk, ...]:
    """Score candidates against ``query`` and return the best ``top_n``.

    Reranking reorders and truncates. It never introduces a chunk that vector search
    did not return, so the scoping guarantee established by resolution survives it.
    """
    if not candidates:
        return ()
    scores = reranker.score(query, [c.text for c in candidates])
    scored = [replace(c, rerank_score=s) for c, s in zip(candidates, scores, strict=True)]
    scored.sort(key=lambda c: c.rerank_score or float("-inf"), reverse=True)
    return tuple(scored[:top_n])


def rerank_margin(chunks: Sequence[EvidenceChunk]) -> float | None:
    """Gap between the best surviving score and the last one kept.

    A wide margin means the reranker separated the evidence cleanly; a narrow one
    means it could not, which is a signal the abstention gate reads. ``None`` when
    there is nothing to compare.
    """
    scores = [c.rerank_score for c in chunks if c.rerank_score is not None]
    if len(scores) < 2:
        return None
    return round(max(scores) - min(scores), 6)
