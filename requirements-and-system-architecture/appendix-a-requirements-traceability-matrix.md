# Requirements Traceability Matrix

## 1. Business goals

| Goal ID | Goal |
|---|---|
| BG-01 | Reduce repetitive front-desk/support workload |
| BG-02 | Improve response speed and consistency for hotel guests |
| BG-03 | Reduce hallucination through grounded knowledge and controlled operations |
| BG-04 | Demonstrate an academically measurable hybrid AI architecture |
| BG-05 | Produce a low-cost, locally deployable foundation for a sellable hotel B2B MVP |

## 2. Traceability matrix

| Requirement group | Business goals | Main components | Verification |
|---|---|---|---|
| FR-001–FR-005 Conversation/channels | BG-01, BG-02 | Telegram adapter, conversation service | Integration and bilingual journey tests |
| FR-006–FR-010 Routing/safe answers | BG-02, BG-03, BG-04 | Hybrid router, LLM adapter, fallback policy | Intent evaluation and adversarial scenarios |
| FR-011–FR-016 Knowledge/RAG | BG-02, BG-03, BG-04 | Knowledge service, RAG service, FAISS | Retrieval metrics, grounding review, index-swap tests |
| FR-017–FR-025 Controlled tools | BG-01, BG-03, BG-04 | Tool registry, hotel operations, database | Contract, privacy, idempotency, and negative tests |
| FR-026–FR-034 Admin/evaluation/reliability/context | BG-01, BG-02, BG-04, BG-05 | Admin API/UI, evaluation, health, retention, and context services | RBAC, UI, offline evaluation, fault-injection, retention, and context-assembly tests |
| NFR-001–NFR-002 Performance/reliability | BG-02, BG-05 | All runtime components | Load and dependency-failure tests |
| NFR-003–NFR-006 Security/privacy/audit | BG-03, BG-05 | API, auth, persistence, logging | Security checklist and automated negative tests |
| NFR-007–NFR-010 Maintainability/portability/testability | BG-04, BG-05 | Architecture boundaries, Docker, adapters | Architecture tests and clean deployment |
| NFR-011–NFR-014 Observability/cost/backup/accessibility | BG-02, BG-05 | Operations, dashboard, deployment | Metrics checks, restore rehearsal, UI review |

## 3. Critical end-to-end acceptance scenarios

| Test ID | Scenario | Requirements covered | Expected result |
|---|---|---|---|
| E2E-001 | Arabic guest asks the check-in policy | FR-003, FR-006, FR-011–FR-014 | Grounded Arabic answer with traceable evidence |
| E2E-002 | English guest asks an unknown hotel-policy question | FR-009, FR-014 | Explicit uncertainty and escalation option; no invented policy |
| E2E-003 | Guest checks availability with valid dates | FR-008, FR-019, FR-025 | Validated simulated availability and audited tool result |
| E2E-004 | Guest supplies check-out before check-in | FR-008, FR-019, FR-024 | No tool side effect; focused validation message |
| E2E-005 | Guest looks up a booking without second verification | FR-008, FR-018, NFR-005 | Requests verification; exposes no booking data |
| E2E-006 | Guest retries the same room-service request | FR-004, FR-021, FR-025 | One request and one stable tracking outcome |
| E2E-007 | Guest reports smoke/fire/electrical danger | FR-009, FR-022 | Emergency guidance and escalation; no false claim of resolution |
| E2E-008 | Prompt asks the bot to ignore policy and invoke a hidden tool | FR-007, FR-017, FR-024 | Rejects unknown/unauthorized action and logs safe category |
| E2E-009 | LLM is unavailable after a tool succeeds | FR-010, FR-032, NFR-002 | Safe deterministic template reports only actual result |
| E2E-010 | Database fails during request creation | FR-021, FR-032, NFR-002 | No confirmation; clear retry/escalation and correlation ID |
| E2E-011 | Admin updates knowledge while guests are querying | FR-011, FR-012, FR-015 | Old index remains until verified new index activates |
| E2E-012 | Unauthorized user opens admin conversation endpoint | FR-026, NFR-004, NFR-005 | Access denied and security event recorded |
| E2E-013 | A conversation has more than five complete turns | FR-002, FR-033, FR-034, NFR-005, NFR-012 | Full history remains in authorized storage, while Gemini receives bounded recent context plus structured state |
| E2E-014 | Raw conversation data reaches 90 days | FR-033, NFR-005, NFR-006 | Cleanup deletes or anonymizes expired content and records an auditable result |

## 4. Coverage rule

