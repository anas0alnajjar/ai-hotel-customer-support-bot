# Implementation Roadmap

## 1. Purpose and control

هذه الوثيقة هي المرجع التنفيذي للمشروع. لا تبدأ خطوة جديدة قبل اجتياز Exit Gate للخطوة الحالية وموافقة مالك المشروع على المتابعة. تفاصيل المتطلبات المعتمدة موجودة في [`requirements-and-system-architecture/requirements-and-system-architecture.md`](./requirements-and-system-architecture/requirements-and-system-architecture.md).

| Field | Value |
|---|---|
| Project | AI Hotel Customer Support Bot Using Large Language Models and Tool Calling |
| Owner | Anas Al-Najjar |
| Roadmap version | 2.0.0 |
| Last updated | 2026-07-24 |
| Current step | Step 12 — Release Evaluation and Operations Hardening |
| Current status | Step 12 completed and verified; public deployment conditions remain explicitly external |

## 2. Execution rules

1. Implement one numbered step at a time.
2. Every change must reference requirements, architecture decisions, or an explicit technical prerequisite.
3. A step is complete only when its automated checks and manual acceptance criteria pass.
4. Secrets stay outside Git; `.env.example` contains placeholders and local-only defaults.
5. Business logic remains independent of FastAPI, Telegram, Gemini, LangChain, FAISS, and database drivers.
6. Any scope or architecture change updates the requirements document, ADRs, traceability matrix, and this roadmap together.

## 3. Delivery sequence

| Step | Deliverable | Requirement coverage | Exit gate | Status |
|---:|---|---|---|---|
| 1 | Project foundation, typed settings, FastAPI factory, MySQL runtime, health endpoints, logging/correlation, Docker, quality checks | NFR-001–NFR-004, NFR-006–NFR-008, NFR-010–NFR-013; foundation for FR-031–FR-032 | Tests, lint, typing, Compose validation, live/readiness checks pass | Completed |
| 2 | MySQL schema, SQLAlchemy models, Alembic migrations, transaction boundaries | FR-002, FR-011–FR-012, FR-018–FR-025, FR-026–FR-030, FR-033; NFR-005–NFR-006, NFR-013 | Migration up/down and schema contract tests pass | Completed |
| 3 | Complete fictional hotel dataset, deterministic seed process, room/inventory/booking/service-request rules | FR-018–FR-023, FR-028 | Repeatable seed and domain rule tests pass | Completed |
| 4 | Conversation sessions, message persistence, structured context state, five-turn context assembly, 90-day cleanup | FR-002–FR-005, FR-033–FR-034; NFR-005–NFR-006, NFR-012 | Context, idempotency, retention, redaction, and cleanup tests pass | Completed |
| 5 | Bilingual intent taxonomy, dataset pipeline, baseline classifier, confidence policy, evaluation | FR-006–FR-010, FR-030 | Frozen split and Macro F1 target evaluation are reproducible | Completed |
| 6 | Knowledge document workflow, multilingual embeddings, FAISS versioning, retrieval and grounding evaluation | FR-011–FR-016, FR-030–FR-032 | Safe index swap and Recall@5/grounding gates pass | Completed |
| 7 | Typed controlled-tool registry and simulated hotel tools | FR-017–FR-025 | Positive, negative, privacy, authorization, and idempotency contracts pass | Completed |
| 8 | Gemini adapter, structured outputs/function calling, hybrid orchestration, fallback and cost controls | FR-007–FR-010, FR-017, FR-024–FR-025, FR-032, FR-034; NFR-012 | Model contract, prompt-injection, fallback, and cost-budget tests pass | Completed |
| 9 | Telegram webhook adapter, update idempotency, bilingual guest flows | FR-001–FR-005, FR-009 | Telegram contract and end-to-end guest journeys pass | Completed |
| 10 | Admin authentication/RBAC, knowledge/conversation/request/evaluation APIs | FR-011, FR-015, FR-026–FR-031 | Auth, RBAC, masking, audit, and API acceptance tests pass | Completed |
| 11 | React + Vite administration dashboard with Arabic RTL and English LTR | FR-027–FR-031; NFR-009, NFR-014 | Dashboard acceptance and accessibility checks pass | Completed |
| 12 | Full evaluation, observability, security hardening, backup/restore, deployment and defense artifacts | All requirements and E2E-001–E2E-014 | Quality targets measured; limitations and release evidence approved | Completed |

## 4. Step 1 scope

### Deliverables

- Python 3.12 backend package using a `src/` layout.
- FastAPI application factory and explicit lifecycle management.
- Typed environment configuration with secret-safe values.
- Async SQLAlchemy engine using the MySQL `asyncmy` driver.
- Separate liveness and database-readiness endpoints.
- Correlation ID middleware and structured JSON logging foundation.
- Dockerfile, MySQL 8.4 LTS service, and Docker Compose topology.
- PowerShell setup and verification scripts for the Windows development environment.
- Unit/API tests, Ruff rules, and strict Mypy configuration.

