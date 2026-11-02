# ChronoVision — Operations Guide

**Phase:** 10 (W §13 M8: setup/deployment instructions; FR-42/FR-43, FR-51/FR-54)

This guide covers deploying and operating ChronoVision: configuration, startup order,
evidence retention, backup/restore, benchmarking, and the health checks to watch. Setup from
scratch (creating the virtualenv, `.env`, and the admin user) is in `README.md`; this document
assumes those steps are done. For starting the stack **locally without Docker** (backend, vision
worker, and dashboard by hand, plus start/stop helper scripts), see `docs/RUNNING_LOCALLY.md`.

## Configuration

Settings are read (highest precedence first) from constructor args, environment variables,
`<repo>/.env`, then `backend/.env`; secrets are never printed. See `.env.example` for the full
list and `README.md` "Configuration reference" for the table. Key operational groups:

- **Secrets (required, ≥ 32 chars):** `POSTGRES_PASSWORD`, `SECRET_KEY`, `INTERNAL_API_TOKEN`.
- **Database:** `POSTGRES_HOST/PORT/DB/USER/PASSWORD`.
- **Sessions/auth:** `SESSION_TTL_SECONDS`, `SESSION_COOKIE_SECURE` (set `true` behind HTTPS),
  `SESSION_COOKIE_SAMESITE`, `LOGIN_RATE_LIMIT_*`.
- **Cameras/SSRF:** `CAMERA_ALLOWED_STREAM_SCHEMES`, `CAMERA_ALLOW_PRIVATE_NETWORKS`,
  `VISION_STREAM_HOST_MODE` (leave `pin`).
- **Vision worker:** `VISION_MAX_CONCURRENT_CAMERAS`, `VISION_PROCESS_TARGET_FPS`,
  `VISION_DETECTOR_WEIGHTS`, `VISION_DETECTOR_DEVICE`, `VISION_QUEUE_MAXSIZE`, reconnect and
  latency-sample settings.
- **Evidence:** `EVIDENCE_DIR`, `EVIDENCE_RETENTION_DAYS`, `EVIDENCE_STORAGE_LIMIT_GB`,
  `EVIDENCE_RETENTION_ON_REGISTER` (**keep `false`**).
- **Live playback (opt-in, default off):** `LIVE_PLAYBACK_ENABLED`, `MEDIAMTX_API_URL`,
  `MEDIAMTX_WEBRTC_URL`, optional `MEDIAMTX_API_USERNAME`/`MEDIAMTX_API_PASSWORD`,
  `MEDIAMTX_PATH_PREFIX`, `LIVE_GATEWAY_CLOSE_AFTER_SECONDS`, `LIVE_GATEWAY_PIN_HOSTS`
  (keep `true`). Setting the URLs while `LIVE_PLAYBACK_ENABLED=false` is a startup error.

The validated configuration **fails fast** on missing/short/placeholder secrets and on
`debug=true` in production.

## Startup order

1. **PostgreSQL** — `docker compose up -d db` (or an external managed instance, or an existing
   system cluster — see `docs/RUNNING_LOCALLY.md`).
2. **Migrations** — `cd backend && alembic upgrade head`. Verify no drift with
   `scripts/verify_migrations.sh` during upgrades.
3. **Administrator** — `python -m app.cli create-admin --username admin` (once).
4. **Backend API** — `uvicorn app.main:app --host 127.0.0.1 --port 8000`.
5. **Vision worker** (optional, needs CV deps) — from the repository root
   (`python -m vision.runtime`), with `INTERNAL_API_TOKEN` and `VISION_BACKEND_BASE_URL` set.
6. **Dashboard** (development) — `cd frontend && npm run dev`.

Continuous processing requires **explicit activation**: opening the dashboard or the WebSocket
never starts monitoring; use `POST /api/monitoring/start` (or the Start button).

## Live playback gateway (optional)

Live view is delivered by a separate MediaMTX service and is **off by default**. Enabling it is
opt-in and requires both the flag and the URLs (see `docs/LIVE_PLAYBACK.md`):

```bash
# .env
LIVE_PLAYBACK_ENABLED=true
MEDIAMTX_API_URL=http://127.0.0.1:9997
MEDIAMTX_WEBRTC_URL=http://<host-or-lan-ip>:8889

docker compose --profile playback up -d mediamtx   # pinned bluenviron/mediamtx:1.21.3
```

Operational notes:

- The gateway is **not required** for monitoring, events, or evidence. Stopping it degrades only
  the live view; the UI falls back to stored evidence.
- It uses **host networking** (Linux) so WebRTC can advertise a LAN-reachable ICE candidate; the
  Control API binds to `127.0.0.1:9997` and must never be exposed to the LAN.
- Ports: `8889/tcp` (WHEP signalling + TCP media, browser-facing), `8189/udp` (ICE/media,
  browser-facing), `9997/tcp` (Control API, loopback), `8554/tcp` (RTSP diagnostics, loopback).
