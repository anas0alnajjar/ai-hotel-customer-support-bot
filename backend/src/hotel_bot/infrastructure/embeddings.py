"""Embedding adapters with a production multilingual model and an offline test double."""

import hashlib
import importlib
import math
import re
from collections.abc import Sequence
from pathlib import Path
from typing import Any, Protocol, cast

from hotel_bot.domain.knowledge.errors import KnowledgeValidationError

TOKEN_PATTERN = re.compile(r"[\w\u0600-\u06ff]+", re.UNICODE)


def _l2_normalize(vector: list[float]) -> list[float]:
    norm = math.sqrt(sum(value * value for value in vector))
    if norm == 0:
        return vector
    return [value / norm for value in vector]


class HashingEmbeddingProvider:
    """Deterministic multilingual lexical embedder reserved for tests and offline CI."""

    def __init__(self, *, dimension: int = 384) -> None:
        if dimension < 8:
            raise ValueError("hashing embedding dimension must be at least 8")
        self._dimension = dimension

    @property
    def model_id(self) -> str:
        return f"hashing-test-v1:{self._dimension}"

    @property
    def dimension(self) -> int:
        return self._dimension

    def embed_documents(self, texts: Sequence[str]) -> list[list[float]]:
        return [self._embed(text) for text in texts]

    def embed_query(self, text: str) -> list[float]:
        return self._embed(text)

    def _embed(self, text: str) -> list[float]:
        normalized = " ".join(text.casefold().split())
        features = TOKEN_PATTERN.findall(normalized)
        compact = normalized.replace(" ", "")
        features.extend(compact[index : index + 3] for index in range(max(0, len(compact) - 2)))
        vector = [0.0] * self._dimension
        for feature in features:
            digest = hashlib.blake2b(feature.encode("utf-8"), digest_size=8).digest()
            bucket = int.from_bytes(digest[:4], "big") % self._dimension
            sign = 1.0 if digest[4] & 1 else -1.0
            vector[bucket] += sign
        return _l2_normalize(vector)


class _SentenceTransformerModel(Protocol):
    def get_sentence_embedding_dimension(self) -> int | None: ...

    def encode(
        self,
        sentences: str | Sequence[str],
        *,
        batch_size: int = ...,
        convert_to_numpy: bool = ...,
        normalize_embeddings: bool = ...,
        show_progress_bar: bool = ...,
    ) -> Any: ...


class SentenceTransformerEmbeddingProvider:
    """Lazy Sentence Transformers adapter pinned to a model revision."""

    def __init__(
        self,
        *,
        model_name: str,
        revision: str,
        expected_dimension: int,
        batch_size: int = 32,
        cache_path: Path | None = None,
    ) -> None:
        if not model_name.strip() or not revision.strip():
            raise ValueError("embedding model and revision are required")
        self._model_name = model_name.strip()
        self._revision = revision.strip()
        self._expected_dimension = expected_dimension
        self._batch_size = batch_size
        self._cache_path = cache_path
        self._model: _SentenceTransformerModel | None = None

    @property
    def model_id(self) -> str:
        return f"{self._model_name}@{self._revision}"

    @property
    def dimension(self) -> int:
        return self._expected_dimension

    def embed_documents(self, texts: Sequence[str]) -> list[list[float]]:
        if not texts:
            return []
        values = self._load().encode(
            list(texts),
            batch_size=self._batch_size,
            convert_to_numpy=True,
            normalize_embeddings=True,
            show_progress_bar=False,
        )
        return cast(list[list[float]], values.tolist())

    def embed_query(self, text: str) -> list[float]:
        values = self._load().encode(
            text,
            convert_to_numpy=True,
            normalize_embeddings=True,
            show_progress_bar=False,
        )
        return cast(list[float], values.tolist())

    def _load(self) -> _SentenceTransformerModel:
        if self._model is not None:
            return self._model
        try:
            module = importlib.import_module("sentence_transformers")
        except ImportError as exc:
            raise RuntimeError(
                "sentence-transformers is not installed; install the 'embeddings' extra"
            ) from exc
        model_class = cast(Any, module).SentenceTransformer
        model = cast(
            _SentenceTransformerModel,
            model_class(
                self._model_name,
                revision=self._revision,
                cache_folder=str(self._cache_path) if self._cache_path else None,
            ),
        )
        actual_dimension = model.get_sentence_embedding_dimension()
        if actual_dimension != self._expected_dimension:
            raise KnowledgeValidationError(
                "embedding_dimension_mismatch",
                f"configured dimension {self._expected_dimension} does not match model dimension "
                f"{actual_dimension}",
            )
        self._model = model
        return model
