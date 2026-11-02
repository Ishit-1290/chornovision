# ChronoVision

Real-time, event-driven video intelligence for home monitoring (academic prototype).

ChronoVision ingests live camera streams, detects and tracks people and objects,
evaluates temporal event rules, records structured events, and captures evidence.
Event messages are generated deterministically from templates — **there is no runtime
LLM or generative AI dependency**.

> **Status: Phase 10 — opt-in live camera playback (MediaMTX + WebRTC).**
> FastAPI app, PostgreSQL/SQLAlchemy/Alembic, secure single-admin auth, camera
> configuration with SSRF-validated stream addresses, a per-camera lifecycle state machine,
> a monitoring start/pause/stop/status control plane, and an independent vision worker with
> bounded frame ingestion, pretrained YOLO detection, per-camera ByteTrack tracking, metrics,
> and connection-time SSRF enforcement exist. Phases 5–6 add all eight canonical event types
> as per-camera temporal rules with a validated lifecycle, deterministic message templates,
> persisted events with transition history, a bounded authenticated worker→backend handoff,
> snapshot/short-clip evidence capture off the frame loop, an authorized evidence endpoint
> with path-traversal protection, and a configurable evidence retention policy. **Phase 7**
> adds a React/TypeScript/Vite/MUI dashboard (login + protected routes, overview, cameras,
> event timeline and details, read-only settings), authenticated real-time WebSocket
> notifications, and the human-review workflow (audited `review_status` + evidence
> pin/unpin). **Phase 8** adds multi-camera isolation (independent per-camera worker threads in
> one process; a failing/blocked camera does not affect others), configuration-change
> reconciliation, optional bounded per-camera latency percentiles, and a reproducible synthetic
> benchmark harness (`python -m vision.benchmarks`). **Phase 9** adds reproducible one-command
> verification (`scripts/verify.sh`), an offline labelled-evaluation package with per-activity
> precision/recall/F1, false-positive/negative counts, timing and occupancy error
> (`backend/app/evaluation/`; a clearly-**synthetic** sample dataset only), extended runtime
> benchmarking (GPU availability, duplication rate, recovery time), security and
> retention/backup-restore verification, and honest documentation
> (`docs/{TESTING,EVALUATION,OPERATIONS,KNOWN_LIMITATIONS}.md`). **Phase 10** adds **opt-in**
> live browser playback through a MediaMTX + WebRTC (WHEP) gateway (D-62–D-65): stable
> source-on-demand paths per camera, encrypted write-only camera credentials, SSRF-pinned
> gateway source URLs, and a dashboard `LivePlayer`. It is **off by default**; with no gateway
> configured the UI states that and falls back to stored evidence. See `docs/LIVE_PLAYBACK.md`.
> Door state, package classes, and pose inputs have interfaces but no detector producer yet.
> **No real-footage detection accuracy, real RTSP camera, real-browser WebRTC session, or GPU
> was available** — see `docs/KNOWN_LIMITATIONS.md`.
> See `docs/IMPLEMENTATION_PROGRESS.md` for current status and
> `docs/IMPLEMENTATION_PLAN.md` for the phased plan.

## Requirements

- Python 3.11+ (developed and verified on 3.14)
- Node.js 20+ and npm (for the Phase 7 dashboard; verified on Node 26)
- Docker + Docker Compose (for PostgreSQL; needed from Phase 2)
- Git
- Optional (Phase 4 vision worker): OpenCV, NumPy, PyTorch (CPU), Ultralytics, and
  `supervision` — installed via the `vision` extra. The backend itself does not require them.

## Repository layout

