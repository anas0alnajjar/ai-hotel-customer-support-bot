"""Load and checksum the immutable knowledge benchmark resource."""

import hashlib
import json
from dataclasses import dataclass
from importlib.resources import files
from pathlib import Path

from hotel_bot.knowledge.schema import KnowledgeDataset


@dataclass(frozen=True, slots=True)
class LoadedKnowledgeDataset:
    dataset: KnowledgeDataset
    sha256: str


def load_knowledge_dataset(path: Path | None = None) -> LoadedKnowledgeDataset:
    raw = (
        path.read_bytes()
        if path is not None
        else files("hotel_bot.knowledge").joinpath("data/knowledge-dataset-v1.json").read_bytes()
    )
    return LoadedKnowledgeDataset(
        dataset=KnowledgeDataset.model_validate(json.loads(raw)),
        sha256=hashlib.sha256(raw).hexdigest(),
    )
