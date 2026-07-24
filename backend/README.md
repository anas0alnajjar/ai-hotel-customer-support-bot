# Backend

FastAPI backend for the AI Hotel Customer Support Bot.

## Local setup on Windows

From the project root:

```powershell
.\scripts\setup.ps1
.\scripts\verify-step-08.ps1
docker compose up --build
```

Docker Desktop must be running with the Linux container engine initialized. If `docker info` cannot reach the engine, start Docker Desktop with Administrator approval and complete its WSL setup before running Compose.

Compose exposes its MySQL instance on host port `3307` by default because the Windows development machine may already run MySQL80 on `3306`. Containers continue to use port `3306` inside the Compose network.

If Docker Desktop remains in `starting` and its logs report `HCS_E_CONNECTION_TIMEOUT` while importing `docker-desktop`, restart Windows before retrying. Do not use Factory Reset because that can delete Docker data and is not required by this project.

Endpoints:

- `GET http://127.0.0.1:8000/api/v1/health/live`
- `GET http://127.0.0.1:8000/api/v1/health/ready`
- `POST http://127.0.0.1:8000/api/v1/telegram/webhook`
- `POST http://127.0.0.1:8000/api/v1/admin/auth/login`
- `GET http://127.0.0.1:8000/api/v1/admin/auth/me`
- `/api/v1/admin/conversations`, `/knowledge`, `/service-requests`, and `/evaluations`
- `GET http://127.0.0.1:8000/docs` in non-production environments

Step 10 administration endpoints use a 15-minute signed bearer token and re-read the active
MySQL user and role on every request. Configure `ADMIN_TOKEN_SECRET` only in `.env` with at least
32 random characters. The MVP intentionally has no refresh token; an expired access token requires
a new login, while disabling a user blocks an otherwise unexpired token immediately.

Create the first administration user interactively so its password never enters shell history:

```powershell
.\.venv\Scripts\python.exe -m hotel_bot.admin `
  --email "admin@example.com" `
  --username "admin" `
  --role admin
```

Available roles are `admin`, `support`, and `evaluator`. Verify all administration security and
real-MySQL acceptance paths with:

```powershell
.\scripts\verify-step-10.ps1
```

Step 8 provides an application-owned Gemini adapter, structured outputs, safe function proposals,
grounding validation, and cost telemetry. A valid key must exist only in `.env`; verify the live path with:

```powershell
.\.venv\Scripts\python.exe -m hotel_bot.llm
```

The command prints provider/model/token status only and never prints the key or response content.
Use `verify-step-08.ps1 -SkipLiveGemini` for offline CI; a release gate must run without that switch.

Verify the Telegram adapter and MySQL-backed guest journeys with:

```powershell
.\scripts\verify-step-09.ps1
```

After deploying the backend behind public HTTPS and setting `TELEGRAM_BOT_TOKEN`,
`TELEGRAM_WEBHOOK_SECRET`, and `TELEGRAM_IDENTITY_PEPPER` only in `.env`, register the webhook:

```powershell
.\scripts\configure-telegram-webhook.ps1 `
  -Url "https://hotel.example/api/v1/telegram/webhook"
```

The webhook accepts private text messages only. Telegram IDs are converted to keyed HMAC values;
the raw user/chat IDs are used transiently for delivery and are not persisted.

Conversation retention can be run manually—or invoked by the deployment scheduler later—with:

```powershell
.\scripts\cleanup-conversations.ps1
```

This command anonymizes raw message text older than the configured 90-day period in bounded, audited batches. It is intentionally separate from the web process so it works on local, regional, or low-cost self-hosted infrastructure.

Rebuild the frozen bilingual intent dataset and offline report with:

```powershell
.\scripts\evaluate-intents.ps1
```

Seed the approved bilingual Nour Al-Sham knowledge documents and run the reproducible
Recall@5 report with:

```powershell
.\scripts\seed-knowledge.ps1
.\scripts\evaluate-knowledge.ps1
```

The default evaluator uses the deterministic offline embedding adapter so CI does not depend
on blocked or unstable external downloads. To validate the pinned production multilingual model,
install `backend[embeddings]` when internet access is available and run:

```powershell
.\scripts\evaluate-knowledge.ps1 -Provider sentence_transformers
```

MySQL stores authoritative document revisions and vector-to-chunk mappings. FAISS and the model
cache are derived local artifacts; Docker keeps them in separate named volumes so an index can be
rebuilt or rolled back without changing approved knowledge.
