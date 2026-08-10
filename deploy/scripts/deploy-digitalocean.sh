#!/usr/bin/env bash
set -euo pipefail

app_dir="${SPEAKEROPS_APP_DIR:-/opt/open-speaker-operations}"
public_url="${SPEAKEROPS_PUBLIC_URL:-https://loop.dharmicdata.org}"
compose_project="${SPEAKEROPS_COMPOSE_PROJECT:-speakerops}"
skip_pull="${SPEAKEROPS_SKIP_PULL:-false}"
expected_app_version="${SPEAKEROPS_EXPECTED_APP_VERSION:-}"
new_image="${1:?usage: deploy-digitalocean.sh ghcr.io/chaiwithjai/open-speaker-operations@sha256:<digest>}"
case "$compose_project" in
  speakerops|speakerops-*) ;;
  *) echo "Refusing unexpected Compose project: $compose_project" >&2; exit 2 ;;
esac
if [ "$skip_pull" = "true" ]; then
  [[ "$new_image" =~ ^ghcr\.io/chaiwithjai/open-speaker-operations:([0-9a-f]{40})$ ]] || {
    echo "Loopback rehearsal requires the preloaded commit-SHA tag: $new_image" >&2
    exit 2
  }
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
else
  [[ "$new_image" =~ ^ghcr\.io/chaiwithjai/open-speaker-operations@sha256:[0-9a-f]{64}$ ]] || {
    echo "Refusing mutable or unexpected production image reference: $new_image" >&2
    exit 2
  }
  [[ "$expected_app_version" =~ ^[0-9a-f]{40}$ ]] || {
    echo "SPEAKEROPS_EXPECTED_APP_VERSION must be the full release commit SHA." >&2
    exit 2
  }
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
  docker pull "$target_image" >/dev/null
  repo_digest="$(
    docker image inspect --format '{{range .RepoDigests}}{{println .}}{{end}}' "$target_image" \
      | awk '/^ghcr\.io\/chaiwithjai\/open-speaker-operations@sha256:[0-9a-f]{64}$/ { print; exit }'
  )"
  test -n "$repo_digest" || {
    echo "Pulled image did not expose the expected GHCR RepoDigest: $target_image" >&2
    return 2
  }
  if [[ "$target_image" == *@sha256:* && "$repo_digest" != "$target_image" ]]; then
    echo "Pulled image digest mismatch: expected $target_image, observed $repo_digest" >&2
    return 2
  fi
  echo "Registry image verified: $target_image -> $repo_digest"
}

pull_images "$new_image"
if [ "$skip_pull" != "true" ]; then
  image_version="$(
    docker image inspect --format '{{range .Config.Env}}{{println .}}{{end}}' "$new_image" \
      | sed -n 's/^APP_VERSION=//p' | tail -n 1
  )"
  test "$image_version" = "$expected_app_version" || {
    echo "Candidate image APP_VERSION mismatch before deployment: expected $expected_app_version, observed $image_version" >&2
    exit 2
  }
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

"${compose[@]}" up -d --wait --remove-orphans

for service in web worker beat mock-accelevents; do
  container_id="$("${compose[@]}" ps -q "$service")"
  test -n "$container_id"
  configured_image="$(docker inspect --format '{{.Config.Image}}' "$container_id")"
  test "$configured_image" = "$new_image" || {
    echo "$service is running unexpected image reference: $configured_image" >&2
    exit 2
  }
  if [ "$skip_pull" != "true" ]; then
    running_version="$("${compose[@]}" exec -T "$service" sh -c 'printf %s "$APP_VERSION"')"
    test "$running_version" = "$expected_app_version" || {
      echo "$service APP_VERSION mismatch: expected $expected_app_version, observed $running_version" >&2
      exit 2
    }
  fi
done

# Conference memory is a contracted production dataset, not part of the lightweight
# event seed. Import and verify it once per immutable deployment so a green release
# proves the buyer-facing history is actually populated, not merely present in the image.
history_source=/app/pretalx_speakerops/data/conferences
history_contract=/app/pretalx_speakerops/data/conference_history_contract.json
"${compose[@]}" exec -T web python -m pretalx speakerops_history_coverage \
  "$history_source" --contract "$history_contract" --strict
"${compose[@]}" exec -T web python -m pretalx speakerops_import_history \
  "$history_source" --contract "$history_contract" \
  --prune --confirm-prune --verify \
  --report /tmp/speakerops-history-verification.json

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