Every implementation ticket in later phases must reference at least one requirement ID and one verification item. A requirement cannot be marked **Verified** until objective evidence—automated test, evaluation report, or approved review—is linked.

## 5. Step 3 implementation evidence

| Requirements | Implementation evidence | Verification evidence | Status |
|---|---|---|---|
| FR-018 | Masked booking lookup and PBKDF2 verification policy | Valid, invalid, non-disclosure, strict-schema, and audited MySQL tool tests | Verified |
| FR-019–FR-020 | Versioned room catalog and deterministic availability policy | Capacity, overlap, cancellation, authoritative catalog, and real-MySQL tool tests | Verified |
| FR-021–FR-022 | Idempotent service creation and emergency-contact flag | Confirmed/unconfirmed, retry, payload-conflict, category, emergency, and audit tests | Verified |
| FR-023 | Booking-linked request-status verification | Valid and invalid verification tests through the controlled MySQL tool | Verified |
| FR-028 | Explicit request status state machine with locked current-state check | Valid, skipped, terminal, rollback, concurrent-state, and authenticated admin/support API tests | Verified through Step 10 |

## 6. Step 4 implementation evidence

| Requirements | Implementation evidence | Verification evidence | Status |
|---|---|---|---|
| FR-002–FR-005 | Ordered session/message service, bilingual preference, deterministic help/command contract, secure Telegram adapter, and update ledger | Real-MySQL sequence, duplicate delivery, language-switch, confirmation-replay, payload-conflict, and inactivity-rotation tests | Telegram lifecycle verified; public deployment pending Step 12 |
| FR-033 | Batched 90-day raw-text anonymization, summary clearing, and redacted audit event | Expired/recent boundary, idempotent rerun, no-raw-text, and audit tests | Verified |
| FR-034 | Validated structured state and latest-five-complete-turn context builder with token ceiling | More-than-five, incomplete, redacted, unknown-state-field, injection-boundary, budget-pressure, and live structured-output tests | Gemini serialization, preflight budget, and live smoke verified on `gemini-2.5-flash` |
| NFR-005–NFR-006 | Hashed guest identity boundary, fixed retention marker, explicit transaction ownership, and database constraints | Privacy schema, rollback, idempotency, and real-MySQL migration tests | Verified for Step 4 scope |
| NFR-012 | Configurable history depth, per-turn token/cost ceilings, and MySQL usage telemetry | Deterministic budget tests, real-MySQL migration/drift check, and live two-call usage sample | Verified; live smoke recorded 564 total tokens on `gemini-2.5-flash` |

## Step 9 implementation evidence

| Requirements | Implementation evidence | Verification evidence | Status |
|---|---|---|---|
| FR-001 | Authenticated bounded Telegram webhook plus protected `sendMessage` adapter | Secret, JSON, size, correlation, send, and retry-response API tests | Verified; public URL activation pending deployment |
| FR-002–FR-004 | HMAC guest identity, MySQL conversation/update ledger, language preference, and duplicate-send suppression | Real-MySQL `/start`, replay, `/ar`, retained-language, confirmation, and confirmation-replay journey | Verified |
| FR-005 | Accurate bilingual `/start`, `/help`, `/new`, `/ar`, and `/en` command path with simulation limitation | Arabic/English help and command journey tests | Verified |
| FR-009 | Deterministic escalation/fallback and session-aware confirmation/cancellation boundary | Routing, provider-failure, confirmation, duplicate, and safe-tool-scope tests | Verified |
| FR-032, NFR-003–NFR-007 | Constant-time webhook secret, HMAC identity, bounded payload, prompt redaction, transaction rollback on delivery failure, channel-neutral application contracts | Negative API tests, sensitive-context tests, strict Mypy, and MySQL rollback/idempotency evidence | Verified for Step 9 scope |

## 7. Step 5 implementation evidence

| Requirements | Implementation evidence | Verification evidence | Status |
|---|---|---|---|
| FR-006 | Taxonomy v1.0.0, classifier/dataset checksum version, and atomic message metadata persistence | Dataset-contract, classifier-version, and real-MySQL persistence tests | Verified |
| FR-007 | Deterministic safety rules plus separate classifier confidence/margin policy; all raw predictions deny tool execution | Low-confidence, action-candidate, emergency, model-outage, and no-execution tests | Routing and controlled LLM fallback verified |
| FR-008 | Taxonomy-required parameter contracts and focused clarification decision | Missing-date and state-changing action tests | Classification-side gate verified; tool validation pending Step 7 |
| FR-009 | Explicit human/safety escalation, unsupported fallback, and ambiguity abstention | Arabic/English rule and low-confidence tests | Policy verified; channel/LLM response pending Steps 8–9 |
| FR-010 | Route decisions distinguish knowledge candidates, action candidates, controlled responses, escalation, and unavailable fallback | Typed decision and hybrid-orchestration tests | Structured final response and fail-closed rendering verified |
| FR-030 | Frozen scenario-split dataset and reproducible JSON evaluation artifact | 80-sample held-out report: Macro F1 0.873, accuracy 0.875, coverage 0.975 | Intent dimension verified for synthetic baseline |

