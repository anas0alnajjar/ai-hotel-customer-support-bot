"""Versioned, checksummed FAISS artifact storage with atomic publication."""

import hashlib
import json
import os
import shutil
from collections.abc import Sequence
from pathlib import Path
from typing import Any, cast
from uuid import UUID, uuid4

import faiss
import numpy as np

from hotel_bot.domain.knowledge.errors import IndexUnavailableError, KnowledgeValidationError
from hotel_bot.domain.knowledge.models import IndexArtifact

SCHEMA_VERSION = 1
INDEX_FILENAME = "index.faiss"
MANIFEST_FILENAME = "manifest.json"


def _canonical_json(payload: dict[str, Any]) -> bytes:
    return json.dumps(payload, ensure_ascii=False, separators=(",", ":"), sort_keys=True).encode(
        "utf-8"
    )


def _sha256(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


class FaissIndexStore:
    """Stores one immutable exact-cosine index per database index version."""

    def __init__(self, root: Path) -> None:
        self._root = root.resolve()

    def build(
        self,
        *,
        index_version_id: UUID,
        embedding_model: str,
        vectors: Sequence[Sequence[float]],
        chunk_keys: Sequence[str],
    ) -> IndexArtifact:
        matrix = np.asarray(vectors, dtype=np.float32)
        if matrix.ndim != 2 or matrix.shape[0] == 0 or matrix.shape[1] == 0:
            raise KnowledgeValidationError(
                "invalid_embedding_matrix", "embedding matrix must be non-empty and two-dimensional"
            )
        if matrix.shape[0] != len(chunk_keys):
            raise KnowledgeValidationError(
                "embedding_chunk_mismatch", "vector and chunk key counts do not match"
            )
        if not np.isfinite(matrix).all():
            raise KnowledgeValidationError(
                "invalid_embedding_values", "embedding matrix contains non-finite values"
            )
        norms = np.linalg.norm(matrix, axis=1, keepdims=True)
        if np.any(norms == 0):
            raise KnowledgeValidationError(
                "zero_embedding_vector", "embedding matrix contains a zero vector"
            )
        matrix = matrix / norms

        self._root.mkdir(parents=True, exist_ok=True)
        relative_path = str(index_version_id)
        final_dir = self._root / relative_path
        if final_dir.exists():
            raise KnowledgeValidationError(
                "index_artifact_exists", "immutable index artifact already exists"
            )
        temporary_dir = self._root / f".tmp-{index_version_id}-{uuid4().hex}"
        temporary_dir.mkdir(parents=False)
        try:
            index = faiss.IndexFlatIP(int(matrix.shape[1]))
            index.add(matrix)
            index_path = temporary_dir / INDEX_FILENAME
            faiss.write_index(index, str(index_path))
            index_bytes = index_path.read_bytes()
            manifest_base: dict[str, Any] = {
                "schema_version": SCHEMA_VERSION,
                "index_version_id": str(index_version_id),
                "embedding_model": embedding_model,
                "dimension": int(matrix.shape[1]),
                "vector_count": int(matrix.shape[0]),
                "chunk_keys": list(chunk_keys),
                "index_sha256": _sha256(index_bytes),
            }
            artifact_checksum = _sha256(index_bytes + _canonical_json(manifest_base))
            manifest = {**manifest_base, "artifact_checksum": artifact_checksum}
            (temporary_dir / MANIFEST_FILENAME).write_bytes(_canonical_json(manifest))
            self._validate_directory(temporary_dir, artifact_checksum)
            os.replace(temporary_dir, final_dir)
            return IndexArtifact(
                relative_path=relative_path,
                checksum=artifact_checksum,
                dimension=int(matrix.shape[1]),
                vector_count=int(matrix.shape[0]),
            )
        except Exception:
            shutil.rmtree(temporary_dir, ignore_errors=True)
            raise

    def search(
        self,
        *,
        relative_path: str,
        expected_checksum: str,
        query_vector: Sequence[float],
        top_k: int,
    ) -> tuple[tuple[int, float], ...]:
        if top_k < 1:
            return ()
        artifact_dir = self._safe_artifact_path(relative_path)
        manifest, index = self._validate_directory(artifact_dir, expected_checksum)
        query = np.asarray(query_vector, dtype=np.float32)
        expected_dimension = int(manifest["dimension"])
        if query.ndim != 1 or query.shape[0] != expected_dimension or not np.isfinite(query).all():
            raise KnowledgeValidationError(
                "invalid_query_embedding", "query embedding does not match the active index"
            )
        norm = float(np.linalg.norm(query))
        if norm == 0:
            raise KnowledgeValidationError(
                "zero_query_embedding", "query embedding cannot be a zero vector"
            )
        query_matrix = (query / norm).reshape(1, -1)
        count = min(top_k, int(manifest["vector_count"]))
        scores, identifiers = index.search(query_matrix, count)
        return tuple(
            (int(identifier), float(score))
            for identifier, score in zip(identifiers[0], scores[0], strict=True)
            if identifier >= 0
        )

    def validate(self, *, relative_path: str, expected_checksum: str) -> IndexArtifact:
        artifact_dir = self._safe_artifact_path(relative_path)
        manifest, _index = self._validate_directory(artifact_dir, expected_checksum)
        return IndexArtifact(
            relative_path=relative_path,
            checksum=expected_checksum,
            dimension=int(manifest["dimension"]),
            vector_count=int(manifest["vector_count"]),
        )

    def _safe_artifact_path(self, relative_path: str) -> Path:
        candidate = Path(relative_path)
        if candidate.is_absolute() or ".." in candidate.parts:
            raise IndexUnavailableError("unsafe_index_path", "index artifact path is unsafe")
        resolved = (self._root / candidate).resolve()
        if resolved.parent != self._root:
            raise IndexUnavailableError("unsafe_index_path", "index artifact path is unsafe")
        return resolved

    @staticmethod
    def _validate_directory(
        artifact_dir: Path, expected_checksum: str
    ) -> tuple[dict[str, Any], Any]:
        try:
            manifest = cast(
                dict[str, Any],
                json.loads((artifact_dir / MANIFEST_FILENAME).read_text(encoding="utf-8")),
            )
            index_bytes = (artifact_dir / INDEX_FILENAME).read_bytes()
            artifact_checksum = str(manifest.pop("artifact_checksum"))
            if int(manifest["schema_version"]) != SCHEMA_VERSION:
                raise ValueError("unsupported manifest schema")
            if _sha256(index_bytes) != manifest["index_sha256"]:
                raise ValueError("index checksum mismatch")
            computed = _sha256(index_bytes + _canonical_json(manifest))
            if computed != artifact_checksum or computed != expected_checksum:
                raise ValueError("artifact checksum mismatch")
            index = faiss.read_index(str(artifact_dir / INDEX_FILENAME))
            if index.d != int(manifest["dimension"]):
                raise ValueError("index dimension mismatch")
            if index.ntotal != int(manifest["vector_count"]):
                raise ValueError("index vector count mismatch")
            if len(manifest["chunk_keys"]) != index.ntotal:
                raise ValueError("manifest chunk count mismatch")
            return manifest, index
        except (
            OSError,
            KeyError,
            TypeError,
            ValueError,
            json.JSONDecodeError,
            RuntimeError,
        ) as exc:
            raise IndexUnavailableError(
                "index_artifact_invalid", "active index artifact failed integrity validation"
            ) from exc
