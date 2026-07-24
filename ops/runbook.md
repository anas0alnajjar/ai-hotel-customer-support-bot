# Operations Runbook

## API or database unavailable

1. Run `docker compose ps` and confirm `mysql`, `backend`, and `frontend` are healthy.
2. Read only the bounded tail: `docker compose logs --tail 200 backend mysql`.
3. Call `/api/v1/health/ready` and record its correlation ID and component checks.
4. If MySQL is unhealthy, stop writes and preserve the volume. Never delete or recreate the volume as a recovery shortcut.
5. Restore only into an isolated rehearsal container until the backup checksum and schema checks pass.

## Elevated HTTP errors

1. Query `hotel_http_requests_total` by `route` and `status_class`.
2. Correlate the affected route with structured backend logs using `correlation_id`.
3. Check Gemini, Telegram, FAISS, and MySQL readiness before retrying a write.
4. Do not report a hotel operation as successful unless its transaction and audit both committed.

## High latency

1. Inspect the P95 histogram and identify the affected route.
2. Separate internal latency from Gemini/Telegram external latency.
3. Check database pool saturation and model download/index rebuild activity.
4. Preserve the 10-second product target; reduce optional LLM work before increasing timeouts.

## Backup failure

1. Keep the last verified manifest and SQL dump immutable.
2. Check free disk space and MySQL health.
3. Rerun `scripts/backup.ps1`; do not overwrite an existing timestamped artifact.
4. Copy verified backups to encrypted off-host storage under operator control.

## Restore procedure

1. Verify the manifest checksum.
2. Run `scripts/restore-rehearsal.ps1 -ManifestPath <manifest>`.
3. Review the generated report under `backend/reports/release/`.
4. For a real incident, stop application writes, take a final incident snapshot, create a new MySQL volume, restore there, run Alembic verification, rebuild FAISS from approved knowledge revisions, and only then switch traffic.

## Retention cleanup

Run daily:

```powershell
.\scripts\cleanup-conversations.ps1
```

The job is idempotent, bounded by `RETENTION_CLEANUP_BATCH_SIZE`, and writes redacted audit evidence.

## Secret rotation

1. Generate new independent values for database, Telegram identity pepper/webhook, Gemini, and admin token secrets.
2. Rotating the admin token secret invalidates all active admin sessions.
3. Rotating the Telegram identity pepper changes pseudonymous identity derivation and requires an approved migration plan; never rotate it casually.
4. Restart services and verify readiness without printing secret values.
