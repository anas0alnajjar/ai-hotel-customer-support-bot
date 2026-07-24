# Architecture Decision Records

## ADR-001 — Use a modular monolith for the academic MVP

- Status: Proposed
- Date: 2026-07-13

### Decision

Build one FastAPI deployable backend with isolated modules for conversations, intent routing, knowledge/RAG, hotel operations/tools, administration, and evaluation. React and Telegram remain external clients/adapters.

### Rationale

This minimizes deployment cost and cross-service failure modes, accelerates the academic MVP, supports transactional operations, and remains separable later through stable module contracts.

### Trade-off

Independent scaling and deployment are limited compared with microservices. This is acceptable until measured traffic or team boundaries justify separation.

## ADR-002 — Keep the LLM provider replaceable

- Status: Proposed
- Date: 2026-07-13

### Decision

Use an application-owned LLM interface with Gemini API and live-verified model ID `gemini-2.5-flash` as the primary implementation. A local OpenAI-compatible/Llama-family runtime remains an optional later fallback. No business module may import provider SDKs directly.

### Rationale

Access, billing, latency, and availability can vary in Syria. A provider-neutral boundary protects the project even though Gemini is the selected MVP provider.

### Trade-off

Only a common subset of provider features can be guaranteed, and provider-specific tool-call formats require adapter tests.

## ADR-003 — Use RAG for hotel facts and tools for operational facts

- Status: Proposed
- Date: 2026-07-13

### Decision

Policies, facilities, and descriptive hotel information come from approved RAG evidence. Booking, inventory, and service-request facts come from deterministic tools. The LLM only composes the final response.

### Rationale

The separation reduces hallucination and makes each claim auditable.

### Trade-off

Some questions span both paths and require orchestration plus explicit precedence rules: tool results override descriptive text for current operational state.

## ADR-004 — Make FAISS a replaceable derived index

- Status: Proposed
- Date: 2026-07-13

### Decision

Store authoritative knowledge revisions outside FAISS. Persist index version and vector-to-chunk mapping so the index can be rebuilt and atomically replaced.

### Rationale

FAISS is efficient and matches the academic scope, but it is not a document system of record and has limited production filtering/tenant capabilities.

### Trade-off

Multi-hotel commercialization will likely require a vector database or PostgreSQL vector extension later.

## ADR-005 — Keep LangChain outside the domain core

- Status: Proposed
- Date: 2026-07-13

### Decision

LangChain MAY be used in provider/retriever adapters, prompt assembly, or experiments. Tool schemas, hotel operations, authorization, persistence, and routing policy remain application-owned.

### Rationale

This preserves testability and avoids coupling core behavior to a fast-changing orchestration framework.

### Trade-off

Some integrations require small custom adapters rather than framework-wide convenience abstractions.

## ADR-006 — Use a deliberately small intent taxonomy

- Status: Accepted
- Date: 2026-07-13

### Decision

Begin with the ten intents defined in the requirements document. Add an intent only when it changes the system path and has enough distinct training/evaluation examples.

### Rationale

Excessive labels reduce classifier quality, increase annotation cost, and provide little value when several labels lead to the same RAG or fallback path.

### Trade-off

Fine-grained analytics are initially limited and may be derived through secondary tags later.

## ADR-007 — Separate stored history from bounded Gemini context

- Status: Accepted
- Date: 2026-07-13

### Decision

Store raw conversation messages for 90 days, but send only the latest five complete turns, structured session summary/state, current message, and request-specific RAG/tool evidence to Gemini. Apply a configurable token budget and scheduled deletion/anonymization after retention expires.

### Rationale

Database retention supports administration and academic evaluation. Bounded context preserves conversational continuity while controlling cost, latency, privacy exposure, and prompt-injection risk. Structured state prevents important tool parameters from disappearing when prose history is truncated.

### Trade-off

Context assembly and summarization require additional application logic and tests. A poor summary may omit conversational nuance, so deterministic workflow state must not depend on the summary alone.

## ADR-008 — Use an explicit MySQL persistence contract and Alembic-only schema evolution

- Status: Accepted
- Date: 2026-07-13

### Decision

Use SQLAlchemy 2.0 typed declarative models for the 18 approved domain entities and Alembic as the only schema-evolution mechanism. Runtime startup MUST NOT call `metadata.create_all()`.

Use application-generated UUID identifiers, `utf8mb4`, UTC database sessions, named foreign keys with explicit deletion behavior, and database checks for critical numeric and temporal invariants. Persist evolving domain enumerations as validated strings with CHECK constraints rather than MySQL-native ENUMs. Use JSON only for localized content, structured context, version metadata, and redacted audit payloads; relational columns remain authoritative for queryable operational state.

