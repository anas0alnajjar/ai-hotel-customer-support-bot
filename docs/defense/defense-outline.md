# Defense Outline

## 1. Problem and contribution

- Hotel support requires natural-language understanding, reliable hotel facts, and controlled operations.
- A plain LLM can hallucinate and must not directly execute database or infrastructure actions.
- The contribution is a modular hybrid architecture combining intent classification, RAG, Gemini, and a closed tool boundary.

## 2. System architecture

1. Telegram accepts private bilingual text messages.
2. FastAPI owns session state, idempotency, routing, and transaction boundaries.
3. The classifier selects deterministic, knowledge, action, escalation, or fallback paths.
4. FAISS returns evidence from approved hotel knowledge only.
5. Gemini proposes structured responses or one intent-scoped tool call.
6. The controlled executor revalidates authorization, schema, confirmation, limits, and audit policy.
7. MySQL stores authoritative operational state; the React dashboard exposes masked administration contracts.

## 3. Core design decisions

- MySQL is authoritative; FAISS is a rebuildable derived artifact.
- Latest five complete turns are sent to Gemini while authorized history remains stored until 90-day anonymization.
- Every write tool requires explicit confirmation and an idempotency key.
- Gemini automatic function execution is disabled.
- All hotel operations are simulations, not legally effective reservations or PMS actions.

## 4. Evaluation evidence

- Intent dataset: 240 bilingual synthetic samples; Macro F1 0.873 and accuracy 0.875.
- Retrieval dataset: 44 bilingual queries; Recall@5 0.977, top-1 accuracy 0.841, and evidence traceability 1.000.
- Release tests: 99 Python/MySQL tests and 4 frontend tests.
- Local Caddy liveness baseline: P95 44.301 ms across 100 measured requests.
- Recovery rehearsal: 20 tables and 22 knowledge documents restored in 75.275 seconds.
- Responsive audit: true 375×812 device emulation measured `innerWidth=375` and `scrollWidth=375` with correct RTL layout.

## 5. Security and reliability argument

- Canonical short-lived admin tokens use HMAC verification with constant-time comparison.
- Telegram identity is pseudonymous; sensitive booking/tool values are masked and excluded from prompts.
- Containers run non-root, read-only, with all Linux capabilities dropped and no-new-privileges enabled.
- Caddy provides TLS termination in production, security headers, same-origin API routing, and blocks public metrics.
- Prometheus receives internal metrics and three validated alert rules.

## 6. Limitations and future work

- Public DNS/TLS and live Telegram webhook activation require the selected deployment host.
- Results use synthetic single-hotel datasets and must be revalidated on consented real traffic.
- The local performance baseline excludes public-network, Telegram, and Gemini latency.
- Real PMS integration, payments, multi-tenancy, voice/media, and human handoff workflow are future extensions.
