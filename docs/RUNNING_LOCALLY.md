# Running ChronoVision Locally

**Audience:** a developer/operator starting ChronoVision on **this machine** without Docker.

This is the practical runbook: how to start, verify, use, and stop the stack by hand. It
assumes the one-time setup in `README.md` is done (virtualenv, `.env`, PostgreSQL role/database,
migrations, admin user). For deployment, retention, backup/restore, and benchmarks see
`docs/OPERATIONS.md`; for the development/verification suites see `docs/TESTING.md`.

> **Environment note (this host).** Docker/Compose is **not available** here, so the stack runs
> against the **system PostgreSQL** cluster (`127.0.0.1:5432`) instead of `docker compose up db`.
> Only the `chronovision` role/database were created; unrelated databases on that cluster are
> never touched. See D-61 in `docs/DECISIONS.md`.

---

## 0. Prerequisites (check once)

Run these from the repository root:

```bash
cd /home/ishit/CHRONO/chronovision

# 1. Configuration file with real secrets (never committed)
test -f .env && echo ".env present" || echo "MISSING .env — copy .env.example and fill it in"

# 2. Backend virtualenv + installed packages
backend/.venv/bin/python -V

# 3. Frontend dependencies
test -d frontend/node_modules && echo "node_modules present" || echo "run: cd frontend && npm install"

# 4. PostgreSQL reachable
pg_isready -h 127.0.0.1 -p 5432
```

`pg_isready` must print `accepting connections`. If it does not, start your PostgreSQL
service first (this host uses the system cluster; there is no Compose fallback).

---

## 1. Start the stack (three processes)

Run each command in **its own terminal** (or use the helper scripts in §6). Order matters: the
backend must be up before the vision worker registers with it.

### 1a. Database migrations (once, or after a code change)

```bash
cd backend
./.venv/bin/python -m alembic upgrade head      # applies to head, e.g. 0003_events_evidence
./.venv/bin/python -m alembic current           # confirm the revision
```

### 1b. Backend API — `http://127.0.0.1:8000`

```bash
cd backend
./.venv/bin/python -m uvicorn app.main:app --host 127.0.0.1 --port 8000
```

Wait for `Application startup complete.` Then leave it running.

### 1c. Vision worker (optional; needs the CV deps)

In a **second** terminal, from the **repository root**:

```bash
cd /home/ishit/CHRONO/chronovision
backend/.venv/bin/python -m vision.runtime
```

Expected: `vision worker starting; backend=http://127.0.0.1:8000` then
`startup reconcile reset 0 processing camera(s)`. The worker idles until monitoring is started.

### 1d. Dashboard (development server) — `http://127.0.0.1:5173`

In a **third** terminal:

```bash
cd frontend
npm run dev
```

Open `http://127.0.0.1:5173` and sign in with your administrator account.

---

## 2. Verify it is running

```bash
# Backend liveness (no auth)
curl -s http://127.0.0.1:8000/api/health          # {"status":"ok",...,"database":"ok"}
curl -s http://127.0.0.1:8000/api/health/cameras   # camera counts only

# A protected route must reject anonymous callers
curl -s -o /dev/null -w "%{http_code}\n" http://127.0.0.1:8000/api/cameras   # 401

# Dashboard dev server
curl -s -o /dev/null -w "%{http_code}\n" http://127.0.0.1:5173/              # 200
```

Sign in through the UI. From the CLI the flow is: `POST /api/auth/login` returns a session
cookie **and** sets a `chronovision_csrf` cookie; send that value back as the `X-CSRF-Token`
header on every write (camera create/update, monitoring start/stop, review):

```bash
JAR=/tmp/cv-cookies.txt; rm -f "$JAR"
curl -s -c "$JAR" -X POST http://127.0.0.1:8000/api/auth/login \
  -H "Content-Type: application/json" \
  -d '{"username":"admin","password":"<your-admin-password>"}'

# Read the CSRF cookie value, then reuse it on writes
CSRF=$(awk '/chronovision_csrf/ {print $7}' "$JAR")
curl -s -b "$JAR" http://127.0.0.1:8000/api/monitoring/status
```

---

## 3. Add a camera and start monitoring

Register a camera (dashboard camera form, or the API). `stream_reference` must be `rtsp://` or
`rtsps://` — no embedded `user:pass@`, and **not** a loopback host such as `127.0.0.1`:

```bash
curl -s -b "$JAR" -X POST http://127.0.0.1:8000/api/cameras \
  -H "Content-Type: application/json" -H "X-CSRF-Token: $CSRF" \
  -d '{"name":"Front Door","stream_reference":"rtsp://192.168.1.50:554/live","enabled":true,"configuration":{}}'
```

**Monitoring is explicit.** Opening the dashboard or the WebSocket never starts processing;
use the Start button or:

```bash
curl -s -b "$JAR" -X POST http://127.0.0.1:8000/api/monitoring/start \
  -H "X-CSRF-Token: $CSRF"
curl -s -b "$JAR" http://127.0.0.1:8000/api/monitoring/status
```

> **iPhone / phone camera.** Phones are not RTSP servers. Point the camera at an RTSP URL that
> is actually reachable on the LAN: either an on-phone RTSP-server app, or push from an app like
> Larix Broadcaster into a local relay and register the **host's LAN IP** (not `127.0.0.1`).
> **Live view is opt-in** and off unless a MediaMTX gateway is configured; confirm activity via
> camera/monitoring status, worker logs, and events. To enable live view, see
> `docs/LIVE_PLAYBACK.md`. See `docs/KNOWN_LIMITATIONS.md`.

