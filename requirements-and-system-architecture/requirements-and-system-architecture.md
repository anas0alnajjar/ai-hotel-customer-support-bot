# وثيقة تحليل المتطلبات والتصميم المعماري للنظام

**Software Requirements Specification and System Architecture Document**

| الحقل | القيمة |
|---|---|
| المشروع | روبوت ذكي لدعم عملاء الفنادق باستخدام نماذج اللغة الكبيرة وتقنية استدعاء الأدوات |
| Project | AI Hotel Customer Support Bot Using Large Language Models and Tool Calling |
| مالك المشروع | Anas Al-Najjar |
| الإصدار | 0.1.0-draft |
| المرحلة | دراسة وتحليل المتطلبات وتصميم النظام |
| التاريخ | 2026-07-13 |
| الحالة | مسودة جاهزة للاعتماد |

الملاحق المرتبطة: [مصفوفة تتبع المتطلبات](./appendix-a-requirements-traceability-matrix.md)، [سجل القرارات المعمارية](./appendix-b-architecture-decisions.md)، و[ميثاق المشروع وضبط النطاق](./appendix-c-project-charter-and-scope.md).

## 1. Purpose

تحدد هذه الوثيقة متطلبات النسخة الأكاديمية الأولى وتصميمها المبدئي بصورة قابلة للتتبع والاختبار. الكلمات **MUST**, **SHOULD**, and **MAY** indicate mandatory, recommended, and optional behavior.

## 2. Assumptions and constraints

- The first release models one complete fictional hotel and uses a coherent synthetic dataset.
- MySQL 8 is the authoritative relational database; FAISS remains a separate derived vector index.
- Gemini API is the primary LLM provider, using the live-verified `gemini-2.5-flash` model ID.
- Hotel operations are simulated and have no legal or financial effect.
- Telegram user identity is not sufficient proof of hotel-guest identity.
- Booking access therefore requires a booking reference plus a second matching attribute, while responses expose only minimal data.
- Arabic and English are mandatory; dialect handling is best-effort and evaluated separately.
- The system must remain usable from a Windows development environment and deployable with Docker.
- Online LLM access may be unreliable or restricted; deterministic tools and administrative functions must not depend on a specific LLM provider.
- FAISS is a local derived index, not the authoritative store for knowledge documents.

### 2.1 Conversation retention versus LLM context

Conversation storage and model context are separate concerns:

- **Database retention:** raw conversation messages remain searchable by authorized administrators for 90 days. A scheduled cleanup then deletes or anonymizes raw guest text and direct identifiers according to the configured policy. Non-identifying aggregate metrics may be retained longer.
- **LLM context:** the complete stored history is never sent to Gemini on every message. The default prompt includes the latest five complete conversation turns (up to five guest messages and their corresponding assistant responses), a compact structured session summary/state, the current user message, and only the RAG evidence or tool results required for the current request.
- **Token budget:** five turns are a safe starting policy, not an unconditional count. Oversized messages are trimmed or summarized to stay within the configured token and cost budget.
- **Structured state:** required parameters already collected—such as language, dates, occupancy, masked booking reference, room number, and active request tracking code—are stored separately from prose so important operational context is not lost when older turns leave the prompt.
- **Session boundary:** an explicit new conversation, prolonged inactivity, or a completed workflow can reset recent context while preserving the auditable database record.

This design keeps follow-up questions coherent without repeatedly transmitting the full 90-day history, reducing latency, token cost, privacy exposure, and prompt-injection surface.

## 3. Primary user journeys

### UC-01 — Answer a hotel-information question

1. Guest asks about a hotel policy or service.
2. System detects the language and intent.
3. Retriever selects relevant approved knowledge chunks.
4. LLM answers only from the supplied context and communicates uncertainty when evidence is insufficient.
5. System stores the response, evidence references, latency, and model metadata.

### UC-02 — Look up a simulated booking

1. Guest supplies a booking reference and a second verification attribute.
2. Backend validates the tool arguments and applies rate limits.
3. Booking service returns a minimal safe result.
4. LLM formats the deterministic result without changing its facts.
5. Tool request and result are added to the audit trail with sensitive fields redacted.

### UC-03 — Check room availability