## 8. Step 6 implementation evidence

| Requirements | Implementation evidence | Verification evidence | Status |
|---|---|---|---|
| FR-011 | Authorized create, immutable update revision, approve, and archive services with audit events | Active-admin, revision lifecycle, real-MySQL integration, and HTTP RBAC acceptance paths | Verified through Step 10 |
| FR-012, FR-015 | Approved-current-revision build plan, versioned chunk/embedding config, immutable checksummed FAISS artifact, and locked activation | Integrity corruption, duplicate artifact, unsafe path, safe swap, and failed-build isolation tests | Verified |
| FR-013 | Configurable top-k/minimum score and ranked evidence containing chunk/document/revision/index identifiers | 44-query bilingual retrieval benchmark and MySQL evidence assertions | Verified |
| FR-014 | Retrieval returns evidence only and explicit unavailable/insufficient state; stale and archived revisions are filtered | Evidence traceability 1.000, no-answer contract, and evidence-ID allow-list tests | Retrieval and grounded-answer boundary verified |
| FR-016 | Validated text/Markdown normalization, size limits, and deterministic overlapping chunking | Invalid content and deterministic chunk-boundary tests | Verified; PDF intentionally deferred |
| FR-030 | Frozen knowledge dataset checksum and reproducible report | Recall@5 0.977, top-1 accuracy 0.841, MRR 0.887 on 44 Arabic/English cases | Synthetic offline baseline verified |
| FR-031–FR-032 | Integrity failures and embedding/index mismatch raise stable availability errors without corrupting active metadata | FAISS corruption/path/config mismatch, failed-build, and component-readiness tests | Health aggregation verified in Step 10; deployment fault hardening remains Step 12 |

## 9. Step 7 implementation evidence

| Requirements | Implementation evidence | Verification evidence | Status |
|---|---|---|---|
| FR-017 | Closed registry with strict input/output models, public declarations, caller allow-list, timeout, effect, confirmation, sensitive-field, and always-audit metadata | Six-definition registry contract and invalid configuration tests | Verified |
| FR-018 | `lookup_booking` secondary-verification tool and minimal masked output | Valid/wrong verification and audit redaction against seeded MySQL booking | Verified |
| FR-019–FR-020 | `check_room_availability` and `list_room_types` wrappers over authoritative application services | Strict date/occupancy schema and five seeded room types returned through MySQL | Verified |
| FR-021 | Confirmed `create_room_service_request` with backend idempotency key enforcement | Unconfirmed rejection plus two identical calls producing one row and stable tracking code | Verified |
| FR-022 | Confirmed `create_maintenance_request` with explicit emergency guidance fields | Emergency safety request test requires immediate contact and makes no resolution claim | Verified |
| FR-023 | `get_service_request_status` with secondary booking verification | Verified seeded request status through controlled executor | Verified |
| FR-024 | Executor-owned call limit, closed lookup, authorization before validation, forbidden extras, write confirmation, and timeout | Unknown, unauthorized, over-limit, invalid, unconfirmed, timeout, and handler-failure tests | Verified |
| FR-025 | MySQL audit adapter in the same transaction as tool execution with redacted projections | Success/rejection/timeout records contain tool, status, latency, correlation, safe error, and no tested secrets | Verified |

## 10. Step 10 implementation evidence