```text
chronovision/
├── AGENTS.md                  project/agent instructions
├── docker-compose.yml         local PostgreSQL + opt-in MediaMTX (`--profile playback`)
├── deploy/mediamtx.yml        MediaMTX gateway config (Phase 10)
├── .env.example               configuration template (placeholders only)
├── .gitignore
├── docs/                      requirements, architecture, plan, decisions
│   ├── TESTING.md             reproducible commands + prerequisites (Phase 9)
│   ├── EVALUATION.md          labels, matching rules, metrics (Phase 9)
│   ├── OPERATIONS.md          deploy, retention, backup/restore (Phase 9)
│   ├── LIVE_PLAYBACK.md       opt-in MediaMTX + WebRTC live view (Phase 10)
│   └── KNOWN_LIMITATIONS.md   consolidated honest limits (Phase 10)
├── scripts/                   verify.sh, verify_migrations.sh, verify_backup_restore.sh (Phase 9)
├── evaluation/                labelled-evaluation datasets (sample/ is synthetic) (Phase 9)
├── backend/
│   ├── pyproject.toml
│   ├── alembic.ini            Alembic config (DB URL from settings, no secrets)
│   ├── app/                   FastAPI app, auth, models, schemas, services
│   │   ├── config.py          validated application settings
│   │   ├── db.py              engine/session lifecycle
│   │   ├── main.py            ASGI entry point (app.main:app)
│   │   ├── api/routes/        health, auth, cameras, monitoring, events, evidence, settings, realtime, internal
│   │   ├── events/            canonical event contract, lifecycle, zones/thresholds
│   │   ├── event_messages/    deterministic templates + sanitising renderer
│   │   ├── evaluation/        offline matching + metrics + CLI (`python -m app.evaluation`)
│   │   ├── services/          camera/monitoring/lifecycle/stream-validation, event persistence, evidence + retention, worker_registry, realtime broadcaster, live gateway/service + credential cipher
│   │   └── cli.py             `create-admin` and `prune-evidence` commands
│   ├── migrations/            Alembic env + auth, cameras (+ stream credentials), events/evidence migrations
│   └── tests/                 config, models, security, auth, health, camera, events, evidence, review, settings, websocket, evaluation, security/retention verification
├── frontend/                  React/TS/Vite/MUI dashboard (Phase 7)
│   ├── package.json           scripts: dev, build, typecheck, lint, format, test
│   ├── vite.config.ts         `/api` + WebSocket dev proxy; Vitest/jsdom
│   └── src/                   api, auth, realtime, layout, pages, components, hooks, test
└── vision/                    independent vision worker (Phase 4; multi-camera in Phase 8)
    ├── runtime.py             `python -m vision.runtime`
    ├── benchmarks/            reproducible synthetic benchmark (`python -m vision.benchmarks`)
    ├── net.py                 connection-time SSRF (IP literal pinning)
    ├── camera_manager/        per-camera worker + manager lifecycle (event engine wired in)
    ├── event_engine/          temporal rules, shared rule base, per-camera orchestration
    ├── event_handoff.py       bounded authenticated event/evidence delivery (per-camera spool)
    ├── evidence/              rolling-buffer capture, snapshot/clip encode, safe paths
    ├── ingestion/             frame source, bounded queue, sampling/validation
    ├── detection/             pretrained YOLO detector (+ NullDetector)
    ├── tracking/              ByteTrack (+ IoU fallback), per camera
    └── tests/                 worker/SSRF/ingestion/metrics/event/evidence/multi-camera/benchmark tests
```

`data/` (runtime, never committed) is introduced when the worker runs.

## Setup

```bash
# 1. Configuration
cp .env.example .env
# Edit .env and replace every CHANGE_ME value. Generate secrets with:
python -c "import secrets; print(secrets.token_urlsafe(48))"

# 2. Backend virtual environment (do not install globally)
cd backend
python -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"

# 3. PostgreSQL (needed from Phase 2). From the repository root, with POSTGRES_PASSWORD
#    set in .env:
docker compose up -d db
docker compose ps

# 4. Apply migrations and create the administrator
cd backend
alembic upgrade head
chronovision-admin create-admin --username admin   # prompts for a password
# or: python -m app.cli create-admin --username admin
# or non-interactive: printf '%s' "$ADMIN_PASSWORD" | \
#       python -m app.cli create-admin --username admin --password-stdin

# 5. Run the API
uvicorn app.main:app --host 127.0.0.1 --port 8000
```

> **Starting the whole stack day-to-day?** `docs/RUNNING_LOCALLY.md` is the copy-paste runbook
> (start/verify/stop the backend, vision worker, and dashboard, with troubleshooting). On a host
> **without Docker**, `scripts/start_local.sh` and `scripts/stop_local.sh` start/stop all three
> processes and write git-ignored logs to `logs/`.