1. Guest provides check-in date, check-out date, and guest count.
2. Backend validates dates and occupancy rules.
3. Availability tool queries simulated inventory.
4. System returns available room types and states that the result is a simulation, not a confirmed booking.

### UC-04 — Create a service or maintenance request

1. Guest describes the need and provides/confirm a room number when required.
2. Backend validates category, description, room, urgency, and duplicate/idempotency key.
3. Tool creates a request and returns a tracking code.
4. System confirms the exact recorded details and escalation guidance for emergencies.

### UC-05 — Administer the knowledge base

1. Authorized administrator creates or updates a knowledge document.
2. System validates content and records the revision.
3. Reindex job chunks and embeds approved documents.
4. New index becomes active only after successful build and health checks.

### UC-06 — Escalate to a human

1. System detects low confidence, unsupported requests, repeated failures, or safety-sensitive language.
2. It explains the limitation and creates an escalation record or gives the configured reception contact path.
3. It does not claim that an employee has acted unless a recorded workflow confirms it.

## 4. Functional requirements

### 4.1 Conversation and channels

| ID | Requirement | Priority | Acceptance summary |
|---|---|---:|---|
| FR-001 | The system MUST receive Telegram text messages and return a response to the originating chat. | Must | Valid webhook update produces one correlated reply |
| FR-002 | The system MUST create and maintain a conversation session with message order, timestamps, language, and correlation ID. | Must | Ordered history is retrievable by an authorized admin |
| FR-003 | The system MUST support Arabic and English and preserve the user's language unless explicitly asked to switch. | Must | Bilingual scenario set passes |
| FR-004 | The system MUST handle duplicate Telegram updates idempotently. | Must | Replayed update does not duplicate effects |
| FR-005 | The system SHOULD provide a clear command/help path describing supported capabilities and limitations. | Should | `/start` or equivalent displays accurate scope |

### 4.2 Intent routing and safe response generation

| ID | Requirement | Priority | Acceptance summary |
|---|---|---:|---|
| FR-006 | The system MUST classify each actionable message into a versioned intent taxonomy and store confidence and classifier version. | Must | Result includes label, confidence, and version |
| FR-007 | The router MUST combine deterministic rules, classifier confidence, and controlled LLM fallback; no single low-confidence prediction may trigger a state-changing tool. | Must | Low-confidence action test cannot execute a tool |
| FR-008 | The system MUST request missing required parameters before tool execution. | Must | Incomplete scenarios produce clarification, not execution |
| FR-009 | The system MUST use a safe fallback or human escalation for unsupported, ambiguous, or sensitive requests. | Must | Defined fallback scenarios pass |
| FR-010 | Final answers MUST distinguish confirmed tool results, knowledge-based information, and unavailable information. | Must | Response evaluation confirms no fabricated status |

### 4.3 Knowledge base and RAG

| ID | Requirement | Priority | Acceptance summary |
|---|---|---:|---|
| FR-011 | Authorized administrators MUST create, update, archive, and version hotel knowledge documents. | Must | CRUD plus revision history tests pass |
| FR-012 | The system MUST build a FAISS index from approved document revisions using a versioned chunking and embedding configuration. | Must | Rebuild produces traceable index metadata |
| FR-013 | Retrieval MUST apply configured similarity/top-k rules and return source document/chunk identifiers. | Must | Retrieval response contains ranked evidence IDs |
| FR-014 | Hotel-fact answers MUST be based on retrieved approved content; insufficient evidence MUST trigger an uncertainty response. | Must | Grounding test set meets target |
| FR-015 | Administrators MUST be able to rebuild the index without corrupting the currently active index. | Must | Failed build leaves previous index active |
| FR-016 | The system SHOULD support common text-based knowledge inputs in the MVP; PDF ingestion MAY be added only if extraction quality is tested. | Should | Supported formats are documented and validated |

### 4.4 Controlled tools

