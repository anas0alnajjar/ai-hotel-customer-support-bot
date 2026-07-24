"""Knowledge seed and retrieval-evaluation command line entry point."""

import argparse
import asyncio
import json
from dataclasses import asdict
from pathlib import Path
from tempfile import TemporaryDirectory

from hotel_bot.core.config import load_settings
from hotel_bot.infrastructure.database import DatabaseManager
from hotel_bot.infrastructure.embeddings import (
    HashingEmbeddingProvider,
    SentenceTransformerEmbeddingProvider,
)
from hotel_bot.infrastructure.faiss_store import FaissIndexStore
from hotel_bot.knowledge.evaluation import evaluate_retrieval, write_report
from hotel_bot.knowledge.loader import load_knowledge_dataset
from hotel_bot.knowledge.seeder import KnowledgeSeeder


async def _seed() -> int:
    database = DatabaseManager(load_settings())
    try:
        async with database.transaction() as session:
            result = await KnowledgeSeeder(session).seed()
        print(json.dumps(asdict(result), ensure_ascii=False, sort_keys=True))
        return 0
    finally:
        await database.dispose()


def _evaluate(provider: str, output: Path) -> int:
    settings = load_settings()
    embedder = (
        HashingEmbeddingProvider(dimension=settings.embedding_dimension)
        if provider == "hashing_test"
        else SentenceTransformerEmbeddingProvider(
            model_name=settings.embedding_model,
            revision=settings.embedding_model_revision,
            expected_dimension=settings.embedding_dimension,
            batch_size=settings.embedding_batch_size,
            cache_path=settings.embedding_cache_path,
        )
    )
    with TemporaryDirectory() as temporary_directory:
        report = evaluate_retrieval(
            load_knowledge_dataset(),
            embedder=embedder,
            store=FaissIndexStore(Path(temporary_directory)),
            top_k=settings.retrieval_top_k,
        )
    write_report(report, output)
    print(report.model_dump_json(indent=2))
    return 0 if report.passed else 1


def main() -> int:
    parser = argparse.ArgumentParser(description="Hotel knowledge operations")
    subcommands = parser.add_subparsers(dest="command", required=True)
    subcommands.add_parser("seed", help="ensure approved fictional-hotel knowledge exists")
    evaluate = subcommands.add_parser("evaluate", help="run the frozen Recall@5 benchmark")
    evaluate.add_argument(
        "--provider",
        choices=("hashing_test", "sentence_transformers"),
        default="hashing_test",
    )
    evaluate.add_argument(
        "--output",
        type=Path,
        default=Path("backend/reports/knowledge-retrieval-v1.json"),
    )
    arguments = parser.parse_args()
    if arguments.command == "seed":
        return asyncio.run(_seed())
    return _evaluate(arguments.provider, arguments.output)


if __name__ == "__main__":
    raise SystemExit(main())
