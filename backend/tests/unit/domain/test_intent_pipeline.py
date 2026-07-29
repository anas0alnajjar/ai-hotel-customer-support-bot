"""Frozen dataset, classifier evaluation, normalization, and safe routing contracts."""

from pathlib import Path

import pytest

from hotel_bot.domain.intent.classifier import (
    ALGORITHM_VERSION,
    NaiveBayesIntentClassifier,
)
from hotel_bot.domain.intent.enums import (
    DatasetSplit,
    IntentCode,
    RoutingDecision,
)
from hotel_bot.domain.intent.evaluation import evaluate_classifier
from hotel_bot.domain.intent.models import IntentPrediction, SupportedLanguage
from hotel_bot.domain.intent.normalization import normalize_text
from hotel_bot.domain.intent.routing import SafeIntentRouter
from hotel_bot.infrastructure.intent_dataset import load_intent_dataset
from hotel_bot.intent.dataset_source import build_dataset

DATASET_PATH = (
    Path(__file__).resolve().parents[3]
    / "src"
    / "hotel_bot"
    / "intent"
    / "data"
    / "intent-dataset-v1.json"
)
EXPECTED_SHA256 = "332df9858773090a2bb3b7e1e91cb92a3f627bc4790415f3cca81688ec638970"


class FixedPredictor:
    def __init__(self, prediction: IntentPrediction) -> None:
        self._prediction = prediction

    def predict(self, text: str, language: SupportedLanguage) -> IntentPrediction:
        return self._prediction


def prediction(intent: IntentCode, confidence: float, margin: float) -> IntentPrediction:
    scores = {item: 0.0 for item in IntentCode}
    scores[intent] = confidence
    return IntentPrediction(
        intent=intent,
        confidence=confidence,
        margin=margin,
        classifier_version="test-classifier-v1",
        scores=scores,
    )


def test_frozen_dataset_is_balanced_versioned_and_scenario_isolated() -> None:
    loaded = load_intent_dataset(DATASET_PATH)

    assert loaded.sha256 == EXPECTED_SHA256
    assert loaded.dataset == build_dataset()
    assert len(loaded.dataset.samples) == 240
    expected_per_language = {
        DatasetSplit.TRAIN: 6,
        DatasetSplit.VALIDATION: 2,
        DatasetSplit.TEST: 4,
    }
    for split, expected in expected_per_language.items():
        for intent in IntentCode:
            for language in ("ar", "en"):
                assert (
                    sum(
                        sample.split is split
                        and sample.intent is intent
                        and sample.language == language
                        for sample in loaded.dataset.samples
                    )
                    == expected
                )


def test_baseline_exceeds_macro_f1_gate_on_frozen_test_split() -> None:
    loaded = load_intent_dataset(DATASET_PATH)
    classifier = NaiveBayesIntentClassifier(classifier_version=f"{ALGORITHM_VERSION}+test")
    classifier.fit(
        sample for sample in loaded.dataset.samples if sample.split is DatasetSplit.TRAIN
    )

    report = evaluate_classifier(
        classifier,
        loaded.dataset,
        dataset_sha256=loaded.sha256,
    )

    assert report.sample_count == 80
    assert report.macro_f1 >= 0.85
    assert report.accuracy >= 0.85
    assert 0 <= report.coverage <= 1
    assert report.accepted_accuracy >= report.accuracy
    assert set(report.per_intent) == set(IntentCode)


def test_arabic_normalization_removes_diacritics_and_unifies_alef() -> None:
    assert normalize_text("أَهْلاًــ وسَهْلاً!") == "اهلا وسهلا"


def test_low_confidence_action_is_clarification_and_never_execution() -> None:
    router = SafeIntentRouter(
        FixedPredictor(prediction(IntentCode.ROOM_SERVICE_REQUEST, 0.55, 0.05))
    )

    result = router.route("send towels", "en")

    assert result.decision is RoutingDecision.CLARIFY
    assert result.missing_parameters == (
        "room_number",
        "category",
        "description",
    )
    assert result.allow_tool_execution is False
    assert result.reason_code == "low_confidence_or_margin"


def test_missing_parameters_block_high_confidence_action() -> None:
    router = SafeIntentRouter(FixedPredictor(prediction(IntentCode.ROOM_AVAILABILITY, 0.95, 0.80)))

    result = router.route("available room", "en", parameters={"adults": 2})

    assert result.decision is RoutingDecision.CLARIFY
    assert result.missing_parameters == ("check_in", "check_out")
    assert result.allow_tool_execution is False


@pytest.mark.parametrize(
    ("text", "language"),
    [
        ("في حجوزات؟", "ar"),
        ("Are there rooms available?", "en"),
    ],
)
def test_explicit_availability_question_uses_required_parameter_metadata(
    text: str,
    language: SupportedLanguage,
) -> None:
    router = SafeIntentRouter(
        FixedPredictor(
            prediction(
                IntentCode.GREETING_SMALLTALK,
                0.99,
                0.90,
            )
        )
    )

    result = router.route(text, language)

    assert result.prediction.intent is IntentCode.ROOM_AVAILABILITY
    assert result.decision is RoutingDecision.CLARIFY
    assert result.missing_parameters == (
        "check_in",
        "check_out",
        "adults",
    )


def test_existing_booking_phrase_is_distinct_from_room_availability() -> None:
    router = SafeIntentRouter(
        FixedPredictor(
            prediction(
                IntentCode.ROOM_AVAILABILITY,
                0.99,
                0.90,
            )
        )
    )

    result = router.route("بدي تابع حجزي", "ar")

    assert result.prediction.intent is IntentCode.BOOKING_LOOKUP
    assert result.decision is RoutingDecision.CLARIFY
    assert result.missing_parameters == (
        "booking_reference",
        "verification_value",
    )


def test_state_changing_prediction_requires_confirmation_and_orchestrator() -> None:
    router = SafeIntentRouter(
        FixedPredictor(prediction(IntentCode.MAINTENANCE_REQUEST, 0.98, 0.90))
    )

    result = router.route(
        "broken shower",
        "en",
        parameters={"room_number": "305", "description": "broken shower"},
    )

    assert result.decision is RoutingDecision.ACTION_CANDIDATE
    assert result.requires_confirmation is True
    assert result.allow_tool_execution is False


@pytest.mark.parametrize(
    ("text", "expected_decision"),
    [
        ("يوجد دخان وخطر في الغرفة", RoutingDecision.ESCALATE),
        ("I need a human agent", RoutingDecision.ESCALATE),
        ("مرحبا", RoutingDecision.CONTROLLED_RESPONSE),
    ],
)
def test_deterministic_safety_rules_override_classifier(
    text: str, expected_decision: RoutingDecision
) -> None:
    router = SafeIntentRouter(FixedPredictor(prediction(IntentCode.HOTEL_INFO, 0.99, 0.90)))

    result = router.route(text, "ar" if any(ord(character) > 127 for character in text) else "en")

    assert result.decision is expected_decision
    assert result.allow_tool_execution is False