### Out of scope

- Business tables and Alembic migrations.
- Hotel seed data.
- Conversation, RAG, intent, Gemini, Telegram, tools, authentication, and React features.

### Exit gate

- [x] `.env` is ignored and `.env.example` contains no real credentials.
- [x] Backend package installs in an isolated Python 3.12 environment.
- [x] Ruff passes.
- [x] Mypy strict mode passes.
- [x] Pytest passes: 9 tests.
- [x] Docker Compose configuration validates.
- [x] `/api/v1/health/live` returns HTTP 200 in a real local server process.
- [x] `/api/v1/health/ready` returns controlled HTTP 503 when the configured database identity is unavailable.
- [x] `/api/v1/health/ready` returns HTTP 200 against the Compose-managed MySQL instance.

## 5. Step 3 scope

### Deliverables

- Versioned bilingual synthetic dataset for one complete fictional hotel.
- Five room types, 22 rooms, pseudonymous guests, eight bookings, and three initial service requests.
- Deterministic UUIDv5 identifiers and ensure-only repeatable seeding.
- PBKDF2-SHA256 storage for synthetic booking verification values.
- Framework-independent availability, booking-verification, idempotency, emergency, and status-transition policies.
- SQLAlchemy repository adapter with row locking for idempotent creation and status updates.
- PowerShell seed and verification commands for Windows development.

### Out of scope

- Conversation persistence and five-turn context assembly.
- Intent classification, RAG/FAISS, Gemini, tool registry, Telegram, administration APIs, and React.
- Real hotel/PMS integrations, payments, or legally effective reservations.

### Exit gate

- [x] Dataset schema and cross-references validate.
- [x] Seed can run repeatedly without duplicate rows.
- [x] Re-seeding does not reset existing operational state.
- [x] Availability handles assigned/unassigned bookings, operational room state, cancellation, capacity, and date boundaries.
- [x] Booking lookup requires reference plus a matching verification value and returns masked data.
- [x] Service-request retry returns one stable tracking result and rejects a mismatched payload.
- [x] Emergency requests require immediate-contact guidance without claiming resolution.
- [x] Service-request status transitions enforce the approved state machine and concurrent-state check.
- [x] Ruff, strict Mypy, Alembic drift check, and all unit/integration tests pass.

## 6. Step 4 scope

### Deliverables

- MySQL-backed guest sessions with a 30-minute inactivity boundary and explicit message ordering.
- Channel-neutral update ledger keyed by channel and external update ID for atomic retry safety.
- Validated bilingual structured conversation state that rejects arbitrary or sensitive fields.
- Provider-neutral context assembly containing the latest five complete turns, current input, structured state, optional summary/evidence, and a configurable token ceiling.
- Batched 90-day message anonymization that clears retained prose summaries and emits redacted audit metadata.
- PowerShell cleanup and verification commands suitable for local or self-hosted scheduling.

### Out of scope

- Intent classification, RAG/FAISS, Gemini calls, real Telegram webhook handling, and administration APIs/UI.
- Deployment scheduler binding; Step 12 will bind the cleanup command to the selected hosting environment.

### Exit gate

- [x] Duplicate external updates return the original inbound message without a second side effect.
- [x] Reusing an external update ID with a different payload raises a stable conflict.
- [x] Per-conversation sequence numbers are positive and unique in MySQL.
- [x] Sessions rotate after 30 minutes of inactivity and preserve Arabic/English preference.
- [x] Context includes no more than five complete prior turns and preserves structured state/current input under budget pressure.
- [x] Expired raw text is irreversibly replaced, summaries are cleared, recent messages remain intact, and cleanup is idempotent and audited.
- [x] Ruff, strict Mypy, Alembic drift check, and all unit/integration tests pass.

## 7. Step 5 scope

### Deliverables

- Accepted ten-label intent taxonomy v1.0.0 with expected paths and required parameters.
- Frozen synthetic Arabic/English dataset with 240 samples and scenario-level train/validation/test isolation.
- Dependency-free lexical + word/character n-gram Naive Bayes baseline suitable for offline Windows/Docker execution.
- Safety-first hybrid routing policy with deterministic greeting, human-request, and emergency rules.
- Separate general/action confidence thresholds, confidence-margin threshold, missing-parameter clarification, and mandatory confirmation for state-changing candidates.
- Versioned intent/confidence persistence on inbound messages and a reproducible JSON evaluation report with dataset checksum, per-class metrics, confusion matrix, coverage, and accepted accuracy.

### Out of scope

- LLM fallback invocation and final-answer generation; these remain Step 8 deliverables.
- Tool execution; Step 5 emits candidates only and always sets `allow_tool_execution=false`.
- Real Telegram traffic and real-guest language collection; Telegram integration is Step 9 and production validation requires a separately consented/anonymized dataset.

