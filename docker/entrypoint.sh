#!/usr/bin/env bash
set -euo pipefail

cd /app
export DJANGO_SETTINGS_MODULE="${DJANGO_SETTINGS_MODULE:-pretalx.settings}"

echo "Waiting for database..."
database_ready=false
for _attempt in $(seq 1 "${DATABASE_WAIT_SECONDS:-60}"); do
  if python -c "import django; django.setup(); from django.db import connection; connection.ensure_connection()" 2>/dev/null; then
    database_ready=true
    break
  fi
  sleep 1
done
if [ "$database_ready" != "true" ]; then
  echo "Database did not become ready within ${DATABASE_WAIT_SECONDS:-60}s." >&2
  exit 1
fi

if [ "${RUN_MIGRATIONS:-true}" = "true" ]; then
  python -m pretalx migrate --noinput
  python -m pretalx collectstatic --noinput
fi

if [ "${SEED_DEMO:-true}" = "true" ]; then
  echo "Seeding deterministic demo data..."
  python -m pretalx speakerops_seed
fi

if [ "$#" -gt 0 ]; then
  exec "$@"
fi

echo "Starting gunicorn..."
exec gunicorn pretalx.wsgi:application \
  --bind 0.0.0.0:8000 \
  --workers "${WEB_WORKERS:-2}" \
  --threads "${WEB_THREADS:-2}" \
  --timeout "${WEB_TIMEOUT:-60}" \
  --access-logfile - \
  --error-logfile -
