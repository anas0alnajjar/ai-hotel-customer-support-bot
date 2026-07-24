"""Dependency-free multinomial Naive Bayes baseline for bilingual intent text."""

from collections import Counter, defaultdict
from collections.abc import Iterable
from math import exp, log

from hotel_bot.domain.intent.enums import IntentCode
from hotel_bot.domain.intent.models import (
    IntentPrediction,
    IntentSample,
    SupportedLanguage,
)
from hotel_bot.domain.intent.normalization import normalize_text

ALGORITHM_VERSION = "nb-lexical-word-char-v1.1.0"

INTENT_LEXICON: dict[IntentCode, tuple[str, ...]] = {
    IntentCode.HOTEL_INFO: (
        "مرافق",
        "موقع الفندق",
        "تسجيل الدخول",
        "تسجيل المغادرة",
        "واي فاي",
        "افطار",
        "سياسة",
        "facility",
        "hotel located",
        "check in",
        "check out",
        "wi fi",
        "breakfast",
        "policy",
    ),
    IntentCode.ROOM_TYPES: (
        "انواع الغرف",
        "فئة غرفة",
        "فئات الغرف",
        "مواصفات الغرفة",
        "ديلوكس",
        "جناح",
        "تنفيذية",
        "room type",
        "room category",
        "room categories",
        "deluxe",
        "suite",
        "executive room",
    ),
    IntentCode.ROOM_AVAILABILITY: (
        "متاح",
        "متاحة",
        "شاغر",
        "شاغرة",
        "التوفر",
        "available",
        "availability",
        "vacant",
        "rooms left",
    ),
    IntentCode.BOOKING_LOOKUP: (
        "حجزي",
        "الحجز",
        "مرجع الحجز",
        "محجوزة",
        "booking",
        "reservation",
        "booking reference",
    ),
    IntentCode.ROOM_SERVICE_REQUEST: (
        "خدمة الغرف",
        "مناشف",
        "وجبة",
        "العشاء",
        "بطانية",
        "تنظيف غرفتي",
        "سرير طفل",
        "room service",
        "towels",
        "food to my room",
        "dinner delivered",
        "blanket",
        "room cleaned",
        "baby crib",
    ),
    IntentCode.MAINTENANCE_REQUEST: (
        "لا يعمل",
        "معطل",
        "مكسور",
        "مسدود",
        "صيانة",
        "تسريب",
        "not working",
        "broken",
        "clogged",
        "repair",
        "maintenance",
        "leaking",
    ),
    IntentCode.SERVICE_REQUEST_STATUS: (
        "حالة الطلب",
        "تتبع طلب",
        "تحديث عن طلب",
        "اكتمل",
        "قيد الانتظار",
        "request status",
        "track my",
        "status of request",
        "request completed",
        "status update",
        "still pending",
    ),
    IntentCode.HUMAN_ESCALATION: (
        "موظف",
        "شخص حقيقي",
        "مشرف",
        "مساعدة بشرية",
        "human",
        "real person",
        "staff member",
        "supervisor",
        "representative",
    ),
    IntentCode.GREETING_SMALLTALK: (
        "مرحبا",
        "اهلا",
        "السلام عليكم",
        "شكرا",
        "ممتن",
        "hello",
        "good morning",
        "good evening",
        "thank you",
        "appreciate",
    ),
    IntentCode.UNSUPPORTED: (
        "طقس",
        "طيران",
        "عملات",
        "طبية",
        "رياضيات",
        "كاس العالم",
        "قانونية",
        "weather",
        "airline",
        "trading",
        "medical",
        "homework",
        "world cup",
        "legal advice",
        "cryptocurrency",
    ),
}


def extract_features(text: str, language: SupportedLanguage) -> Counter[str]:
    normalized = normalize_text(text)
    words = normalized.split()
    features: Counter[str] = Counter({f"language:{language}": 1})
    features.update(f"word:{word}" for word in words)
    features.update(f"word2:{left}_{right}" for left, right in zip(words, words[1:], strict=False))
    compact = f" {normalized} "
    for size in (3, 4):
        features.update(
            f"char{size}:{compact[index : index + size]}"
            for index in range(max(0, len(compact) - size + 1))
        )
    return features


