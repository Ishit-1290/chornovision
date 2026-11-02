#!/usr/bin/env bash
#
# Stop the processes started by scripts/start_local.sh (backend, vision worker,
# frontend, and the optional MediaMTX gateway if it was started).
# See docs/RUNNING_LOCALLY.md.
#
# Usage: scripts/stop_local.sh

set -uo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
LOG_DIR="$REPO_ROOT/logs"

log() { printf '%s %s\n' "[stop_local]" "$*"; }

# stop_group <name> <pidfile> <fallback-pattern>
stop_group() {
  local name="$1" pidfile="$2" pattern="$3"
  local pid=""

  if [ -f "$pidfile" ]; then
    pid="$(cat "$pidfile" 2>/dev/null || true)"
  fi

  if [ -n "$pid" ] && kill -0 "$pid" 2>/dev/null; then
    # Kill the whole process group first (catches e.g. Vite's node child), then the pid.
    kill -TERM -"$pid" 2>/dev/null || true
    kill -TERM "$pid" 2>/dev/null || true
    for _ in $(seq 1 20); do
      kill -0 "$pid" 2>/dev/null || break
      sleep 0.25
    done
    if kill -0 "$pid" 2>/dev/null; then
      kill -KILL -"$pid" 2>/dev/null || true
      kill -KILL "$pid" 2>/dev/null || true
    fi
    log "$name stopped (pid $pid)"
  else
    log "$name: no live process from pidfile"
  fi

  rm -f "$pidfile" 2>/dev/null || true
}

stop_group backend  "$LOG_DIR/backend.pid"  "uvicorn app.main:app"
stop_group vision   "$LOG_DIR/vision.pid"   "vision.runtime"
stop_group frontend "$LOG_DIR/frontend.pid" "node.*vite"
stop_group mediamtx "$LOG_DIR/mediamtx.pid" "mediamtx"

log "done. Data (PostgreSQL rows, evidence tree) is untouched."