### Running the dashboard (Phase 7)

The dashboard is a separate same-origin SPA. In development Vite proxies `/api` (including
the WebSocket upgrade) to the backend on `127.0.0.1:8000`, so the HttpOnly session cookie
and CSRF header work exactly as in production without CORS.

```bash
# From the repository root, with the API already running:
cd frontend
npm install
npm run dev          # http://127.0.0.1:5173
```

Sign in with the administrator created above. Opening a page or the WebSocket never starts
monitoring; use the explicit Start button. Live video is **opt-in**: it is off unless a MediaMTX
gateway is configured (`LIVE_PLAYBACK_ENABLED=true` + `MEDIAMTX_*`; see `docs/LIVE_PLAYBACK.md`),
and while it is off the UI says so and stored snapshot/clip evidence can be reviewed.

### Running the vision worker (Phases 4–8, optional)

The worker is a **separate process** and needs the CV dependencies. The backend does not
require them. Install CPU PyTorch first, then the extra:

```bash
cd backend
source .venv/bin/activate
pip install torch torchvision --index-url https://download.pytorch.org/whl/cpu
pip install -e ".[vision]"

# From the REPOSITORY ROOT (so the top-level `vision` package is importable), with the
# backend API already running:
python -m vision.runtime
```

The worker calls `POST /api/internal/reconcile` at startup, polls
`GET /api/internal/cameras` for the monitoring plan, and reports state through
`POST /api/internal/cameras/{id}/state`, all authenticated with `INTERNAL_API_TOKEN`.
Camera weights (`VISION_DETECTOR_WEIGHTS`, default `yolo11n.pt`) are loaded lazily and
downloaded by Ultralytics on first use; they are git-ignored.

Each worker also runs a per-camera temporal event engine. Event transitions are handed to an
`EvidenceCoordinator` that (a) delivers them to the backend over the authenticated internal
channel with a bounded queue + disk spool, and (b) captures snapshot/short-clip evidence off
the frame loop. The backend persists events with their transition history, renders the
deterministic message once, and serves evidence through authorized endpoints. The current
detector is person-only, so entry/exit, occupancy/crowd, and motionless rules can run;
door/package/pose rules need inputs that are not produced yet. Configure zones and thresholds
through the camera `configuration` JSON (`zones` + optional `event_rules`); malformed
configuration is rejected with HTTP 422.

**Multiple cameras (Phase 8).** Set `VISION_MAX_CONCURRENT_CAMERAS` above `1` to run several
cameras at once. Each camera is an independent worker thread in the one worker process, with its
own capture thread, bounded queue, rolling buffer, tracker, event engine, evidence pipeline, and
event spool (`handoff-<camera_id>-*.json`); a failing or blocked camera does not affect the
others, and editing a camera's configuration restarts only that camera's worker. Isolation is
**thread-based** (a hard native fault in a decoder would still take down the shared process);
OS-process-per-camera is a documented future option.

**Benchmarking (Phase 8; extended in Phase 9, NFR-13).** A reproducible synthetic benchmark
drives the real worker stack with a simulated detector (configurable per-frame cost) and real
OpenCV decode:

```bash
# From the repository root, with the same env vars the worker needs
# (POSTGRES_PASSWORD, SECRET_KEY, INTERNAL_API_TOKEN, ENVIRONMENT):
python -m vision.benchmarks --cameras 1,2,4,8 --duration 8 --detector-cost-ms 20 \
    --output /tmp/bench.json
```

It reports per-camera FPS, latency percentiles, queue depth and drops, plus process RSS/CPU,
**GPU availability** (reported honestly as `available:false` with a reason when there is no
CUDA device), event-handoff delivery latency **and duplication rate**, and **recovery time**
after a simulated stream outage, alongside micro-benchmarks for handoff and snapshot-JPEG
encode. The numbers describe the **pipeline scaffolding** at a configured detector cost — not
detection accuracy — and were measured on a CPU-only host; see `docs/IMPLEMENTATION_PROGRESS.md`
(Phase 9) and `docs/KNOWN_LIMITATIONS.md`.

## Verifying the foundation