| ID | Requirement | Priority | Acceptance summary |
|---|---|---:|---|
| FR-017 | The tool registry MUST expose strict typed schemas, descriptions, authorization policy, timeout, and audit policy for every tool. | Must | Registry contract test passes |
| FR-018 | The system MUST simulate booking lookup with a booking reference and second verification attribute, returning minimal data. | Must | Valid/invalid/privacy cases pass |
| FR-019 | The system MUST simulate room availability for a valid date range, occupancy, and optional room type. | Must | Boundary and inventory cases pass |
| FR-020 | The system MUST list room types and their approved attributes from authoritative application data. | Must | Returned values match seeded data |
| FR-021 | The system MUST create room-service requests with validation and an idempotent tracking code. | Must | Retry produces one request |
| FR-022 | The system MUST create maintenance requests and distinguish normal issues from emergency guidance. | Must | Emergency scenario does not promise automated resolution |
| FR-023 | The system MUST return the status of an existing service request after appropriate verification. | Must | Status lookup privacy cases pass |
| FR-024 | The backend MUST reject unknown tools, invalid arguments, unauthorized calls, and tool calls exceeding configured limits. | Must | Negative contract suite passes |
| FR-025 | Every tool attempt MUST record tool name, validated/redacted arguments, result status, latency, and correlation ID. | Must | Audit record exists for success and failure |

### 4.5 Administration, monitoring, and evaluation

| ID | Requirement | Priority | Acceptance summary |
|---|---|---:|---|
| FR-026 | Administrators MUST authenticate and access only authorized administration functions. | Must | Unauthenticated/forbidden tests pass |
| FR-027 | The dashboard MUST display searchable conversations, detected intents, tool events, feedback, and escalation status with sensitive values masked. | Must | Admin acceptance scenario passes |
| FR-028 | Administrators MUST review and update simulated service-request status. | Must | Valid state transitions pass |
| FR-029 | The system MUST collect explicit guest feedback or evaluator labels without silently treating it as ground truth. | Must | Feedback and evaluation labels remain distinguishable |
| FR-030 | The system MUST support an offline evaluation run that calculates versioned intent, retrieval, answer, and tool metrics. | Must | Repeatable report is generated from frozen dataset |
| FR-031 | The system MUST expose health information for the API, database, active FAISS index, embedding model, and configured LLM provider. | Must | Health scenarios show component status |
| FR-032 | The system MUST degrade gracefully when Telegram, LLM, embedding model, database, or FAISS is unavailable. | Must | Fault-injection scenarios return controlled outcomes |
| FR-033 | Raw conversation messages MUST follow a configurable 90-day retention policy with automated deletion or anonymization and an auditable cleanup result. | Must | Expired-data and cleanup audit tests pass |
| FR-034 | Each Gemini request MUST use a bounded context containing the latest five complete turns, structured session state/summary, current message, and request-specific evidence, subject to a configured token budget. | Must | Context assembly tests exclude unrelated/full history and preserve required state |

## 5. Intent taxonomy v0.1

| Intent code | Meaning | Expected path |
|---|---|---|
| `hotel_info` | Facilities, location, check-in/out, policies, Wi-Fi, dining | RAG |
| `room_types` | Room categories and attributes | Tool or authoritative catalog |
| `room_availability` | Availability for dates and occupancy | Tool |
| `booking_lookup` | Existing booking inquiry | Tool with verification |
| `room_service_request` | Food, amenities, housekeeping request | Tool |
| `maintenance_request` | Room equipment or maintenance problem | Tool |
| `service_request_status` | Existing request status | Tool with verification |
| `human_escalation` | Explicit human request or forced escalation | Escalation workflow |
| `greeting_smalltalk` | Greeting or supported light conversation | Controlled response |
| `unsupported` | Outside system scope | Fallback |

The taxonomy is intentionally small for measurable data quality. New labels require sufficient examples, a distinct business path, and an update to the evaluation set.

## 6. Tool contracts v0.1

| Tool | Required inputs | Key validations | Result |
|---|---|---|---|
| `lookup_booking` | `booking_reference`, `verification_value` | format, rate limit, match, masking | minimal booking summary or safe not-found result |
| `check_room_availability` | `check_in`, `check_out`, `adults` | future dates, check-out after check-in, occupancy | available room types; never a confirmation |
| `list_room_types` | none; optional filters | approved catalog only | room type summaries |
| `create_room_service_request` | `room_number`, `category`, `description` | room format, allowed category, length, idempotency | tracking code and recorded state |
| `create_maintenance_request` | `room_number`, `category`, `description`, `urgency` | allowed values, emergency policy, idempotency | tracking code and recorded state |
| `get_service_request_status` | `tracking_code`, `verification_value` | format, match, masking | status and safe public timeline |
| `create_human_escalation` | `reason`, `conversation_id` | deduplication, configured contact workflow | escalation reference or contact instruction |

