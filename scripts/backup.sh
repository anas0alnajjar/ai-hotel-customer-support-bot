#!/bin/sh
set -eu

umask 077

project_root=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
output_directory=${1:-"$project_root/backups"}
mkdir -p "$output_directory"

cd "$project_root"
container=$(docker compose ps -q mysql)
if [ -z "$container" ]; then
    echo "The Compose MySQL container is not available." >&2
    exit 1
fi

timestamp=$(date -u +%Y%m%dT%H%M%SZ)
base_name="hotel-bot-$timestamp"
container_dump="/tmp/$base_name.sql"
backup_path="$output_directory/$base_name.sql"
manifest_path="$output_directory/$base_name.manifest.json"

cleanup() {
    docker exec "$container" rm -f "$container_dump" >/dev/null 2>&1 || true
}
trap cleanup EXIT HUP INT TERM

docker exec "$container" sh -c \
    'MYSQL_PWD="$MYSQL_ROOT_PASSWORD" mysqldump --user=root --single-transaction --quick --routines --triggers --events --hex-blob --set-gtid-purged=OFF --no-tablespaces "$MYSQL_DATABASE" > "$1"' \
    sh "$container_dump"
docker exec "$container" test -s "$container_dump"
docker cp "$container:$container_dump" "$backup_path" >/dev/null

table_count=$(docker exec "$container" sh -c \
    'MYSQL_PWD="$MYSQL_ROOT_PASSWORD" mysql --user=root --batch --skip-column-names --execute="SELECT COUNT(*) FROM information_schema.tables WHERE table_schema=DATABASE()" "$MYSQL_DATABASE"')
size_bytes=$(stat -c %s "$backup_path")
sha256=$(sha256sum "$backup_path" | awk '{print $1}')
created_at=$(date -u +%Y-%m-%dT%H:%M:%SZ)

printf '{\n  "schema_version": 1,\n  "format": "mysql-logical-sql",\n  "created_at_utc": "%s",\n  "backup_file": "%s",\n  "sha256": "%s",\n  "size_bytes": %s,\n  "source_table_count": %s,\n  "faiss_recovery": "rebuild_from_approved_knowledge_revisions"\n}\n' \
    "$created_at" "$base_name.sql" "$sha256" "$size_bytes" "$table_count" > "$manifest_path"

printf '%s\n' "$manifest_path"