### Exit gate

- [x] Dataset checksum, versions, label/language balance, and scenario split are deterministic.
- [x] Held-out bilingual test split contains 80 samples and no scenario crosses splits.
- [x] Macro F1 is 0.873, exceeding the approved 0.85 baseline gate.
- [x] Accuracy is 0.875; confidence coverage is 0.975; accepted-prediction accuracy is 0.885.
- [x] Low-confidence or low-margin action predictions request clarification and cannot execute tools.
- [x] Missing parameters block action routing; state-changing candidates require confirmation.
- [x] Emergency/human requests deterministically escalate and unsupported requests use fallback.
- [x] Intent, confidence, and classifier version persist atomically on MySQL messages.
- [x] Ruff, strict Mypy, Alembic drift check, and all unit/integration tests pass.

## 8. Step 6 scope

### Deliverables

- Administrator-authorized document creation, immutable revisions, explicit approval, and archive workflow behind provider-neutral application contracts.
- Ensure-only MySQL seed containing 22 approved Arabic/English documents for Nour Al-Sham Grand Hotel.
- Deterministic bounded-character chunking with versioned size and overlap metadata.
- Lazy Sentence Transformers adapter pinned to `paraphrase-multilingual-MiniLM-L12-v2` model revision and a deterministic offline test adapter.
- Exact cosine retrieval using normalized vectors and FAISS `IndexFlatIP`, appropriate for the single-hotel MVP corpus.
- Immutable UUID-named FAISS artifacts with manifests, SHA-256 integrity checks, safe paths, atomic publication, and relational vector-to-chunk mappings.
- Activation only after artifact revalidation; failed builds remain failed and never replace the active index.
- Evidence-only retrieval contract returning ranked document/revision/chunk identifiers or explicit insufficient-evidence status.
- Frozen 44-query bilingual retrieval benchmark and reproducible JSON evaluation report.

### Out of scope

- Final answer generation and prompt-level groundedness judging; Gemini orchestration remains Step 8.
- Admin HTTP endpoints and dashboard screens; these remain Steps 10–11.
- PDF ingestion; only validated plain-text and Markdown inputs are accepted in this step.
- Multi-hotel approximate-vector optimization; exact search is cheaper and simpler for the approved single-hotel MVP.

### Exit gate

- [x] Only approved current revisions enter a build and archived/stale revisions are excluded at retrieval time.
- [x] A checksummed artifact is revalidated before activation and a failed later build leaves the prior active index unchanged.
- [x] Evidence includes ranked chunk, document, revision, index-version identifiers, and similarity score.
- [x] Missing active evidence returns controlled `active_index_unavailable` or `insufficient_evidence` status; the retrieval layer never invents an answer.
- [x] Frozen offline benchmark Recall@5 is 0.977, top-1 accuracy is 0.841, and evidence traceability is 1.000.
- [x] Seed is repeatable without overwriting administrator changes.
- [x] Migration downgrade/upgrade, Ruff, strict Mypy, Alembic drift, and all 55 unit/integration tests pass.

## 9. Step 7 scope

### Deliverables

- Closed six-tool allow-list for room types, availability, booking lookup, room service, maintenance, and request-status lookup.
- Provider-neutral JSON-schema declarations with strict Pydantic input/output contracts and forbidden extra fields.
- Explicit caller authorization, per-tool timeout, read/write effect, mandatory write confirmation, and always-audit policy.
- Executor-owned maximum calls per turn so a caller cannot expand its own execution budget.
- Deterministic mapping to existing hotel services; no generated SQL, code, shell, URLs, or dynamically imported tools.
- Minimal booking/status outputs and redacted arguments/results for booking references, verification values, room numbers, descriptions, and idempotency keys.
- MySQL audit records for successful, rejected, failed, timed-out, unknown, unauthorized, invalid, and over-limit attempts.
- Atomic service-request side effect and audit record within the caller-owned transaction boundary.

### Out of scope

- Gemini function-call parsing and multi-step orchestration; these remain Step 8.
- Telegram confirmation UX and update-derived idempotency keys; these remain Step 9.
- Real PMS, payment, lock, or building-control integrations; all operations remain explicit simulations.
- Staff status transitions through tool calling; those stay behind later authenticated administration APIs.

### Exit gate

- [x] All six definitions expose name, description, strict schema, caller policy, timeout, effect, confirmation, and audit policy.
- [x] Unknown tools, extra/wrong arguments, unauthorized callers, missing confirmation, and calls above the configured maximum are rejected before business execution.
- [x] Booking and request-status tools require secondary verification and expose only minimal safe results.
- [x] Room-service retries reuse one request/tracking code; payload conflicts remain rejected by the domain idempotency policy.
- [x] Emergency maintenance returns immediate-contact guidance and never claims real-world resolution.
- [x] Every tested attempt persists name, redacted arguments/result, status, latency, correlation ID, and safe error code in MySQL.
- [x] Ruff, formatting, strict Mypy, Alembic drift, and all 63 unit/integration tests pass.