### 3a. Optional: enable live view (MediaMTX)

Live playback is **off by default** and needs a gateway. On a host **without** Docker you can run
the pinned MediaMTX binary directly:

```bash
# 1. Configure .env (see .env.example / docs/LIVE_PLAYBACK.md):
#    LIVE_PLAYBACK_ENABLED=true
#    MEDIAMTX_API_URL=http://127.0.0.1:9997
#    MEDIAMTX_WEBRTC_URL=http://<host-lan-ip>:8889
# 2. Restart the backend so it picks up the new settings.
# 3. Run the gateway with the shipped config:
mediamtx deploy/mediamtx.yml          # or: docker compose --profile playback up -d mediamtx
# 4. Open Cameras → Live in the dashboard.
```

If no `mediamtx` binary is on `PATH`, install the pinned **v1.21.3** static build (matches the
compose image) to a stable path so it survives reboots and `/tmp` cleanup:

```bash
mkdir -p ~/.local/bin
curl -fsSL -o /tmp/mediamtx.tgz \
  https://github.com/bluenviron/mediamtx/releases/download/v1.21.3/mediamtx_v1.21.3_linux_amd64.tar.gz
tar -xzf /tmp/mediamtx.tgz -C /tmp mediamtx
install -m 0755 /tmp/mediamtx ~/.local/bin/mediamtx
~/.local/bin/mediamtx --version       # expect: v1.21.3
```

`scripts/start_local.sh` starts the gateway automatically when `LIVE_PLAYBACK_ENABLED=true` and a
`mediamtx` binary is found (on `PATH` or at `~/.local/bin/mediamtx`); pass `--no-mediamtx` to skip
it. `scripts/stop_local.sh` stops it too.

The gateway is not required for monitoring/events/evidence; stopping it only disables live view.

---

## 4. Watch the logs

When you start the processes by hand, their output goes straight to the terminal. With the
helper scripts (§6) logs are written to the git-ignored `logs/` directory:

```bash
tail -f logs/backend.log    # API requests, errors
tail -f logs/vision.log     # worker lifecycle, per-camera processing
tail -f logs/frontend.log   # Vite dev server
```

---

## 5. Stop the stack

Ctrl-C in each terminal. If you used the helper scripts:

```bash
scripts/stop_local.sh
```

Manual fallback:

```bash
pkill -f "uvicorn app.main:app"
pkill -f "vision.runtime"
pkill -f "node.*vite"
pkill -x mediamtx
```

Your data is safe: PostgreSQL rows and the evidence tree (`EVIDENCE_DIR`) persist. The worker
resets any `processing` cameras to idle on its next startup.

---

## 6. Optional helper scripts

`scripts/start_local.sh` starts the backend, vision worker, and frontend with preflight checks,
waits for backend health, and writes PIDs + logs under `logs/`. It also starts the MediaMTX gateway
when live playback is enabled and a binary is available (§3a). `scripts/stop_local.sh` stops them
using those PIDs (with a pattern fallback).

```bash
scripts/start_local.sh      # start everything, print URLs and log paths
scripts/start_local.sh --no-vision   # skip the vision worker (e.g. no CV deps installed)
scripts/start_local.sh --no-mediamtx # skip the live-view gateway
scripts/stop_local.sh       # stop everything started by the script
```

The scripts never modify `.env`, the database, or the evidence tree; they only launch/stop
processes and write to `logs/`.

---

## 7. Troubleshooting

| Symptom | Cause | Fix |
|---|---|---|
| Backend exits with a secret/validation error on startup | Missing or placeholder value in `.env` | Fill real values (≥ 32 chars) for `POSTGRES_PASSWORD`, `SECRET_KEY`, `INTERNAL_API_TOKEN`; `DEBUG=false` in production |
| `could not connect to server` / `database:degraded` | PostgreSQL not running or wrong host/port | `pg_isready -h 127.0.0.1 -p 5432`; start the system PostgreSQL service |
| `relation ... does not exist` | Migrations not applied | `cd backend && ./.venv/bin/python -m alembic upgrade head` |
| `ModuleNotFoundError: vision` | Worker started from the wrong directory | Run `python -m vision.runtime` from the **repository root** |
| Frontend loads but API calls fail | Backend not up, or CORS/origin mismatch | Confirm `curl http://127.0.0.1:8000/api/health`; start backend first |
| `address already in use` | A previous instance is still running | `scripts/stop_local.sh`, or the `pkill` commands in §5 |
| `401` on every write from the CLI | Missing/incorrect `X-CSRF-Token` | Send the `chronovision_csrf` cookie value as `X-CSRF-Token` |
| Vision log: no cameras processed | Monitoring not started, or no enabled camera | Add/enable a camera and `POST /api/monitoring/start` |
| Camera rejected `422 Invalid stream reference` | Non-RTSP scheme, embedded credentials, or loopback host | Use `rtsp://<LAN-IP>:<port>/<path>` |

---

## 8. Related documents

- `README.md` — project overview, one-time setup, API/config tables.
- `docs/OPERATIONS.md` — configuration, retention, backup/restore, benchmarks, live gateway.
- `docs/TESTING.md` — running the backend/vision/frontend test suites and linters.
- `docs/LIVE_PLAYBACK.md` — opt-in MediaMTX + WebRTC live view (Phase 10).
- `docs/KNOWN_LIMITATIONS.md` — what is deliberately not implemented (real camera, real-browser WebRTC, GPU).
- `docs/DECISIONS.md` — D-62…D-65 (live playback), D-61 (local run procedures).
