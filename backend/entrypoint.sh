#!/usr/bin/env bash
set -e

# Parse connection details from DATABASE_URL so pg_isready gets the right
# host, port, and user without hardcoding them in a second place.
DB_HOST=$(python -c "import os; from urllib.parse import urlparse; u=urlparse(os.environ['DATABASE_URL']); print(u.hostname)")
DB_PORT=$(python -c "import os; from urllib.parse import urlparse; u=urlparse(os.environ['DATABASE_URL']); print(u.port or 5432)")
DB_USER=$(python -c "import os; from urllib.parse import urlparse; u=urlparse(os.environ['DATABASE_URL']); print(u.username)")

echo "Waiting for Postgres at $DB_HOST:$DB_PORT..."
until pg_isready -h "$DB_HOST" -p "$DB_PORT" -U "$DB_USER"; do
  sleep 1
done
echo "Postgres ready."

echo "Running migrations..."
python manage.py migrate

echo "Starting server..."
exec "$@"
