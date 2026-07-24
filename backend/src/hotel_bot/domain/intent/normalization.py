"""Deterministic Arabic/English normalization for the offline baseline."""

import re
import unicodedata

ARABIC_DIACRITICS = re.compile(r"[\u0610-\u061a\u064b-\u065f\u0670\u06d6-\u06ed]")
NON_WORD = re.compile(r"[^\w\s]", flags=re.UNICODE)
WHITESPACE = re.compile(r"\s+")
ARABIC_TRANSLATION = str.maketrans(
    {
        "أ": "ا",
        "إ": "ا",
        "آ": "ا",
        "ٱ": "ا",
        "ى": "ي",
        "ؤ": "و",
        "ئ": "ي",
        "ـ": "",
    }
)


def normalize_text(text: str) -> str:
    normalized = unicodedata.normalize("NFKC", text).lower().translate(ARABIC_TRANSLATION)
    normalized = ARABIC_DIACRITICS.sub("", normalized)
    normalized = NON_WORD.sub(" ", normalized)
    return WHITESPACE.sub(" ", normalized).strip()