**One command** runs every automatically-checkable gate (backend + vision + frontend tests,
lint/format/typecheck, and an offline Alembic render); from the repository root:

```bash
scripts/verify.sh                    # backend, vision, frontend tests + lint/format + offline migration render
scripts/verify_migrations.sh         # live `alembic upgrade head` + `alembic check` on a disposable PostgreSQL cluster
scripts/verify_backup_restore.sh     # pg_dump/pg_restore round trip + evidence accessibility on a disposable cluster
```

The two database-backed scripts create their own **disposable** `initdb` cluster and remove it
on exit; they never touch the application database or evidence directory. Full prerequisites
and per-suite commands are in `docs/TESTING.md`. The equivalent manual commands:

```bash
# All backend tests (no live database required — they use in-memory SQLite)
cd backend
source .venv/bin/activate
pytest

# Lint and formatting (backend)
ruff check .
ruff format --check .

# Vision worker tests (run from the repository root; CV packages optional)
cd ..
python -m pytest vision/tests

# Lint/format the vision package with the backend config (from the repository root)
ruff check --config backend/pyproject.toml vision
ruff format --check --config backend/pyproject.toml vision

# Frontend: typecheck, lint, formatting, unit/component tests, production build
cd frontend
npm run typecheck
npm run lint
npm run format:check
npm test
npm run build

# Optional: exercise real YOLO weights (downloads yolo11n.pt; not run in CI)
VISION_TEST_WEIGHTS=1 python -m pytest vision/tests/test_integration_pipeline.py::test_real_yolo_loads_and_runs

# Event evaluation against labelled reference events (see docs/EVALUATION.md)
cd backend
./.venv/bin/python -m app.evaluation \
  --labels ../evaluation/sample/synthetic_labels.json \
  --detected ../evaluation/sample/synthetic_detected.json --window-hours 2

# Migration DDL without connecting to a database
alembic upgrade head --sql

# Load and validate the configuration (fails fast on missing/insecure values)
python -c "from app.config import get_settings; s = get_settings(); print(s.app_name, s.environment.value); print(s.database_url)"

# API smoke test (with the server running)
curl -i http://127.0.0.1:8000/api/health
curl -i -c cookies.txt -X POST http://127.0.0.1:8000/api/auth/login \
  -H 'Content-Type: application/json' \
  -d '{"username":"admin","password":"<your password>"}'
```

> **Do not** run the backend and vision suites in one `pytest` process; run them as separate
> commands (as above). Mixing them can leak configuration and cause spurious vision failures.
> See `docs/TESTING.md`.

### Event evaluation (Phase 9; AC-14, G §16.2)

`backend/app/evaluation/` compares human-annotated reference events with system detections under
fixed, documented matching rules (same `(camera_id, event_type)`; interval overlap or start
within a tolerance; one-to-one best-first) and reports per-activity precision/recall/F1,
false-positive/negative counts, signed/absolute timing error, occupancy error, micro/macro F1,
false alarms per hour, and missed-event rate. The repository ships a clearly-**synthetic**
sample in `evaluation/sample/`; **no real-footage accuracy is claimed**. The label format,
annotation conventions, and the procedure to score real footage are in `docs/EVALUATION.md`.

### API endpoints (Phase 2–10)

