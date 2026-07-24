# Ten-Minute Defense Demo

## Preflight

1. Run `docker compose ps` and show three healthy services.
2. Open `http://127.0.0.1:8080` and show that the dashboard and API are same-origin.
3. Keep `backend/reports/release/step-12-release-evidence.json` available as fallback evidence.

## Demo sequence

1. Show Arabic/English direction switching and the component-readiness overview.
2. Submit a hotel-information question and identify the approved knowledge evidence.
3. Submit a room-service request, show the separate confirmation boundary, and replay the confirmation to demonstrate idempotency.
4. Show the resulting masked conversation/tool timeline in the dashboard.
5. Show the service-request workflow and role-controlled transition action.
6. Open an evaluation run and explain intent, retrieval, answer, and tool metrics.
7. Show that the public proxy returns 404 for `/api/v1/metrics`, while internal backend metrics remain available.
8. Open the latest performance and restore-rehearsal JSON reports.

## Failure-path demonstration

- Explain that provider failure returns controlled unavailability and never a false operational success.
- Show that an unconfirmed write is rejected before Gemini/tool execution.
- Show that an unauthorized dashboard role receives backend-enforced 403 behavior.

## Closing statement

The release proves a secure, observable, recoverable single-hotel MVP. It does not claim real PMS integration or production Telegram activation until a public HTTPS deployment passes the same release gate.