Tool outputs are structured application facts. The LLM may rephrase them but MUST NOT add statuses, prices, confirmations, or commitments absent from the result.

## 7. Non-functional requirements

| ID | Category | Requirement / proposed target |
|---|---|---|
| NFR-001 | Performance | P95 online end-to-end response ≤ 10 s; deterministic tool endpoint ≤ 2 s excluding external network latency |
| NFR-002 | Availability | Dependency failure returns a controlled response and correlation ID; no silent message loss |
| NFR-003 | Security | Secrets only through environment/secret storage; no secret or token in repository, prompts, client bundle, or logs |
| NFR-004 | Access control | Admin endpoints use authenticated RBAC; guest endpoints cannot access admin data |
| NFR-005 | Privacy | Collect minimum guest data, mask identifiers in the UI/logs, and configure retention/deletion |
| NFR-006 | Auditability | Conversation, retrieval, model, prompt, tool, and admin events are traceable by correlation ID and version |
| NFR-007 | Maintainability | Layer boundaries keep domain/application logic independent of Telegram, LangChain, FAISS, and a specific LLM vendor |
| NFR-008 | Portability | Local Windows development and Docker deployment must be supported without AWS/GCP/Vercel dependencies |
| NFR-009 | Internationalization | UTF-8 throughout; Arabic RTL and English LTR render correctly in Telegram and dashboard |
| NFR-010 | Testability | Core routing, tools, and RAG evaluation run offline with mocked LLM/provider boundaries |
| NFR-011 | Observability | Structured logs, correlation IDs, error categories, latency, token usage, and tool metrics are available |
| NFR-012 | Cost control | Per-request token limits, context limits, timeouts, retries, caching policy, and provider usage metrics are configurable |
| NFR-013 | Backup | Authoritative database and knowledge documents have documented backup/restore; FAISS can be rebuilt |
| NFR-014 | Accessibility | Admin dashboard supports keyboard navigation, readable contrast, and clear status/error text |

## 8. Logical component design

| Component | Responsibility | Must not own |
|---|---|---|
| Channel adapters | Telegram webhook mapping and future channel integration | Business rules or direct model prompts |
| API layer | HTTP contracts, authentication boundary, validation, error mapping | Database-specific business logic |
| Conversation service | Session lifecycle, message orchestration, correlation | Vendor-specific SDK logic |
| Hybrid intent router | Rules, classifier, confidence policy, route decision | Tool execution |
| RAG service | Query normalization, retrieval, context assembly, evidence metadata | Authoritative document CRUD |
| Knowledge service | Document revisions, approval state, reindex orchestration | Natural-language answer generation |
| Tool registry | Allowed tool definitions, typed validation, execution policy | Arbitrary dynamic code execution |
| Hotel operations | Booking/inventory/request business rules | LLM prompt logic |
| LLM adapter | Provider-neutral chat/tool proposal interface, retries, token accounting | Authorization or final business validation |
| Evaluation service | Frozen datasets, metric calculation, run/version metadata | Production mutation workflows |

## 9. Data design v0.1

### 9.1 Core entities

| Entity | Key fields | Notes |
|---|---|---|
| `admin_users` | id, username/email, password_hash, role, status, timestamps | No plaintext passwords |
| `guests` | id, telegram_user_hash, preferred_language, timestamps | Store minimal/pseudonymous identity |
| `conversations` | id, guest_id, channel, status, summary, context_state_json, summary_through_message_id, started_at, closed_at | One guest can have multiple sessions; structured context is not raw model memory |
| `messages` | id, conversation_id, direction, text, language, intent, confidence, correlation_id, timestamps | Retention and redaction apply |
| `llm_runs` | id, message_id, provider, model, prompt_version, token counts, latency, status | Prompts/secrets must be sanitized |
| `knowledge_documents` | id, title, language, status, current_revision_id, timestamps | Authoritative metadata |
| `knowledge_revisions` | id, document_id, content, checksum, version, created_by, created_at | Immutable revisions preferred |
| `knowledge_chunks` | id, revision_id, chunk_index, text, metadata, embedding_config_id | FAISS maps vector IDs to these rows |
| `index_versions` | id, embedding_model, chunk_config, checksum, status, activated_at | Enables safe index swap |
| `bookings` | id, reference, guest verification hash, dates, room_type_id, status | Synthetic data only |
| `room_types` | id, code, localized name/description, capacity, active | Prices optional and explicitly labeled |
| `rooms` | id, room_number, room_type_id, operational_status | Simulated inventory |
| `service_requests` | id, tracking_code, type, category, room_id, description, urgency, status, idempotency_key, timestamps | Auditable state transitions |
| `tool_executions` | id, message_id, tool_name, arguments_redacted, result_status, latency, correlation_id, timestamps | Never store secrets/raw verification values |
| `escalations` | id, conversation_id, reason, status, assigned_to, timestamps | Does not imply human action until updated |
| `feedback` | id, message_id, source, rating, label, comment, timestamps | Separate guest vs evaluator labels |
| `evaluation_runs` | id, dataset_version, system_versions, metrics_json, started_at, finished_at | Reproducible comparisons |
| `audit_events` | id, actor_type, actor_id, action, resource_type/id, metadata_redacted, created_at | Append-oriented |