## 10. Step 8 scope

### Deliverables

- Provider-neutral LLM request/response, usage, grounded-answer, error, and audit contracts.
- Google GenAI SDK adapter pinned to `google-genai==2.12.1` and configured for `gemini-2.5-flash`, bounded retries/timeouts/output, provider-default thinking compatibility, and explicit client shutdown.
- Automatic SDK function execution disabled; Gemini can propose only application-supplied declarations and the Step 7 executor remains authoritative.
- Versioned prompt factory that serializes the latest-five-turn envelope, state, evidence, and tool results into explicit untrusted-data sections.
- Pydantic-validated structured final answers with basis, evidence IDs, tool names, uncertainty, and escalation metadata.
- Hybrid orchestration for deterministic responses, RAG answers, one-intent/one-tool execution, mandatory write confirmation, and controlled fallback.
- Conservative per-turn token/cost reservation plus MySQL telemetry for request kind, input/output/thought/total tokens, estimated cost, provider request ID, latency, status, and safe error code.
- Offline contract tests and a separate live structured-output/function-call smoke command.

### Out of scope

- Telegram webhook/session delivery and channel confirmation UX; these remain Step 9.
- Admin HTTP APIs and dashboard model observability; these remain Steps 10–11.
- A local Llama fallback runtime; the provider boundary supports it later, while the MVP currently returns explicit controlled unavailability when Gemini is inaccessible.
- Multi-tool planning loops; the single-hotel MVP permits exactly one intent-scoped tool proposal per orchestration turn.

### Exit gate

- [x] Gemini SDK cannot execute functions automatically; only the closed application registry can execute a proposal.
- [x] Structured answers are schema-validated and cannot cite evidence/tool identifiers outside the per-request allow-list.
- [x] Prompt-injection text remains inside an explicitly untrusted JSON data boundary.
- [x] Missing confirmation blocks model and tool calls for state-changing routes.
- [x] Unknown functions, invalid proposal counts, provider outage, invalid structured output, and insufficient RAG evidence fail closed without false execution claims.
- [x] Per-turn token and estimated-cost ceilings are checked before provider invocation.
- [x] LLM telemetry is stored in MySQL without prompt or response content; Alembic reports no schema drift.
- [x] Ruff, formatting, strict Mypy, and all 70 unit/integration tests pass.
- [x] Live Gemini structured-output and function-call smoke passes on `gemini-2.5-flash`: two calls and 564 total tokens; no key or response content was logged.
- [x] Owner approved the live-verified `gemini-2.5-flash` operational baseline after `gemini-3.5-flash` timed out with both 20-second and 60-second limits in the target environment.

## 11. Step 9 scope

### Deliverables

- `POST /api/v1/telegram/webhook` with constant-time validation of `X-Telegram-Bot-Api-Secret-Token`, JSON-only bounded bodies, and controlled 4xx/5xx behavior.
- Strict Telegram update parsing that accepts only private, non-bot text messages and safely acknowledges unsupported update types.
- HMAC-SHA256 pseudonymous user identities using a deployment secret pepper; raw Telegram user/chat identifiers are never persisted.
- Application-lifetime Bot API and Gemini clients with explicit shutdown; `sendMessage` uses protected content and wraps transport/provider errors without token-bearing logs.
- Atomic inbound processing, conversation/routing/LLM/tool audits, outbound persistence, and Telegram delivery inside one caller-owned MySQL transaction; delivery failure rolls back and returns HTTP 502 so Telegram retries.
- Duplicate `update_id` handling that returns the persisted reply and prevents a second tool side effect or second send.
- Session-aware Arabic/English preference with `/ar`, `/en`, `/start`, `/help`, and `/new` commands.
- Deterministic parameter extraction for ISO dates, occupancy, room number, booking reference, verification code, and tracking code; sensitive fields are removed from Gemini context and supplied only to typed tool validation.
- Two-message write confirmation workflow with stable update-derived idempotency and cancellation support.
- Intent-scoped tool enforcement so a valid but unrelated registered tool cannot execute.
- Safe webhook registration command restricted to HTTPS, `message` updates, secret header, and bounded connections.

### Out of scope

- Public domain/TLS/tunnel provisioning and deployment; Step 12 owns the production hosting decision.
- Admin authentication/APIs and React dashboard; these remain Steps 10–11.
- Media, group, channel, business-account, inline, and callback-query flows; the MVP deliberately supports private text messages only.
- Guaranteed exactly-once outbound delivery after an ambiguous Telegram network acknowledgement; the Bot API does not expose an application idempotency key for `sendMessage`.

### Exit gate