| Method | Path | Auth | Notes |
|---|---|---|---|
| GET | `/api/health` | none | `ok`/`degraded`; never exposes secrets |
| GET | `/api/health/cameras` | none | non-sensitive: camera count, `by_status`, `{id, status}` only |
| POST | `/api/auth/login` | none | sets HttpOnly session + CSRF cookies; 401/429 |
| POST | `/api/auth/logout` | session | requires `X-CSRF-Token`; revokes the session |
| GET | `/api/auth/me` | session | current user, or 401 |
| GET | `/api/cameras` | session | list cameras; stream reference is redacted |
| POST | `/api/cameras` | session + CSRF | create camera; optional `stream_username`/`stream_password` (write-only, encrypted); 409 duplicate name, 422 invalid/unsafe stream or invalid zones/rules |
| GET | `/api/cameras/{id}` | session | fetch one camera; 404 if unknown |
| PATCH | `/api/cameras/{id}` | session + CSRF | partial update; set/`clear_stream_credentials`; validates zones/rules; disabling a processing camera stops it (no DELETE) |
| GET | `/api/cameras/{id}/live` | session | read-only live status (`unavailable`/`connecting`/`live`/`disconnected`/`error`); never mutates the gateway |
| POST | `/api/cameras/{id}/live/start` | session + CSRF | idempotent path (re)registration; never starts monitoring |
| POST | `/api/monitoring/start` | session + CSRF | start/resume; enabled cameras move to `connecting` |
| POST | `/api/monitoring/pause` | session + CSRF | pause running monitoring; 409 if not running |
| POST | `/api/monitoring/stop` | session + CSRF | stop monitoring; processing cameras move to `stopped` |
| GET | `/api/monitoring/status` | session | global state + per-camera lifecycle state (stale workers projected `disconnected`) |
| GET | `/api/events` | session | event timeline; filters `camera_id`,`event_type`,`status`,`review_status`,`since`,`until`,`order`; paginated |
| GET | `/api/events/{id}` | session | one event with transition history + evidence metadata; 404 if unknown |
| PATCH | `/api/events/{id}` | session + CSRF | record `review_status` (+ optional note); never alters the stored message/timestamps/state; audit-logged |
| GET | `/api/evidence/{id}` | session | authorized evidence bytes; 404/409/410 as appropriate; never a static dir |
| PATCH | `/api/evidence/{id}` | session + CSRF | pin (`protected`) / release (`retained`) evidence; 409 if deleted; audit-logged |
| GET | `/api/settings` | session | read-only evidence/retention policy + evidence storage usage (never secrets) |
| WS | `/api/ws` | session cookie | authenticated real-time notifications (event/camera/monitoring/evidence); error + close 1008 if unauthenticated |
| GET | `/api/internal/cameras` | `X-Internal-Token` | worker only; runtime plan incl. stream references; excluded from OpenAPI |
| POST | `/api/internal/cameras/{id}/state` | `X-Internal-Token` | worker state report; `applied=false` if unchanged, 409 + `current_status` if illegal |
| POST | `/api/internal/reconcile` | `X-Internal-Token` | worker startup reset of stale processing cameras |
| POST | `/api/internal/events` | `X-Internal-Token` | worker event transition; idempotent by `event_id`; `applied=false` on stale/duplicate |
| POST | `/api/internal/events/{event_id}/evidence` | `X-Internal-Token` | register snapshot/clip metadata; backend verifies the file before `available` |

The configuration layer rejects missing secrets, secrets shorter than 32 characters,
placeholder values from `.env.example`, invalid environment/log-level values, and
`debug=true` in production.

## Configuration reference

Settings are read (highest precedence first) from constructor arguments, environment
variables, `<repo>/.env`, then `backend/.env`. Secrets are never printed. See
`.env.example` for the full list. Key variables:

