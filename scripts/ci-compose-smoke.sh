#!/usr/bin/env bash
set -euo pipefail

project="${COMPOSE_PROJECT_NAME:-speakerops-ci-local}"
case "$project" in
  speakerops-ci-*) ;;
  *) echo "Refusing to clean unexpected Compose project: $project" >&2; exit 2 ;;
esac

export APP_IMAGE="${APP_IMAGE:-open-speaker-operations:ci}"
export WEB_BIND="${WEB_BIND:-127.0.0.1:18001}"
export MOCK_BIND="${MOCK_BIND:-127.0.0.1:19001}"
export CELERY_CONCURRENCY="${CELERY_CONCURRENCY:-1}"

cleanup() {
  docker compose --project-name "$project" down --volumes --remove-orphans
}
trap cleanup EXIT

docker build --tag "$APP_IMAGE" .
docker compose --project-name "$project" config --quiet
docker compose --project-name "$project" up --detach --no-build --wait --wait-timeout 120

port="${WEB_BIND##*:}"
curl --fail --silent --show-error "http://127.0.0.1:${port}/speakerops-demo/cfp" >/dev/null
docker compose --project-name "$project" ps
