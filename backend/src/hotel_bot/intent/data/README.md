# Intent dataset

`intent-dataset-v1.json` is generated deterministically from the explicit bilingual scenario
source in `hotel_bot.intent.dataset_source`.

Scenarios 1–6 per intent are training data, 7–8 are validation data, and 9–12 are
held-out test data. Arabic and English expressions of one scenario always remain in the
same split. This synthetic baseline supports reproducible engineering tests but must not
be represented as real-world guest-language performance.
