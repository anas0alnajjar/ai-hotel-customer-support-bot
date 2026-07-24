# Release Security Checklist

- [ ] `.env` and `.env.production` are ignored and readable only by the operator.
- [ ] Database, Gemini, Telegram, and admin secrets are independent.
- [ ] Production uses an explicit `TRUSTED_HOSTS` list and no wildcard.
- [ ] MySQL and FastAPI have no public production ports.
- [ ] Caddy serves HTTPS and the expected security headers.
- [ ] `/api/v1/metrics` is unavailable through the public proxy.
- [ ] Admin bearer tokens are memory-only, short-lived, canonical, and signature-checked in constant time.
- [ ] Telegram webhook secret comparison and guest pseudonymization use constant-time/HMAC boundaries.
- [ ] Tool calls remain closed, typed, intent-scoped, confirmed for writes, idempotent, and audited.
- [ ] No critical/high dependency or image finding is accepted without documented mitigation.
- [x] Backup checksum and isolated restore rehearsal pass in the release environment.
- [ ] Production host installs the supplied retention/backup timers and reviews their first successful runs.
- [x] Prometheus configuration and three alert rules pass `promtool`; production target health remains a deployment-host check.
- [ ] Logs contain correlation IDs but no tested credentials, raw Telegram IDs, booking verification values, or bearer tokens.
