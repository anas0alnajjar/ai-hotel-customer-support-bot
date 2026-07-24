# Step 12 Release Readiness

## Verified release baseline

| Gate | Result |
|---|---:|
| Backend/MySQL tests | 99 passed |
| Frontend tests | 4 passed |
| Ruff / format / strict Mypy | Passed |
| Alembic drift | None |
| Prometheus config | Valid; 3 rules |
| Local proxy P95 | 44.301 ms / 2,000 ms gate |
| Missing correlation IDs | 0 / 100 |
| Restore rehearsal | 20 tables; 22 knowledge docs; 75.275 s |
| Mobile RTL visual audit | 375×812; scrollWidth 375; passed |
| Frontend image | 159 MB |
| Backend CPU-only image | 2.14 GB |
| Runtime services | MySQL, backend, frontend healthy |

The machine-readable source is `backend/reports/release/step-12-release-evidence.json`. Backup SQL files and manifests stay under the ignored `backups/` directory.
Visual evidence is stored in `docs/defense/dashboard-login-desktop.png` and `docs/defense/dashboard-login-mobile.png`.

## Release conditions

- Use `compose.production.yaml` with a private `.env.production` containing independent secrets.
- Point a real domain to the host and allow inbound TCP 80/443 only.
- Confirm Caddy has obtained a valid certificate before registering the Telegram webhook.
- Install and monitor the supplied systemd backup and retention timers.
- Copy verified backups to encrypted off-host storage.
- Run the full `scripts/verify-step-12.ps1` gate for every release candidate.

## Accepted limitations

- The current environment verifies local containers, not public DNS/TLS issuance.
- Telegram delivery remains inactive until a public HTTPS endpoint is selected.
- The performance report is a local reverse-proxy liveness baseline, not an LLM/provider load test.
- The fictional hotel operations are simulations and do not connect to a real PMS or payment system.
- Synthetic evaluation establishes a reproducible baseline but is not evidence of real-guest production quality.
