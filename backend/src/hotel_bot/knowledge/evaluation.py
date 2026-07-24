"""Deterministic Recall@K and evidence-grounding evaluation."""

from pathlib import Path
from uuid import uuid4

from hotel_bot.application.knowledge import EmbeddingProvider, VectorIndexStore
from hotel_bot.knowledge.loader import LoadedKnowledgeDataset
from hotel_bot.knowledge.schema import RetrievalEvaluationReport


def evaluate_retrieval(
    loaded: LoadedKnowledgeDataset,
    *,
    embedder: EmbeddingProvider,
    store: VectorIndexStore,
    top_k: int = 5,
    recall_gate: float = 0.85,
    top_1_gate: float = 0.80,
) -> RetrievalEvaluationReport:
    dataset = loaded.dataset
    document_keys = [document.key for document in dataset.documents]
    artifact = store.build(
        index_version_id=uuid4(),
        embedding_model=embedder.model_id,
        vectors=embedder.embed_documents([document.content for document in dataset.documents]),
        chunk_keys=document_keys,
    )
    recalls: list[float] = []
    reciprocal_ranks: list[float] = []
    top_1_hits = 0
    traceable_hits = 0
    failed: list[str] = []
    for case in dataset.evaluation_cases:
        hits = store.search(
            relative_path=artifact.relative_path,
            expected_checksum=artifact.checksum,
            query_vector=embedder.embed_query(case.query),
            top_k=top_k,
        )
        retrieved = [document_keys[vector_id] for vector_id, _score in hits]
        relevant = set(case.relevant_document_keys)
        recall = len(relevant.intersection(retrieved)) / len(relevant)
        recalls.append(recall)
        first_relevant_rank = next(
            (rank for rank, key in enumerate(retrieved, start=1) if key in relevant), None
        )
        reciprocal_ranks.append(0.0 if first_relevant_rank is None else 1 / first_relevant_rank)
        top_1_hits += int(bool(retrieved and retrieved[0] in relevant))
        traceable_hits += int(all(key in document_keys for key in retrieved))
        if recall < 1:
            failed.append(case.id)
    sample_count = len(dataset.evaluation_cases)
    recall_at_k = sum(recalls) / sample_count
    top_1_accuracy = top_1_hits / sample_count
    traceability_rate = traceable_hits / sample_count
    return RetrievalEvaluationReport(
        dataset_version=dataset.dataset_version,
        dataset_sha256=loaded.sha256,
        embedding_model=embedder.model_id,
        sample_count=sample_count,
        top_k=top_k,
        recall_at_k=recall_at_k,
        top_1_accuracy=top_1_accuracy,
        mean_reciprocal_rank=sum(reciprocal_ranks) / sample_count,
        traceability_rate=traceability_rate,
        passed=(
            recall_at_k >= recall_gate and top_1_accuracy >= top_1_gate and traceability_rate == 1.0
        ),
        failed_case_ids=tuple(failed),
    )


def write_report(report: RetrievalEvaluationReport, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(report.model_dump_json(indent=2), encoding="utf-8")