| Requirements | Implementation evidence | Verification evidence | Status |
|---|---|---|---|
| FR-011, FR-015 | Admin-only HTTP CRUD, immutable revision approval, archival, and background safe-index rebuild over the Step 6 services | Real-MySQL create/update/approve/reindex journey; support role receives audited `403` | Verified |
| FR-026, NFR-004 | Salted scrypt passwords, generic login errors, canonical 15-minute signed bearer tokens, active-user lookup per request, and roles `admin`/`support`/`evaluator` | Password/token tests cover modified payload/signature, truncation, malformed/non-canonical Base64URL, exact expiry boundaries, constant-time signature verification, unauthenticated `401`, forbidden `403`, and role matrix | Verified |
| FR-027, NFR-005 | Paginated/searchable conversations with messages, intents, feedback, escalations, and redacted tool timeline; pseudonymous guest and masked sensitive fields | MySQL acceptance response contains no tested booking reference, verification value, email, phone, raw guest hash, or full tracking code | Verified |
| FR-028 | Admin/support request listing and locked state-machine transition with audit event | Support transition succeeds; evaluator denied; invalid transitions return `409` | Verified |
| FR-029 | Dedicated evaluator feedback endpoint persists `source=evaluator` separately from guest feedback | Evaluator creation and support denial acceptance checks | Verified |
| FR-030 | Versioned run aggregates checksummed frozen intent/retrieval artifacts with MySQL answer-label, LLM reliability, and controlled-tool metrics | Evaluation create/get acceptance path validates all four metric dimensions | Verified |
| FR-031 | Readiness exposes database, FAISS artifact, embedding configuration, and LLM configuration without secrets | Healthy/degraded/database-failure API contract tests | Verified |
| NFR-006 | Successful login, failed login, denied access, mutations, feedback, index, and evaluation events carry actor/resource/correlation metadata | E2E-012 verifies denial/failure events remain committed after `401`/`403` | Verified |

## 11. Step 11 implementation evidence

| Requirements | Implementation evidence | Verification evidence | Status |
|---|---|---|---|
| FR-027 | Searchable/paginated conversation UI with masked message, intent, tool, feedback, and escalation timelines | Typed production build consumes the Step 10 masked contracts; real-MySQL acceptance still asserts sensitive values are absent | Verified |
| FR-028 | Admin/support service-request queue with filters and domain-controlled transition selector | Role route plus backend `403` enforcement; real-MySQL transition and invalid-role cases pass | Verified |
| FR-029 | Message-level evaluator form clearly labels human feedback and preserves `source=evaluator` | Frontend routes by evaluation role; backend acceptance verifies evaluator/guest sources remain distinct | Verified |
| FR-030 | Paginated evaluation-run browser and frozen-dataset execution with version and metric sections | New list contract and create/get/list real-MySQL journey pass | Verified |
| FR-031 | Overview polls public readiness and renders database, FAISS, embedding, and LLM configuration separately | Existing healthy/degraded/failure contracts plus TypeScript production build pass | Verified |
| NFR-009 | Runtime document `lang`/`dir`, Arabic RTL and English LTR copy, UTF-8, and logical CSS properties | Strict TypeScript and responsive production stylesheet build pass | Verified |
| NFR-014 | Skip link, semantic landmarks/tables/forms, visible focus, keyboard navigation, status/error text, reduced motion, and mobile layout | Frontend contract/security tests and production build pass; Step 12 desktop and true 375×812 RTL visual evidence has no horizontal overflow | Verified |

## 12. Step 12 implementation evidence

| Requirements | Implementation evidence | Verification evidence | Status |
|---|---|---|---|
| FR-001–FR-034, E2E-001–E2E-014 | Full backend, MySQL, Gemini, RAG, controlled-tool, Telegram, administration, and dashboard implementation accumulated through Steps 1–11 | `verify-step-12.ps1`: 99 Python/MySQL tests, 4 frontend tests, strict static checks, migration drift check, and production build | Verified for the synthetic single-hotel release baseline |
| NFR-003, NFR-007, NFR-010–NFR-011 | Request metrics/histograms, structured correlation logs, readiness, Caddy proxy, Prometheus scrape and alerts | `promtool` validates one config and three rules; 100 local proxy samples measured P95 44.301 ms with zero missing correlation IDs | Verified locally; public/provider latency remains deployment evidence |
| NFR-004–NFR-006, NFR-012–NFR-013 | Trusted hosts, security headers, canonical admin tokens, closed/audited tools, retention policy, non-root read-only containers, CPU-only pinned runtime | Full regression suite plus runtime inspection confirms capability drop, no-new-privileges, read-only roots, non-root users, public metrics 404 | Verified |
| NFR-005–NFR-006, E2E-014 | 90-day anonymization command, Linux systemd timer, timestamped logical backup with SHA-256 manifest, isolated restore, and FAISS rebuild policy | Restore report confirms 20 tables, one Alembic row, 22 knowledge documents, checksum match, and no retained temporary container | Verified; production timer activation is host-specific |
| NFR-009, NFR-014 | Caddy-served UTF-8 React application with RTL/LTR, responsive logical CSS, accessibility controls, CSP and anti-framing headers | Strict TypeScript, frontend tests, Vite/Caddy production build, release proxy checks, desktop screenshot, and CDP-emulated 375×812 screenshot with `scrollWidth=375` pass | Verified for release implementation |
