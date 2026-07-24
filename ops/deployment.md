# Self-Hosted Deployment

## Recommended target

A single Linux VPS in a region reachable from Syria and the hotel, with Docker Engine, Compose v2, 4 vCPU, 8–16 GB RAM, and encrypted SSD storage. This avoids dependence on AWS, GCP, Vercel, Stripe, or PayPal. Commercial delivery can use a B2B annual license plus deployment/support fees paid through available regional channels or USDT where legally permitted.

## DNS and firewall

1. Point `PUBLIC_DOMAIN` to the VPS.
2. Allow inbound TCP 80 and 443 only.
3. Restrict SSH by key and operator IP where possible.
4. MySQL, FastAPI, and Prometheus have no public production ports.

## First release

1. Copy `.env.production.example` to `.env.production`.
2. Replace every placeholder with independent random secrets and restrict the file to the deployment operator.
3. Validate:

   `docker compose -f compose.production.yaml --env-file .env.production config --quiet`

4. Build:

   `docker compose -f compose.production.yaml --env-file .env.production build`

5. Apply migrations with a verified backup available.
6. Start:

   `docker compose -f compose.production.yaml --env-file .env.production up -d`

7. Confirm all health checks and HTTPS before registering the Telegram webhook.

Caddy obtains and renews certificates automatically when the domain resolves and ports 80/443 reach the host. The public proxy blocks `/api/v1/metrics`; Prometheus scrapes it only over the internal Compose network.

## Scheduled jobs

- The selected production baseline is Linux systemd. Create a dedicated `hotel-bot` service account, grant only the Docker access required on that host, and ensure `/var/backups/hotel-support-bot` is owned by that account with mode `0700`.
- Copy the four units under `ops/systemd/` to `/etc/systemd/system/`. If the checkout is not `/opt/hotel-support-bot`, update `WorkingDirectory` and absolute script paths first.
- Run `sudo systemctl daemon-reload` and `sudo systemctl enable --now hotel-bot-backup.timer hotel-bot-retention.timer`.
- Verify with `systemctl list-timers 'hotel-bot-*'`, then manually start each service once and inspect its journal.
- `scripts/backup.sh` is the Linux logical-backup path; `scripts/backup.ps1` remains the verified Windows operator path.
- Weekly restore rehearsal: run against a temporary MySQL container and retain the JSON report.
- Monthly dependency/image review and credential-access review.

Do not register the Telegram webhook until HTTPS, restore rehearsal, health checks, and the release gate all pass.