- Health: the backend surfaces gateway reachability through `GET /api/cameras/{id}/live`
  (`state: unavailable` + a non-sensitive `detail` when the gateway is unreachable/unauthorized).
- Camera paths are created/refreshed by the backend on camera change and on `POST
  /api/cameras/{id}/live/start`; the config mount is read-only, so paths do not survive a gateway
  restart until the next `start`.
- If the backend-facing API is put on a non-loopback interface, set
  `MEDIAMTX_API_USERNAME`/`MEDIAMTX_API_PASSWORD` and a matching `authInternalUsers` entry in
  `deploy/mediamtx.yml`.

## Health and monitoring endpoints

| Endpoint | Auth | Use |
|---|---|---|
| `GET /api/health` | none | `ok`/`degraded`; database reachability; never secrets |
| `GET /api/health/cameras` | none | camera count, `by_status`, `{id,status}` only |
| `GET /api/monitoring/status` | session | global monitoring state + per-camera lifecycle state |
| `GET /api/settings` | session | read-only retention policy + evidence storage usage |

A processing camera whose worker has not reported within
`WORKER_HEARTBEAT_TIMEOUT_SECONDS` is projected `disconnected` in the API without touching the
stored state.

## Evidence retention

Evidence bytes live under `EVIDENCE_DIR` (`camera-<id>/YYYY/MM/DD/...`); the database stores only
relative paths, and files are served solely through the authenticated `GET /api/evidence/{id}`
endpoint (never a static directory).

Retention is **explicit, not a capture side effect** (`EVIDENCE_RETENTION_ON_REGISTER=false`).
Run it manually or from an operator-scheduled job:

```bash
cd backend
python -m app.cli prune-evidence --dry-run   # report what would be deleted
python -m app.cli prune-evidence             # delete expired items, oldest-first
```

It enforces `EVIDENCE_RETENTION_DAYS` and `EVIDENCE_STORAGE_LIMIT_GB` oldest-first and **never**
removes protected (pinned) evidence; if the cap is still exceeded because every remaining
candidate is protected, it reports `blocked_by_protection` instead of deleting pinned bytes.
Eviction unlinks the file but keeps the row (`retention_status='deleted'`) for traceability.

## Backup and restore

Two things must be backed up **together**: the PostgreSQL database and the `EVIDENCE_DIR`
tree. Because evidence rows reference files by relative path, restoring one without the other
leaves dangling references.

```bash
# Backup
pg_dump -Fc "$DATABASE_URL" -f backups/chronovision-$(date +%F).dump
tar czf backups/evidence-$(date +%F).tar.gz -C "$(dirname "$EVIDENCE_DIR")" evidence

# Restore into a fresh database, then restore the evidence tree to the SAME EVIDENCE_DIR
createdb chronovision_restore
pg_restore -d "$RESTORE_DATABASE_URL" backups/chronovision-YYYY-MM-DD.dump
tar xzf backups/evidence-YYYY-MM-DD.tar.gz -C "$(dirname "$EVIDENCE_DIR")"
cd backend && alembic upgrade head    # if the dump predates the current schema
```

To verify the procedure on a disposable cluster (never touching real data):

```bash
scripts/verify_backup_restore.sh
```

It creates an isolated `initdb` cluster, migrates it, seeds a camera/event/evidence row,
`pg_dump`s it, `pg_restore`s into a fresh database, and checks that row counts match,
foreign keys are intact, and the evidence file is accessible and identical after the evidence
tree is copied alongside.

## Benchmarks

The runtime benchmark drives the real worker/manager stack with a simulated detector and real
OpenCV decode:

```bash
POSTGRES_PASSWORD=... SECRET_KEY=... INTERNAL_API_TOKEN=... ENVIRONMENT=test \
  python -m vision.benchmarks --cameras 1,2,4 --duration 8 \
  --detector-cost-ms 20 --output /tmp/benchmark.json
```

It reports per-camera processed FPS, ingest FPS, latency p50/p95/p99, queue depth, dropped
frames, process RSS/CPU, **GPU availability** (explicitly `available:false` with a reason when
there is no CUDA device), plus micro-benchmarks for event-handoff delivery latency and
duplication rate, snapshot-JPEG encode latency, and **recovery time** after a dropped stream.
The report records `detector_mode: "synthetic"` and the environment.

**Interpretation:** the numbers describe the **pipeline scaffolding at a configured detector
cost**, not detection accuracy, and are machine-dependent. Do not present them as real-time
guarantees. See the measured Phase 9 figures in `docs/IMPLEMENTATION_PROGRESS.md`.

## Security posture (operational reminders)

- Bind services to localhost unless remote access is explicitly required; terminate TLS in
  front of the API and set `SESSION_COOKIE_SECURE=true`.
- The internal worker channel (`/api/internal/*`, `X-Internal-Token`) is excluded from OpenAPI
  and must stay on a trusted network segment.
- Never log or commit secrets, footage, evidence, or database files (all git-ignored).
- The runtime has **no** dependency on OpenCode, DeepSeek, or any coding agent.
