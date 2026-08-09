#!/usr/bin/env bash
set -euo pipefail

app_dir="${SPEAKEROPS_APP_DIR:-/opt/open-speaker-operations}"
public_url="${SPEAKEROPS_PUBLIC_URL:-https://loop.dharmicdata.org}"
compose_project="${SPEAKEROPS_COMPOSE_PROJECT:-speakerops}"
skip_pull="${SPEAKEROPS_SKIP_PULL:-false}"
new_image="${1:?usage: deploy-digitalocean.sh ghcr.io/chaiwithjai/open-speaker-operations:<sha>}"

if [[ ! "$new_image" =~ ^ghcr\.io/chaiwithjai/open-speaker-operations:[0-9a-f]{40}$ ]]; then
  echo "Refusing non-commit-SHA or unexpected image tag: $new_image" >&2
  exit 2
fi
case "$compose_project" in
  speakerops|speakerops-*) ;;
  *) echo "Refusing unexpected Compose project: $compose_project" >&2; exit 2 ;;
esac
if [ "$skip_pull" = "true" ]; then
  [[ "$public_url" =~ ^http://127\.0\.0\.1:[0-9]+$ ]] || {
    echo "SPEAKEROPS_SKIP_PULL is allowed only for a loopback drill." >&2
    exit 2
  }
  [[ "$compose_project" == speakerops-hci* ]] || {
    echo "SPEAKEROPS_SKIP_PULL is allowed only for a speakerops-hci project." >&2
    exit 2
  }
elif [ "$skip_pull" != "false" ]; then
  echo "SPEAKEROPS_SKIP_PULL must be true or false." >&2
  exit 2
fi

cd "$app_dir"
test -f .env
test -f docker-compose.yml
umask 077
mkdir -p backups

previous_image="$(awk -F= '$1 == "APP_IMAGE" { print substr($0, index($0, "=") + 1) }' .env)"
test -n "$previous_image"
env_changed=false
compose=(docker compose --project-name "$compose_project")

pull_images() {
  local target_image="$1"
  local image_id repo_digest
  if [ "$skip_pull" = "true" ]; then
    image_id="$(docker image inspect --format '{{.Id}}' "$target_image" 2>/dev/null)" || {
      echo "Preloaded local rehearsal image is unavailable: $target_image" >&2
      return 2
    }
    [[ "$image_id" =~ ^sha256:[0-9a-f]{64}$ ]] || {
      echo "Preloaded local rehearsal image has an invalid image ID: $target_image" >&2
      return 2
    }
    echo "Loopback rehearsal only: $target_image resolves to local image $image_id; no registry immutability is claimed."
    return
  fi
  "${compose[@]}" pull web worker mock-accelevents
  repo_digest="$(
    docker image inspect --format '{{range .RepoDigests}}{{println .}}{{end}}' "$target_image" \
      | awk '/^ghcr\.io\/chaiwithjai\/open-speaker-operations@sha256:[0-9a-f]{64}$/ { print; exit }'
  )"
  test -n "$repo_digest" || {
    echo "Pulled image did not expose the expected GHCR RepoDigest: $target_image" >&2
    return 2
  }
  echo "Registry image verified: $target_image -> $repo_digest"
}

if [ "$skip_pull" = "true" ]; then
  pull_images "$new_image"
fi

previous_env="$(mktemp "$app_dir/.env.previous.XXXXXX")"
cp .env "$previous_env"

rollback() {
  exit_code=$?
  if [ "$exit_code" -eq 0 ]; then
    rm -f "$previous_env"
    return
  fi
  if [ "$env_changed" != "true" ]; then
    rm -f "$previous_env"
    trap - EXIT
    exit "$exit_code"
  fi
  echo "Deployment failed; restoring $previous_image" >&2
  cp "$previous_env" .env
  pull_images "$previous_image" || true
  "${compose[@]}" up -d --wait || true
  rm -f "$previous_env"
  trap - EXIT
  exit "$exit_code"
}
trap rollback EXIT

timestamp="$(date -u +%Y%m%dT%H%M%SZ)"
"${compose[@]}" exec -T postgres sh -c \
  'pg_dump -U "$POSTGRES_USER" -d "$POSTGRES_DB" -Fc' \
  > "backups/speakerops-${timestamp}.dump"

awk -v image="$new_image" '
  BEGIN { replaced = 0 }
  $0 ~ /^APP_IMAGE=/ { print "APP_IMAGE=" image; replaced = 1; next }
  { print }
  END { if (!replaced) print "APP_IMAGE=" image }
' .env > .env.next
chmod 0600 .env.next
mv .env.next .env
env_changed=true

pull_images "$new_image"
"${compose[@]}" up -d --wait --remove-orphans
curl --fail --silent --show-error "$public_url/" >/dev/null
curl --fail --silent --show-error "$public_url/speakerops-demo/cfp" >/dev/null
smoke_script="$app_dir/smoke_journey.py"
test -f "$smoke_script" || smoke_script="$app_dir/deploy/smoke_journey.py"
test -f "$smoke_script"
smoke_password="${SPEAKEROPS_SMOKE_PASSWORD:-}"
if [ -z "$smoke_password" ]; then
  smoke_password="$(sed -n 's/^SPEAKEROPS_DEMO_PASSWORD=//p' .env | tail -n 1)"
fi
if [ -z "$smoke_password" ]; then
  smoke_password="$(
    "${compose[@]}" exec -T web sh -c 'printf %s "$SPEAKEROPS_DEMO_PASSWORD"'
  )"
fi
test -n "$smoke_password" || { echo "SPEAKEROPS_DEMO_PASSWORD is required for protected smoke." >&2; exit 1; }
SPEAKEROPS_SMOKE_PASSWORD="$smoke_password" \
  python3 "$smoke_script" --base-url "$public_url"
printf '%s\n' "$new_image" > .last-successful-image

trap - EXIT
rm -f "$previous_env"
echo "Deployed $new_image"