- [x] Missing/wrong webhook secret, malformed JSON, unsupported content type, and oversized bodies are rejected before business processing.
- [x] Private Arabic/English messages and commands map to typed channel-neutral input; unsupported updates are acknowledged without side effects.
- [x] Raw Telegram identifiers are converted to keyed HMAC identities and never stored directly.
- [x] Duplicate updates do not create duplicate messages, tool effects, confirmations, or Telegram sends.
- [x] Telegram delivery failure produces a retryable 502 and rolls back the database transaction.
- [x] Language switching persists across later updates even when Telegram's profile language differs.
- [x] State-changing requests require a separate confirmation message and replaying that confirmation is idempotent.
- [x] Booking references, verification codes, tracking codes, and room numbers are removed from Gemini prompt context.
- [x] Webhook registration sends only `message` in `allowed_updates` and includes the configured secret token.
- [x] Ruff, formatting, strict Mypy, Alembic drift, Compose validation, and all 84 unit/integration tests pass in the final Step 9 verifier.
- [ ] Live Telegram delivery is activated. BotFather credentials and local secret configuration passed validation on 2026-07-22; registration is operationally pending only a public HTTPS endpoint and does not block the adapter contract gate.

## 12. Step 10 scope

### Deliverables

- Salted scrypt password hashing and an interactive bootstrap command that never places passwords in shell history.
- Generic credential failures, identifier-scoped login throttling, and committed security audit events.
- Signed 15-minute bearer access tokens with strict parsing, expiry/tamper rejection, no refresh token, and no raw token persistence.
- Per-request active-user lookup and explicit `admin`, `support`, and `evaluator` RBAC policies.
- Searchable/paginated conversation list and message/tool/feedback/escalation timeline with guest pseudonymization and sensitive-value masking.
- Admin-only knowledge create, immutable update revision, approval, archive, and asynchronous checksummed FAISS rebuild endpoints.
- Admin/support service-request listing and validated locked status transitions.
- Explicit evaluator-feedback creation that remains distinguishable from guest feedback.
- Versioned evaluation create/get APIs aggregating frozen intent/retrieval reports and operational answer/LLM/tool metrics.
- Readiness aggregation for MySQL, active FAISS artifact, embedding configuration, and configured Gemini provider.
- Interactive `python -m hotel_bot.admin` bootstrap command and a dedicated `verify-step-10.ps1` gate.

### Out of scope

- React/Vite administration UI, browser token-memory handling, RTL/LTR, and accessibility; these remain Step 11.
- MFA, password reset/email delivery, refresh-token rotation, SSO, multi-hotel tenancy, and individually revocable sessions.
- Production domain/TLS, reverse proxy, secret manager, backup/restore, monitoring alerts, and job recovery; these remain Step 12.
- Treating evaluator labels or guest ratings as automatic ground truth; they remain explicitly sourced observations.

### Exit gate

- [x] Password hashes are salted and verifiable; plaintext passwords and bearer tokens are absent from persistence and logs.
- [x] Missing, malformed, tampered, expired, disabled-user, and wrong-role access fails with controlled `401`/`403` behavior.
- [x] Login failures and role denials remain committed as redacted audit events after the HTTP error response.
- [x] Conversation and service-request projections mask the tested guest hash, booking reference, verification value, email, phone, and tracking code.
- [x] Knowledge CRUD/approval/reindex and request-status transitions reuse existing domain/application rules and pass real-MySQL acceptance.
- [x] Evaluator feedback stays distinct from guest feedback and the evaluation report exposes version/checksum metadata.
- [x] Readiness reports database, FAISS, embedding, and LLM component state without exposing secrets.
- [x] Ruff, formatting, strict Mypy, Alembic drift, Compose validation, and all 89 unit/integration tests pass through `verify-step-10.ps1`.
- [x] Local administration is activated with an ignored `.env` token secret and one explicitly bootstrapped active owner account using a salted scrypt password; no credential value was logged.

## 13. Step 11 scope

### Deliverables

- React 19 and Vite 8 TypeScript SPA with a responsive hotel-operations visual system and no hosted UI dependency.
- Arabic RTL and English LTR runtime switching, logical CSS properties, UTF-8 content, mobile navigation, reduced-motion handling, and high-contrast adjustments.
- Short-lived bearer session held only in React memory, protected routes, and role-aware navigation/actions for `admin`, `support`, and `evaluator`.
- Typed API client with controlled error codes and correlation-ID display; Vite development proxy keeps local API traffic same-origin.
- Operational overview with live readiness for MySQL, FAISS, embedding configuration, and Gemini configuration.
- Searchable/paginated conversation UI with masked detail timeline, intents, tool events, escalation state, and evaluator feedback capture.
- Admin knowledge UI for create, revision review, approval, archive confirmation, and checksummed FAISS rebuild.
- Admin/support service-request queue with filters and domain-approved status transitions.
- Evaluation run list, frozen-dataset execution, version metadata, and four-dimension metric report.
- Paginated evaluation-list API required by the dashboard and covered by the existing real-MySQL administration journey.
- Locked npm dependency graph and `verify-step-11.ps1` full-stack quality gate.