| Variable | Default | Notes |
|---|---|---|
| `ENVIRONMENT` | `development` | `development` \| `test` \| `production` |
| `DEBUG` | `false` | must be `false` in production |
| `POSTGRES_*` | localhost/5432/chronovision/chronovision | `POSTGRES_PASSWORD` required |
| `SECRET_KEY` | — | required, ≥ 32 chars |
| `INTERNAL_API_TOKEN` | — | required, ≥ 32 chars (worker↔backend auth, D-12) |
| `SESSION_TTL_SECONDS` | `86400` | > 0 |
| `SESSION_COOKIE_NAME` | `chronovision_session` | HttpOnly session cookie |
| `SESSION_COOKIE_SECURE` | `false` | set `true` for HTTPS; forced when SameSite is `none` |
| `SESSION_COOKIE_SAMESITE` | `lax` | `lax` \| `strict` \| `none` |
| `CSRF_COOKIE_NAME` | `chronovision_csrf` | readable CSRF cookie |
| `LOGIN_RATE_LIMIT_ATTEMPTS` | `5` | attempts per window before 429 |
| `LOGIN_RATE_LIMIT_WINDOW_SECONDS` | `300` | rate-limit window |
| `PASSWORD_MIN_LENGTH` | `12` | minimum admin password length |
| `CAMERA_ALLOWED_STREAM_SCHEMES` | `rtsp,rtsps` | accepted camera stream URL schemes (D-22) |
| `CAMERA_ALLOW_PRIVATE_NETWORKS` | `true` | allow RFC1918/ULA camera addresses; metadata always blocked |
| `CAMERA_RESOLVE_STREAM_HOSTNAMES` | `false` | config-time DNS lookups off (rebinding); worker enforces at connect time |
| `WORKER_HEARTBEAT_TIMEOUT_SECONDS` | `15` | stale processing camera is projected `disconnected` after this (D-30) |
| `VISION_BACKEND_BASE_URL` | `http://127.0.0.1:8000` | backend base URL used by the worker |
| `VISION_MAX_CONCURRENT_CAMERAS` | `1` | independent camera worker threads per worker process; raise for multi-camera (D-50) |
| `VISION_STREAM_HOST_MODE` | `pin` | `pin` (IP-literal SSRF pinning, D-28) \| `hostname` (residual, opt-in) |
| `VISION_QUEUE_MAXSIZE` | `8` | bounded per-camera frame queue |
| `VISION_PROCESS_TARGET_FPS` | `5` | sampling rate for detection |
| `VISION_READ_TIMEOUT_SECONDS` | `10` | no frame within this → stalled stream |
| `VISION_RECONNECT_MAX_ATTEMPTS` | `0` | `0` = retry indefinitely with capped backoff; > 0 → terminal `failed` when exhausted |
| `VISION_METRICS_LATENCY_SAMPLE_CAPACITY` | `0` | bounded per-camera latency sample ring for p50/p95/p99; `0` disables (D-52) |
| `VISION_DETECTOR_WEIGHTS` | `yolo11n.pt` | pretrained YOLO weights (git-ignored) |
| `VISION_DETECTOR_DEVICE` | `cpu` | inference device |
| `VISION_DETECTOR_CONFIDENCE` | `0.25` | detection confidence threshold |
| `VISION_TRACKER` | `bytetrack` | `bytetrack` \| `iou` (dependency-free fallback) |
| `VISION_ROLLING_BUFFER_MAX_MB` | `256` | in-memory rolling pre-event buffer byte cap (FR-35) |
| `VISION_EVIDENCE_ENCODER_QUEUE_MAXSIZE` | `16` | bounded off-loop evidence encode queue |
| `VISION_EVIDENCE_HANDOFF_QUEUE_MAXSIZE` | `1000` | bounded in-memory event/evidence handoff queue |
| `VISION_EVIDENCE_HANDOFF_SPOOL_MAX_MB` | `5` | bounded on-disk spill when the handoff queue is full |
| `EVIDENCE_DIR` | `<repo>/data/evidence` | evidence root; files stored by relative path only |
| `EVIDENCE_ROLLING_BUFFER_SECONDS` | `15` | pre-event rolling window (sizes the worker buffer) |
| `EVIDENCE_PRE_EVENT_SECONDS` | `5` | retained before the trigger |
| `EVIDENCE_POST_EVENT_SECONDS` | `5` | captured after the trigger |
| `EVIDENCE_SNAPSHOT_ENABLED` | `true` | snapshot on every trigger (a clip is encoded too) |
| `EVIDENCE_CLIP_FPS` | `5` | clip frame rate |
| `EVIDENCE_CLIP_MAX_FRAMES` | `150` | per-clip frame bound (encoder memory guard) |
| `EVIDENCE_RETENTION_DAYS` | `30` | confirmed default (D-43); oldest-first expiry |
| `EVIDENCE_STORAGE_LIMIT_GB` | `25` | confirmed default (D-43); oldest-first eviction |
| `EVIDENCE_RETENTION_ON_REGISTER` | `false` | keep `false`: deletion is explicit, never a capture side effect |
| `LIVE_PLAYBACK_ENABLED` | `false` | opt-in live playback; requires **both** URLs below (D-62) |
| `MEDIAMTX_API_URL` | — | MediaMTX Control-API base URL (e.g. `http://127.0.0.1:9997`); set while disabled → startup error |
| `MEDIAMTX_WEBRTC_URL` | — | browser-reachable WHEP base URL (e.g. `http://<lan-ip>:8889`); must be reachable from the browser |
| `MEDIAMTX_API_USERNAME` | — | optional Control-API user (must match an `authInternalUsers` entry) |
| `MEDIAMTX_API_PASSWORD` | — | optional Control-API password (`SecretStr`); only needed when the API is exposed beyond loopback |
| `MEDIAMTX_PATH_PREFIX` | `cv` | gateway path prefix, 1–32 chars `[A-Za-z0-9_-]` (D-63) |
| `MEDIAMTX_REQUEST_TIMEOUT_SECONDS` | `2.0` | Control-API request timeout (`0 < x ≤ 30`) |
| `LIVE_GATEWAY_CLOSE_AFTER_SECONDS` | `10` | source-on-demand close timeout (D-63) |
| `LIVE_GATEWAY_PIN_HOSTS` | `true` | pin the validated source IP literal for plain RTSP (D-65); keep `true` |

