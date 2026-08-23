"""Local encoders. These do not traverse the firewall.

The firewall exposes no ``/v1/embeddings``, and inspecting a corpus embedding
request would serve no security purpose - the corpus is public policy text and the
query is criterion text, neither of which is a caller turn a detector could
usefully classify (ADR-006, ADR-016). So embedding runs in-process, on CPU by
default, with no egress.

``sentence_transformers`` and ``torch`` live in the optional ``retrieval`` extra and
are imported lazily. That keeps the default image small and lets every test that
does not need a real encoder run without a 2 GB dependency - which matters, because
the properties worth testing here (scoping, temporal filtering, citation
verification) are not properties of the encoder.

Model choice is provisional until the Phase 1 comparison report exists. Until then
the word "best" is not used (OD-10).
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Protocol, runtime_checkable

import structlog

__all__ = ["QUERY_INSTRUCTIONS", "Embedder", "SentenceTransformerEmbedder"]

log = structlog.get_logger(__name__)

#: Asymmetric retrieval models expect the *query* side to carry an instruction
#: prefix while passages are encoded bare. Omitting it silently degrades recall,
#: and the degradation looks like a ranking problem rather than a configuration
#: one, so the mapping is explicit here rather than assumed.
QUERY_INSTRUCTIONS: dict[str, str] = {
    "BAAI/bge-base-en-v1.5": "Represent this sentence for searching relevant passages: ",
    "BAAI/bge-small-en-v1.5": "Represent this sentence for searching relevant passages: ",
    "BAAI/bge-large-en-v1.5": "Represent this sentence for searching relevant passages: ",
    "intfloat/e5-base-v2": "query: ",
    "intfloat/e5-small-v2": "query: ",
}

#: Passage-side prefixes, where the model expects one.
PASSAGE_INSTRUCTIONS: dict[str, str] = {
    "intfloat/e5-base-v2": "passage: ",
    "intfloat/e5-small-v2": "passage: ",
}


@runtime_checkable
class Embedder(Protocol):
    """What retrieval needs from an encoder. Deliberately small."""

    @property
    def model_id(self) -> str: ...

    @property
    def dimension(self) -> int: ...

    def encode_passages(self, texts: Sequence[str]) -> list[list[float]]: ...

    def encode_query(self, text: str) -> list[float]: ...


class SentenceTransformerEmbedder:
    """`sentence-transformers` encoder, loaded lazily and normalized for cosine."""

    def __init__(
        self,
        model_id: str = "BAAI/bge-base-en-v1.5",
        *,
        device: str = "cpu",
        batch_size: int = 32,
    ) -> None:
        self._model_id = model_id
        self._device = device
        self._batch_size = batch_size
        self._model: object | None = None
        self._dimension: int | None = None

    @property
    def model_id(self) -> str:
        return self._model_id

    def _load(self) -> object:
        if self._model is None:
            try:
                from sentence_transformers import SentenceTransformer
            except ImportError as exc:  # pragma: no cover - environment dependent
                raise ImportError(
                    "sentence-transformers is not installed. It lives in the optional "
                    "`retrieval` extra: `uv sync --extra retrieval`"
                ) from exc
            log.info("loading_encoder", model=self._model_id, device=self._device)
            self._model = SentenceTransformer(self._model_id, device=self._device)
        return self._model

    @property
    def dimension(self) -> int:
        """Measured from the loaded model, never assumed.

        Ingest compares this against the vector column width and refuses to write on
        a mismatch, because a silently truncated embedding degrades retrieval in a
        way that looks like a model-quality problem.
        """
        if self._dimension is None:
            model = self._load()
            self._dimension = int(model.get_sentence_embedding_dimension())  # type: ignore[attr-defined]
        return self._dimension

    def _encode(self, texts: Sequence[str]) -> list[list[float]]:
        model = self._load()
        vectors = model.encode(  # type: ignore[attr-defined]
            list(texts),
            batch_size=self._batch_size,
            convert_to_numpy=True,
            # Unit-normalized, so cosine distance and inner product agree and the
            # pgvector HNSW index built with vector_cosine_ops is used as intended.
            normalize_embeddings=True,
            show_progress_bar=False,
        )
        return [[float(x) for x in row] for row in vectors]

    def encode_passages(self, texts: Sequence[str]) -> list[list[float]]:
        prefix = PASSAGE_INSTRUCTIONS.get(self._model_id, "")
        return self._encode([f"{prefix}{t}" for t in texts] if prefix else list(texts))

    def encode_query(self, text: str) -> list[float]:
        prefix = QUERY_INSTRUCTIONS.get(self._model_id, "")
        return self._encode([f"{prefix}{text}"])[0]