### 9.2 Data ownership

- The relational database is authoritative for operational and document metadata.
- Knowledge revision content is authoritative in database or managed file storage; the exact choice is an implementation decision.
- FAISS contains derived vectors and can always be rebuilt from approved revisions.
- The dashboard never receives secrets, raw verification values, or unrestricted model prompts.

## 10. API surface v0.1

| Method and path | Purpose | Actor |
|---|---|---|
| `POST /api/v1/telegram/webhook` | Receive validated Telegram updates | Telegram |
| `GET /api/v1/health/live` | Process liveness | Operator |
| `GET /api/v1/health/ready` | Dependency readiness | Operator |
| `POST /api/v1/admin/auth/login` | Admin authentication | Admin |
| `GET /api/v1/admin/auth/me` | Resolve current active principal and role | Admin/support/evaluator |
| `GET /api/v1/admin/conversations` | Filtered, paginated, masked conversation list | Admin/support/evaluator |
| `GET /api/v1/admin/conversations/{id}` | Masked message, feedback, escalation, and tool timeline | Admin/support/evaluator |
| `GET/POST /api/v1/admin/knowledge` | List/create knowledge documents | Admin |
| `GET/PATCH/DELETE /api/v1/admin/knowledge/{id}` | Read/update/archive document | Admin |
| `POST /api/v1/admin/knowledge/{id}/revisions/{revision_id}/approve` | Approve one immutable revision | Admin |
| `POST /api/v1/admin/knowledge/reindex` | Start controlled index build | Admin |
| `GET /api/v1/admin/service-requests` | List operational requests | Admin/support |
| `PATCH /api/v1/admin/service-requests/{id}/status` | Valid request-state transition | Admin/support |
| `POST /api/v1/admin/messages/{id}/feedback` | Store an explicit evaluator label/rating | Admin/evaluator |
| `POST /api/v1/admin/evaluations` | Run an offline/versioned evaluation | Admin/evaluator |
| `GET /api/v1/admin/evaluations/{id}` | Retrieve metrics/report status | Admin/evaluator |

Step 10 freezes these contracts with strict Pydantic request bodies, bounded search/pagination,
stable machine-readable errors, `401` for invalid authentication, `403` for role denial, `409` for
invalid operational transitions, and `422` for invalid domain commands. Login returns a signed
15-minute bearer token with no refresh token in the MVP; every protected request reloads the active
user and current role from MySQL.

## 11. Security and safety controls

1. Verify Telegram webhook secret/header and reject oversized or malformed updates.
2. Authenticate admins with secure password hashing and short-lived access tokens; define refresh/session behavior in Phase 2.
3. Rate-limit login, booking verification, request-status lookup, and LLM-heavy endpoints.
4. Treat user text and retrieved documents as untrusted input; retrieved instructions cannot override system/tool policies.
5. Use allow-listed tools with strict schemas; never execute generated code, SQL, shell commands, or arbitrary URLs.
6. Redact booking verification values, tokens, credentials, and sensitive identifiers before logging.
7. Apply output rules for emergencies: direct the guest to hotel emergency/reception channels and do not claim real-world action without a recorded workflow.
8. Record prompt/model/index/tool versions for post-incident analysis.
9. Enforce the 90-day raw-conversation retention policy through an auditable scheduled cleanup; evaluation datasets are separately versioned and anonymized.