### Evidence retention and backup/restore (Phase 6; FR-42, FR-43)

Evidence bytes live under `EVIDENCE_DIR` (`camera-<id>/YYYY/MM/DD/...`); the database stores
only relative paths. Access is always through the authenticated `GET /api/evidence/{id}`
endpoint — the directory is never served statically, and paths that escape the root are
rejected.

Retention is **explicit**, not automatic. Run it manually or from a scheduled job:

```bash
cd backend
python -m app.cli prune-evidence --dry-run   # report what would be deleted
python -m app.cli prune-evidence             # delete expired items (oldest-first)
```

It enforces `EVIDENCE_RETENTION_DAYS` and `EVIDENCE_STORAGE_LIMIT_GB` oldest-first and never
removes protected (pinned) evidence; if the cap is still exceeded because every candidate is
protected, it reports that instead of deleting pinned bytes.

Backup and restore (verified with a live PostgreSQL round-trip; a full disposable-cluster
check is in `scripts/verify_backup_restore.sh`):

```bash
# Backup: the structured database + the evidence tree.
pg_dump -Fc "$DATABASE_URL" -f backups/chronovision-$(date +%F).dump
tar czf backups/evidence-$(date +%F).tar.gz -C "$(dirname "$EVIDENCE_DIR")" evidence

# Restore into a fresh database, then restore the evidence tree to the same EVIDENCE_DIR.
pg_restore -d "$RESTORE_DATABASE_URL" backups/chronovision-YYYY-MM-DD.dump
tar xzf backups/evidence-YYYY-MM-DD.tar.gz -C "$(dirname "$EVIDENCE_DIR")"
```

Because evidence files are local and referenced by relative path, the database dump and the
evidence tree must be restored together to keep references valid.

## Documentation

| Document | Purpose |
|---|---|
| `docs/REQUIREMENTS_TRACEABILITY.md` | requirement IDs → source → phase → verification |
| `docs/ARCHITECTURE.md` | components, boundaries, data flow, deployment |
| `docs/IMPLEMENTATION_PLAN.md` | ordered phases, dependencies, acceptance criteria |
| `docs/OPEN_QUESTIONS.md` | unresolved questions and resolutions |
| `docs/DECISIONS.md` | confirmed decisions and pending proposals |
| `docs/IMPLEMENTATION_PROGRESS.md` | current status and next task |
| `docs/TESTING.md` | reproducible test/verification commands and prerequisites (Phase 9) |
| `docs/EVALUATION.md` | event-evaluation format, matching rules, metrics, procedure (Phase 9) |
| `docs/OPERATIONS.md` | deployment, retention, backup/restore, benchmarks (Phase 9) |
| `docs/RUNNING_LOCALLY.md` | start/verify/stop the stack by hand, troubleshooting (D-61) |
| `docs/LIVE_PLAYBACK.md` | opt-in MediaMTX + WebRTC live view: enabling, deployment, security, verification (Phase 10) |
| `docs/KNOWN_LIMITATIONS.md` | consolidated honest limitations (Phase 10; AC-15) |

## Security notes

- Never commit `.env`, credentials, footage, evidence, or database files.
- Bind development services to localhost unless remote access is explicitly required.
- The runtime must not depend on OpenCode, DeepSeek, or any coding agent.