Each application use case owns one explicit `AsyncSession` transaction. Successful use cases commit atomically, while exceptions roll back the complete unit of work. FAISS remains outside MySQL as a rebuildable derived index whose version and vector-to-chunk mapping are stored relationally.

### Rationale

This contract keeps the academic MVP portable, auditable, privacy-aware, and safe under retries. Named constraints and deterministic migrations make schema drift detectable. String-based checked enums avoid MySQL's comparatively expensive native-ENUM alteration path as the MVP taxonomy evolves.

### Trade-off

MySQL DDL is not fully transactional, so failed production migrations can leave partial structural changes. Deployment therefore requires tested upgrade/downgrade paths, backups, and forward-repair procedures. UUID keys and JSON fields also cost more storage and indexing overhead than narrow integer keys and fully normalized tables, which is acceptable for the single-hotel MVP and its external identifiers.

## ADR-009 — Use a versioned ensure-only synthetic hotel seed

- Status: Accepted
- Date: 2026-07-13

### Decision

Use **Nour Al-Sham Grand Hotel** as the single fictional MVP hotel. Store its operational fixture in a strict, bilingual JSON dataset with a semantic dataset version. Generate stable UUIDv5 identifiers from versioned natural keys and use an ensure-only seed process: insert missing seed rows, preserve existing operational changes, and fail when a natural key belongs to an unexpected identifier.

Keep hotel business policies framework-independent. SQLAlchemy implements a repository adapter, while availability, verification, idempotency, emergency classification, and request-state rules remain pure domain/application code. Store only PBKDF2-SHA256 hashes of synthetic booking verification values in MySQL.

### Rationale

A fixed dataset makes academic evaluation reproducible and gives Telegram, tools, RAG, and the dashboard one coherent operational baseline. Ensure-only behavior prevents an ordinary deployment or repeated development command from silently resetting service-request or room state. Stable identifiers make tests and future knowledge references deterministic.

### Trade-off

The committed demonstration verification values are intentionally public synthetic fixtures and are unsuitable for production identity verification. Ensure-only seeding does not repair modified reference data automatically; explicit dataset migrations or an authorized reset workflow will be required when the baseline version changes.

## ADR-010 — Use an ordered, idempotent, privacy-bounded conversation lifecycle

- Status: Accepted
- Date: 2026-07-13

### Decision

Persist a positive sequence number unique within each conversation and serialize message appends by locking the conversation row. Maintain a channel-neutral idempotency ledger with a unique `(channel, external_update_id)` key and a SHA-256 payload fingerprint. Reuse an open guest session for up to 30 minutes of inactivity; close it and create a new session afterward.

Allow only Arabic/English and a validated, small operational context-state schema. Build provider-neutral model context from the current input, structured state, optional request evidence and summary, and at most the latest five complete turns under a configurable token ceiling. Incomplete and retention-redacted messages never enter context.

After 90 days, irreversibly replace raw message text with a fixed retention marker, timestamp and classify the action, clear prose summaries for affected conversations, and retain only structural records and redacted audit metadata. Run cleanup in bounded transactions through a host-schedulable command.

### Rationale

Database constraints protect ordering and retry safety even when later Telegram deliveries are duplicated or concurrent. Separating long-term storage from model context limits Gemini cost and privacy exposure without losing short-session continuity. Anonymization preserves non-content operational metrics and referential integrity while enforcing the approved raw-text lifetime.

### Trade-off

The raw text cannot be recovered after cleanup, so any authorized academic evaluation dataset must be anonymized and versioned separately before expiry. MySQL cannot express a partial unique index for one open conversation per guest, so the application serializes session creation with a guest-row lock. Deployment-specific scheduling remains part of Step 12, while the cleanup command and audit contract are complete now.

## ADR-011 — Use an offline lexical/Naive Bayes baseline with abstention

- Status: Accepted
- Date: 2026-07-13

### Decision

Use a dependency-free multinomial Naive Bayes baseline over normalized Arabic/English word and character n-grams, augmented by a small versioned business lexicon derived from the approved taxonomy. Train only from the frozen training split and version every prediction with algorithm, dataset, and dataset-checksum identifiers.

Apply deterministic rules before statistical prediction for explicit human requests, safety/emergency language, and greeting-only messages. Use stricter confidence for action intents than informational intents plus a minimum top-two margin. Missing required parameters always produce clarification. A state-changing prediction requires later confirmation and backend validation; classification alone always has `allow_tool_execution=false`.

### Rationale

The baseline is reproducible without cloud access, external model downloads, GPU resources, or paid infrastructure, which supports Syrian development constraints and low-cost self-hosting. The abstention policy optimizes safety rather than raw classification coverage and provides a measurable reference before later LLM fallback integration.

### Trade-off

