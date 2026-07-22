#!/bin/bash
# ── AMI Engine entrypoint ─────────────────────────────────────────────────────
# Runs inside the Docker container.
# Waits for Postgres, applies migrations, seeds data if the DB is empty,
# then starts gunicorn (or runserver in dev mode).
set -e

echo "==> Waiting for Postgres at ${POSTGRES_HOST:-db}:${POSTGRES_PORT:-5432}..."
until python - <<'PY'
import socket, sys, os, time
host = os.environ.get("POSTGRES_HOST", "db")
port = int(os.environ.get("POSTGRES_PORT", 5432))
for attempt in range(30):
    try:
        with socket.create_connection((host, port), timeout=2):
            sys.exit(0)
    except OSError:
        time.sleep(1)
sys.exit(1)
PY
do
  echo "    Postgres not ready — retrying..."
  sleep 2
done
echo "==> Postgres is up."

echo "==> Running migrations..."
python manage.py migrate --noinput

echo "==> Checking if data seeding is needed..."
COURSE_COUNT=$(python manage.py shell -c "
from ami_course_recommendations.models import Course
print(Course.objects.count())
" 2>/dev/null | tail -1)

if [ "$COURSE_COUNT" = "0" ] || [ -z "$COURSE_COUNT" ]; then
  echo "==> Database is empty — seeding synthetic data (1000 users)..."
  python datagen/generate.py
  echo "==> Seeding complete."
else
  echo "==> Data already present ($COURSE_COUNT courses) — skipping seed."
fi

echo "==> Collecting static files..."
python manage.py collectstatic --noinput --clear 2>/dev/null || true

# Use gunicorn in production, runserver in dev (set DEV=1 to use runserver)
if [ "${DEV:-0}" = "1" ]; then
  echo "==> Starting Django development server..."
  exec python manage.py runserver 0.0.0.0:8000
else
  echo "==> Starting gunicorn..."
  # Use `python -m gunicorn` instead of the gunicorn script directly.
  # This avoids shebang path issues when the venv was built on a different
  # OS/arch (e.g. macOS vs linux/arm64 inside the container).
  exec python -m gunicorn ami_engine.wsgi:application \
    --bind 0.0.0.0:8000 \
    --workers "${GUNICORN_WORKERS:-3}" \
    --timeout "${GUNICORN_TIMEOUT:-120}" \
    --access-logfile - \
    --error-logfile -
fi