### Out of scope

- Production reverse proxy, frontend container, public domain/TLS, CDN, secret manager, monitoring alerts, and backup/restore; Step 12 owns deployment hardening.
- Refresh tokens, browser-persisted bearer credentials, MFA, password recovery, and SSO.
- Automatic acceptance of evaluator labels as ground truth; the dashboard states and preserves the Step 10 observation-only policy.

### Exit gate

- [x] Role-aware routes expose only authorized operational areas and the backend remains the enforcement boundary.
- [x] Bearer credentials have no `localStorage`, `sessionStorage`, IndexedDB, or cookie persistence path.
- [x] Arabic/English direction switching updates document `lang` and `dir`; layout uses responsive logical properties and keyboard-visible focus.
- [x] Conversations, knowledge, service requests, evaluation runs, evaluator feedback, and component readiness use real Step 10 contracts.
- [x] Destructive knowledge archival requires a visible confirmation dialog and all mutations surface controlled errors.
- [x] Strict TypeScript, 4 frontend contract/security tests, production Vite build, Ruff, formatting, strict Mypy, Alembic drift, all 93 Python/MySQL tests, and Compose validation pass through `verify-step-11.ps1`.

## 14. Step 12 scope

### Deliverables

- Production and local Compose topologies with a non-root Caddy frontend, same-origin FastAPI proxy, internal-only MySQL/API surfaces in production, automatic HTTPS configuration, and persisted certificate storage.
- Read-only backend/frontend containers with all Linux capabilities dropped, no-new-privileges, bounded writable mounts, explicit trusted hosts, and browser/API security headers.
- Dependency-free Prometheus HTTP metrics, structured request completion logs, internal scrape configuration, and validated availability/error-rate/P95 alerts.
- CPU-only Sentence Transformers runtime that avoids CUDA/NCCL/CUDNN production dependencies.
- Timestamped MySQL logical backups with SHA-256 manifests, isolated restore rehearsal, FAISS rebuild policy, and Windows/Linux operator paths.
- Linux systemd timer templates for daily backup and 90-day conversation cleanup, plus deployment, operations, and security runbooks.
- Reproducible local performance evidence, machine-readable release evidence, defense outline, and ten-minute demonstration script.

### Out of scope

- Purchasing a domain, provisioning a public VPS, issuing a real certificate, opening firewall ports, or registering the live Telegram webhook.
- Real hotel PMS/payment integration, multi-hotel tenancy, or production claims based on real guest traffic.
- Treating the local liveness benchmark as public-network, Gemini, Telegram, or concurrency load-test evidence.

### Exit gate

- [x] Ruff, formatting, strict Mypy, Alembic drift, 99 Python/MySQL tests, 4 frontend tests, and the Vite production build pass.
- [x] Development and production Compose configurations validate; Prometheus config and all three alert rules pass `promtool`.
- [x] Backend and frontend release images build; CPU-only Torch prevents CUDA dependency expansion.
- [x] Backend and frontend run non-root with read-only root filesystems, all capabilities dropped, and no-new-privileges.
- [x] Caddy serves the SPA/API with security headers; the public proxy returns 404 for `/api/v1/metrics` while internal metrics remain available.
- [x] Local reverse-proxy liveness measured P95 44.301 ms across 100 samples with zero missing correlation IDs, below the 2,000 ms release gate.
- [x] A checksummed backup restored into an isolated MySQL container: 20 tables, one Alembic row, and 22 knowledge documents in 75.275 seconds; the temporary container was removed.
- [x] Desktop and true 375×812 device-emulated RTL login views pass visual review; measured `innerWidth=375` and `scrollWidth=375` prove no horizontal overflow.
- [x] MySQL, backend, and frontend release containers are healthy after forced recreation.
- [x] Public DNS/TLS, production timer activation, and Telegram webhook registration remain visible deployment-host conditions and are not falsely reported as complete.

## 15. Progress log

