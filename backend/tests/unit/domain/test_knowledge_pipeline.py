"""Knowledge chunking, FAISS integrity, and retrieval quality contracts."""

import asyncio
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

import pytest

from hotel_bot.application.knowledge import KnowledgeRetrievalService
from hotel_bot.domain.knowledge.chunking import chunk_text, normalize_content, validate_content
from hotel_bot.domain.knowledge.enums import IndexStatus
from hotel_bot.domain.knowledge.errors import IndexUnavailableError, KnowledgeValidationError
from hotel_bot.domain.knowledge.models import IndexVersionSnapshot, StoredChunk
from hotel_bot.infrastructure.embeddings import HashingEmbeddingProvider
from hotel_bot.infrastructure.faiss_store import FaissIndexStore
from hotel_bot.knowledge import evaluate_retrieval, load_knowledge_dataset

EXPECTED_DATASET_SHA256 = "1549cc8570c09e30b8a200d57fb3259e4c2a3560e6e285f3d60c55ff0a8ef946"


def test_retrieval_reranks_clear_arabic_word_forms_ahead_of_weak_semantics() -> None:
    index_id = uuid4()
    now = datetime.now(UTC)
    breakfast = StoredChunk(
        id=uuid4(),
        revision_id=uuid4(),
        index_version_id=index_id,
        chunk_index=0,
        text="يقدم مطعم الياسمين بوفيه إفطار يومياً من السادسة والنصف صباحاً.",
        metadata={
            "document_id": str(uuid4()),
            "title": "خدمة الإفطار",
            "language": "ar",
            "revision_version": 1,
        },
        faiss_vector_id=0,
    )
    pets = StoredChunk(
        id=uuid4(),
        revision_id=uuid4(),
        index_version_id=index_id,
        chunk_index=0,
        text="يسمح باصطحاب الحيوانات الأليفة في غرف محددة.",
        metadata={
            "document_id": str(uuid4()),
            "title": "سياسة الحيوانات الأليفة",
            "language": "ar",
            "revision_version": 1,
        },
        faiss_vector_id=1,
    )
    index = IndexVersionSnapshot(
        id=index_id,
        embedding_model="test-model",
        dimension=8,
        chunk_config={},
        checksum="checksum",
        artifact_path="active",
        document_count=2,
        chunk_count=2,
        status=IndexStatus.ACTIVE,
        build_error=None,
        activated_at=now,
        created_at=now,
    )

    class Repository:
        async def get_active_index(
            self,
        ) -> tuple[IndexVersionSnapshot, tuple[StoredChunk, ...]]:
            return index, (breakfast, pets)

    class Embedder:
        model_id = "test-model"
        dimension = 8

        def embed_query(self, _text: str) -> list[float]:
            return [1.0] + [0.0] * 7

    class Store:
        requested_top_k = 0

        def search(self, **values: object) -> tuple[tuple[int, float], ...]:
            self.requested_top_k = int(values["top_k"])
            return ((1, 0.90), (0, 0.60))

    store = Store()
    service = KnowledgeRetrievalService(  # type: ignore[arg-type]
        Repository(),
        Embedder(),
        store,
        top_k=1,
        minimum_score=0.35,
    )

    result = asyncio.run(service.retrieve("شو وقت تقديم الفطور؟"))

    assert store.requested_top_k == 2
    assert result.sufficient is True
    assert len(result.evidence) == 1
    assert result.evidence[0].title == "خدمة الإفطار"


def test_content_normalization_and_overlapping_chunking_are_deterministic() -> None:
    content = "First   paragraph contains enough words for validation.\r\n\r\n" + (
        "Second paragraph contains stable bounded content. " * 8
    )

    first = chunk_text(content, max_chars=120, overlap_chars=20)
    second = chunk_text(content, max_chars=120, overlap_chars=20)

    assert first == second
    assert len(first) > 1
    assert all(20 <= len(item) <= 120 for item in first)
    assert normalize_content(content).startswith("First paragraph")
    with pytest.raises(KnowledgeValidationError):
        validate_content("too short")


def test_frozen_bilingual_retrieval_dataset_exceeds_quality_gates(tmp_path: Path) -> None:
    loaded = load_knowledge_dataset()
    report = evaluate_retrieval(
        loaded,
        embedder=HashingEmbeddingProvider(dimension=384),
        store=FaissIndexStore(tmp_path),
    )

    assert loaded.sha256 == EXPECTED_DATASET_SHA256
    assert len(loaded.dataset.documents) == 22
    assert len(loaded.dataset.evaluation_cases) == 44
    assert {item.language for item in loaded.dataset.documents} == {"ar", "en"}
    assert report.recall_at_k >= 0.85
    assert report.top_1_accuracy >= 0.80
    assert report.traceability_rate == 1.0
    assert report.passed is True


def test_faiss_artifact_is_immutable_checksummed_and_path_safe(tmp_path: Path) -> None:
    embedder = HashingEmbeddingProvider(dimension=64)
    store = FaissIndexStore(tmp_path)
    vectors = embedder.embed_documents(["breakfast buffet morning", "underground parking car"])
    index_id = uuid4()
    artifact = store.build(
        index_version_id=index_id,
        embedding_model=embedder.model_id,
        vectors=vectors,
        chunk_keys=["breakfast", "parking"],
    )

    hits = store.search(
        relative_path=artifact.relative_path,
        expected_checksum=artifact.checksum,
        query_vector=embedder.embed_query("breakfast buffet"),
        top_k=2,
    )
    assert hits[0][0] == 0

    with pytest.raises(KnowledgeValidationError, match="already exists"):
        store.build(
            index_version_id=index_id,
            embedding_model=embedder.model_id,
            vectors=vectors,
            chunk_keys=["breakfast", "parking"],
        )
    with pytest.raises(IndexUnavailableError) as unsafe:
        store.search(
            relative_path="../outside",
            expected_checksum=artifact.checksum,
            query_vector=embedder.embed_query("breakfast"),
            top_k=1,
        )
    assert unsafe.value.code == "unsafe_index_path"

    index_path = tmp_path / artifact.relative_path / "index.faiss"
    index_path.write_bytes(index_path.read_bytes() + b"tampered")
    with pytest.raises(IndexUnavailableError) as corrupted:
        store.search(
            relative_path=artifact.relative_path,
            expected_checksum=artifact.checksum,
            query_vector=embedder.embed_query("breakfast"),
            top_k=1,
        )
    assert corrupted.value.code == "index_artifact_invalid"
