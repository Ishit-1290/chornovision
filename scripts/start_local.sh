#!/usr/bin/env bash
#
# Start ChronoVision locally (backend + vision worker + frontend) without Docker.
# See docs/RUNNING_LOCALLY.md. Logs and PID files are written to the git-ignored logs/.
#
# Usage:
#   scripts/start_local.sh [--no-vision] [--no-frontend] [--no-mediamtx]
#
# It never modifies .env, the database, or the evidence tree; it only launches processes.
#
# MediaMTX (live view) is started only when LIVE_PLAYBACK_ENABLED is true in .env AND a
# 'mediamtx' binary is on PATH or at ~/.local/bin/mediamtx. See docs/LIVE_PLAYBACK.md.

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_ROOT"

VENV_PY="$REPO_ROOT/backend/.venv/bin/python"
LOG_DIR="$REPO_ROOT/logs"
BACKEND_URL="http://127.0.0.1:8000"
FRONTEND_URL="http://127.0.0.1:5173"

START_VISION=1
START_FRONTEND=1
START_MEDIAMTX=1
for arg in "$@"; do
  case "$arg" in
    --no-vision) START_VISION=0 ;;
    --no-frontend) START_FRONTEND=0 ;;
    --no-mediamtx) START_MEDIAMTX=0 ;;
    -h|--help) sed -n '2,9p' "${BASH_SOURCE[0]}"; exit 0 ;;
    *) echo "unknown option: $arg" >&2; exit 2 ;;
  esac
done

log()  { printf '%s %s\n' "[start_local]" "$*"; }
fail() { printf '%s %s\n' "[start_local] ERROR:" "$*" >&2; exit 1; }

# --- Preflight -----------------------------------------------------------------
[ -f "$REPO_ROOT/.env" ] || fail ".env is missing. Copy .env.example to .env and fill in real secrets."
[ -x "$VENV_PY" ] || fail "backend/.venv missing. Create it and install dependencies (see README.md)."
if [ "$START_FRONTEND" -eq 1 ] && [ ! -d "$REPO_ROOT/frontend/node_modules" ]; then
  fail "frontend/node_modules missing. Run: cd frontend && npm install"
fi
if ! pg_isready -h 127.0.0.1 -p 5432 >/dev/null 2>&1; then
  log "WARNING: PostgreSQL is not accepting connections on 127.0.0.1:5432 (backend may report 'degraded')."
fi

mkdir -p "$LOG_DIR"

# --- Launch helper -------------------------------------------------------------
# launch <name> <workdir> <command...>
launch() {
  local name="$1"; shift
  local wd="$1"; shift
  local pidfile="$LOG_DIR/$name.pid"

  if [ -f "$pidfile" ] && kill -0 "$(cat "$pidfile")" 2>/dev/null; then
    log "$name already running (pid $(cat "$pidfile")); leaving it up."
    return 0
  fi

  (
    cd "$wd"
    if command -v setsid >/dev/null 2>&1; then
      setsid nohup "$@" >"$LOG_DIR/$name.log" 2>&1 &
    else
      nohup "$@" >"$LOG_DIR/$name.log" 2>&1 &
    fi
    echo $! >"$pidfile"
  )
  log "$name -> pid $(cat "$pidfile"), log logs/$name.log"
}

# --- Start ---------------------------------------------------------------------
launch backend "$REPO_ROOT/backend" \
  "$VENV_PY" -m uvicorn app.main:app --host 127.0.0.1 --port 8000

# Wait for the backend to answer before starting the worker.
if command -v curl >/dev/null 2>&1; then
  for _ in $(seq 1 30); do
    if curl -fsS "$BACKEND_URL/api/health" >/dev/null 2>&1; then break; fi
    sleep 0.5
  done
  if curl -fsS "$BACKEND_URL/api/health" >/dev/null 2>&1; then
    log "backend healthy: $BACKEND_URL/api/health"
  else
    log "WARNING: backend did not answer /api/health within 15s; check logs/backend.log"
  fi
fi

if [ "$START_VISION" -eq 1 ]; then
  # The worker module must be run from the repository root so `vision` is importable.
  launch vision "$REPO_ROOT" "$VENV_PY" -m vision.runtime
fi

if [ "$START_FRONTEND" -eq 1 ]; then
  launch frontend "$REPO_ROOT/frontend" npm run dev
fi

# --- Live playback gateway (optional, opt-in) ----------------------------------
# Started only when live playback is enabled in .env AND a mediamtx binary is available
# (on PATH or at ~/.local/bin/mediamtx). It is not required for monitoring, events, or
# evidence; skipping it just leaves live view unavailable. See docs/LIVE_PLAYBACK.md.
if [ "$START_MEDIAMTX" -eq 1 ]; then
  MEDIAMTX_BIN="$(command -v mediamtx 2>/dev/null || true)"
  if [ -z "$MEDIAMTX_BIN" ] && [ -x "$HOME/.local/bin/mediamtx" ]; then
    MEDIAMTX_BIN="$HOME/.local/bin/mediamtx"
  fi
  LIVE_ENABLED="$(grep -E '^LIVE_PLAYBACK_ENABLED=' "$REPO_ROOT/.env" | tail -1 | cut -d= -f2 | tr -d '[:space:]')"
  case "$LIVE_ENABLED" in
    true|True|1|yes|YES)
      if [ -n "$MEDIAMTX_BIN" ]; then
        launch mediamtx "$REPO_ROOT" "$MEDIAMTX_BIN" "$REPO_ROOT/deploy/mediamtx.yml"
        if command -v curl >/dev/null 2>&1; then
          for _ in $(seq 1 20); do
            if curl -fsS "http://127.0.0.1:9997/v3/config/global/get" >/dev/null 2>&1; then break; fi
            sleep 0.5
          done
          if curl -fsS "http://127.0.0.1:9997/v3/config/global/get" >/dev/null 2>&1; then
            log "mediamtx Control API healthy: http://127.0.0.1:9997"
          else
            log "WARNING: mediamtx did not answer the Control API within 10s; check logs/mediamtx.log"
          fi
        fi
      else
        log "WARNING: LIVE_PLAYBACK_ENABLED is on but no 'mediamtx' binary was found; live view will be unavailable."
        log "         Install it (e.g. to ~/.local/bin/mediamtx) — see docs/LIVE_PLAYBACK.md §2.2."
      fi
      ;;
    *)
      log "mediamtx: skipped (LIVE_PLAYBACK_ENABLED is not true)"
      ;;
  esac
fi

# --- Summary -------------------------------------------------------------------
echo
log "running:"
log "  backend  : $BACKEND_URL"
[ "$START_VISION" -eq 1 ]   && log "  vision   : worker (polling the backend)"
[ "$START_FRONTEND" -eq 1 ] && log "  dashboard: $FRONTEND_URL"
[ "$START_MEDIAMTX" -eq 1 ] && [ -f "$LOG_DIR/mediamtx.pid" ] && log "  mediamtx : gateway (API 127.0.0.1:9997, WebRTC :8889)"
log "logs: logs/{backend,vision,frontend,mediamtx}.log    stop: scripts/stop_local.sh"
log "Reminder: monitoring starts only on explicit activation (dashboard Start, or POST /api/monitoring/start)."
