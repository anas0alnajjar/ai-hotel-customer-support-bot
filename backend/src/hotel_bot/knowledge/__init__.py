"""Versioned fictional-hotel knowledge dataset and retrieval evaluation."""

from hotel_bot.knowledge.evaluation import evaluate_retrieval
from hotel_bot.knowledge.loader import LoadedKnowledgeDataset, load_knowledge_dataset
from hotel_bot.knowledge.schema import KnowledgeDataset, RetrievalEvaluationReport

__all__ = [
    "KnowledgeDataset",
    "LoadedKnowledgeDataset",
    "RetrievalEvaluationReport",
    "evaluate_retrieval",
    "load_knowledge_dataset",
]
