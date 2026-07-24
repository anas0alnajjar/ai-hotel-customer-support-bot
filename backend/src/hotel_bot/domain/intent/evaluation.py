"""Dependency-free reproducible intent classification metrics."""

from collections import Counter

from hotel_bot.domain.intent.classifier import NaiveBayesIntentClassifier
from hotel_bot.domain.intent.enums import DatasetSplit, IntentCode
from hotel_bot.domain.intent.models import (
    IntentDataset,
    IntentEvaluationReport,
    IntentMetric,
)


def evaluate_classifier(
    classifier: NaiveBayesIntentClassifier,
    dataset: IntentDataset,
    *,
    dataset_sha256: str,
    split: DatasetSplit = DatasetSplit.TEST,
    confidence_threshold: float = 0.60,
    confidence_margin_threshold: float = 0.15,
) -> IntentEvaluationReport:
    samples = [sample for sample in dataset.samples if sample.split is split]
    if not samples:
        raise ValueError(f"dataset split {split.value!r} is empty")

    confusion = {expected: {predicted: 0 for predicted in IntentCode} for expected in IntentCode}
    correct = 0
    accepted_count = 0
    accepted_correct = 0
    for sample in samples:
        prediction = classifier.predict(sample.text, sample.language)
        confusion[sample.intent][prediction.intent] += 1
        correct += int(prediction.intent is sample.intent)
        accepted = (
            prediction.confidence >= confidence_threshold
            and prediction.margin >= confidence_margin_threshold
        )
        accepted_count += int(accepted)
        accepted_correct += int(accepted and prediction.intent is sample.intent)

    metrics: dict[IntentCode, IntentMetric] = {}
    for intent in IntentCode:
        true_positive = confusion[intent][intent]
        false_positive = sum(
            confusion[other][intent] for other in IntentCode if other is not intent
        )
        support = sum(confusion[intent].values())
        precision = (
            true_positive / (true_positive + false_positive)
            if true_positive + false_positive
            else 0.0
        )
        recall = true_positive / support if support else 0.0
        f1 = 2 * precision * recall / (precision + recall) if precision + recall else 0.0
        metrics[intent] = IntentMetric(
            precision=precision,
            recall=recall,
            f1=f1,
            support=support,
        )

    count = len(IntentCode)
    return IntentEvaluationReport(
        report_version="intent-evaluation-v1.0.0",
        dataset_version=dataset.dataset_version,
        dataset_sha256=dataset_sha256,
        taxonomy_version=dataset.taxonomy_version,
        classifier_version=classifier.classifier_version,
        split=split,
        sample_count=len(samples),
        accuracy=correct / len(samples),
        macro_precision=sum(item.precision for item in metrics.values()) / count,
        macro_recall=sum(item.recall for item in metrics.values()) / count,
        macro_f1=sum(item.f1 for item in metrics.values()) / count,
        confidence_threshold=confidence_threshold,
        confidence_margin_threshold=confidence_margin_threshold,
        accepted_count=accepted_count,
        coverage=accepted_count / len(samples),
        accepted_accuracy=accepted_correct / accepted_count if accepted_count else 0.0,
        per_intent=metrics,
        confusion_matrix=confusion,
    )


def class_distribution(dataset: IntentDataset) -> Counter[tuple[DatasetSplit, IntentCode]]:
    return Counter((sample.split, sample.intent) for sample in dataset.samples)
