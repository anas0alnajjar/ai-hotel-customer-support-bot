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

## Hostinger Docker Manager behind Nginx Proxy Manager

Use `compose.hostinger.yaml` only when the VPS already runs Nginx Proxy
Manager. The standalone `compose.production.yaml` remains the Caddy/ACME
deployment path and is intentionally unchanged.

The Hostinger variant:

- does not read `.env.production`;
- runs the frontend Caddy container in HTTP-only mode;
- publishes only the frontend on `${HOSTINGER_FRONTEND_HOST_PORT:-8088}`;
- leaves MySQL, FastAPI, and Prometheus on the private Compose network;
- applies Alembic migrations and idempotently seeds the fictional hotel before
  starting FastAPI;
- preserves the MySQL, FAISS, embedding-model, and Prometheus volumes; and
- leaves Gemini, Telegram, and admin authentication disabled when their secret
  values are empty.

### 1. Create the Docker Manager project

In hPanel, open the VPS, select **Docker Manager**, and create a project from
the public GitHub repository:

- Repository: `https://github.com/anas0alnajjar/ai-hotel-customer-support-bot`
- Branch: `main`
- Compose file: `compose.hostinger.yaml`

If Docker Manager requests a direct Compose URL instead, use:

`https://raw.githubusercontent.com/anas0alnajjar/ai-hotel-customer-support-bot/refs/heads/main/compose.hostinger.yaml`

Do not select `compose.production.yaml` for this VPS.

### 2. Set Docker Manager environment variables

Set these values in the project environment before the first deployment:

| Variable | Required value |
| --- | --- |
| `HOSTINGER_DB_PASSWORD` | A new independent random password; required before deployment |
| `HOSTINGER_DB_ROOT_PASSWORD` | A different new random password; required before deployment |
| `HOSTINGER_TRUSTED_HOSTS` | The public hostname followed by the Docker service name, for example `hotel.example.com,backend` |
| `HOSTINGER_ADMIN_TOKEN_SECRET` | A random value of at least 32 characters; required before admin login is enabled |
| `HOSTINGER_FRONTEND_HOST_PORT` | `8088`, unless that host port is already occupied |

Generate each secret independently on a trusted machine. For example,
`openssl rand -hex 32` produces a suitable 64-character value. Never place the
generated values in Git, a Compose file, an issue, or a build log.

The following non-secret defaults are safe and normally do not need changes:

| Variable | Default |
| --- | --- |
| `DB_NAME` | `hotel_bot` |
| `DB_USER` | `hotel_bot` |
| `GEMINI_MODEL` | `gemini-2.5-flash` |
| `CONVERSATION_RETENTION_DAYS` | `90` |
| `CONVERSATION_CONTEXT_TURNS` | `5` |

Gemini and Telegram may remain empty during the first deployment. To enable
Gemini later, set `HOSTINGER_GEMINI_API_KEY`. To enable Telegram later, set all
three variables together:

- `HOSTINGER_TELEGRAM_BOT_TOKEN`
- `HOSTINGER_TELEGRAM_WEBHOOK_SECRET` (16–256 letters, numbers, underscores, or hyphens)
- `HOSTINGER_TELEGRAM_IDENTITY_PEPPER` (at least 32 random characters)

Leaving only part of the Telegram secret set is invalid. Updating these values
does not register or modify the Telegram webhook.

An empty `HOSTINGER_DB_PASSWORD` or `HOSTINGER_DB_ROOT_PASSWORD` deliberately
prevents MySQL from initializing. This is fail-closed behavior, not a usable
default. The `HOSTINGER_` namespace also prevents Docker Compose from
accidentally importing same-named secrets from the developer `.env` file.

### 3. Validate and deploy

From a clean repository checkout, validation must succeed without a local
environment file:

`docker compose -f compose.hostinger.yaml config`

Deploy the project in Docker Manager after the required environment values are
set. The expected steady state is:

- `mysql`, `backend`, and `frontend`: running and healthy;
- `migrate` and `bootstrap`: exited successfully with code `0`;
- `prometheus`: not started unless the `monitoring` profile is explicitly
  enabled.

Docker Manager must not show host ports for MySQL, FastAPI, or Prometheus. The
only published mapping is the selected frontend host port to container port
`8080`.

From the VPS, verify the frontend and the proxied backend without changing DNS:

`curl --fail http://127.0.0.1:8088/healthz`

`curl --fail http://127.0.0.1:8088/api/v1/health/live`

If a different `HOSTINGER_FRONTEND_HOST_PORT` was selected, use it in both
commands.

### 4. Point the existing Nginx Proxy Manager proxy host

In the existing Nginx Proxy Manager instance, configure the application proxy
host with:

- Scheme: `http`
- Forward hostname/IP: the VPS host address reachable from the Nginx Proxy
  Manager container
- Forward port: `8088` (or the selected `HOSTINGER_FRONTEND_HOST_PORT`)
- WebSocket support: enabled
- Public SSL and certificate renewal: handled by Nginx Proxy Manager

Do not use `127.0.0.1` as the forward hostname from inside the Nginx Proxy
Manager container; that address refers to the proxy container itself. Do not
publish this project's ports `80` or `443`, and do not enable
`Caddyfile.production` in the Hostinger project.

After proxying, verify:

`curl --fail https://<public-domain>/healthz`

`curl --fail https://<public-domain>/api/v1/health/live`

This procedure does not change DNS, firewall rules, the running Nginx Proxy
Manager service, or the Telegram webhook.
