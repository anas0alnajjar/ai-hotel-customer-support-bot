# AI Hotel Customer Support Bot Using Large Language Models and Tool Calling

روبوت ذكي لدعم عملاء الفنادق باستخدام نماذج اللغة الكبيرة وتقنية استدعاء الأدوات.

## Project status

Requirements and architecture are documented. **Steps 1–11 are complete and verified.** Telegram credentials have been validated against the live Bot API; delivery activation requires a public HTTPS webhook. The administration API and bilingual React dashboard are locally ready. Production serving, TLS, backup/restore, and release hardening remain Step 12.

## Implementation reference

- [`implementation-roadmap.md`](./implementation-roadmap.md) is the controlled execution plan and progress reference.
- [`backend/`](./backend/README.md) contains the FastAPI application.
- [`frontend/`](./frontend/) contains the React + Vite administration dashboard.

## Local administration dashboard

With MySQL and the backend running on `127.0.0.1:8000`:

```powershell
cd frontend
npm install
npm run dev
```

Open `http://127.0.0.1:5173`. The Vite development proxy forwards `/api` to FastAPI. Admin bearer tokens are held only in React memory and are discarded on reload or tab closure.

Run the complete Step 11 gate from the repository root:

```powershell
.\scripts\verify-step-11.ps1
```

## الوثيقة الرسمية للمشروع

المخرج المعتمد للمرحلة الأولى هو:

- [وثيقة تحليل المتطلبات والتصميم المعماري للنظام](./requirements-and-system-architecture/requirements-and-system-architecture.md)

وتوجد الملاحق ومعلومات ضبط الوثيقة في [فهرس الوثيقة](./requirements-and-system-architecture/README.md).

## Current scope

- Telegram guest interface.
- React administration dashboard.
- FastAPI modular-monolith backend.
- Hybrid intent routing, RAG, and controlled tool calling.
- Local FAISS knowledge index.
- Simulated hotel operations; no connection to a real PMS in the first release.
- Arabic and English guest support.

## Repository policy

- `requirements-and-system-architecture/` contains the official requirements and architecture document and its appendices.
- Decisions that affect scope, cost, security, or architecture must be recorded before implementation.
