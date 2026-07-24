"""Load and strictly validate the frozen bilingual intent dataset."""

import hashlib
from collections import Counter, defaultdict
from dataclasses import dataclass
from pathlib import Path

from hotel_bot.domain.intent.enums import DatasetSplit, IntentCode
from hotel_bot.domain.intent.models import IntentDataset
from hotel_bot.domain.intent.normalization import normalize_text
from hotel_bot.domain.intent.taxonomy import TAXONOMY_VERSION


@dataclass(frozen=True, slots=True)
class LoadedIntentDataset:
    dataset: IntentDataset
    sha256: str
    source_path: Path


def load_intent_dataset(path: Path) -> LoadedIntentDataset:
    raw = path.read_bytes()
    dataset = IntentDataset.model_validate_json(raw)
    if dataset.taxonomy_version != TAXONOMY_VERSION:
        raise ValueError(
            f"dataset taxonomy {dataset.taxonomy_version!r} does not match {TAXONOMY_VERSION!r}"
        )

    identifiers: set[str] = set()
    normalized_samples: dict[tuple[str, str], DatasetSplit] = {}
    scenario_splits: dict[str, set[DatasetSplit]] = defaultdict(set)
    scenario_intents: dict[str, set[IntentCode]] = defaultdict(set)
    coverage: Counter[tuple[DatasetSplit, IntentCode, str]] = Counter()
    for sample in dataset.samples:
        if sample.id in identifiers:
            raise ValueError(f"duplicate sample id: {sample.id}")
        identifiers.add(sample.id)
        normalized = normalize_text(sample.text)
        duplicate_key = (sample.language, normalized)
        previous_split = normalized_samples.get(duplicate_key)
        if previous_split is not None:
            raise ValueError(f"normalized duplicate sample crosses dataset rows: {sample.id}")
        normalized_samples[duplicate_key] = sample.split
        scenario_splits[sample.scenario_id].add(sample.split)
        scenario_intents[sample.scenario_id].add(sample.intent)
        coverage[(sample.split, sample.intent, sample.language)] += 1

    leaking = sorted(key for key, splits in scenario_splits.items() if len(splits) != 1)
    if leaking:
        raise ValueError(f"scenario leakage across splits: {', '.join(leaking)}")
    mixed = sorted(key for key, intents in scenario_intents.items() if len(intents) != 1)
    if mixed:
        raise ValueError(f"scenarios contain multiple intents: {', '.join(mixed)}")

    minimums = {
        DatasetSplit.TRAIN: 6,
        DatasetSplit.VALIDATION: 2,
        DatasetSplit.TEST: 4,
    }
    for split, minimum in minimums.items():
        for intent in IntentCode:
            for language in ("ar", "en"):
                count = coverage[(split, intent, language)]
                if count < minimum:
                    raise ValueError(
                        f"insufficient {split.value}/{intent.value}/{language} coverage: {count}"
                    )

    return LoadedIntentDataset(
        dataset=dataset,
        sha256=hashlib.sha256(raw).hexdigest(),
        source_path=path,
    )
