#!/usr/bin/env bash
# Entrypoint: decouple seed from runserver so the site always comes up.
# Seed failures (e.g. re-running against existing data) never block the server.
set -e

cd /app

# 1. Wait for postgres
echo "Waiting for database..."
for i in $(seq 1 30); do
  if python -c "import django; django.setup(); from django.db import connection; connection.ensure_connection()" 2>/dev/null; then
    break
  fi
  sleep 1
done

# 2. Migrations (always)
python -m pretalx migrate --noinput

# 3. Seed — idempotent, never blocks server
echo "Seeding..."
python -m pretalx speakerops_seed || echo "Seed completed with warnings (non-fatal)."

# 4. Runserver (always reaches here)
echo "Starting server..."
exec python -m pretalx runserver 0.0.0.0:8000 --noreload