Lexical models are weaker on novel phrasing, code-switching, spelling variation, and dialects than well-evaluated multilingual embeddings. The synthetic 0.873 Macro F1 result is an engineering baseline, not a production claim. Before commercial deployment, the dataset must be expanded with consented, anonymized real guest language and independently re-evaluated without tuning on the held-out set.

## ADR-012 — Use exact cosine FAISS artifacts with validated atomic activation

- Status: Accepted
- Date: 2026-07-13

### Decision

Keep MySQL as the authoritative store for knowledge documents, immutable revisions, approval state, index versions, and vector-to-chunk mappings. Build one immutable UUID-named FAISS artifact from approved current revisions. Normalize multilingual embeddings and use `IndexFlatIP` for exact cosine similarity. Store a canonical manifest containing the pinned embedding identifier, dimension, chunk keys, vector count, and SHA-256 checksums.

Publish the artifact through a temporary directory and atomic rename, then revalidate the complete artifact immediately before a database transaction retires the old active version and activates the new one. A failed build records a bounded error on its own version and cannot alter the active version. Retrieval filters mappings against documents that are still approved and still point to the indexed revision.

Use the pinned multilingual Sentence Transformers model in production. Keep a deterministic hashing adapter exclusively for offline CI and reproducible pipeline evaluation when external package/model access is unavailable. The adapter is forbidden in production configuration.

### Rationale

The single-hotel corpus is small enough that exact search is simpler, deterministic, and cheaper to operate than an approximate index. Checksums and database state prevent a partially written or tampered artifact from silently becoming active. Keeping the offline adapter separate supports development under Syrian connectivity restrictions without misrepresenting it as the production semantic model.

### Trade-off

`IndexFlatIP` grows linearly and would need re-evaluation for a multi-hotel SaaS corpus. The first production model download is comparatively large and requires external connectivity, so deployments should cache or pre-bake the model. The frozen offline metric validates retrieval plumbing and traceability; a production release must also rerun the same benchmark with the pinned Sentence Transformers model in its target environment.

## ADR-013 — Enforce a closed, application-owned controlled-tool boundary

- Status: Accepted
- Date: 2026-07-13

### Decision

Expose exactly six hotel-operation tools through an application-owned registry. Every definition carries strict input/output schemas, a bounded description, allowed callers, timeout, read/write effect, confirmation requirement, sensitive audit fields, and an always-audit policy. The executor—not the LLM or caller—owns the per-turn call ceiling and rejects unknown, unauthorized, invalid, over-limit, and unconfirmed calls before invoking business logic.

Keep handlers as thin adapters over deterministic hotel application services. Never interpret model output as code, SQL, shell commands, imports, or URLs. Execute state-changing service requests and their audit rows within the same caller-owned MySQL transaction. Return controlled status/error codes rather than internal exception messages.

### Rationale

The LLM becomes a proposal source rather than an authority. Central validation preserves privacy and business rules across Gemini, tests, Telegram, and future providers. Reusing the existing domain idempotency policy prevents duplicate service requests under delivery retries while the mandatory audit trail supports incident review and academic evaluation.

### Trade-off

Explicit wrappers require more code than exposing Python functions automatically, but they provide stable security and provider boundaries. A database outage can prevent both the operation and its audit transaction; the orchestrator must fail closed and never claim success. The six-tool allow-list is deliberately single-hotel and must be reviewed before adding any real PMS or physical-control integration.

## ADR-014 — Keep Gemini generative and non-authoritative

- Status: Accepted
- Date: 2026-07-21

### Decision

Use the official Google GenAI Python SDK behind the existing provider-neutral application interface. Pin the tested SDK version and live-verified `gemini-2.5-flash` model identifier. Disable SDK automatic function execution and expose only the intent-scoped declaration selected by the deterministic router. The application validates the proposed function name and arguments through the Step 7 registry/executor before any business operation.

Use structured JSON output for final responses, then revalidate it with Pydantic and enforce per-request evidence-ID and tool-name allow-lists. Serialize conversation text, retrieved chunks, and tool results as explicitly untrusted JSON data under a fixed versioned system instruction. Reserve a conservative token/cost ceiling before each call and store metadata—not prompt/response content—in `llm_runs`.

### Rationale

Function calling is a model proposal mechanism, while business authority belongs to deterministic application code. This preserves confirmation, idempotency, privacy, audit, and fail-closed behavior across Gemini outages and prompt-injection attempts. The provider interface and explicit unavailable response are also deployable from Syria without making the core hotel workflow cloud-only.

### Trade-off

The MVP permits one intent-scoped function proposal per turn rather than an open-ended agent loop. This limits compositional automation but produces predictable cost and a substantially smaller security surface. A live credential is still required to validate provider availability in each target deployment; offline contract tests cannot prove regional network access or account quota.

