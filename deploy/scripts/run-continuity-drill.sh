#!/usr/bin/env bash
set -euo pipefail

app_dir="${SPEAKEROPS_APP_DIR:-/opt/open-speaker-operations}"
public_url="${SPEAKEROPS_PUBLIC_URL:-https://loop.dharmicdata.org}"
current_image=""
previous_image=""
current_version=""
previous_version=""

usage() {
  echo "usage: run-continuity-drill.sh --current IMAGE --current-version SHA --previous IMAGE --previous-version SHA [--app-dir PATH] [--public-url URL]"
}

while [ "$#" -gt 0 ]; do
  case "$1" in
    --current) current_image="${2:?missing --current value}"; shift 2 ;;
    --current-version) current_version="${2:?missing --current-version value}"; shift 2 ;;
    --previous) previous_image="${2:?missing --previous value}"; shift 2 ;;
    --previous-version) previous_version="${2:?missing --previous-version value}"; shift 2 ;;
    --app-dir) app_dir="${2:?missing --app-dir value}"; shift 2 ;;
    --public-url) public_url="${2:?missing --public-url value}"; shift 2 ;;
    -h|--help) usage; exit 0 ;;
    *) usage >&2; exit 2 ;;
  esac
done

image_pattern='^ghcr\.io/chaiwithjai/open-speaker-operations@sha256:[0-9a-f]{64}$'
[[ "$current_image" =~ $image_pattern ]] || { echo "Current image must use a full GHCR digest." >&2; exit 2; }
[[ "$previous_image" =~ $image_pattern ]] || { echo "Previous image must use a full GHCR digest." >&2; exit 2; }
[[ "$current_version" =~ ^[0-9a-f]{40}$ ]] || { echo "Current version must be a full commit SHA." >&2; exit 2; }
[[ "$previous_version" =~ ^[0-9a-f]{40}$ ]] || { echo "Previous version must be a full commit SHA." >&2; exit 2; }
test "$current_image" != "$previous_image"
app_dir="$(cd "$app_dir" && pwd)"
cd "$app_dir"

for executable in backup-nightly.sh verify-restore.sh drill-image-rollback.sh; do
  test -x "$app_dir/$executable" || { echo "Missing executable: $app_dir/$executable" >&2; exit 2; }
done

configured_image="$(sed -n 's/^APP_IMAGE=//p' .env | tail -n 1)"
test "$configured_image" = "$current_image" || {
  echo "Configured production image does not match declared current image." >&2
  exit 2
}

smoke_password="$(
  docker compose --project-name speakerops --file docker-compose.yml \
    exec -T web sh -c 'printf %s "$SPEAKEROPS_DEMO_PASSWORD"'
)"
test -n "$smoke_password" || { echo "Deployed container has no protected-smoke credential." >&2; exit 2; }

echo "CONTINUITY_STAGE backup:start"
./backup-nightly.sh --app-dir "$app_dir" --project speakerops --retention-days 14
backup_path="$(
  find "$app_dir/backups" -mindepth 1 -maxdepth 1 -type d \
    -name 'speakerops-????????T??????Z' -print | sort | tail -n 1
)"
test -n "$backup_path"
test -s "$backup_path/database.dump"
test -s "$backup_path/media.tar.gz"
test -s "$backup_path/SHA256SUMS"
grep -Fx 'retention_days=14' "$backup_path/manifest.env" >/dev/null
echo "CONTINUITY_STAGE backup:passed snapshot=$(basename "$backup_path") retention_days=14"

echo "CONTINUITY_STAGE restore:start"
SPEAKEROPS_SMOKE_PASSWORD="$smoke_password" ./verify-restore.sh \
  --app-dir "$app_dir" --project speakerops \
  --bind 127.0.0.1:48001 --backup "$backup_path" --yes
echo "CONTINUITY_STAGE restore:passed"

echo "CONTINUITY_STAGE rollback:start previous=$previous_image current=$current_image"
SPEAKEROPS_SMOKE_PASSWORD="$smoke_password" ./drill-image-rollback.sh \
  --app-dir "$app_dir" --public-url "$public_url" \
  --current "$current_image" --current-version "$current_version" \
  --previous "$previous_image" --previous-version "$previous_version" --yes
test "$(sed -n 's/^APP_IMAGE=//p' .env | tail -n 1)" = "$current_image"
echo "CONTINUITY_STAGE rollback:passed current=$current_image"

echo "CONTINUITY_DRILL_PASSED"