## 12. RAG design

1. Admin creates or edits a versioned document.
2. Approved content is normalized without losing Arabic characters or semantic structure.
3. Content is chunked using a versioned configuration.
4. A multilingual Sentence Transformers model generates normalized embeddings locally.
5. FAISS index build is written to a new version and validated before atomic activation.
6. Query retrieves top-k chunks and applies a relevance/confidence policy.
7. Prompt receives only approved evidence, source metadata, language instruction, and strict grounding rules.
8. Answer stores evidence IDs, prompt version, provider/model, and evaluation metadata.

Initial embedding candidate: `sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2` for a lightweight bilingual baseline. This is a proposed benchmark candidate, not a final model choice; it must be compared with at least one stronger multilingual candidate on the project dataset.

## 13. Error and fallback policy

| Condition | Required behavior |
|---|---|
| Low intent confidence | Ask a focused clarification or escalate; do not execute an action |
| No sufficiently relevant knowledge | State that verified information is unavailable and offer escalation |
| Invalid tool arguments | Explain the required field/format without exposing internals |
| Duplicate update/retry | Return/reuse prior safe outcome; do not duplicate state |
| LLM unavailable | Return deterministic tool data through a safe template where possible; otherwise controlled fallback |
| FAISS/index unavailable | Disable grounded FAQ answers and expose component failure to health/operations |
| Database unavailable | Do not claim requests/bookings were recorded; return a retry/escalation message |
| Suspected prompt injection | Ignore instruction conflict, avoid tool execution, log security category, and safely respond |

## 14. Evaluation design

| Dimension | Dataset unit | Primary metrics |
|---|---|---|
| Intent | Bilingual utterance with gold intent | Macro F1, per-class precision/recall, confusion matrix |
| Retrieval | Question with relevant chunk IDs | Recall@k, MRR, nDCG@k |
| Answer quality | Question, evidence, expected facts | Correctness, groundedness, completeness, refusal quality |
| Tool selection | User scenario and expected tool/arguments | Tool accuracy, argument exact/field match, invalid-call rate |
| Tool execution | Valid/invalid contract cases | Pass rate, idempotency, authorization/privacy failures |
| End-to-end | Complete guest journey | Success rate, P50/P95 latency, fallback rate, token/cost estimate |

Evaluation data must be split by scenario—not by paraphrase—to prevent near-duplicate leakage between train and test sets.

## 15. Risks and mitigations

| Risk | Impact | Mitigation |
|---|---|---|
| Gemini or other cloud access is unavailable from Syria | High | Provider adapter, local compatible runtime, cached/offline evaluation, no cloud-only architecture |
| Arabic/dialect retrieval quality is weak | High | Multilingual model benchmark, Arabic-aware normalization, curated hard-negative test cases |
| LLM hallucinates hotel facts or tool success | High | Evidence-only prompts, deterministic tool results, response distinction, automated evaluation |
| Intent classifier causes wrong action | High | Confidence thresholds, confirmation/missing-parameter flow, backend validation, no direct execution from raw model output |
| Personal data leaks in logs/dashboard | High | Minimization, hashing, redaction, RBAC, retention policy, privacy tests |
| Scope expands into a full PMS | High | Enforce out-of-scope list and phase change control |
| Framework/vendor lock-in | Medium | Domain boundaries, provider interfaces, limited LangChain surface |
| Local hardware cannot run selected models | Medium | Lightweight embeddings, quantized optional LLM, online provider when accessible, benchmark before freeze |

## 16. Phase 1 acceptance checklist

- [ ] Owner approves the in-scope and out-of-scope lists.
- [ ] Owner approves the intent taxonomy and simulated tool list.
- [x] Owner selects MySQL 8 as the relational database baseline.
- [x] Owner selects Gemini API with live-verified model ID `gemini-2.5-flash` as the primary LLM (approved 2026-07-21 after 3.5 timed out in the target environment).
- [x] Owner selects one complete fictional hotel and a 90-day raw-conversation retention policy.
- [ ] Owner confirms whether a local LLM fallback is required for offline demonstrations.
- [ ] Academic supervisor feedback is incorporated where required.
- [ ] Requirements and traceability matrix are baselined as `1.0.0`.
