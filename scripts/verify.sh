#!/usr/bin/env bash
#
# verify.sh — Phase 9 reproducible verification entry point (W §13 M8, G §16).
#
# Runs every automatically-checkable gate in one place:
#
#   * backend unit/integration tests          (pytest, in-memory SQLite)
#   * vision worker tests                      (pytest)
#   * frontend tests                           (vitest, if node_modules is installed)
#   * backend ruff lint + format check
#   * vision ruff lint + format check
#   * frontend eslint + prettier + typecheck   (if node_modules is installed)
#   * Alembic offline migration render         (no database required)
#
# The live, database-backed drift check lives in ``scripts/verify_migrations.sh`` and the
# backup/restore verification in ``scripts/verify_backup_restore.sh``; run those separately
# because they start a disposable PostgreSQL cluster.
#
# Nothing here touches the application's real database or evidence directory. Every command
# is the same one documented in ``docs/TESTING.md``.
#
# Usage:  scripts/verify.sh
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
BACKEND="$ROOT/backend"
PY="$BACKEND/.venv/bin/python"
RUFF="$BACKEND/.venv/bin/ruff"
VISION_RUFF_CONFIG="$BACKEND/pyproject.toml"

[[ -x "$PY" ]] || { echo "FAIL: backend virtualenv missing at $PY (see docs/TESTING.md)" >&2; exit 127; }

section() { printf '\n=== %s ===\n' "$1"; }

section "backend tests"
(cd "$BACKEND" && "$PY" -m pytest)

section "vision tests"
(cd "$ROOT" && "$PY" -m pytest vision/tests)

section "backend ruff lint"
(cd "$BACKEND" && "$RUFF" check .)

section "backend ruff format"
(cd "$BACKEND" && "$RUFF" format --check .)

section "vision ruff lint"
(cd "$ROOT" && "$RUFF" check --config "$VISION_RUFF_CONFIG" vision)

section "vision ruff format"
(cd "$ROOT" && "$RUFF" format --check --config "$VISION_RUFF_CONFIG" vision)

if [[ -d "$ROOT/frontend/node_modules" ]]; then
    section "frontend tests"
    (cd "$ROOT/frontend" && npm test)
    section "frontend lint"
    (cd "$ROOT/frontend" && npm run lint)
    section "frontend format"
    (cd "$ROOT/frontend" && npm run format:check)
    section "frontend typecheck"
    (cd "$ROOT/frontend" && npm run typecheck)
else
    section "frontend checks SKIPPED"
    echo "frontend/node_modules not installed; run 'cd frontend && npm install' first."
fi

section "alembic offline render (upgrade head --sql)"
# Settings are required to import; values are non-secret placeholders for an offline render.
(cd "$BACKEND" && \
    POSTGRES_PASSWORD="offline-render-password-not-a-real-secret" \
    SECRET_KEY="offline-render-secret-key-$(printf 'e%.0s' {1..32})" \
    INTERNAL_API_TOKEN="offline-render-internal-token-$(printf 'f%.0s' {1..32})" \
    ENVIRONMENT=test \
    "$BACKEND/.venv/bin/alembic" upgrade head --sql >/dev/null)

printf '\nPASS: all verify.sh gates passed\n'
