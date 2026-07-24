"""Build the frozen dataset and generate a reproducible offline evaluation report."""

import argparse
import json
from pathlib import Path

from hotel_bot.domain.intent.classifier import (
    ALGORITHM_VERSION,
    NaiveBayesIntentClassifier,
)
from hotel_bot.domain.intent.enums import DatasetSplit
from hotel_bot.domain.intent.evaluation import evaluate_classifier
from hotel_bot.infrastructure.intent_dataset import load_intent_dataset
from hotel_bot.intent.dataset_source import build_dataset

PACKAGE_DIRECTORY = Path(__file__).resolve().parent
BACKEND_DIRECTORY = Path(__file__).resolve().parents[3]
DEFAULT_DATASET_PATH = PACKAGE_DIRECTORY / "data" / "intent-dataset-v1.json"
DEFAULT_REPORT_PATH = BACKEND_DIRECTORY / "artifacts" / "evaluation" / "intent-evaluation-v1.json"


def write_dataset(path: Path) -> None:
    dataset = build_dataset()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            dataset.model_dump(mode="json"),
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )


def evaluate(dataset_path: Path, report_path: Path) -> None:
    loaded = load_intent_dataset(dataset_path)
    classifier_version = f"{ALGORITHM_VERSION}+{loaded.dataset.dataset_version}.{loaded.sha256[:8]}"
    classifier = NaiveBayesIntentClassifier(classifier_version=classifier_version)
    classifier.fit(
        sample for sample in loaded.dataset.samples if sample.split is DatasetSplit.TRAIN
    )
    report = evaluate_classifier(
        classifier,
        loaded.dataset,
        dataset_sha256=loaded.sha256,
        split=DatasetSplit.TEST,
    )
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(
        json.dumps(
            report.model_dump(mode="json"),
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )
    print(
        json.dumps(
            {
                "event": "intent_evaluation_completed",
                "classifier_version": report.classifier_version,
                "dataset_sha256": report.dataset_sha256,
                "sample_count": report.sample_count,
                "accuracy": round(report.accuracy, 6),
                "macro_f1": round(report.macro_f1, 6),
                "coverage": round(report.coverage, 6),
                "accepted_accuracy": round(report.accepted_accuracy, 6),
                "report": str(report_path),
            },
            separators=(",", ":"),
            sort_keys=True,
        )
    )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("build", "evaluate", "rebuild"))
    parser.add_argument("--dataset", type=Path, default=DEFAULT_DATASET_PATH)
    parser.add_argument("--report", type=Path, default=DEFAULT_REPORT_PATH)
    arguments = parser.parse_args()

    if arguments.command in {"build", "rebuild"}:
        write_dataset(arguments.dataset)
    if arguments.command in {"evaluate", "rebuild"}:
        evaluate(arguments.dataset, arguments.report)


if __name__ == "__main__":
    main()