def _lexicon_hits(normalized: str, intent: IntentCode) -> int:
    padded = f" {normalized} "
    hits = 0
    for phrase in INTENT_LEXICON[intent]:
        normalized_phrase = normalize_text(phrase)
        if any("\u0600" <= character <= "\u06ff" for character in normalized_phrase):
            hits += int(normalized_phrase in normalized)
        else:
            hits += int(f" {normalized_phrase} " in padded)
    return hits


class NaiveBayesIntentClassifier:
    """Small deterministic baseline trained from the frozen dataset in memory."""

    def __init__(self, *, classifier_version: str, alpha: float = 1.0) -> None:
        if alpha <= 0:
            raise ValueError("alpha must be positive")
        self.classifier_version = classifier_version
        self._alpha = alpha
        self._document_counts: Counter[IntentCode] = Counter()
        self._feature_counts: dict[IntentCode, Counter[str]] = defaultdict(Counter)
        self._feature_totals: Counter[IntentCode] = Counter()
        self._vocabulary: set[str] = set()
        self._document_total = 0
        self._fitted = False

    def fit(self, samples: Iterable[IntentSample]) -> None:
        self._document_counts.clear()
        self._feature_counts.clear()
        self._feature_totals.clear()
        self._vocabulary.clear()
        self._document_total = 0

        for sample in samples:
            features = extract_features(sample.text, sample.language)
            self._document_counts[sample.intent] += 1
            self._feature_counts[sample.intent].update(features)
            self._feature_totals[sample.intent] += sum(features.values())
            self._vocabulary.update(features)
            self._document_total += 1

        missing = set(IntentCode) - set(self._document_counts)
        if missing:
            labels = ", ".join(sorted(item.value for item in missing))
            raise ValueError(f"training data is missing intents: {labels}")
        self._fitted = True

    def predict(self, text: str, language: SupportedLanguage) -> IntentPrediction:
        if not self._fitted:
            raise RuntimeError("classifier must be fitted before prediction")
        features = extract_features(text, language)
        label_count = len(IntentCode)
        vocabulary_size = max(1, len(self._vocabulary))
        log_scores: dict[IntentCode, float] = {}

        for intent in IntentCode:
            prior = (self._document_counts[intent] + self._alpha) / (
                self._document_total + self._alpha * label_count
            )
            denominator = self._feature_totals[intent] + self._alpha * vocabulary_size
            score = log(prior)
            counts = self._feature_counts[intent]
            for feature, frequency in features.items():
                score += frequency * log((counts[feature] + self._alpha) / denominator)
            log_scores[intent] = score

        highest_log_score = max(log_scores.values())
        exponentials = {
            intent: exp(score - highest_log_score) for intent, score in log_scores.items()
        }
        total = sum(exponentials.values())
        baseline_probabilities = {intent: value / total for intent, value in exponentials.items()}
        normalized = normalize_text(text)
        lexical_hits = {intent: _lexicon_hits(normalized, intent) for intent in IntentCode}
        if max(lexical_hits.values()) > 0:
            combined = {
                intent: exp(4 * lexical_hits[intent]) * (0.5 + baseline_probabilities[intent])
                for intent in IntentCode
            }
            combined_total = sum(combined.values())
            probabilities = {intent: value / combined_total for intent, value in combined.items()}
        else:
            probabilities = baseline_probabilities
        ranked = sorted(probabilities.items(), key=lambda item: (-item[1], item[0].value))
        predicted_intent, confidence = ranked[0]
        margin = confidence - ranked[1][1]
        return IntentPrediction(
            intent=predicted_intent,
            confidence=confidence,
            margin=margin,
            classifier_version=self.classifier_version,
            scores=probabilities,
        )
