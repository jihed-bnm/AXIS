#!/bin/sh
set -e

PGHOST="${POSTGRES_HOST:-axis-db}"
PGPORT="${POSTGRES_PORT:-5432}"
PGUSER_VAL="${POSTGRES_USER:-erp_user}"

echo "[entrypoint] Waiting for PostgreSQL at ${PGHOST}:${PGPORT}..."
until pg_isready -h "$PGHOST" -p "$PGPORT" -U "$PGUSER_VAL" >/dev/null 2>&1; do
    echo "[entrypoint] PostgreSQL not ready, retrying in 2s..."
    sleep 2
done
echo "[entrypoint] PostgreSQL is ready — starting uvicorn."

exec uvicorn backend.main:app --host 0.0.0.0 --port 8000
