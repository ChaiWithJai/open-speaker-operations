#!/usr/bin/env bash
set -euo pipefail

script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
default_app_dir="$(cd "$script_dir/../.." && pwd)"
if [ -f "$script_dir/docker-compose.yml" ]; then
  default_app_dir="$script_dir"
fi
app_dir="${SPEAKEROPS_APP_DIR:-$default_app_dir}"
project="${SPEAKEROPS_COMPOSE_PROJECT:-speakerops-hci}"
backup_path=""
restore_bind="${SPEAKEROPS_RESTORE_BIND:-127.0.0.1:48001}"
confirmed=false

usage() {
  echo "usage: verify-restore.sh --backup PATH [--app-dir PATH] [--project speakerops-*] [--bind 127.0.0.1:PORT] [--yes]"
}

while [ "$#" -gt 0 ]; do
  case "$1" in
    --backup) backup_path="${2:?missing --backup value}"; shift 2 ;;
    --app-dir) app_dir="${2:?missing --app-dir value}"; shift 2 ;;
    --project) project="${2:?missing --project value}"; shift 2 ;;
    --bind) restore_bind="${2:?missing --bind value}"; shift 2 ;;
    --yes) confirmed=true; shift ;;
    -h|--help) usage; exit 0 ;;
    *) usage >&2; exit 2 ;;
  esac
done

test -n "$backup_path" || { usage >&2; exit 2; }
case "$project" in speakerops|speakerops-*) ;; *) echo "Refusing unexpected Compose project: $project" >&2; exit 2 ;; esac
[[ "$restore_bind" =~ ^127\.0\.0\.1:[0-9]{2,5}$ ]] || {
  echo "Restore web must bind explicitly to 127.0.0.1 and a numeric port." >&2
  exit 2
}
app_dir="$(cd "$app_dir" && pwd)"
backup_path="$(cd -P "$(dirname "$backup_path")" && pwd)/$(basename "$backup_path")"
case "$(basename "$backup_path")" in speakerops-????????T??????Z) ;; *) echo "Backup must be a timestamped speakerops snapshot." >&2; exit 2 ;; esac
case "$backup_path" in "$app_dir/backups/"*) ;; *) echo "Backup must remain under $app_dir/backups." >&2; exit 2 ;; esac
test -f "$backup_path/database.dump"
test -f "$backup_path/media.tar.gz"
test -f "$backup_path/SHA256SUMS"
test -f "$app_dir/docker-compose.yml"
smoke_script="$app_dir/smoke_journey.py"
test -f "$smoke_script" || smoke_script="$app_dir/deploy/smoke_journey.py"
test -f "$smoke_script"

if [ "$confirmed" != true ]; then
  echo "DRY RUN: would restore $backup_path into an isolated database and temporary media volume."
  echo "No running web, worker, database, Redis, or mock service would be restarted. Re-run with --yes."
  exit 0
fi
test -n "${SPEAKEROPS_SMOKE_PASSWORD:-}" || { echo "Set SPEAKEROPS_SMOKE_PASSWORD." >&2; exit 2; }

if command -v sha256sum >/dev/null 2>&1; then
  (cd "$backup_path" && sha256sum --check SHA256SUMS)
else
  (cd "$backup_path" && shasum -a 256 --check SHA256SUMS)
fi

timestamp="$(date -u +%Y%m%d%H%M%S)"
restore_db="speakerops_restore_verify_$timestamp"
container_name="${project}-restore-verify-$timestamp"
media_volume="${project}-restore-media-$timestamp"
compose=(docker compose --project-name "$project" --file "$app_dir/docker-compose.yml")
database_created=false
volume_created=false

cleanup() {
  docker rm --force "$container_name" >/dev/null 2>&1 || true
  if [ "$volume_created" = true ]; then docker volume rm "$media_volume" >/dev/null 2>&1 || true; fi
  if [ "$database_created" = true ]; then
    "${compose[@]}" exec -T postgres sh -c \
      'dropdb --if-exists -U "$POSTGRES_USER" "$1"' sh "$restore_db" >/dev/null 2>&1 || true
  fi
}
trap cleanup EXIT

for service in postgres redis mock-accelevents; do
  test -n "$("${compose[@]}" ps --quiet --status running "$service")" || {
    echo "Required $project service is not running: $service" >&2
    exit 1
  }
done
"${compose[@]}" exec -T postgres sh -c \
  'createdb -U "$POSTGRES_USER" "$1"' sh "$restore_db"
database_created=true
"${compose[@]}" exec -T postgres sh -c \
  'pg_restore -U "$POSTGRES_USER" -d "$1" --exit-on-error' sh "$restore_db" \
  < "$backup_path/database.dump"

docker volume create --label speakerops.recovery=true "$media_volume" >/dev/null
volume_created=true
"${compose[@]}" run --rm --no-deps --entrypoint sh \
  --volume "$media_volume:/restore-data" web -c 'tar -xzf - -C /restore-data' \
  < "$backup_path/media.tar.gz"

"${compose[@]}" run --detach --no-deps --name "$container_name" \
  --publish "$restore_bind:8000" \
  --volume "$media_volume:/data" \
  --env "PRETALX_DB_NAME=$restore_db" \
  --env "PRETALX_SITE_URL=http://$restore_bind" \
  --env RUN_MIGRATIONS=false \
  --env SEED_DEMO=false \
  web >/dev/null

ready=false
for _attempt in $(seq 1 90); do
  if curl --fail --silent --show-error "http://$restore_bind/" >/dev/null 2>&1; then
    ready=true
    break
  fi
  sleep 1
done
test "$ready" = true || { echo "Isolated restore web did not become ready." >&2; exit 1; }

SPEAKEROPS_SMOKE_PASSWORD="$SPEAKEROPS_SMOKE_PASSWORD" \
  python3 "$smoke_script" --base-url "http://$restore_bind"
echo "Restore verified in isolated database $restore_db; temporary resources will now be removed."
