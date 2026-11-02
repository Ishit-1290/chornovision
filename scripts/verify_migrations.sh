#!/usr/bin/env bash
#
# verify_migrations.sh — Phase 9 Alembic migration-drift check (W §13 M8).
#
# Runs the migration chain against a *disposable* PostgreSQL cluster and then runs
# ``alembic check``, which fails if the ORM models differ from the migrated schema (drift).
# This is the authoritative drift check; the offline ``alembic upgrade head --sql`` render in
# ``scripts/verify.sh`` only proves the migrations *render* and does not need a database.
#
# The application's real database and PostgreSQL service are never used or modified.
#
# Usage:  scripts/verify_migrations.sh
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
BACKEND="$ROOT/backend"
PY="$BACKEND/.venv/bin/python"
ALEMBIC="$BACKEND/.venv/bin/alembic"

for tool in initdb pg_ctl psql createdb; do
    command -v "$tool" >/dev/null 2>&1 || { echo "FAIL: '$tool' not found on PATH" >&2; exit 127; }
done
[[ -x "$PY" ]] || { echo "FAIL: backend virtualenv missing at $PY" >&2; exit 127; }

WORK="$(mktemp -d "${TMPDIR:-/tmp/opencode}/chronovision-migrations-XXXXXX")"
DATA="$WORK/pgdata"
SOCK="$WORK/sock"
PGRUN="$WORK/pg.log"
mkdir -p "$SOCK"

PORT="$("$PY" - <<'PYEOF'
import socket
s = socket.socket(); s.bind(("127.0.0.1", 0)); print(s.getsockname()[1]); s.close()
PYEOF
)"

cleanup() { pg_ctl -D "$DATA" -m immediate stop >/dev/null 2>&1 || true; rm -rf "$WORK"; }
trap cleanup EXIT

echo "==> disposable cluster on port $PORT"
initdb -D "$DATA" -U postgres --auth-local=trust --auth-host=trust >/dev/null
pg_ctl -D "$DATA" -o "-p $PORT -k $SOCK -c listen_addresses=127.0.0.1" -l "$PGRUN" -w start >/dev/null
psql -h 127.0.0.1 -p "$PORT" -U postgres -c "CREATE DATABASE chronovision;" >/dev/null

export POSTGRES_HOST=127.0.0.1
export POSTGRES_PORT="$PORT"
export POSTGRES_USER=postgres
export POSTGRES_DB=chronovision
export POSTGRES_PASSWORD="disposable-password-not-a-real-secret"
export SECRET_KEY="migration-verify-secret-key-$(printf 'c%.0s' {1..32})"
export INTERNAL_API_TOKEN="migration-verify-internal-token-$(printf 'd%.0s' {1..32})"
export ENVIRONMENT=test

echo "==> alembic upgrade head"
(cd "$BACKEND" && "$ALEMBIC" upgrade head)

echo "==> alembic check (model vs migrated schema drift)"
if (cd "$BACKEND" && "$ALEMBIC" check); then
    echo "PASS: migrations apply cleanly with no model/schema drift"
else
    echo "FAIL: Alembic detected schema drift" >&2
    exit 1
fi
