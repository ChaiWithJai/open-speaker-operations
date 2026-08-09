#!/usr/bin/env bash
set -euo pipefail

script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
default_app_dir="$(cd "$script_dir/../.." && pwd)"
if [ -f "$script_dir/docker-compose.yml" ]; then
  default_app_dir="$script_dir"
fi
app_dir="${SPEAKEROPS_APP_DIR:-$default_app_dir}"
public_url="${SPEAKEROPS_PUBLIC_URL:-https://loop.dharmicdata.org}"
current_image=""
previous_image=""
confirmed=false

usage() {
  echo "usage: drill-image-rollback.sh --current IMAGE_SHA --previous IMAGE_SHA [--app-dir PATH] [--public-url URL] [--yes]"
}

while [ "$#" -gt 0 ]; do
  case "$1" in
    --current) current_image="${2:?missing --current value}"; shift 2 ;;
    --previous) previous_image="${2:?missing --previous value}"; shift 2 ;;
    --app-dir) app_dir="${2:?missing --app-dir value}"; shift 2 ;;
    --public-url) public_url="${2:?missing --public-url value}"; shift 2 ;;
    --yes) confirmed=true; shift ;;
    -h|--help) usage; exit 0 ;;
    *) usage >&2; exit 2 ;;
  esac
done

image_pattern='^ghcr\.io/chaiwithjai/open-speaker-operations:[0-9a-f]{40}$'
[[ "$current_image" =~ $image_pattern ]] || { echo "Current image must use a full GHCR commit-SHA tag." >&2; exit 2; }
[[ "$previous_image" =~ $image_pattern ]] || { echo "Previous image must use a full GHCR commit-SHA tag." >&2; exit 2; }
test "$current_image" != "$previous_image" || { echo "Current and previous images must differ." >&2; exit 2; }
app_dir="$(cd "$app_dir" && pwd)"
test -f "$app_dir/.env"
test -x "$app_dir/deploy-digitalocean.sh" || test -x "$app_dir/deploy/scripts/deploy-digitalocean.sh"
deploy_script="$app_dir/deploy-digitalocean.sh"
test -x "$deploy_script" || deploy_script="$app_dir/deploy/scripts/deploy-digitalocean.sh"
smoke_script="$app_dir/smoke_journey.py"
test -f "$smoke_script" || smoke_script="$app_dir/deploy/smoke_journey.py"
test -f "$smoke_script"
configured_image="$(sed -n 's/^APP_IMAGE=//p' "$app_dir/.env" | tail -n 1)"
test "$configured_image" = "$current_image" || {
  echo "Refusing drill: .env is not pinned to the declared current image." >&2
  exit 2
}

if [ "$confirmed" != true ]; then
  echo "DRY RUN: would deploy and smoke $previous_image, then deploy and smoke $current_image."
  echo "The current image is restored on every exit path. Re-run with --yes under owner supervision."
  exit 0
fi
test -n "${SPEAKEROPS_SMOKE_PASSWORD:-}" || { echo "Set SPEAKEROPS_SMOKE_PASSWORD." >&2; exit 2; }

if [ "${SPEAKEROPS_SKIP_PULL:-false}" = "true" ]; then
  for image in "$current_image" "$previous_image"; do
    image_id="$(docker image inspect --format '{{.Id}}' "$image" 2>/dev/null)" || {
      echo "Preloaded local rehearsal image is unavailable: $image" >&2
      exit 2
    }
    [[ "$image_id" =~ ^sha256:[0-9a-f]{64}$ ]] || {
      echo "Preloaded local rehearsal image has an invalid image ID: $image" >&2
      exit 2
    }
    echo "Local rehearsal image: $image -> $image_id"
  done
fi

returned_to_current=false
restore_current() {
  exit_code=$?
  if [ "$returned_to_current" != true ]; then
    echo "Returning to declared current image after drill exit." >&2
    SPEAKEROPS_APP_DIR="$app_dir" SPEAKEROPS_PUBLIC_URL="$public_url" \
      SPEAKEROPS_COMPOSE_PROJECT="${SPEAKEROPS_COMPOSE_PROJECT:-speakerops}" \
      SPEAKEROPS_SKIP_PULL="${SPEAKEROPS_SKIP_PULL:-false}" \
      "$deploy_script" "$current_image" || true
  fi
  trap - EXIT
  exit "$exit_code"
}
trap restore_current EXIT

SPEAKEROPS_APP_DIR="$app_dir" SPEAKEROPS_PUBLIC_URL="$public_url" \
  SPEAKEROPS_COMPOSE_PROJECT="${SPEAKEROPS_COMPOSE_PROJECT:-speakerops}" \
  SPEAKEROPS_SKIP_PULL="${SPEAKEROPS_SKIP_PULL:-false}" \
  "$deploy_script" "$previous_image"
SPEAKEROPS_SMOKE_PASSWORD="$SPEAKEROPS_SMOKE_PASSWORD" \
  python3 "$smoke_script" --base-url "$public_url"

SPEAKEROPS_APP_DIR="$app_dir" SPEAKEROPS_PUBLIC_URL="$public_url" \
  SPEAKEROPS_COMPOSE_PROJECT="${SPEAKEROPS_COMPOSE_PROJECT:-speakerops}" \
  SPEAKEROPS_SKIP_PULL="${SPEAKEROPS_SKIP_PULL:-false}" \
  "$deploy_script" "$current_image"
SPEAKEROPS_SMOKE_PASSWORD="$SPEAKEROPS_SMOKE_PASSWORD" \
  python3 "$smoke_script" --base-url "$public_url"
returned_to_current=true
trap - EXIT
echo "Rollback drill passed: previous image verified and current image restored."
