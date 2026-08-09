#!/usr/bin/env bash
set -euo pipefail

script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
default_app_dir="$(cd "$script_dir/../.." && pwd)"
if [ -f "$script_dir/docker-compose.yml" ]; then
  default_app_dir="$script_dir"
fi
app_dir="${SPEAKEROPS_APP_DIR:-$default_app_dir}"
project="${SPEAKEROPS_COMPOSE_PROJECT:-speakerops-hci}"
backup_dir=""
retention_days="${SPEAKEROPS_BACKUP_RETENTION_DAYS:-14}"
dry_run=false

usage() {
  echo "usage: backup-nightly.sh [--app-dir PATH] [--project speakerops-*] [--backup-dir PATH] [--retention-days DAYS] [--dry-run]"
}

while [ "$#" -gt 0 ]; do
  case "$1" in
    --app-dir) app_dir="${2:?missing --app-dir value}"; shift 2 ;;
    --project) project="${2:?missing --project value}"; shift 2 ;;
    --backup-dir) backup_dir="${2:?missing --backup-dir value}"; shift 2 ;;
    --retention-days) retention_days="${2:?missing --retention-days value}"; shift 2 ;;
    --dry-run) dry_run=true; shift ;;
    -h|--help) usage; exit 0 ;;
    *) usage >&2; exit 2 ;;
  esac
done

case "$project" in speakerops|speakerops-*) ;; *) echo "Refusing unexpected Compose project: $project" >&2; exit 2 ;; esac
case "$retention_days" in ''|*[!0-9]*) echo "Retention days must be a non-negative integer." >&2; exit 2 ;; esac
app_dir="$(cd "$app_dir" && pwd)"
backup_dir="${backup_dir:-$app_dir/backups}"
case "$backup_dir" in "$app_dir/backups"|"$app_dir/backups/"*) ;; *) echo "Backup directory must remain under $app_dir/backups" >&2; exit 2 ;; esac
compose_file="$app_dir/docker-compose.yml"
test -f "$compose_file"

timestamp="$(date -u +%Y%m%dT%H%M%SZ)"
final_dir="$backup_dir/speakerops-$timestamp"
staging_dir="$backup_dir/.speakerops-$timestamp.tmp"
compose=(docker compose --project-name "$project" --file "$compose_file")

if [ "$dry_run" = true ]; then
  echo "DRY RUN project=$project backup=$final_dir retention_days=$retention_days"
  echo "Would dump PostgreSQL, archive /data from web, write checksums, and prune expired speakerops-* snapshots."
  exit 0
fi

umask 077
mkdir -p "$backup_dir"
test ! -e "$final_dir"
mkdir "$staging_dir"
cleanup() { rm -rf -- "$staging_dir"; }
trap cleanup EXIT

"${compose[@]}" ps --status running postgres web >/dev/null
"${compose[@]}" exec -T postgres sh -c \
  'pg_dump -U "$POSTGRES_USER" -d "$POSTGRES_DB" -Fc' > "$staging_dir/database.dump"
"${compose[@]}" exec -T web tar -C /data -czf - . > "$staging_dir/media.tar.gz"

if command -v sha256sum >/dev/null 2>&1; then
  (cd "$staging_dir" && sha256sum database.dump media.tar.gz > SHA256SUMS)
else
  (cd "$staging_dir" && shasum -a 256 database.dump media.tar.gz > SHA256SUMS)
fi
{
  echo "created_at=$timestamp"
  echo "compose_project=$project"
  echo "database_format=postgres-custom"
  echo "media_format=tar-gzip"
  echo "retention_days=$retention_days"
} > "$staging_dir/manifest.env"
mv "$staging_dir" "$final_dir"
trap - EXIT

# Retention deletion is deliberately restricted to timestamped snapshot directories
# under the validated application backup root.
find "$backup_dir" -mindepth 1 -maxdepth 1 -type d -name 'speakerops-????????T??????Z' \
  -mtime "+$retention_days" -print -exec rm -rf -- {} +

echo "Backup complete: $final_dir"
