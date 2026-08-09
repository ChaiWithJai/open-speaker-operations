#!/usr/bin/env bash
set -euo pipefail

app_dir="${SPEAKEROPS_APP_DIR:-/opt/open-speaker-operations}"
public_url="${SPEAKEROPS_PUBLIC_URL:-https://loop.dharmicdata.org}"
new_image="${1:?usage: deploy-digitalocean.sh ghcr.io/chaiwithjai/open-speaker-operations:<sha>}"

if [[ ! "$new_image" =~ ^ghcr\.io/chaiwithjai/open-speaker-operations:[0-9a-f]{40}$ ]]; then
  echo "Refusing non-immutable or unexpected image: $new_image" >&2
  exit 2
fi

cd "$app_dir"
test -f .env
test -f docker-compose.yml
umask 077
mkdir -p backups

previous_env="$(mktemp "$app_dir/.env.previous.XXXXXX")"
cp .env "$previous_env"
previous_image="$(awk -F= '$1 == "APP_IMAGE" { print substr($0, index($0, "=") + 1) }' .env)"
test -n "$previous_image"
env_changed=false

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
  docker compose --project-name speakerops pull web worker mock-accelevents || true
  docker compose --project-name speakerops up -d --wait || true
  rm -f "$previous_env"
  trap - EXIT
  exit "$exit_code"
}
trap rollback EXIT

timestamp="$(date -u +%Y%m%dT%H%M%SZ)"
docker compose --project-name speakerops exec -T postgres sh -c \
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

docker compose --project-name speakerops pull web worker mock-accelevents
docker compose --project-name speakerops up -d --wait --remove-orphans
curl --fail --silent --show-error "$public_url/" >/dev/null
curl --fail --silent --show-error "$public_url/speakerops-demo/cfp" >/dev/null
printf '%s\n' "$new_image" > .last-successful-image

trap - EXIT
rm -f "$previous_env"
echo "Deployed $new_image"