## ADR-015 — Use an authenticated private-text Telegram webhook boundary

- Status: Accepted
- Date: 2026-07-21

### Decision

Receive Telegram updates only through `POST /api/v1/telegram/webhook`. Validate Telegram's configured secret header with a constant-time comparison before parsing a bounded JSON body. Accept only private, non-bot text messages for the MVP and acknowledge other update types without invoking business logic. Register the webhook with HTTPS, `allowed_updates=["message"]`, a secret token, and bounded connections.

Derive the stored guest identity using HMAC-SHA256 over the Telegram user ID and a deployment-only pepper. Use the raw user/chat ID only transiently to send the current reply. Keep update reservation, conversation/routing/LLM/tool audit, reply persistence, and outbound send inside one transaction so a definite send failure rolls back and Telegram can retry. A completed duplicate update returns without a second send or tool effect.

### Rationale

The boundary minimizes Telegram data, prevents arbitrary public callers from impersonating the platform, and reuses the existing channel-neutral idempotency ledger. Webhooks remove a permanently running polling worker, which is cheaper for the single-hotel MVP and easier to deploy on regional VPS infrastructure. Explicit private-text scope keeps the academic evaluation deterministic.

### Trade-off

Holding a database transaction during LLM and Telegram network calls increases lock duration and will need an outbox/worker redesign at larger scale. A rare ambiguous case remains if Telegram accepts `sendMessage` but the HTTP acknowledgement or database commit is lost, because the Bot API does not accept an application idempotency key for `sendMessage`. Media, groups, callbacks, and business-account updates are intentionally deferred.

## ADR-016 — Use short-lived signed admin access with database-backed RBAC

- Status: Accepted
- Date: 2026-07-22

### Decision

Hash administration passwords with salted scrypt and expose only a bounded login endpoint. Issue
an HMAC-SHA256 signed opaque bearer token containing the admin UUID, issue/expiry timestamps, and a
random token identifier. Access tokens expire after 15 minutes by default. The MVP has no refresh
token: expiration requires a new login and bearer tokens are never stored in MySQL or logs.

On every protected request, verify the signature and lifetime, then reload the user from MySQL and
authorize the current `admin`, `support`, or `evaluator` role. This makes account disabling and role
changes effective without waiting for token expiry. Rate-limit login identifiers through hashed
audit resources, return one generic invalid-credential error, and commit denied/failed security
events before returning `401`, `403`, or `429`. If mandatory audit persistence fails, fail the
request rather than falsely claiming the event was recorded.

Expose only masked/pseudonymous guest references, redact high-risk values from conversation text,
and mask service tracking codes. Keep evaluator feedback explicitly typed as `evaluator`; never
merge it silently with guest feedback or treat it as ground truth.

### Rationale

This design needs no external identity service, Redis, cloud KMS, or paid infrastructure, which
keeps the Syrian/self-hosted MVP deployable and low-cost. Short token lifetime plus a database check
on every request provides simple revocation behavior without introducing refresh-token storage.
Explicit roles and committed denial audits satisfy the academic RBAC and traceability requirements.

### Trade-off

Every protected request performs a small MySQL lookup, and a database outage blocks administration
access. Stateless access tokens cannot be individually revoked; urgent revocation disables the user
or rotates `ADMIN_TOKEN_SECRET`, while a future multi-hotel SaaS may add persisted sessions, MFA,
and refresh-token rotation. Bearer tokens must be held in memory by the Step 11 SPA and must not be
written to localStorage.

## Resolved decisions

| ID | Decision | Accepted baseline | Date |
|---|---|---|---|
| OD-001 | Relational database | MySQL 8 | 2026-07-13 |
| OD-002 | Default online LLM | Gemini API using live-verified `gemini-2.5-flash`; owner approved after 3.5 timed out in the target environment | 2026-07-21 |
| OD-004 | Dataset source | One complete fictional hotel with coherent synthetic data | 2026-07-13 |
| OD-005 | Conversation retention | Raw messages retained for 90 days; bounded five-turn Gemini context plus structured state | 2026-07-13 |

### MySQL trade-off

MySQL matches the approved proposal and is sufficient for the single-hotel MVP. It does not replace FAISS: knowledge embeddings stay in a separately versioned FAISS index. A later multi-hotel product may revisit the storage strategy, but no database migration is justified before product validation.

## Open decisions

| ID | Decision needed | Options | Recommendation | Blocks |
|---|---|---|---|---|
| OD-003 | Local runtime | Ollama / llama.cpp-compatible server / none | Choose after recording CPU, RAM, and GPU/VRAM | Offline demonstration |
| OD-006 | Admin frontend | React + Vite / Next.js | React + Vite for a dashboard-only SPA and simpler self-hosting | Frontend skeleton |