| Date | Step | Event | Evidence |
|---|---:|---|---|
| 2026-07-13 | 1 | Step started | Foundation implementation created |
| 2026-07-13 | 1 | Static and automated verification passed | Ruff clean; Ruff format clean; Mypy strict clean; Pytest 9/9 passed; Compose config valid |
| 2026-07-13 | 1 | Local HTTP verification passed | Liveness HTTP 200; unavailable-database readiness HTTP 503 with safe body |
| 2026-07-13 | 1 | Docker runtime diagnostic completed | Engine initially responded, but the image pull left a locked containerd layer; after a safe restart, Docker failed to recreate its WSL distribution with `HCS_E_CONNECTION_TIMEOUT`. No images, containers, volumes, or user WSL distributions were deleted. A Windows restart/WSL recovery is required before Compose runtime verification. |
| 2026-07-13 | 1 | Docker runtime verification passed after Windows restart | Backend and MySQL 8.4 containers healthy; host MySQL port moved to 3307 to avoid the existing MySQL80 service on 3306; liveness HTTP 200; readiness HTTP 200 with `database=ok`; correlation IDs returned. Step 1 closed. |
| 2026-07-13 | 2 | Persistence schema implemented | 18 approved domain tables modeled with SQLAlchemy 2.0; portable checked enums, UUID identifiers, explicit foreign-key deletion policies, privacy-safe fields, and transactional `AsyncSession` boundaries added. |
| 2026-07-13 | 2 | Migration cycle and drift verification passed | Alembic upgraded from base to head, downgraded completely, and re-upgraded on a clean MySQL volume; `alembic check` reported no new operations. |
| 2026-07-21 | 8 | Gemini orchestration implementation verified | Ruff and formatting clean; strict Mypy clean; Alembic upgraded to `a8210f76e4ce` with no drift; 70/70 unit and MySQL integration tests passed. |
| 2026-07-21 | 8 | Live Gemini credential and provider path verified | `gemini-2.5-flash` passed structured output and function calling in two calls using 564 total tokens; no secret or generated content was printed. |
| 2026-07-21 | 8 | Approved 3.5 model compatibility check remained inconclusive | `gemini-3.5-flash` timed out at both 20 and 60 seconds from the same environment; local runtime restored to the verified 2.5 model pending owner decision. |
| 2026-07-21 | 8 | Owner approved operational model and closed Step 8 | `gemini-2.5-flash` adopted as the documented baseline; Step 9 authorized. |
| 2026-07-21 | 9 | Telegram channel and guest-flow implementation completed | Secure webhook, HMAC identity, Bot API sender, command/language flow, bounded parameter extraction, confirmation state, and webhook configuration command added. |
| 2026-07-21 | 9 | MySQL guest journey passed before final gate | `/start`, duplicate replay, `/ar`, retained Arabic, service request, separate confirmation, and duplicate confirmation passed against MySQL. |
| 2026-07-21 | 9 | Final verification passed and Step 9 closed | Ruff and formatting clean; strict Mypy clean; Alembic reported no drift; 84/84 tests passed; Compose configuration valid. |
| 2026-07-22 | 9 | Live Telegram credentials validated securely | Real values are isolated in ignored `.env`, `.env.example` contains placeholders, all Telegram secret formats passed, and the Bot API `getMe` call authenticated `@anas_hotel_support_bot`; webhook registration remains pending public HTTPS deployment. |
| 2026-07-22 | 10 | Administration security and APIs implemented | Scrypt login, short-lived signed bearer access, MySQL-backed active-role checks, three-role RBAC, masked admin projections, knowledge/service/evaluation APIs, component readiness, and bootstrap command added. |
| 2026-07-22 | 10 | Real-MySQL administration acceptance journey passed | Unauthenticated and forbidden access, masking, evaluator feedback, knowledge revision/approval/reindex, support request transition, evaluation aggregation, and committed security audits passed end to end. |
| 2026-07-22 | 10 | Final verifier passed and Step 10 code/test gate closed | Ruff and formatting clean; strict Mypy clean across 135 files; Alembic at `b2d4e6f8091a` with no drift; 89/89 tests passed; Compose configuration valid. |
| 2026-07-22 | 10 | Local administration activated | `ADMIN_TOKEN_SECRET` validated in ignored `.env`; active `anas` owner account with `admin` role and scrypt password hash verified; one bootstrap audit event persisted; no secret or hash value printed. |
| 2026-07-22 | 11 | React administration dashboard implemented | Responsive RTL/LTR shell, memory-only authentication, RBAC navigation, live overview, conversations, evaluator feedback, knowledge lifecycle, service workflow, and versioned evaluation reports added. |
| 2026-07-22 | 11 | Evaluation browsing contract completed | Paginated/status-filtered evaluation-list API added and verified in the real-MySQL administration acceptance journey. |
| 2026-07-22 | 11 | Full Step 11 gate passed | Ruff and formatting clean; strict Mypy clean across 135 files; Alembic reported no drift; 89/89 Python/MySQL and 4/4 frontend tests passed; Vite production build and Compose validation succeeded. |
| 2026-07-23 | 11 | Admin token canonicalization regression fixed | Strict Base64URL, canonical JSON/UUID claims, fixed SHA-256 signature length, constant-time HMAC comparison, and generic malformed/tampered/expired rejection added; payload, signature, truncation, malformed Base64, pad-bit, and exact-expiry boundary regressions pass. |
| 2026-07-23 | 11 | Step 11 re-verification and rebuilt-container check passed | `verify-step-11.ps1` passed 93/93 Python/MySQL and 4/4 frontend tests; rebuilt image and running container IDs matched; container health became `healthy`; in-container non-canonical signature rejection returned the controlled error. |
| 2026-07-24 | 12 | Production runtime and observability implemented | Caddy frontend/reverse proxy, production Compose, non-root/read-only container controls, trusted hosts, security headers, Prometheus metrics, and three alert rules added. |
| 2026-07-24 | 12 | Recovery and CPU-only release hardening passed | SHA-256 backup restored 20 tables and 22 knowledge documents in an isolated container; backend runtime pinned Torch 2.9.1 CPU and avoided CUDA packages. |
| 2026-07-24 | 12 | Full release gate passed | 99/99 Python/MySQL and 4/4 frontend tests; Prometheus valid; Caddy/metrics/security checks pass; P95 44.301 ms; MySQL/backend/frontend healthy; machine-readable release evidence generated. |
| 2026-07-24 | 12 | Responsive release audit passed | Desktop and CDP-emulated 375×812 RTL screenshots reviewed; mobile `scrollWidth` equals `innerWidth` at 375, with fields, action, and copy inside the viewport. |
| 2026-07-13 | 2 | Static and integration verification passed | Ruff clean; Ruff format clean; Mypy strict clean; Pytest 16/16 passed, including real-MySQL schema and commit/rollback tests. Step 2 closed. |
| 2026-07-13 | 3 | Fictional hotel dataset frozen | Nour Al-Sham Grand Hotel dataset v1.0.0 validated: 5 room types, 22 rooms, 6 pseudonymous guests, 8 bookings, and 3 service requests. |
| 2026-07-13 | 3 | Deterministic operations implemented | Availability, masked booking lookup, PBKDF2 verification, idempotent service requests, emergency flags, and controlled status transitions implemented behind a repository boundary. |
| 2026-07-13 | 3 | Static and MySQL verification passed | Ruff clean; Ruff format clean; Mypy strict clean; Alembic drift clean; Pytest 34/34 passed with real-MySQL repeatability and operation scenarios. Step 3 closed. |
| 2026-07-13 | 4 | Conversation lifecycle implemented | Ordered messages, inactivity-based sessions, structured state, and channel-update idempotency ledger added behind provider-neutral service/repository contracts. |
| 2026-07-13 | 4 | Bounded context and retention implemented | Latest-five-complete-turn assembly and token budgeting added; 90-day batched anonymization clears summaries and writes redacted audit evidence. |
| 2026-07-13 | 4 | Static and MySQL verification passed | Ruff clean; Ruff format clean; Mypy strict clean; Alembic drift clean; Pytest 40/40 passed, including real-MySQL idempotency, ordering, session rotation, redaction, and audit scenarios. Step 4 closed. |
| 2026-07-13 | 5 | Taxonomy and frozen dataset implemented | Ten intents frozen at v1.0.0; 240 balanced Arabic/English samples split by scenario into 120 train, 40 validation, and 80 test rows. |
| 2026-07-13 | 5 | Baseline and routing safety implemented | Offline lexical/Naive Bayes classifier, configurable confidence/margin policy, deterministic escalation, missing-parameter clarification, and no-tool-execution invariant added. |
| 2026-07-13 | 5 | Evaluation and MySQL verification passed | Macro F1 0.873; accuracy 0.875; coverage 0.975; accepted accuracy 0.885; Ruff/Mypy/Alembic clean; Pytest 50/50 passed. Step 5 closed. |
| 2026-07-13 | 6 | Bilingual knowledge baseline frozen | 22 approved Arabic/English hotel documents and 44 versioned retrieval cases added with deterministic checksum and ensure-only MySQL seeding. |
| 2026-07-13 | 6 | Safe FAISS lifecycle implemented | Exact cosine index, immutable checksummed artifacts, relational chunk mapping, pre-activation revalidation, and failed-build isolation implemented. |
| 2026-07-13 | 6 | Retrieval and MySQL verification passed | Recall@5 0.977; top-1 0.841; traceability 1.000; Ruff/Mypy/Alembic clean; migration down/up passed; Pytest 55/55 passed. Step 6 closed. |
| 2026-07-13 | 7 | Controlled tool boundary implemented | Six strict allow-listed tools added with caller authorization, executor-owned call limits, per-tool timeout, mandatory write confirmation, and no dynamic execution path. |
| 2026-07-13 | 7 | Privacy and audit contracts implemented | Sensitive arguments/results are redacted; every controlled outcome is persisted with tool name, status, latency, correlation ID, and safe error code. |
| 2026-07-13 | 7 | Full verification passed | All six tools exercised against MySQL; write retry produced one request; emergency guidance and negative contracts passed; Ruff/Mypy/Alembic clean; Pytest 63/63 passed. Step 7 closed. |
