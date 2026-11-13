# ChronoVision Implementation Progress

## Current Status
- [x] Project directory created
- [x] Git repository initialized on main
- [x] AGENTS.md created
- [x] Requirements and workflow documents reviewed
- [x] Architecture and implementation plan finalized (Phase 0 planning documents)
- [x] Decision set finalized (OQ-01, OQ-02, OQ-06, OQ-09, OQ-14 resolved)
- [x] Phase 1 — Repository foundation and configuration
- [x] Backend foundation (FastAPI application — Phase 2)
- [x] Database schema and migrations (Phase 2: `users`, `sessions`, `audit_logs`)
- [x] Authentication and authorization (Phase 2: single admin)
- [x] Camera management and configuration (Phase 3: `cameras` model, CRUD, SSRF-validated stream references, lifecycle state machine, monitoring control plane)
- [x] Video ingestion and processing pipeline (Phase 4: independent `vision` worker, bounded frame queue, sampling, metrics, worker-health channel, connection-time SSRF)
- [x] Person detection and tracking (Phase 4: pretrained YOLO + per-camera ByteTrack; lazy load/release)
- [x] Seven activity detection rules (Phase 5: eight canonical event types, temporal rules, lifecycle, deterministic messages; detector-input limitations documented)
- [x] Event persistence and transition history (Phase 6: `events`/`event_transitions`, idempotent/ordered/immutable handoff, message rendered + stored at write time)
- [x] Evidence snapshot and clip storage (Phase 6: bounded off-loop capture, safe relative paths, authorized `GET /api/evidence/{id}`)
- [x] Evidence retention and backup/restore (Phase 6: explicit `prune-evidence`, 30 d / 25 GB oldest-first, protected never evicted; verified `pg_dump`/`pg_restore` procedure)
- [x] Real-time event delivery (Phase 7: authenticated `/api/ws` + bounded in-process broadcaster)
- [x] Dashboard and event timeline (Phase 7: React/TS/Vite/MUI)
- [x] Human review workflow (Phase 7: audited `review_status` + evidence pin/unpin)
- [x] Multiple cameras and reliability (Phase 8: per-camera isolation, config reconciliation, per-camera latency percentiles, reproducible benchmark harness)
- [x] Testing, benchmarking, and documentation (Phase 9: reproducible verification scripts, labelled-evaluation tooling + metrics, extended runtime benchmarks, security and retention/backup-restore verification, honest docs)
- [x] Generic live camera playback (Phase 10: opt-in MediaMTX + WebRTC/WHEP for arbitrary RTSP/RTSPS cameras; backend-authoritative source-on-demand gateway paths; encrypted write-only camera credentials; SSRF-pinned gateway source; honest live/unavailable UI)

## Current Phase
**Phase 11 complete** — interactive zone & event setup wizard (frontend-only; see §Phase 11). It lets
an operator pick supported events, draw zones/entrance boundaries over the camera preview, adjust
thresholds, review, and save — generating the existing `{ zones, event_rules }` format without
hand-writing JSON. The vision engine, detection algorithms, auth/CSRF/SSRF controls, and evidence
paths are unchanged; generated config is validated by the backend and by the wizard.
**Live-view follow-up (2026-11-02):** the live player gained a display-only, per-camera 90° rotation
control for sideways feeds (D-71) — since **superseded by D-72**, which persists the rotation as
the camera setting `configuration.rotation`, uses it for **detection** (the worker rotates the
detector input and maps boxes back) as well as display, and keeps the stored zone geometry in the
original camera frame. The zone-setup wizard now exposes the same setting — a rotated preview with
rotate/reset controls, while drawn coordinates are inverse-rotated back into the original frame
(D-73); recorded snapshots/clips are now encoded in the same rotation so recorded evidence also
matches the live view (D-74). The same day, the local MediaMTX gateway was installed to a stable
path and is now started/stopped by the local scripts (D-70).
**Phase 10 complete and verified** (generic live camera playback over MediaMTX + WebRTC/WHEP).
A camera's live picture can be watched in the dashboard for **any** RTSP/RTSPS camera registered
through the existing API/UI — nothing is hard-coded. Playback is **opt-in**: it requires
`LIVE_PLAYBACK_ENABLED=true` **and** both `MEDIAMTX_API_URL`/`MEDIAMTX_WEBRTC_URL` (URLs set while
disabled fail startup). The backend stays authoritative: it registers one stable, source-on-demand
gateway path per camera (`<MEDIAMTX_PATH_PREFIX>-cam-<camera_id>`, default `cv`), validates and
IP-pins the gateway source (SSRF), and stores per-camera RTSP credentials Fernet-encrypted at rest
(write-only through the API; rotating `SECRET_KEY` invalidates them). The browser receives only an
opaque path + WHEP URL — never the camera source or credentials — and the viewing path is separate
from the analysis worker, so a gateway outage degrades only live view. The frontend adds a native
`RTCPeerConnection` WHEP player (`LivePlayer`) and an honest live/unavailable notice. **Decisions:**
D-62–D-65; new setup/security/troubleshooting doc `docs/LIVE_PLAYBACK.md`; migration
`0004_camera_stream_credentials` (additive nullable column). **Not claimed:** a real IP camera and a
real browser WebRTC session (the MediaMTX v1.21.3 process and the WHEP contract *were* exercised
against a local `ffmpeg` H.264 loop, and the feature is covered by backend integration + frontend
component tests against a faked gateway). The Docker Compose `mediamtx` service was not exercised
(no Docker daemon here).

## Submission Review (2026-11-02)
A code-quality / submission pass was run on branch `submission-review` (see D-76). It is
**zero-behaviour cleanup only**: unused symbols, parameters, imports and dead code removed;
duplicated helpers consolidated (`frontend/src/lib/errors.ts` `formatErrorText`, a single
`humanizeToken`, `BaseRule._trim_states`); stale docstrings/comments corrected; and small
typing/accessibility fixes (aria labels, `type="button"` on Retry, an explicit null guard instead
of a `cameraId as number` cast). No API contract, DB schema, config format, event threshold, zone
geometry, tracking, event semantic, migration, or monitoring lifecycle was changed.

Re-verified after the pass: backend **511 passed**, vision **310 passed / 1 skipped**, frontend
**114 passed** (17 files); backend/vision ruff and frontend eslint/prettier/typecheck clean; and
`./scripts/verify.sh` PASSED (including the offline Alembic render).

Three behaviour-changing defects were found and are **deferred for owner approval** (D-76):
destructive `prune-evidence --dry-run`, 422 validation responses echoing raw request input
(including passwords), and an unguarded `new Date(since).toISOString()` in `EventsPage` that can
throw `RangeError`. A source-only submission ZIP was **not** created — it awaits review of the
cleanup summary and the proposed file list.

## Session Handoff (start of next session)
You are continuing ChronoVision. **Phases 1–11 are complete and verified.** Before doing anything,
read `AGENTS.md`, this file, and the relevant parts of `../guidelines.md` /
`../workflow_requirements.md`.

Verified state (see §Phase 10, §Phase 11, and the D-72/D-73/D-74 sections for details): backend
**511 passed**; vision **310 passed / 1 skipped**; frontend **114 passed** (17 files); backend and
vision ruff check/format clean. `scripts/verify.sh` passes end-to-end; `scripts/verify_migrations.sh` reports no
drift;
`scripts/verify_backup_restore.sh` passes on a disposable cluster. Migration head is
`0004_camera_stream_credentials`. The repository is on branch `submission-review` with a single
commit `ee802bd`; the submission-review cleanup is **uncommitted**. **Do not commit or push**
without explicit approval.

Outstanding work is **optional and outside the current plan** (pick only if the user asks):
real-footage labelled evaluation (procedure in `docs/EVALUATION.md`); real RTSP camera validation
(including a real IP camera + browser WebRTC session for live playback); GPU benchmarking on the
RTX 3060 target; a Playwright/E2E suite; OS-process-per-camera isolation (D-50); door/package/pose
producers (EV-04/EV-05/EV-07); a TURN server for WebRTC NAT traversal.

Do **not** claim real detection accuracy, real-camera results, GPU results, or real-browser
playback — none were measured. Keep `EVIDENCE_RETENTION_ON_REGISTER=false`, the deterministic-template
constraint (no runtime LLM), and all auth/CSRF/SSRF/evidence-path protections. Live playback is
opt-in and off by default; keep it that way unless the user asks. Run the backend and vision suites
as **separate** `pytest` processes (mixing them causes spurious failures — `docs/TESTING.md`).

**Running locally (2026-10-31; live-view durability 2026-11-02):** the start/stop procedure is
documented and scripted — `docs/RUNNING_LOCALLY.md`, `scripts/start_local.sh`,
`scripts/stop_local.sh` (D-61). Because this host has no Docker, the stack runs against the
**system** PostgreSQL 18.6 cluster (`127.0.0.1:5432`; only the additive `chronovision`
role/database). MediaMTX for live playback is the pinned v1.21.3 static binary, now installed at
`~/.local/bin/mediamtx` and started/stopped by the local scripts when `LIVE_PLAYBACK_ENABLED=true`
(`--no-mediamtx` opts out) — see `docs/LIVE_PLAYBACK.md` §2.2 and D-70. The compose `mediamtx`
service (profile `playback`) was not exercised here (no Docker daemon). Verified live: backend
(`127.0.0.1:8000`), vision worker, dashboard (`127.0.0.1:5173`), and the gateway (Control API
`127.0.0.1:9997`, WebRTC `:8889`). Stop with `scripts/stop_local.sh`.

## Phase 0 — Planning (complete)
Deliverables: `docs/REQUIREMENTS_TRACEABILITY.md`, `docs/ARCHITECTURE.md`,
`docs/IMPLEMENTATION_PLAN.md`, `docs/OPEN_QUESTIONS.md`, `docs/DECISIONS.md`.
The four decisions (OQ-01, OQ-02, OQ-06, OQ-09) were resolved and propagated across all
documents. See `docs/DECISIONS.md` D-09…D-12.

## Phase 1 — Repository foundation and configuration (complete, verified)

### Files created
- `backend/pyproject.toml` — Phase 1 dependency surface (`pydantic`,
  `pydantic-settings`; dev: `pytest`, `ruff`), pytest and ruff config. FastAPI,
  SQLAlchemy, and Alembic are intentionally deferred to Phase 2.
- `backend/app/__init__.py` — package marker documenting the planned module boundaries.
- `backend/app/config.py` — typed, validated settings (fail-fast).
- `backend/tests/__init__.py`, `backend/tests/test_config.py` — 16 tests.
- `docker-compose.yml` — PostgreSQL service only (`postgres:16-alpine`, localhost-bound,
  named volume, healthcheck).
- `.gitignore` — secrets, env files, virtualenvs, caches, runtime `data/`, recordings,
  evidence, logs, model weights.
- `.env.example` — placeholders only; no real credentials.
- `README.md` — setup, verification, and configuration reference.

### Design decisions finalized in this phase
- **D-13:** Local PostgreSQL via Docker Compose, pinned `postgres:16-alpine`, bound to
  `127.0.0.1:5432`, named volume `chronovision-db-data`.
- **D-14:** Configuration is typed/validated with `pydantic-settings`; secrets are
  `SecretStr` and never logged; `.env` is git-ignored; placeholder values are rejected;
  `debug` is forbidden in production.
- Backend module boundaries (`api`, `auth`, `models`, `schemas`, `services`,
  `repositories`, `event_messages`) are documented but **not yet created**, so no empty
  structure predates its owning phase. `frontend/` and `vision/` are likewise deferred.

### Commands run and results (actually executed)
- `python3 -m venv .venv` + `pip install -e ".[dev]"` — succeeded in a **local** venv
  (no global installs). Installed: pydantic 2.14.1, pydantic-settings 2.16.2,
  pytest 8.4.2 (Python 3.14.7).
- `python -m pytest` — **16 passed** (0.09s).
- `ruff check .` — **All checks passed**; `ruff format --check .` — **clean**.
- `python -m py_compile ...` — syntax OK.
- YAML parse of `docker-compose.yml` — valid; asserts `127.0.0.1:5432:5432` binding,
  `POSTGRES_PASSWORD` present, volume declared.
- Config load with valid environment — prints settings and computed
  `postgresql+psycopg://` URL.
- Fail-fast checks — missing required secrets and `.env.example` placeholder values are
  both rejected with `ValidationError` and clear messages.
- `git check-ignore` — `.env` ignored, `.env.example` tracked; `git add -A --dry-run`
  shows no secrets, venv, or runtime data would be committed.

### Verification limitations (honest reporting)
- **PostgreSQL container was not started.** The Docker CLI is present but the Compose v2
  plugin (`docker compose`) is not installed, there is no legacy `docker-compose`, and
  the Docker socket is not accessible to this user (`permission denied` on
  `/var/run/docker.sock`). The compose file was therefore validated at the YAML level
  only. To verify later:
  ```bash
  cp .env.example .env    # then set POSTGRES_PASSWORD to a real value
  docker compose up -d db && docker compose ps
  ```
- No database, API, authentication, vision, or frontend verification was performed
  because those are out of Phase 1 scope.

## Next Task
**Phase 11 (zone & event setup wizard) is complete and test-verified; awaiting user review in the
running stack.** The original phased plan (`docs/IMPLEMENTATION_PLAN.md`) ended at Phase 9; Phase 10
(generic live camera playback) and Phase 11 (the wizard) were implemented on the user's request.
Remaining work is user review and optional follow-ups (all outside the plan unless the user requests
them): real-footage labelled evaluation to produce actual detection-quality numbers
(`docs/EVALUATION.md` gives the procedure); real RTSP camera validation, including a real IP camera +
real browser WebRTC session for live playback; GPU benchmarking on the target RTX 3060 host; a
browser/E2E (Playwright) suite; OS-process-per-camera isolation (D-50); the door/package/pose
producers (EV-04/EV-05/EV-07); and a TURN server for WebRTC NAT traversal. Door/package/pose
producers remain deferred, unchanged from Phases 5–10 — which is why the wizard shows door-open and
fall-from-bed as **Not available yet**.

## Phase 11 — Zone & event setup wizard (complete, test-verified)

**Scope delivered:** an interactive, frontend-only wizard so an operator can configure camera zones
and events without hand-writing JSON. **Step 1** choose events (with honest capability labels:
door-open and fall-from-bed are disabled and marked "Not available yet"; package detection carries a
detector-configuration note). **Step 2** draw/edit/delete polygons and entrance boundaries on an SVG
overlay sized to the visible video content, with vertex dragging, an interior-side control for
boundaries, undo/cancel, and mouse+touch input. **Step 3** friendly threshold controls shown only for
the selected events. **Step 4** a plain-language review with an optional collapsible Advanced JSON
view. **Step 5** save through the existing camera `PATCH` endpoint (session auth + CSRF), surfaces
422/`ApiError` inline, preserves configuration the wizard does not own, and offers a separate explicit
"Start monitoring" action. **Coordinates** are normalised to `[0, 1]` and mapped from the pointer
through the letterboxed video content rectangle; the person anchor remains bottom-centre. For a
sideways camera the preview can be rotated with rotate/reset controls; drawn coordinates are
inverse-rotated back into the original camera frame and the saved rotation also drives detection
(D-73). **Decision:** D-69 (rotation follow-up: D-72/D-73).

### Files created
- `frontend/src/lib/whep.ts` — shared WHEP connection hook extracted from `LivePlayer`.
- `frontend/src/wizard/coordinates.ts` — pure letterbox/pointer→normalised maths (tested).
- `frontend/src/wizard/wizardTypes.ts` — typed wizard UI state (separate from the DTO).
- `frontend/src/wizard/eventCatalog.ts` — event metadata/capabilities + role↔kind map.
- `frontend/src/wizard/thresholdCatalog.ts` — friendly threshold definitions + defaults.
- `frontend/src/wizard/convert.ts` — wizard-state ↔ `{ zones, event_rules }` conversion + validation.
- `frontend/src/wizard/{CameraPreview,ZoneCanvas,ZoneEditor,StepChooseEvents,StepThresholds,StepReview,ZoneSetupWizard}.tsx`.
- Tests: `frontend/src/wizard/{coordinates,convert}.test.ts`, `{ZoneCanvas,ZoneEditor,ZoneSetupWizard}.test.tsx`.

### Files changed
- `frontend/src/components/LivePlayer.tsx` — now uses the shared `useWhep` hook (behaviour unchanged;
  guarded by the existing `LivePlayer.test.tsx`).
- `frontend/src/pages/CamerasPage.tsx` — new per-camera "Zones & events" action opening the wizard;
  the raw JSON editor moved into an optional "Advanced" accordion.
- `frontend/src/pages/CamerasPage.test.tsx` — the invalid-JSON test expands the Advanced section.
- `docs/DECISIONS.md` — D-69.

### Commands run and results (actually executed)
- Backend (separate process): `backend/.venv/bin/python -m pytest` → **500 passed**.
- Vision (separate process): `backend/.venv/bin/python -m pytest vision/tests` → **286 passed / 1 skipped**.
- Frontend: `npm run typecheck` (clean), `npm run lint` (clean), `npm run test` → **84 passed** (15 files).
- Backend schema check: the wizard-generated configuration validated with
  `parse_camera_rules(...)`; the same invalid cases the UI blocks (unknown role ref, entrance zone
  without a boundary) were rejected by the backend.

### Verification limitations (honest reporting)
- No real-browser interaction with the wizard was performed (no browser automation here); coverage is
  unit/component tests plus a direct `parse_camera_rules` check of a representative generated config.
- The editor's geometry was exercised with deterministic stubbed element sizes in jsdom, not a real
  video element; the letterbox maths is covered by pure-function tests.
- The end-to-end "draw → save → start monitoring → see events" loop was not driven through a real
  camera from the UI (operator credentials unavailable to the agent); the save/start flow is covered
  with mocked APIs and the generated config is backend-validated.

### Unresolved questions, assumptions, blockers, next task
- Assumption: the wizard is opened per **saved** camera (so a live preview can be registered); the
  create-camera flow keeps the Advanced JSON field. Documented in D-69.
- Package detection is shown as available-but-conditional because the frontend cannot read
  `VISION_DETECTOR_PERSON_ONLY`; a person-only detector will not emit package events.
- Next task: user review in the running stack; optional follow-ups listed under **Next Task** above.

## Phase 10 — Generic live camera playback (complete, verified)

**Scope delivered:** opt-in live camera playback over MediaMTX + WebRTC (WHEP) for **any**
RTSP/RTSPS camera registered through the existing API/UI — nothing is hard-coded to one camera. The
backend registers one stable, source-on-demand gateway path per camera, validates and IP-pins the
gateway source (SSRF), and stores per-camera RTSP credentials Fernet-encrypted at rest (write-only
through the API). The dashboard gains a native `RTCPeerConnection` WHEP player and an honest
live/unavailable notice. **Not in scope / not claimed:** a real IP camera and a real browser WebRTC
session (the MediaMTX **v1.21.3** process and the WHEP contract *were* exercised against a local
`ffmpeg` H.264 loop), the Docker Compose `mediamtx` service (no Docker daemon on this host),
TURN/NAT traversal, and H.265 re-encoding. **Decisions:** D-62–D-65; **OQ-13 superseded for live
view** (the D-48 truthful fallback is retained when playback is not enabled).

### Files created
- `backend/app/services/live_gateway.py` — dependency-free MediaMTX v3 Control-API client: fixed
  `/v3/config/paths/{add,patch,delete,get}` calls, `path_name`/`whep_url`, and a `GatewayError` with
  a machine-readable `reason` (`unreachable`/`unauthorized`/`rejected`/…). It is **not** a general
  URL fetcher.
- `backend/app/services/live_service.py` — registration/status orchestration (`on_camera_changed`,
  `playback_status`, `start_playback`) and the `gateway_source_url` SSRF policy (validate + IP-pin).
- `backend/app/services/credential_cipher.py` — Fernet encryption of a `{"username","password"}`
  document whose key is derived from `SECRET_KEY` with a domain-separation constant (D-64); rotating
  `SECRET_KEY` invalidates stored credentials.
- `backend/app/schemas/live.py` — `LivePlaybackInfo` response schema: an opaque path + WHEP URL +
  coarse state and detail, never the camera source or credentials.
- `backend/migrations/versions/0004_camera_stream_credentials.py` — additive nullable
  `cameras.stream_credentials_encrypted` column; **downgrade drops the column and destroys the
  credentials**.
- `backend/tests/test_live_playback.py` — encrypted-credential round-trip/tamper rejection,
  write-only credentials, auth + CSRF on both endpoints, state mapping
  (`unavailable`/`connecting`/`live`/`disconnected`), gateway-failure isolation, stable unique paths,
  cleanup on disable, source validation/pinning (loopback/metadata/`::1` rejected), credential
  injection, RTSPS validate-only, and `/v3` request/error mapping (against a fake gateway).
- `frontend/src/api/live.ts` — typed live-playback client (`get`/`start`).
- `frontend/src/components/LivePlayer.tsx` — native `RTCPeerConnection` WHEP player: non-trickle ICE,
  `POST` offer → SDP answer, `DELETE` on teardown, missing-WebRTC fallback, error reporting, retry.
- `frontend/src/components/LivePlaybackDialog.tsx` — dialog wrapping the player, keyed by `whep_url`
  so a re-registration restarts cleanly.
- `frontend/src/components/LivePlayer.test.tsx` — WHEP offer/answer, error, retry, cleanup/`DELETE`,
  and missing-WebRTC fallback.
- `deploy/mediamtx.yml` — MediaMTX v1.21.3 gateway config: Control API on loopback, WebRTC
  listeners, `sourceOnDemand`, unused servers disabled, and anonymous localhost Control-API access
  (optional `MEDIAMTX_API_USERNAME`/`_PASSWORD` for a non-loopback API). (Corrected during
  real-binary verification: `sourceRedirect` is a **string** target for `source: redirect`, not a
  "follow redirects" boolean, so it was removed; the camera source is always IP-pinned instead.)
- `docs/LIVE_PLAYBACK.md` — enabling, security model, registration, troubleshooting, and an honest
  verification-status section.

### Files changed
- `backend/app/config.py` — live-playback settings (`LIVE_PLAYBACK_ENABLED`, `MEDIAMTX_API_URL`,
  `MEDIAMTX_WEBRTC_URL`, `MEDIAMTX_API_USERNAME`/`_PASSWORD`, `MEDIAMTX_PATH_PREFIX`,
  `MEDIAMTX_REQUEST_TIMEOUT_SECONDS`, `LIVE_GATEWAY_PIN_HOSTS`, `LIVE_GATEWAY_CLOSE_AFTER_SECONDS`)
  plus a `_check_live_playback` fail-fast validator (URLs set while disabled → startup error).
- `backend/app/services/stream_validation.py` — `validate_stream_host`, `pin_stream_host`, and
  `build_source_url` (shared by monitoring and the gateway source).
- `backend/app/api/routes/cameras.py` — `GET /api/cameras/{id}/live` and
  `POST /api/cameras/{id}/live/start` (CSRF); best-effort registration on camera create/update.
- `backend/app/models/camera.py`, `backend/app/schemas/camera.py`,
  `backend/app/services/camera_service.py` — `stream_credentials_encrypted` column;
  `CameraCreate`/`CameraUpdate` accept `stream_username`/`stream_password` (required together) and
  `clear_stream_credentials`; responses expose only `has_stream_credentials`.
- `backend/pyproject.toml` — `cryptography>=43,<47` dependency.
- `docker-compose.yml` — `mediamtx` service behind the `playback` profile (host networking);
  pinned `bluenviron/mediamtx:1.21.3`; mounts `deploy/mediamtx.yml` read-only. With anonymous
  localhost Control-API access no credential injection is needed (`MEDIAMTX_API_*` optional).
- `.env.example` — live-playback variables (URLs commented out by default so a plain copy runs with
  playback disabled).
- `frontend/src/api/{cameras,types}.ts`, `src/hooks/queries.ts`,
  `src/pages/{CamerasPage,OverviewPage}.tsx`, `src/pages/{CamerasPage,OverviewPage}.test.tsx` — live
  dialog launch + settings-gated unavailable notice.
- `docs/DECISIONS.md` (D-62–D-65), `docs/ARCHITECTURE.md`, `docs/REQUIREMENTS_TRACEABILITY.md`,
  `docs/KNOWN_LIMITATIONS.md`, `docs/OPERATIONS.md`, `docs/IMPLEMENTATION_PLAN.md`, `README.md`, and
  this file.

### Endpoints added/changed
- `GET /api/cameras/{id}/live` — session; read-only `LivePlaybackInfo`; never mutates the gateway.
- `POST /api/cameras/{id}/live/start` — session + CSRF; idempotent path registration; never starts
  monitoring.
- `POST/PATCH /api/cameras[/{id}]` — accept `stream_username`/`stream_password`/
  `clear_stream_credentials`; responses add `has_stream_credentials`.

### Security and correctness controls
- **Opt-in and fail-fast:** playback requires `LIVE_PLAYBACK_ENABLED=true` **and** both URLs;
  setting either URL while disabled is a startup error rather than a silent enable.
- **Backend-authoritative paths:** `"<MEDIAMTX_PATH_PREFIX>-cam-<camera_id>"` (default prefix `cv`),
  derived only from the numeric id, `sourceOnDemand: true`, bounded start timeout, and
  `LIVE_GATEWAY_CLOSE_AFTER_SECONDS`. The path's `source` is always the validated camera URL — never
  `source: redirect` — so no redirect target can bypass validation.
- **SSRF:** the gateway source uses the monitoring policy — plain RTSP resolves the host, validates
  **every** address, and pins one as an IP literal; RTSPS hostnames are validated but not rewritten
  (pinning breaks TLS/SNI — the documented D-28 residual).
- **Credentials:** Fernet-encrypted at rest, write-only, decrypted only in-process for registration,
  never logged/returned/placed in an exception; the browser receives no source or credentials and no
  session cookie is sent to the gateway.
- **Failure isolation:** every gateway call on create/update is best-effort, so a gateway outage
  degrades **only** live view; monitoring, events, and evidence are untouched.
- **No coupling:** live view never changes the monitoring plan, per-camera lifecycle, or the vision
  worker's capture.

### Commands run and results (actually executed)
- `cd backend && ./.venv/bin/python -m pytest` — **497 passed** (up from 456).
- `backend/.venv/bin/python -m pytest vision/tests` (repo root) — **286 passed, 1 skipped** (skip =
  opt-in real-weights test; unchanged).
- `cd frontend && npm run typecheck && npm run lint && npm run format:check && npm test` — clean;
  **38 passed (10 files)** (up from 27), including `LivePlayer.test.tsx`.
- `./scripts/verify.sh` — **PASSED** end-to-end: backend **497 passed**, vision **286 passed /
  1 skipped**, frontend **38 passed (10 files)**, backend ruff **All checks passed** + **119 files
  already formatted**, vision ruff **All checks passed** + **77 files already formatted**, frontend
  eslint/prettier/tsc clean, offline Alembic render OK.
- `./scripts/verify_migrations.sh` — **PASSED** on a disposable cluster: `alembic upgrade head` →
  `0004_camera_stream_credentials (head)`, then `alembic check` → **"No new upgrade operations
  detected"**. `alembic heads` → `0004_camera_stream_credentials (head)`.
- **Applied to the local system PostgreSQL (2026-11-01):** `alembic upgrade head` moved the live
  database from `0003_events_evidence` → `0004_camera_stream_credentials`; the
  `cameras.stream_credentials_encrypted` column was confirmed present (`text`, nullable) via
  `information_schema`. Additive only; no existing data changed.
- **MediaMTX v1.21.3 (static binary, real process)** run against the shipped `deploy/mediamtx.yml`:
  config load (API `127.0.0.1:9997`, WebRTC `:8889`, ICE `:8189`, RTSP `:8554`), Control API health,
  `ensure_path` add + `PATCH` refresh (stored config exactly `source`/`sourceOnDemand: true`/
  `sourceOnDemandCloseAfter`/`rtspTransport: "tcp"`), idempotent `remove_path`, invalid-source
  rejection, and a full WHEP handshake against a local `ffmpeg` H.264 loop (`POST …/whep` →
  **`201 Created`** + `Location` → `DELETE` → **`200`**). Details in `docs/LIVE_PLAYBACK.md` §8.
- **Lint/format drift found and fixed during verification (honest note):**
  `backend/tests/test_live_playback.py` was reformatted by ruff, and the six `vision/evidence/*.py`
  modules (previously hidden from ruff by the old `evidence/` `.gitignore` pattern, D-60) gained a
  trailing newline plus three removed unused imports (`Sequence` ×2, `EventSnapshot`). Reruns after
  the fix are the clean results above.

### Verification limitations (honest reporting)
- **No real IP camera and no real browser WebRTC session** were available. The MediaMTX process and
  the WHEP contract were exercised with a local `ffmpeg` H.264 loop and a hand-written SDP offer —
  not a camera and not a browser — so end-to-end browser playback is **not** claimed.
- **The Docker Compose `mediamtx` service was not exercised** (no reachable Docker daemon); MediaMTX
  was run directly from the pinned binary.
- **No TURN server** and no public-internet/NAT traversal; RTSPS hostname pinning was not tested
  against a real certificate; H.265-only cameras may not play.
- **Gateway paths are not persisted** by the read-only config mount; they are recreated on demand,
  so a gateway restart loses idle registrations until the next `start`.
- These are unchanged non-live limitations: no real-footage accuracy, no GPU results, no
  Playwright/E2E suite, door/package/pose producers still absent (EV-04/EV-05/EV-07).

### Unresolved questions, assumptions, blockers, next task
- **OQ-13 superseded for live view by D-62…D-65** (previously D-48 deferred it); the truthful
  unavailable fallback is retained when playback is disabled.
- **Assumption:** MediaMTX is the gateway; the browser is expected to negotiate H.264; a reverse
  proxy/TURN is the operator's responsibility for remote access.
- **Blocker for real playback verification:** no real IP camera, no browser session, and no Docker
  daemon in this environment.
- **Next task:** none in the plan; Phase 10 is final. Await user review; pick a follow-up from the
  "Next Task" list if desired.

## Phase 9 — Testing, evaluation, and documentation (complete, verified)

**Scope delivered:** reproducible test tooling and one-command verification; an offline,
deterministic detection-quality evaluation package (matching rules fixed before scoring) with a
clearly-synthetic sample; an extension of the Phase 8 benchmark harness for the remaining runtime
metrics; an exhaustive security-verification sweep; retention and backup/restore verification on
disposable environments; and the honest documentation set (testing, evaluation, operations,
known limitations). **Not delivered (deliberately, documented):** real-footage accuracy, real
RTSP camera validation, GPU benchmarking, browser/E2E (Playwright) tests, and any schema change
(none was required). **Decisions:** D-55–D-60. **OQ-07/OQ-08 resolved.**

### Files created
- `backend/app/evaluation/{__init__,model,matching,metrics,dataset,cli,__main__}.py` — offline
  evaluation package (`python -m app.evaluation`): fixed matching rules, per-activity metrics,
  dataset loaders, and a CLI that prints a per-activity table and writes a JSON report (D-55).
- `evaluation/sample/synthetic_labels.json`, `evaluation/sample/synthetic_detected.json` —
  hand-authored, clearly-marked (`"synthetic": true`) sample dataset (8 reference / 9 detected)
  used to regression-test the tooling; **not** real footage.
- `backend/tests/test_evaluation.py` — 24 tests: matching rules, metric arithmetic, loaders, and
  the CLI on the synthetic sample.
- `backend/tests/test_security_verification.py` — 39 tests: exhaustive 401 sweep over every
  protected route, 403 CSRF sweep, logout-while-monitoring, WebSocket auth, internal-channel
  isolation, SSRF rejection, evidence-path confinement (D-56).
- `backend/tests/test_retention_verification.py` — 8 tests: time expiry, cap oldest-first,
  protected-never-evicted, `blocked_by_protection`, file-unlink/row-retention, and
  retention-not-on-register (D-57).
- `scripts/verify.sh` — one-command reproducible verification (backend + vision + frontend tests,
  ruff lint/format, frontend lint/format/typecheck, offline Alembic render).
- `scripts/verify_migrations.sh` — disposable-cluster `alembic upgrade head` + `alembic check`
  drift check.
- `scripts/verify_backup_restore.sh` — disposable-cluster `pg_dump`/`pg_restore` round trip with
  row-count, FK, Alembic-revision, and evidence-bytes checks (D-57).
- `docs/TESTING.md`, `docs/EVALUATION.md`, `docs/OPERATIONS.md`, `docs/KNOWN_LIMITATIONS.md` (D-59).

### Files changed
- `vision/benchmarks/harness.py` — `gpu_info()` (explicit `available:false` + reason),
  `measure_recovery_time` (real worker through a simulated outage), duplication counters in the
  handoff micro-benchmark, and `detector_mode: "synthetic"` on camera runs (D-58).
- `vision/benchmarks/__main__.py` — `--skip-recovery` flag; report includes GPU + recovery.
- `vision/tests/test_benchmarks.py` — added GPU, duplication, and recovery cases (8 → 10 tests).
- `README.md`, `docs/ARCHITECTURE.md`, `docs/DECISIONS.md` (D-55–D-60),
  `docs/OPEN_QUESTIONS.md` (OQ-07/OQ-08 resolved), `docs/IMPLEMENTATION_PLAN.md`,
  `docs/REQUIREMENTS_TRACEABILITY.md`, and this file.
- `.gitignore` — **reproducibility bug fixed:** the pattern `evidence/` also matched the
  **source** package `vision/evidence/`, so a fresh checkout would silently omit its six
  `.py` modules and the vision worker would not import. Anchored the runtime pattern to the
  repository root (`/evidence/`); the default `EVIDENCE_DIR` (`data/evidence`) is still
  covered by `data/`. Verified that `vision/evidence/*.py` is now stageable while runtime
  `evidence/` and `data/evidence/` remain ignored.

### Evaluation results (tooling only — no real accuracy claimed)
- Matching/metrics verified by 24 unit tests; on the synthetic sample the CLI reports micro
  precision **0.7778**, recall **0.875**, F1 **0.8235**, macro F1 **0.933** — these are
  **tool-behaviour** figures on hand-authored data, not detection accuracy.
- The shipped detector is person-only, so the sample's `package_left_at_entrance`,
  `door_open_too_long`, `crowd_forming`, etc. rows exercise reporting paths only.

### Security / retention / backup-restore results
- Security sweep: **39 passed**; **no security defect found** (a deliberate honest finding).
  Confirms 401 on every protected route, 403 without CSRF, session invalidation on logout for
  API + WebSocket while the monitoring control plane stays `running`, token-only internal channel,
  SSRF rejection, and evidence-id/path confinement.
- Retention: **8 passed** — strictly-older expiry, oldest-first cap, protected never evicted,
  `blocked_by_protection`, file unlinked but row kept (`retention_status='deleted'`), and
  retention-not-on-register while `EVIDENCE_RETENTION_ON_REGISTER=false`.
- Backup/restore (`scripts/verify_backup_restore.sh`): **PASSED** on a disposable `initdb`
  cluster — migrations to head, seeded camera/event/evidence, `pg_dump`/`pg_restore`, counts
  `cameras 1 / events 1 / evidence 1`, FK integrity OK, evidence bytes byte-identical,
  Alembic `0003_events_evidence` preserved.

### Runtime benchmark results (Phase 9 sweep)
- Host: **CPU-only, 16 CPUs, ~15 GiB RAM, no CUDA/GPU** (`torch 2.15.0+cpu`, `cv2 5.0.0`,
  Python 3.14.7). Synthetic detector cost 20 ms; target 10 fps; 8 s per run.
- 1 cam → 80 processed / 9.96 fps / CPU 7.58 % / RSS +8.94 MB; 2 cam → 158 / 19.65 fps /
  CPU 14.17 % / +7.97 MB; 4 cam → 318 / 39.54 fps / CPU 26.07 % / +14.83 MB; **0 dropped**.
- Micro: event-handoff p50 **2.738 ms** / p95 4.441 / p99 4.611, **0 dropped, 0 duplicates**;
  snapshot-JPEG encode p50 **0.693 ms** (~5425 bytes); recovery after a **1.0 s** outage =
  **1.475 s** (reconnect overhead 0.475 s); `gpu.available=false` (reason `cuda_not_available`).

### Commands run and results (actually executed)
- `scripts/verify.sh` — **PASSED** end-to-end: backend **456 passed**, vision **286 passed /
  1 skipped**, frontend **27 passed (8 files)**; backend ruff **clean** (113 files formatted),
  vision ruff **clean** (71 files), frontend eslint/prettier/tsc clean, offline Alembic render OK.
- `scripts/verify_migrations.sh` — **PASSED**: `alembic upgrade head` then `alembic check` →
  "No new upgrade operations detected".
- `scripts/verify_backup_restore.sh` — **PASSED** (results above).
- `python -m app.evaluation` on `evaluation/sample/` — prints the per-activity table and writes
  the JSON report (figures above).
- Concurrency repeats: vision subset **31 passed ×3**; backend subset **18 passed ×3** (run
  per-suite; mixing backend+vision in one `pytest` process causes spurious vision failures — see
  `docs/TESTING.md`).
- Backend tests **456 passed** total; vision **286 passed / 1 skipped** total.
- Alembic head remains `0003_events_evidence`; **no Phase 9 migration** (no schema change).

### Verification limitations (honest reporting)
- **No real-footage detection accuracy was measured.** No labelled recordings or camera exist
  here; only the evaluation *infrastructure* plus a synthetic sample were delivered. Do not quote
  the sample numbers as system accuracy (`docs/EVALUATION.md`, `docs/KNOWN_LIMITATIONS.md`).
- **No real RTSP camera was tested; no GPU was available.** GPU is reported as
  `available:false` with a reason; no GPU/real-camera performance is claimed.
- **No browser/E2E (Playwright) suite**; frontend coverage is component-level Vitest.
- Benchmark numbers describe the **pipeline scaffolding at a configured detector cost**, not
  accuracy, and are machine-dependent.
- Door/package/pose rules still have **no detector producer**; live video remains undeployed
  (D-48); isolation remains thread-based (D-50).

### Unresolved questions, assumptions, blockers, next task
- **OQ-07 resolved → D-58** (targets set empirically from the extended harness); **OQ-08
  resolved → D-59** (parent docs referenced; TESTING/EVALUATION/OPERATIONS/KNOWN_LIMITATIONS
  created).
- **Assumption:** the extended benchmark and the synthetic sample are sufficient to demonstrate
  the *tooling*; producing real numbers requires labelled footage and a real camera, which are
  outside this environment.
- **Blocker for real accuracy / live video:** no labelled footage, no RTSP camera, and no media
  gateway are available here.
- **Next task:** none in the phased plan (Phase 9 is final). Await user review; pick a follow-up
  from the "Next Task" list if desired. Do **not** treat this as authorization to start scope not
  in the plan.

## Phase 8 — Multiple cameras and reliability (complete, verified)

**Scope delivered:** independent per-camera runtimes (FR-06/AC-04) as separate
`CameraWorker` threads inside **one** vision process (`VISION_MAX_CONCURRENT_CAMERAS`), each
owning its capture thread, bounded frame queue, rolling buffer, tracker, `TemporalEventEngine`,
evidence coordinator, and event handoff; per-camera event/evidence attribution; configuration-change
reconciliation; optional bounded per-camera latency percentiles; and a reproducible synthetic
benchmark harness that establishes the one-camera baseline before scaling (NFR-13). **Not
delivered (deliberately, documented):** OS-process-per-camera isolation (isolation is
thread-based, D-50); real-footage detection-quality metrics and GPU/resource profiling
(Phase 9); live video (D-48); door/package/pose producers.

### Files created
- `vision/benchmarks/{__init__,harness,__main__}.py` — reproducible benchmark harness and CLI
  (`python -m vision.benchmarks`): a throttled, lock-guarded `LoopingClipSource` that decodes a
  generated clip with real OpenCV and loops by **reopening** it (seeking under concurrent decode
  was nondeterministic), a `SyntheticDetector` with configurable per-frame cost, and
  `run_camera_benchmark` + `measure_event_handoff_latency`/`measure_evidence_encode_latency`
  micro-benchmarks; writes a JSON report (D-54).
- `vision/tests/test_multi_camera.py` — concurrent cameras keep independent tracker/engine/
  evidence/handoff state; a terminal-failing camera and a blocked (stalled-detector) camera do
  not affect healthy cameras; events are attributed to the producing camera; the manager stops
  only the requested camera; each camera reports its own health.
- `vision/tests/test_reliability.py` — prompt, bounded stop while connecting and during
  reconnect backoff; terminal failure idles without restart churn; tracker + engine reset on
  every (re)connection; safe repeated start/stop; manager replaces a dead worker; manager
  applies a config change; concurrent `ensure` calls converge. Threaded paths use bounded
  `wait_until` synchronisation instead of fixed sleeps.
- `vision/tests/test_benchmarks.py` — harness unit tests (nearest-rank percentiles, resource
  helpers, synthetic detector, JSON round-trip, clip looping, one-camera benchmark fields,
  handoff and encode micro-benchmarks); CV-dependent tests are gated.
- `backend/tests/test_multi_camera_isolation.py` — per-camera staleness projection;
  a dead camera does not project a live camera as disconnected; monitoring survives browser
  **logout** and **WebSocket disconnect** (NFR-01); interleaved/out-of-order events stay
  attributed; evidence is attributed to its own event.

### Files changed
- `vision/camera_manager/manager.py` — `ensure` now stops and recreates a live worker whose
  `CameraConfig` changed (stale zones/rules), in addition to pruning undesired/dead workers
  (D-53).
- `vision/camera_manager/worker.py` — public `config` property exposing the worker's
  `CameraConfig` for reconciliation (D-53).
- `vision/event_handoff.py` — per-camera spool isolation: `_spool_files`/`_scan_spool` use
  `handoff-<camera_id>-*.json`, and `spool_max_bytes` is enforced per camera so one camera's
  backlog cannot evict or be delivered as another's (D-51); fixed a **lost wakeup** in the
  deliverer `_run` (re-check the queue under the condition lock before `wait(0.1)`), which cut
  measured hand-off delivery p50 from ≈102 ms to ≈2 ms (D-51).
- `vision/metrics.py` — optional bounded latency-sample ring plus nearest-rank
  `latency_p50_ms`/`p95`/`p99` and `latency_sample_count` in the snapshot (disabled by default)
  (D-52).
- `vision/config.py` — `metrics_latency_sample_capacity` (default `0`), documented (D-52).
- `vision/tests/test_metrics.py` — added latency-sampling-disabled-by-default and
  percentile-bound cases (5 → 7 tests).
- `vision/tests/test_event_handoff.py` — added the cross-camera spool-isolation case (9 → 10).
- `vision/tests/test_manager.py` — `FakeWorker.config` + config-change reconciliation cases
  (added 2 tests).
- `backend/tests/test_event_broadcaster.py` — added stuck-subscriber isolation and
  concurrent-publisher cases (2 new tests).

### Commands run and results (actually executed)
- `./.venv/bin/python -m pytest` (backend) — **385 passed** (up from 377). Includes the new
  `test_multi_camera_isolation.py` (6) and 2 new broadcaster tests.
- `backend/.venv/bin/python -m pytest vision/tests` — **284 passed, 1 skipped** (up from 257/1;
  the skip is the opt-in real-weights test). New: `test_multi_camera.py` (5),
  `test_reliability.py` (9), `test_benchmarks.py` (8), plus 2 metrics / 1 handoff / 2 manager
  cases.
- `ruff check .` + `ruff format --check .` (backend) — **All checks passed**; **103 files already
  formatted**. `ruff check --config backend/pyproject.toml vision` + `ruff format --check`
  (vision) — **All checks passed**; **71 files already formatted**.
- `python -m vision.benchmarks --cameras 1,2,4,8 --duration 8 --detector-cost-ms 20` (synthetic
  detector; real OpenCV decode; host **CPU-only, 16 CPUs, ~15 GiB RAM, no CUDA/GPU**; per-camera
  ingest ≈29.6 fps, `process_target_fps` 10, **0 frames dropped**, queue depth 1):
  1 camera → 80 processed / 10.0 fps / p50 20.4 ms / CPU ≈7 %; 2 → 158 / 19.7 fps;
  4 → 316 / 39.2 fps; 8 → 620 / 76.3 fps / CPU ≈53 % / RSS +27.5 MB. Micro-benchmarks:
  event-handoff delivery p50 ≈ 2.6 ms (200 messages, 0 dropped, 0 spooled); snapshot JPEG encode
  p50 ≈ 0.64 ms (640×480, ≈5.4 KB). The 1/2/4/8 sweep was repeated (5 s and 8 s durations) with
  the same trend and exit status.
- Offline migration render examined (no schema change in Phase 8); Alembic head stays
  `0003_events_evidence` (Phase 8 adds no migration).

### Verification limitations (honest reporting)
- **Isolation is thread-based, not OS-process-based (D-50).** A failing/blocked *camera* is
  contained (verified), but a hard fault inside a native decoder (e.g. `SIGSEGV`/OOM in
  OpenCV) would still take down the shared worker process. OS-process-per-camera is documented
  as future work.
- **Benchmark numbers describe pipeline scaffolding, not detection quality (D-54).** The
  detector is simulated at a configured per-frame cost; the source decodes a local generated
  clip. `frames_received`/CPU reflect paced capture (`capture_fps`), and `process_fps` is
  sampling-limited to `process_target_fps`. No real-footage accuracy or GPU numbers are claimed.
- **No real RTSP camera was tested**, and the benchmark host had no GPU; the RTX 3060 target
  (NFR-15) was not exercised.
- The Docker-Compose PostgreSQL path remains unexercised (as in earlier phases); Phase 8 made no
  schema change, so no migration was applied.
- `EventHandoff` still polls with a ≤100 ms idle interval when nothing is queued (bounded; the
  lost-wakeup fix removed the *avoidable* delay for queued items).

## Phase 7 — Web dashboard, real-time delivery, and human review (complete, verified)

**Scope delivered:** a same-origin React 19 / TypeScript / Vite / MUI dashboard with login +
protected routes, overview, camera management + monitoring controls, an event timeline
(filters/ordering/pagination), event details (deterministic message, transitions, evidence
viewer), and read-only settings; authenticated real-time notifications over `/api/ws`; and
the deferred human-review workflow (audited `PATCH /api/events/{id}` for `review_status`, and
audited `PATCH /api/evidence/{id}` for `protected`/`retained`). **Not delivered (deliberately,
documented):** live video playback (no MediaMTX/WebRTC gateway; D-48) and Playwright E2E
(unit/component + backend integration tests were used instead). Door/package/pose producers
and multi-camera isolation remain unchanged (Phases 5/8).

### Files created
- **Frontend (`frontend/`)** — `package.json`, `tsconfig.json`, `vite.config.ts`
  (dev proxy `/api` + `ws: true`; Vitest/jsdom), `eslint.config.js`, `.prettierrc.json`,
  `.prettierignore`, `index.html`.
  - `src/api/` — `client.ts` (same-origin fetch + CSRF + `ApiError` + 401 event),
    `types.ts`, `auth.ts`, `cameras.ts`, `events.ts`, `evidence.ts`, `monitoring.ts`,
    `settings.ts`, `health.ts`, `ws.ts` (bounded-backoff reconnecting socket).
  - `src/auth/` — `AuthContext.tsx` (provider), `auth-context.ts`, `useAuth.ts`,
    `ProtectedRoute.tsx`.
  - `src/realtime/` — `RealtimeProvider.tsx`, `realtime-context.ts`, `useRealtime.ts`.
  - `src/layout/AppLayout.tsx`, `src/theme.ts`, `src/lib/format.ts`,
    `src/hooks/queries.ts`, `src/components/{chips,states}.tsx`.
  - `src/pages/` — `LoginPage`, `OverviewPage`, `CamerasPage`, `EventsPage`,
    `EventDetailPage`, `SettingsPage`, `NotFoundPage`.
  - `src/App.tsx`, `src/main.tsx`, `src/test/{setup.ts,render.tsx,fixtures.ts}`.
  - Tests: `src/api/{client,ws}.test.ts`,
    `src/auth/ProtectedRoute.test.tsx`, `src/pages/{LoginPage,EventsPage,EventDetailPage,
    CamerasPage}.test.tsx`, `src/realtime/RealtimeProvider.test.tsx`.
- **Backend** — `app/services/event_broadcaster.py` (thread-safe bounded fan-out +
  notification builders), `app/api/routes/realtime.py` (`/api/ws`),
  `app/api/routes/settings.py` + `app/schemas/settings.py` (read-only settings),
  tests `test_event_review_api.py`, `test_evidence_protection_api.py`,
  `test_settings_api.py`, `test_event_broadcaster.py`, `test_ws_api.py`.

### Files changed
- `backend/app/auth/dependencies.py` — extracted `resolve_session()` so the HTTP dependency
  and the WebSocket handshake enforce identical session rules.
- `backend/app/api/routes/events.py` — `review_status` + `order` filters and
  `PATCH /api/events/{id}` (audit + broadcast; only `review_status` changes).
- `backend/app/api/routes/evidence.py` — `PATCH /api/evidence/{id}` pin/unpin
  (reuses `protect_evidence`/`release_evidence`; audit + broadcast; `409` if deleted).
- `backend/app/schemas/event.py` (`EventReviewUpdate`), `backend/app/schemas/evidence.py`
  (`EvidenceRetentionTarget`/`EvidenceRetentionUpdate`), `backend/app/schemas/__init__.py`.
- `backend/app/repositories/events.py` — `review_status` filter + explicit `order`.
- `backend/app/services/event_service.py`/repositories — small helpers used by review.
- Broadcast wiring in `api/routes/{internal,monitoring,cameras}.py`.
- `backend/app/api/router.py` — mounts `realtime` + `settings` routers.
- `backend/app/__init__.py` — version `0.7.0`.
- `backend/tests/conftest.py` — reset the broadcaster per test.
- `backend/app/api/routes/realtime.py` — handler teardown no longer `await`s the cancelled
  send/receive tasks (done-callback drain instead); fixes the spurious `CancelledError` found
  during verification (D-49).
- `backend/tests/test_ws_api.py` — added a repeated connect/close regression test
  (`test_websocket_sessions_tear_down_cleanly`).
- `.gitignore` — ignores `node_modules/`, `frontend/dist/`, `*.tsbuildinfo`.
- `README.md`, `docs/ARCHITECTURE.md`, `docs/IMPLEMENTATION_PLAN.md`, `docs/DECISIONS.md`
  (D-44–D-49), `docs/REQUIREMENTS_TRACEABILITY.md`, `docs/OPEN_QUESTIONS.md`, this file.

### Endpoints added/changed
- `PATCH /api/events/{id}` — session + CSRF; body `{review_status, note?}`; writes an
  `audit_logs` row (`event_reviewed`) and publishes a notification; returns the full event.
- `PATCH /api/evidence/{id}` — session + CSRF; body `{retention_status: "protected" |
  "retained"}`; audit + notification; `409` for deleted evidence.
- `GET /api/settings` — session; effective non-sensitive evidence/retention policy +
  `evidence_storage_used_bytes`.
- `WS /api/ws` — session cookie; sends `{type:"ready",user}` then event/camera/monitoring/
  evidence notifications; unauthenticated/revoked → `{type:"error"}` + close `1008`.
- `GET /api/events` — added `review_status` and `order=asc|desc`.

### Security and correctness controls
- The dashboard uses only same-origin `/api` requests with `credentials: 'same-origin'`;
  writes echo the readable `chronovision_csrf` cookie in `X-CSRF-Token`. No token is stored
  in the browser (D-44).
- WebSocket authentication shares `resolve_session` with REST, so revoked/expired/inactive
  sessions are rejected; payloads contain no evidence bytes, stream references, or
  credentials. Fan-out queues are bounded (slow client drops oldest); fan-out is in-process
  (single uvicorn worker) — documented limitation.
- Review changes only `review_status`; the deterministic message, timestamps, lifecycle
  state, severity, and confidence are untouched. Review and evidence protection are separate
  audited mutations (no implicit pinning).
- Protected evidence is excluded from retention/eviction (D-43); the endpoint never deletes.
- Opening a page or the WebSocket never starts monitoring; Start/Pause/Stop are explicit.
- The UI states live video is unavailable and never fabricates camera health, events, or
  evidence.

### Commands run and results (actually executed)
- `cd backend && ./.venv/bin/python -m pytest` — **377 passed** (repeat runs; the WebSocket
  teardown-cancellation bug found during verification was fixed — see §*Verification
  limitations* and D-49 — and the suite is now stable across 5+ consecutive full runs).
- `cd backend && ruff check .` — **All checks passed**; `ruff format --check .` —
  **102 files already formatted**.
- `./backend/.venv/bin/python -m pytest vision/tests` (repo root) — **257 passed, 1 skipped**
  (skip = opt-in real-weights test; unchanged).
- `ruff check --config backend/pyproject.toml vision` + `ruff format --check` — clean
  (**65 files**; unchanged).
- `cd frontend && npm run typecheck` — passed (`tsc --noEmit`).
- `cd frontend && npm run lint` — **0 errors, 0 warnings** (ESLint 10 flat config).
- `cd frontend && npm run format:check` — **All matched files use Prettier code style**.
- `cd frontend && npm test` — **27 passed** (8 test files; Vitest 5 + Testing Library).
- `cd frontend && npm run build` — succeeded (`tsc --noEmit && vite build`).
- Alembic: **no new migration** — Phase 7 reuses the existing `events.review_status`,
  `evidence.retention_status`, and `audit_logs` columns/tables. `alembic upgrade head --sql`
  still ends at `0003_events_evidence`.

### Verification limitations (honest reporting)
- **Live video playback is not implemented.** No MediaMTX/WebRTC gateway exists; the
  dashboard explicitly says live view is unavailable and only stored snapshot/clip evidence
  is viewable (D-48). FR-51/FR-54 are therefore **not** delivered.
- **No Playwright/browser E2E test** was written. Frontend behaviour is covered by Vitest
  component/unit tests (auth redirect, login, event filtering, review, evidence protection,
  WebSocket reconnection/cache invalidation, camera controls) plus backend integration tests;
  a real browser session against a running stack was not exercised.
- **A real WebSocket teardown defect was found and fixed during final verification.** The
  original `/api/ws` handler `await`ed `asyncio.gather(...)` for its send/receive tasks inside
  its `finally` block. When the server cancels the handler during close (uvicorn, and
  Starlette's `TestClient` portal), an `await` of an already-cancelled child in `finally`
  let a spurious `CancelledError` escape the ASGI application instead of being absorbed by
  the server's cancel scope. In the test suite this produced an intermittent failure of
  `test_websocket_sends_ready_and_receives_notifications` — measured at ≈32% of isolated runs,
  not merely a rare race. A minimal reproduction confirmed the pattern itself (`asyncio.wait`
  + `await gather` in `finally`) fails ≈47% of runs, while the corrected form (cancel + drain
  via done-callback, no awaiting in `finally`) passes 100/100 with no unretrieved-task
  warnings. The handler was fixed (D-49) and a repeated connect/close regression test
  (`test_websocket_sessions_tear_down_cleanly`) was added, which reproduces the old failure
  24/25 times and now always passes. The backend total is therefore **377 passed**.
- **No live RTSP camera** was tested (unchanged from Phase 4–6); the detector remains
  person-only, so door/package/pose rules (EV-04/EV-05/EV-07) are still not end-to-end.
- The in-process broadcaster is single-worker only; horizontal scaling would need a shared
  bus (not implemented).

### Unresolved questions, assumptions, blockers, next task
- **OQ-10 resolved → D-45** (audited review implemented), **OQ-13 resolved → D-48** (live
  view deferred). **OQ-12** (multi-camera acceptance timing) remains for Phase 8.
- **Assumption:** the dashboard is a single-operator tool; no roles/permissions beyond the
  single admin were added.
- **Blocker for EV-04/EV-05/EV-07:** unchanged — no door-state, package-class, or pose
  producer exists.
- **Next task:** Phase 8 (multi-camera isolation/reliability and benchmarking). Do not start
  it here.

## Phase 6 — Persistence and evidence (complete, verified)

**Scope delivered:** durable event persistence with transition history, a bounded
authenticated worker→backend handoff for events and evidence metadata, off-loop
snapshot/short-clip evidence capture with safe relative paths, authorized evidence
delivery, retention with an explicit CLI, and an FR-43 backup/restore procedure verified
against a live PostgreSQL instance. **Not in scope / not started:** dashboard, WebSocket
delivery, live view, human-review/`PATCH` (Phase 7), multi-camera process isolation
(Phase 8), and door/package/pose producers (unchanged from Phase 5).

### Files created
- `backend/migrations/versions/0003_events_evidence.py` — additive migration for `events`,
  `event_transitions`, `evidence` (down_revision `0002_cameras`).
- `backend/app/models/event.py` — `Event` (current state) + `EventTransitionRecord`
  (immutable history); unique `event_id`, `state_version`, denormalised
  `rule_version`/`config_version`.
- `backend/app/models/evidence.py` — `Evidence`, `EvidenceMediaType`, `EvidenceStatus`
  (`pending`/`available`/`failed`), `RetentionStatus` (`retained`/`protected`/`deleted`).
- `backend/app/repositories/events.py`, `backend/app/repositories/evidence.py` —
  parameterised persistence helpers.
- `backend/app/services/event_service.py` — idempotent, monotonic, terminal-immutable event
  upsert; renders the deterministic message once at write time.
- `backend/app/services/evidence_service.py` — evidence registration, path confinement
  inside `EVIDENCE_DIR`, file-existence verification before `available`, and `run_retention`
  (time window + storage cap, oldest-first, protected never evicted).
- `backend/app/schemas/event.py`, `backend/app/schemas/evidence.py` — event/evidence
  response schemas (no absolute paths, no credentials).
- `backend/app/api/routes/events.py` — read-only `GET /api/events` (filters + pagination)
  and `GET /api/events/{id}` (transitions + evidence metadata).
- `backend/app/api/routes/evidence.py` — authorized `GET /api/evidence/{id}` (404/409/410;
  never a static directory).
- `vision/evidence/{__init__,paths,encoding,store,manager,coordinator}.py` — capture windows,
  safe path construction, injectable encoder, filesystem store, and the event-sink +
  capture coordinator.
- `vision/event_handoff.py` — bounded in-memory queue + bounded on-disk spool, single
  delivery thread, capped-backoff retries, permanent-failure discard.
- `backend/tests/test_event_persistence.py`, `backend/tests/test_evidence_service.py`,
  `backend/tests/test_events_api.py`, `backend/tests/test_evidence_api.py`,
  `backend/tests/test_internal_events_api.py`, `backend/tests/event_builders.py`.
- `vision/tests/test_evidence_paths.py`, `test_evidence_store.py`,
  `test_evidence_manager.py`, `test_evidence_coordinator.py`, `test_event_handoff.py`,
  `test_worker_evidence.py`, `vision/tests/evidence_helpers.py`.

### Files changed
- `backend/app/models/__init__.py`, `backend/app/schemas/__init__.py`,
  `backend/app/schemas/internal.py`, `backend/app/api/routes/internal.py` — register the new
  models/schemas and add `POST /api/internal/events` +
  `POST /api/internal/events/{event_id}/evidence`.
- `backend/app/config.py` — evidence/rolling-buffer knobs; retention defaults confirmed and
  `evidence_retention_on_register` set to `False` (D-43).
- `backend/app/cli.py` — `prune-evidence [--dry-run]`.
- `vision/runtime.py`, `vision/camera_manager/worker.py`, `vision/config.py` — wire the
  `EvidenceCoordinator` in place of `NullEventSink`, bind the rolling buffer, and add the
  evidence/handoff settings.
- `.env.example` — documented `EVIDENCE_*`, `VISION_ROLLING_BUFFER_*`,
  `VISION_EVIDENCE_*` knobs incl. `EVIDENCE_RETENTION_ON_REGISTER=false`.
- `README.md`, `docs/ARCHITECTURE.md`, `docs/DECISIONS.md` (D-40–D-43),
  `docs/REQUIREMENTS_TRACEABILITY.md`, `docs/OPEN_QUESTIONS.md` (OQ-06), and this file.

### Persistence and evidence invariants
- `event_id` is unique → re-delivered transitions upsert the same row; a `state_version`
  not newer than the stored one is a stale no-op; `completed`/`cancelled` are immutable
  (a recurrence is a new event). The rendered message is stored once and never regenerated.
- Evidence bytes live only under `EVIDENCE_DIR` with a relative path recorded in the DB;
  both the writer and reader reject absolute paths, `..`, drive letters, and symlinks
  resolving outside the root. An item is `available` only after the backend verifies the
  file exists; a declared-but-missing file becomes `failed`.
- Retention enforces the time window and storage cap oldest-first, never removes
  `protected` evidence, and reports `blocked_by_protection` when only pinned items remain.
  Deletion runs only through `prune-evidence` (auto retention-on-register disabled).

### Commands run and results (actually executed)
- `cd backend && ./.venv/bin/python -m pytest` — **353 passed** (up from 306).
- `backend/.venv/bin/python -m pytest vision/tests` (repo root) — **257 passed, 1 skipped**
  (up from 189 passed/1 skipped); skip = opt-in real-weights test.
- `cd backend && ruff check .` — **All checks passed**; `ruff format --check .` — **93 files
  already formatted**.
- `ruff check --config backend/pyproject.toml vision` + `ruff format --check` — **All checks
  passed**; **65 files already formatted**.
- `alembic upgrade head --sql` — renders `events`, `event_transitions`, `evidence` after the
  Phase 2/3 tables.
- Live throwaway PostgreSQL cluster (127.0.0.1:55432): `alembic upgrade head` →
  `0003_events_evidence (head)`; `alembic check` = **"No new upgrade operations detected"**;
  a live smoke persisted an event + evidence (rendered message + `available` evidence);
  FR-43 backup (`pg_dump -Fc` + evidence-tree copy) restored into a fresh DB (1 event,
  1 evidence, message intact, evidence file present); `alembic downgrade base` clean.

### Independent re-verification (2026-10-30)

The working tree was re-inspected and Phase 6 re-verified in a fresh session on 2026-10-30
(the repository was already in the completed Phase 6 state from the interrupted 2026-10-29
session). **No implementation changes were required.**
- `cd backend && ./.venv/bin/python -m pytest` — **353 passed**.
- `backend/.venv/bin/python -m pytest vision/tests` — **257 passed, 1 skipped** (skip =
  opt-in real-weights test).
- `ruff check .` + `ruff format --check .` (backend) — clean (93 files); vision — clean
  (65 files).
- `alembic upgrade head --sql` renders `events`, `event_transitions`, `evidence` after the
  Phase 2/3 tables.
- Live throwaway PostgreSQL 18.6 cluster (127.0.0.1:55433): `alembic upgrade head` →
  `0003_events_evidence (head)`; `alembic check` = "No new upgrade operations detected". A
  two-process smoke test persisted an event (2 transitions) and a snapshot through the
  authenticated internal channel (missing token → 401; a `../../etc/passwd` path was recorded
  as `failed`, never served), re-read it from a **fresh process** (rendered message, history
  `[1, 2]`, `evidence_refs=['snapshot:1']`, evidence bytes intact), then `pg_dump -Fc` +
  evidence-tree copy was restored into a fresh database (1 event, 2 evidence rows) and the
  restored event/evidence served correctly (FR-43). `prune-evidence --dry-run` and
  `prune-evidence` ran against live data (0 deleted, 26 bytes remaining); `alembic downgrade
  base` dropped all three tables cleanly (0 remaining).
- `git check-ignore` confirms `.env` and `data/` are ignored; `git add -A --dry-run` stages no
  secrets, venv, database, dump, or evidence files.

### Verification limitations (honest reporting)
- **The Phase 4 YOLO detector is person-only.** Door state, package classes, and pose remain
  explicit interfaces **with no producer**, so EV-04/EV-05/EV-07 are still not end-to-end;
  the door/package/fall event rules are unit-tested with synthetic transitions.
- **No live RTSP camera was exercised.** Capture, handoff, and persistence were verified
  with the test fixtures/fakes and a synthetic-payload live PostgreSQL smoke, not real
  video. Real end-to-end latency/quality measurement remains Phase 9.
- The storage-cap eviction and clip-encoding paths are covered by unit tests with a fake
  encoder; real OpenCV clip encoding on live frames was not benchmarked.
- Human review, evidence pin/unpin, and `PATCH /api/events/{id}` are **not** implemented
  (Phase 7); `retention_status='protected'` is supported in the schema/service but nothing
  sets it yet.
- Multi-camera process isolation remains Phase 8; the default runtime still targets one
  camera.

### Unresolved questions, assumptions, blockers, next task
- **OQ-06 resolved → D-11/D-43:** retention/storage defaults confirmed 2026-10-29.
- **Assumption:** the confirmed retention window/cap are starting values to tune in Phase 9
  after benchmarking; they are fully configurable.
- **Blocker for end-to-end EV-04/EV-05/EV-07:** unchanged — no door-state, package-class, or
  pose producer exists.
- **Next task:** Phase 7 (web dashboard + human review). Do not start it here.

## Phase 5 — Temporal event engine and deterministic messages (complete, verified)

**Scope delivered:** the eight canonical event types (seven activities; two occupancy
categories) as per-camera temporal rules with the full lifecycle, deterministic identity,
camera-specific zones/thresholds, deterministic message templates/sanitisation/fallbacks,
camera-config API validation, and worker frame adaptation/reset/finalisation. **Not in
scope / not started:** persistence, event handoff, evidence, dashboard, WebSocket, pose
model, door-state classifier, package detector (Phases 6–8).

### Files created
- `backend/app/events/__init__.py` — public exports for the shared contract.
- `backend/app/events/types.py` — eight `EventType`s, five `EventStatus`es, actions,
  severity, `Certainty`, `ReviewStatus`, `EventSnapshot`, `EventTransition`, UTC
  normalisation.
- `backend/app/events/lifecycle.py` — `EVENT_TRANSITIONS`, `can_transition`,
  `transition`, `InvalidEventTransition`, terminal-state set.
- `backend/app/events/zones.py` — `Point`, `BoundaryLine`, `Zone`, `ZoneKind`,
  `EventThresholds`, `CameraRulesConfig`, `parse_camera_rules`,
  `validate_camera_configuration`, `CameraRulesError`.
- `backend/app/event_messages/__init__.py`, `templates.py` — fixed templates for all eight
  types, required-field declarations, documented fallbacks.
- `backend/app/event_messages/renderer.py` — `EventMessageContext`,
  `render_event_message`, `render_event`, `message_context_from_event`,
  `sanitize_display_text`, UTC time formatting, URL/credential redaction.
- `vision/event_engine/__init__.py`, `types.py` — `EngineFrame`,
  `EntityObservation`, `DoorStateObservation`, `PoseObservation`, `Posture`, `EventSink`,
  `NullEventSink`.
- `vision/event_engine/geometry.py` — normalisation, bottom-centre anchor,
  point-in-polygon, directed boundary side/epsilon.
- `vision/event_engine/base.py` — `EventIdFactory` (deterministic UUIDv5),
  `ActiveEvent`, `BaseRule`, severity map, confidence→certainty mapping,
  `RULE_VERSION="phase5-v1"`.
- `vision/event_engine/engine.py` — `TemporalEventEngine`, `build_engine`, per-rule error
  isolation, sink publishing, reset, stream-end finalisation.
- `vision/event_engine/rules/{__init__,boundary,occupancy,door,package,motionless,fall}.py`
  — all activity rules.
- `vision/tests/event_helpers.py`, `test_event_boundary.py`, `test_event_occupancy.py`,
  `test_event_door.py`, `test_event_package.py`, `test_event_motionless.py`,
  `test_event_fall.py`, `test_event_engine.py`, `test_worker_events.py`.
- `backend/tests/test_event_contract.py`, `test_event_zones.py`,
  `test_event_messages.py`, `test_camera_config_api.py`.

### Files changed
- `vision/camera_manager/worker.py` — `CameraConfig.configuration`, optional `event_sink`,
  injectable `wall_clock`, engine build/reset/finalise, frame adaptation, event counters.
- `backend/app/schemas/internal.py`, `backend/app/api/routes/internal.py` — `configuration`
  included in the internal runtime plan.
- `vision/internal_client.py`, `vision/supervisor.py` — propagate camera configuration.
- `backend/app/services/camera_service.py` — validate `configuration` on create/update
  (`InvalidCameraConfiguration`); `backend/app/api/routes/cameras.py` maps it to HTTP 422.
- `backend/tests/test_internal_api.py`, `backend/tests/test_camera_api.py` — updated plan
  payload and a now-valid zone configuration.
- `docs/ARCHITECTURE.md`, `docs/DECISIONS.md` (D-34–D-39),
  `docs/REQUIREMENTS_TRACEABILITY.md`, `docs/OPEN_QUESTIONS.md` (OQ-03/04/05),
  `docs/IMPLEMENTATION_PLAN.md`, this file.

### Event types and lifecycle
- Canonical types: `person_entering`, `person_leaving`, `room_occupancy_change`,
  `crowd_forming`, `door_open_too_long`, `package_left_at_entrance`, `person_motionless`,
  `fall_from_bed` (D-10).
- Lifecycle: `candidate → {active, uncertain, cancelled}`,
  `active → {completed, uncertain, cancelled}`,
  `uncertain → {active, completed, cancelled, uncertain}`; `completed`/`cancelled` are
  terminal and immutable. Instantaneous events (entry, exit, occupancy change) emit
  `opened` + `resolved` in one frame; persistent events update and complete only on an
  observed end condition. Stream end marks open events `uncertain`, not completed.
- Identity is a deterministic UUIDv5; `state_version` increments per transition; events
  carry `rule_version` and `config_version`.

### Rule behaviour implemented (details in D-36)
- **Entry/exit:** bottom-centre anchor; first observation is presence (never an entrance);
  confirmed crossing (2 frames) with cooldown; disappearance without an outward crossing
  is not a leaving event; instantaneous.
- **Occupancy:** 3 s retained-track smoothing; debounced `room_occupancy_change` only when
  the count changes; `crowd_forming` persistent at ≥3 for 15 s, release after 5 s below
  threshold−1.
- **Door:** explicit `DoorStateObservation` input; 60 s open threshold; 5 s unknown
  tolerance; throttled updates; close completes; unknown/stream end → `uncertain`.
- **Package:** configurable package classes; stationary 45 s within 0.02; movement
  cancels/restarts; absence 5 s completes; nearby person forces low certainty.
- **Motionless:** anchor displacement ≤0.01 for 120 s with ≥5 observations; resumed
  movement completes; track loss → `uncertain`. This is track-motion only (no pose
  producer); pose-based refinement is deferred.
- **Fall:** bed + pose input required; recent bed→low/lying outside bed within 5 s; low
  posture in a configured floor zone without transition → `uncertain`; upright 5 s
  completes; track/stream end → `uncertain`; potential-fall wording only.

### Commands run and results (actually executed)
- `cd backend && ./.venv/bin/python -m pytest` — **306 passed** (7.07 s), up from 180.
- `backend/.venv/bin/python -m pytest vision/tests` (repo root) — **189 passed, 1 skipped**
  (3.61 s), up from 130 passed/1 skipped; skip = opt-in real-weights test.
- `cd backend && ruff check .` — **All checks passed**; `ruff format --check .` — **76 files
  already formatted**.
- `ruff check --config backend/pyproject.toml vision` + `ruff format --check` — **All checks
  passed**; **57 files already formatted**.
- `alembic upgrade head --sql` — renders `users`/`sessions`/`audit_logs`/`cameras` and ends
  at `0002_cameras`; **no new migration/table**.
- Live throwaway PostgreSQL cluster (127.0.0.1:55432): `alembic upgrade head` OK,
  `alembic current` = `0002_cameras (head)`, `alembic check` = **"No new upgrade operations
  detected"**; cluster stopped and removed.

### Verification limitations (honest reporting)
- **The Phase 4 YOLO detector is person-only.** Door state, package classes, and pose are
  explicit input interfaces with **no producer** in the current pipeline. The door,
  package, and fall rules are unit-tested with synthetic inputs but are **not end-to-end
  capable**; do not claim those detections work from live video.
- EV-01/EV-02 (entry/exit), EV-03 (occupancy/crowd), and EV-06 (motionless) can run on
  person tracks, but were verified with synthetic tracks/frames, not labelled real
  footage. Motionlessness uses bounding-box anchor displacement, not pose. Detection
  quality/precision/recall remains Phase 9 work.
- The entry/exit and occupancy rules depend on the tracker's coordinate space matching the
  prepared frame dimensions; the worker uses the prepared image shape. A future detector
  that resizes internally must preserve that contract.
- Persistence, authenticated event handoff, evidence, and message storage are **not**
  implemented (Phase 6). Production uses `NullEventSink`; transitions are dropped after
  in-memory publication.
- No WebSocket, dashboard, live view, review workflow, or retention policy exists yet.
- Multi-camera process isolation remains Phase 8; the engine state is per camera but the
  default runtime limit is one camera.

### Unresolved questions, assumptions, blockers, next task
- **OQ-04 remains partially open:** the door-state consumer contract is fixed, but the
  producer (classifier vs. geometric heuristic) is undecided/unimplemented.
- **Assumption:** all threshold defaults are tunable proposals except the source-stated
  60 s door, 30–60 s package (45 s chosen), and 120 s motionless values. They need
  evaluation on real footage (Phase 9).
- **Blocker for end-to-end EV-04/EV-05/EV-07:** no door-state, package-class, or pose
  producer exists. The rules are implemented and unit-tested but stay inactive on the
  current person-only detector.
- **Next task:** Phase 6 (persistence and evidence). Do not start it here.

## Phase 4 — One-camera vision pipeline (complete, verified)

**Scope delivered:** independent vision-worker runtime, per-camera lifecycle with bounded
reconnect, connection-time SSRF enforcement, bounded ingestion/sampling, pretrained YOLO
detector and per-camera ByteTrack, metrics, and an authenticated worker↔backend health
channel. **Not in scope / not started:** temporal event rules, evidence capture, pose,
WebSocket/dashboard, live-view gateway (Phases 5–8).

### Files created
- `vision/__init__.py`, `vision/runtime.py` — `python -m vision.runtime` entry point
  (signal handlers, startup reconcile, supervisor run, clean shutdown).
- `vision/config.py` — `VisionSettings` (`VISION_*`), `StreamHostMode`, `TrackerKind`;
  reuses `app.config` for the internal token and stream policy.
- `vision/net.py` — connection-time SSRF: `resolve_and_validate`, `PinnedTarget`,
  `StreamSecurityError` (D-28).
- `vision/health.py` — machine-readable detail codes (non-sensitive).
- `vision/metrics.py` — `StreamMetrics` (FPS/latency/counters).
- `vision/buffer.py` — bounded rolling frame buffer (FR-35 skeleton).
- `vision/internal_client.py` — worker→backend internal HTTP (stdlib `urllib`,
  injectable transport, bounded retries).
- `vision/supervisor.py` — plan polling + reconcile loop.
- `vision/ingestion/{__init__,queue,sources,prepare}.py` — bounded queue, OpenCV frame
  source, validation/sampling.
- `vision/detection/{__init__,detector}.py` — `YoloDetector`, `NullDetector`, `Detection`.
- `vision/tracking/{__init__,tracker}.py` — `ByteTrackTracker`, `IoUTracker`.
- `vision/camera_manager/{__init__,worker,manager}.py` — `CameraWorker` lifecycle,
  `CameraManager` ownership/concurrency/shutdown.
- `vision/pytest.ini`, `vision/tests/` (13 test modules + `fakes.py` + `conftest.py`).
- `backend/app/services/worker_registry.py` — in-memory worker-health registry.
- `backend/app/auth/internal.py` — constant-time `X-Internal-Token` dependency.
- `backend/app/schemas/internal.py`, `backend/app/api/routes/internal.py` — internal API.
- `backend/tests/test_internal_api.py`, `backend/tests/test_worker_registry.py`.

### Files changed
- `backend/app/config.py` — `worker_heartbeat_timeout_seconds` (default 15).
- `backend/app/api/router.py` — mounts the internal router (excluded from OpenAPI).
- `backend/app/api/routes/health.py` — camera health uses the projected status.
- `backend/app/services/monitoring_service.py` — `effective_status` projection +
  `monitoring_snapshot`.
- `backend/app/services/__init__.py`, `backend/app/__init__.py` — exports; version 0.4.0.
- `backend/tests/conftest.py` — reset the worker registry per test.
- `backend/pyproject.toml` — optional `[project.optional-dependencies] vision` extra.

### Endpoints (internal only)
- `GET /api/internal/cameras` — runtime plan (monitoring state + cameras) for the worker.
- `POST /api/internal/cameras/{id}/state` — state report; `applied=false` when unchanged;
  HTTP 409 + `current_status` for illegal transitions.
- `POST /api/internal/reconcile` — startup reset of stale processing cameras.
All require `X-Internal-Token`, are excluded from the OpenAPI schema, and do not accept
the browser session cookie.

### Lifecycle implemented
- `connecting → active` only after a real decodable frame is processed; `degraded` on
  sustained drops; `disconnected → reconnecting → connecting` with capped exponential
  backoff; terminal `failed` for insecure/unresolvable targets, detector-load failure, and
  exhausted reconnects; `stopped` on stop/shutdown with source + model release.
- Tracker reset on every new connection (FR-08); one tracker per camera (no cross-camera
  re-ID).

### Security controls implemented
- Connection-time SSRF (D-28): scheme allow-list, embedded credentials rejected, **every**
  resolved address validated (fail closed), validated IP literal pinned into the decoder
  URL so DNS rebinding cannot redirect the socket; no redirects/alternate handlers; no
  generic URL-fetch endpoint.
- Internal channel: constant-time token compare, no cookie access, non-sensitive payloads,
  excluded from OpenAPI. No stream reference or credential is logged.

### Commands run and results (actually executed)
- `cd backend && ./.venv/bin/python -m pytest` — **180 passed** (5.99s).
- `python -m pytest vision/tests` (repo root, `backend/.venv/bin/python`) — **130 passed,
  1 skipped**, 1 warning (skip = opt-in real-weights test; warning = `supervision`
  `ByteTrack` deprecation FutureWarning).
- `VISION_TEST_WEIGHTS=1 python -m pytest vision/tests/test_integration_pipeline.py::test_real_yolo_loads_and_runs`
  — **passed** (downloaded `yolo11n.pt`; weights then deleted; `*.pt` git-ignored).
- `cd backend && ruff check .` — All checks passed; `ruff format --check .` — 65 files
  already formatted.
- `ruff check --config backend/pyproject.toml vision` + `ruff format --check` — All checks
  passed; 36 files formatted.
- `alembic upgrade head --sql` — renders `users`/`sessions`/`audit_logs`/`cameras` + indexes
  (no schema change in Phase 4).
- Live throwaway PostgreSQL cluster on `127.0.0.1:55432`: `alembic upgrade head` OK,
  `alembic current` = `0002_cameras (head)`, `alembic check` = "No new upgrade operations
  detected", `alembic downgrade base` OK; cluster stopped and removed.

### Verification limitations (honest reporting)
- **No live/authorised RTSP camera was tested.** Ingestion was verified with a locally
  generated synthetic MJPG/AVI clip through the real OpenCV decoder and the full worker
  path; the RTSP path shares that source/decoder boundary but was not exercised.
- **Detector→ByteTrack on real person imagery was not verified** (no offline person
  fixture). Real YOLO weight load + one inference on a blank frame was verified opt-in;
  ByteTrack was verified with the real `supervision` library on synthetic detections; the
  end-to-end clip pipeline used `NullDetector` + `IoUTracker`.
- **RAM/GPU metrics and soak testing are not done** (Phase 9); FPS/latency/queue/drop
  counters are implemented and unit-tested.
- Process-per-camera isolation and multi-camera scaling remain Phase 8.
- Docker Compose is still unavailable to this user; migrations were verified against a
  private local PostgreSQL cluster instead.
- `supervision` is pinned `<0.31` because 0.31 removed the bundled `ByteTrack`; the
  installed `ByteTrack` emits a deprecation warning (works in 0.30).

## Phase 3 — Camera configuration and monitoring lifecycle (complete, verified)

### Files created
- `backend/app/models/camera.py` — `Camera` ORM model (`name` unique, `stream_reference`,
  `enabled`, `status`, `configuration` JSON, timestamps) and `CameraStatus` `StrEnum`
  (configured/connecting/active/degraded/disconnected/reconnecting/stopped/failed).
- `backend/app/services/stream_validation.py` — SSRF/address policy:
  `validate_stream_reference`, `is_disallowed_address`, `redact_stream_reference`,
  `default_resolver`, metadata address/hostname denylists, `StreamValidationError`.
- `backend/app/services/lifecycle.py` — `LEGAL_TRANSITIONS`, `PROCESSING_STATES`,
  `STARTABLE_STATES`, `can_transition`, `transition`, `coerce_status`,
  `InvalidStateTransition`.
- `backend/app/services/camera_service.py` — create/update/read conversion, uniqueness and
  validation, redacted responses (`CameraNameConflict`, `CameraNotFound`,
  `InvalidStreamReference`).
- `backend/app/services/monitoring_service.py` — thread-safe `MonitoringController`
  (stopped/running/paused), `start/pause/stop_monitoring`, `monitoring_snapshot`,
  `reset_monitoring_controller`.
- `backend/app/schemas/camera.py`, `backend/app/schemas/monitoring.py`; rewrote
  `backend/app/schemas/health.py` (non-sensitive `CameraHealthItem` + `by_status`).
- `backend/app/repositories/cameras.py` — parameterised CRUD/status helpers.
- `backend/app/api/routes/cameras.py`, `backend/app/api/routes/monitoring.py`.
- `backend/migrations/versions/0002_cameras.py` — `cameras` table + unique name index +
  status index (down_revision `0001_initial_auth`).
- Tests: `backend/tests/test_stream_validation.py`, `test_lifecycle.py`,
  `test_camera_api.py`, `test_monitoring_api.py`.

### Files changed
- `backend/app/config.py` — `camera_allowed_stream_schemes` (default `rtsp,rtsps`),
  `camera_allow_private_networks` (default true), `camera_resolve_stream_hostnames`
  (default false), a scheme-list validator, and the `allowed_stream_schemes` property.
- `backend/app/auth/dependencies.py` — added `get_csrf_auth_context` (auth + CSRF).
- `backend/app/api/router.py`, `backend/app/api/routes/health.py` — registered the new
  routers and populated `/api/health/cameras` with non-sensitive lifecycle data.
- `backend/app/models/__init__.py`, `schemas/__init__.py`, `repositories/__init__.py`,
  `services/__init__.py` — exports updated.
- `backend/app/__init__.py` — version `0.3.0`.
- `backend/tests/conftest.py` — monitoring-controller reset per test; new `auth_client`
  and `csrf_headers` fixtures.
- `backend/tests/test_models.py`, `test_health_api.py` — `cameras` table/constraints and
  the updated health response shape.
- `docs/DECISIONS.md` (D-21–D-26), `docs/ARCHITECTURE.md` §3.3/§3.14/§7/§8,
  `docs/REQUIREMENTS_TRACEABILITY.md`, `docs/OPEN_QUESTIONS.md` (OQ-14),
  `docs/IMPLEMENTATION_PLAN.md` (Phase 3 status), `README.md`, `.env.example`.

### Endpoints
- `GET /api/cameras` — authenticated; lists cameras with a **redacted** stream reference.
- `POST /api/cameras` — authenticated + CSRF; creates a camera (422 on invalid/unsafe
  reference, 409 on duplicate name).
- `GET /api/cameras/{id}` — authenticated; 404 when unknown.
- `PATCH /api/cameras/{id}` — authenticated + CSRF; partial update; disabling a processing
  camera moves it to `stopped`; 404/409/422 as appropriate. **No DELETE endpoint** (W §10).
- `POST /api/monitoring/start|pause|stop` — authenticated + CSRF; control the runtime; 409
  on an illegal monitoring transition (e.g. pause while stopped).
- `GET /api/monitoring/status` — authenticated; global state + per-camera lifecycle state.
- `GET /api/health/cameras` — unauthenticated but non-sensitive (count, `by_status`,
  per-camera `{id, status}` only).

### Lifecycle transitions implemented
- Per camera (`LEGAL_TRANSITIONS`): `configured → {connecting, stopped, failed}`;
  `connecting → {active, disconnected, failed, stopped}`;
  `active → {degraded, disconnected, reconnecting, stopped, failed}`;
  `degraded → {active, disconnected, reconnecting, stopped, failed}`;
  `disconnected → {reconnecting, connecting, stopped, failed}` (no direct `→ active`);
  `reconnecting → {connecting, active, disconnected, stopped, failed}`;
  `stopped → {connecting, configured}`; `failed → {connecting, stopped}`.
- Monitoring: `stopped → running` (start), `running → paused` (pause; 409 otherwise),
  `{running, paused} → stopped` (stop). Phase 3 `start` moves enabled
  configured/stopped cameras to `connecting` only — **never `active`**.

### Security controls implemented
- Stream references are treated as untrusted: scheme allow-list, embedded-credential
  rejection, and rejection of loopback/link-local/multicast/reserved/unspecified and cloud
  metadata addresses (IPv4 + IPv6, including IPv4-mapped forms) and metadata hostnames.
- Responses never echo credentials: stream references are redacted to
  scheme/host/port/path (userinfo, query, fragment removed); audit records store action +
  field names only.
- All camera/monitoring endpoints require authentication; writes require a valid CSRF
  token, reusing the Phase 2 dependency unchanged. No existing control was weakened.
- `/api/health/cameras` remains unauthenticated but exposes only ids and lifecycle states.

### Commands run and results (actually executed)
- `./.venv/bin/python -m pytest` — **162 passed** (5.0s), up from 65 in Phase 2.
- `./.venv/bin/ruff check .` — **All checks passed**; `ruff format --check .` — **59 files
  already formatted**.
- `alembic upgrade head --sql` (offline DDL) — renders `cameras` (columns, `ix_cameras_name`
  unique index, `ix_cameras_status` index) after the Phase 2 tables.
- **Live PostgreSQL verification** (private throwaway cluster via `initdb`/`pg_ctl` on
  `127.0.0.1:55432`, since Compose is unavailable): `alembic upgrade head` created the four
  tables; `alembic current` = `0002_cameras (head)`; `alembic check` reported **"No new
  upgrade operations detected"**; `alembic downgrade base` dropped the tables cleanly. Live
  smoke test exercised the real services against PostgreSQL: create camera (stored the full
  query-string reference, response redacted), start monitoring → `connecting`, status
  counts, stop → `stopped`. Cluster stopped and deleted after the check.

### Verification limitations (honest reporting)
- The project's `docker compose up -d db` path remains unexercised (`docker compose` plugin
  missing, no `docker-compose`, Docker socket inaccessible); migrations were verified
  against a private local PostgreSQL 18.6 cluster instead.
- **SSRF validation is configuration-time only.** Hostname resolution is disabled by default
  and no connection is opened to validate a URL. DNS rebinding and redirect-based bypasses
  are therefore **not** defeated in Phase 3; authoritative connection-time enforcement
  (resolve → verify every address → pin → refuse redirects) is a Phase 4 worker requirement
  (D-22, OQ-14, SEC-06). Stated as a limitation rather than claimed as comprehensive.
- Disconnection detection, bounded recovery, and per-camera FPS/latency metrics (FR-04,
  NFR-06) are **not** implemented; only static lifecycle-state reporting exists.

## Phase 2 — Backend foundation, database, and authentication (complete, verified)

### Files created
- `backend/app/db.py` — lazy SQLAlchemy engine/session factory; `get_db` dependency;
  `dispose_engine()` on shutdown.
- `backend/app/utils.py` — UTC helpers (`utcnow`, `ensure_utc`) handling SQLite's naive
  datetimes.
- `backend/app/main.py` — FastAPI app factory, logging setup, lifespan (disposes engine).
- `backend/app/cli.py` — `create-admin` command (`chronovision-admin` / `python -m
  app.cli`); password via stdin/env/prompt, never a CLI argument.
- `backend/app/models/{base,user,auth_session,audit_log,__init__}.py` — `users`,
  `sessions`, `audit_logs` ORM models.
- `backend/app/schemas/{__init__,user,auth,health}.py` — Pydantic request/response models.
- `backend/app/repositories/{__init__,users,sessions,audit}.py` — parameterised DB helpers.
- `backend/app/services/{__init__,auth_service,admin_service}.py` — auth/session logic and
  admin provisioning with validation.
- `backend/app/auth/{__init__,security,rate_limit,cookies,dependencies}.py` — Argon2id
  hashing, token helpers, in-process login limiter, cookie helpers, auth/CSRF deps.
- `backend/app/api/{__init__,errors,router}.py`,
  `backend/app/api/routes/{__init__,health,auth}.py` — routers and consistent error shape.
- `backend/alembic.ini`, `backend/migrations/{env.py,script.py.mako}`,
  `backend/migrations/versions/0001_initial_auth.py` — Alembic setup reading the DB URL
  from validated settings (no credentials committed).
- `backend/tests/{conftest,test_models,test_security,test_rate_limit,test_health_api,
  test_auth_api,test_admin_service}.py`.

### Files changed
- `backend/app/config.py` — added `SameSite` enum and cookie/CSRF/rate-limit/password
  settings plus a `SameSite=None` => `secure=True` validator (existing validation intact).
- `backend/app/__init__.py` — version `0.2.0`; module boundaries documented.
- `backend/pyproject.toml` — added FastAPI, uvicorn, SQLAlchemy, Alembic, psycopg,
  argon2-cffi, httpx (dev); `[project.scripts] chronovision-admin`; Ruff `B008` ignored
  (FastAPI `Depends` pattern).
- `docs/DECISIONS.md` — decisions D-15 to D-20.
- `docs/ARCHITECTURE.md` — source layout and Phase 2 process note.

### Endpoints
- `GET /api/health` — unauthenticated; `ok`/`degraded` (DB failure means `degraded`, HTTP 200).
- `GET /api/health/cameras` — unauthenticated; empty until Phase 3.
- `POST /api/auth/login` — sets HttpOnly session cookie + readable CSRF cookie; 401 on bad
  credentials; 429 (+`Retry-After`) when rate-limited.
- `POST /api/auth/logout` — requires `X-CSRF-Token`; revokes the session; clears cookies.
- `GET /api/auth/me` — returns the authenticated user; 401 otherwise.

### Security controls implemented
- Argon2id password hashing; only hashes stored, never plaintext.
- Server-side sessions storing only SHA-256 hashes of session and CSRF tokens.
- HttpOnly / SameSite (Lax) / configurable-Secure session cookie; session-bound CSRF via
  `X-CSRF-Token`; expiry + revocation; inactive users rejected.
- In-process fixed-window login rate limiting (5 / 300 s) returning 429.
- `audit_logs` records `login`, `login_failed`, `logout` without secrets.
- Parameterised ORM operations only; no secrets in health output or logs.

### Commands run and results (actually executed)
- `./.venv/bin/python -m pip install -e ".[dev]"` — succeeded.
- `python -m pytest` — **65 passed** (2.21s).
- `ruff check .` — **All checks passed**; `ruff format --check .` — **44 files already
  formatted**.
- `python -c "import app.main"` — imports without a live database; OpenAPI lists all five
  routes.
- `alembic upgrade head --sql` (offline DDL) — renders `users`, `sessions`, `audit_logs`.
- **Live PostgreSQL verification** (private throwaway cluster via `initdb`/`pg_ctl` on
  `127.0.0.1:55432`, since Compose is unavailable): `alembic upgrade head` created the
  three tables; `alembic check` reported **"No new upgrade operations detected"** (models
  match the migration); `alembic downgrade base` dropped them cleanly. Live smoke test:
  CLI created admin (id=1); login 401 for wrong password, 200 for correct; `/me` 200;
  logout 200; `/me` 401 afterwards. DB inspection confirmed `$argon2id$...` hashes, hashed
  session/CSRF tokens with `revoked_at` set, and audit rows (`login_failed`, `login`,
  `logout`). Cluster stopped and deleted after the check.
- `git status` / ignore check — no secrets, venv, DB, or runtime data would be committed.

### Verification limitations (honest reporting)
- The project's own `docker compose up -d db` path was **not** exercised: `docker compose`
  is not installed, there is no `docker-compose`, and the Docker socket is inaccessible
  (`permission denied`). The live migration was instead verified against a private local
  PostgreSQL 18.6 cluster started with `initdb`/`pg_ctl`; results above are real but were
  produced on that cluster rather than a Compose-managed `postgres:16-alpine`.

## Implementation Log
- 2026-10-29 (Phase 0): planning documents created; decisions OQ-01/02/06/09 resolved.
- 2026-10-29 (Phase 1): repository foundation, compose, gitignore, env example,
  backend package + validated config; 16 config tests pass; ruff clean.
  No application features implemented.
- 2026-10-29 (Phase 2): FastAPI foundation, SQLAlchemy models + Alembic migration for
  `users`/`sessions`/`audit_logs`, Argon2id single-admin auth with server-side sessions,
  CSRF, login rate limiting, admin CLI, health/auth endpoints; 65 tests pass; ruff clean;
  live migration + login/logout verified against a throwaway local PostgreSQL cluster.
  No camera/vision/event/frontend work.
- 2026-10-29 (Phase 3): `cameras` model + `0002_cameras` migration; camera CRUD API;
  stream-address validation with SSRF defence (scheme allow-list, credential rejection,
  address/metadata denylists, redaction); per-camera lifecycle state machine; monitoring
  start/pause/stop/status control plane; non-sensitive camera health. 162 tests pass; ruff
  clean; offline + live migration verified and `alembic check` reports no drift. No video
  inference / worker / events / frontend.
- 2026-10-29 (Phase 4): independent `vision` worker runtime (`python -m vision.runtime`)
  with per-camera lifecycle, bounded reconnect, degraded signalling and terminal-failure
  policy; connection-time SSRF via IP-literal pinning (resolves OQ-14); bounded frame queue
  + sampling + validation + rolling buffer skeleton; lazy YOLO detector and per-camera
  ByteTrack (optional `vision` extra); StreamMetrics; authenticated internal worker-health
  channel + registry + read-time staleness projection. Backend **180 passed**, vision
  **130 passed / 1 skipped** (opt-in real weights), ruff clean, migrations unchanged and
  drift-free. No event rules, evidence, pose, dashboard, or MediaMTX. Phase 5 not started.
- 2026-10-29 (Phase 5): shared canonical event contract/lifecycle (`app/events/`), camera
  zone/threshold validation in camera configuration (HTTP 422), all eight canonical event
  types as per-camera temporal rules (`vision/event_engine/`), deterministic UUIDv5 ids and
  `state_version`, worker frame adaptation/reset/finalisation with per-rule error isolation,
  fixed deterministic message templates with sanitisation/fallbacks, and config validation
  tests. Backend **306 passed**, vision **189 passed / 1 skipped**, ruff clean; Alembic head
  unchanged at `0002_cameras`, offline + live `alembic check` show no drift. Door state,
  package classes, and pose have interfaces but no producers; persistence/evidence/handoff
  remain Phase 6. No LLM, dashboard, or WebSocket.
- 2026-10-29 (Phase 6): `events`/`event_transitions`/`evidence` models + `0003_events_evidence`
  migration; idempotent, stale-safe, terminal-immutable event persistence with the
  deterministic message rendered once at write time; bounded authenticated worker→backend
  handoff with an on-disk spool; off-loop snapshot/short-clip evidence capture under
  `EVIDENCE_DIR` with safe relative paths; authorized `GET /api/evidence/{id}` and read-only
  `GET /api/events[/{id}]`; retention + `prune-evidence` CLI (FR-42); FR-43 backup/restore
  verified with a live PostgreSQL round-trip. Backend **353 passed**, vision **257 passed /
  1 skipped**, ruff check/format clean; live `alembic upgrade head` → `0003_events_evidence`,
  `alembic check` no drift, clean `downgrade base`. Confirmed 2026-10-29: keep D-11 retention
  defaults but disable automatic retention-on-register (deletion only via CLI; D-43). Door/
  package/pose producers still absent; no live RTSP camera tested; dashboard/WebSocket/review
  remain Phase 7.

- 2026-10-30 (Phase 6 re-verification): independently re-ran the backend (**353 passed**) and
  vision (**257 passed / 1 skipped**) suites, backend + vision ruff (clean), offline migration
  render, and a live PostgreSQL round-trip (upgrade → `0003_events_evidence`, `alembic check`
  no drift, two-process persistence, FR-43 `pg_dump`/`pg_restore` + evidence-tree restore,
  `prune-evidence`, clean `downgrade base`). No code changes were needed; Phase 6 confirmed
  complete and verified. Phase 7 not started.
- 2026-10-30 (Phase 7): same-origin React 19 / TypeScript / Vite / MUI dashboard
  (`frontend/`) with login + protected routes, overview, camera management + monitoring
  controls, event timeline (filters/ordering/pagination), event details (stored deterministic
  message, transitions, authorized evidence viewer), and read-only settings. Backend
  extensions (smallest justified): `GET /api/settings`, authenticated `WS /api/ws` with a
  bounded in-process broadcaster (`event_broadcaster.py`), audited `PATCH /api/events/{id}`
  (`review_status`), audited `PATCH /api/evidence/{id}` (`protected`/`retained`), `review_status`
  and `order` filters on `GET /api/events`, shared `resolve_session()` for HTTP + WS auth, and
  version `0.7.0`. **No new migration** — reuses existing `events.review_status`,
  `evidence.retention_status`, and `audit_logs`; `alembic upgrade head --sql` still ends at
  `0003_events_evidence`. Evidence retained `EVIDENCE_RETENTION_ON_REGISTER=false` and the
  approved retention defaults; monitoring never auto-starts from a page/socket. Final
  verification also fixed a genuine `/api/ws` teardown defect (awaiting a cancelled task in
  `finally`; D-49) and added a repeated connect/close regression test. Backend **377 passed**
  (stable across 5+ consecutive full runs), vision **257 passed / 1 skipped**, backend ruff
  clean (**102 files**), vision ruff clean (**65 files**), frontend typecheck/lint
  (**0 problems**)/format/test (**27 passed**, 8 files)/build all pass. **Deferred
  (documented):** live video playback (no MediaMTX/WebRTC gateway; D-48) and Playwright E2E;
  door/package/pose producers and multi-camera isolation remain unimplemented. Decisions
  recorded as D-44–D-49; `EVIDENCE_RETENTION_ON_REGISTER=false`. No commit or push performed.
- 2026-10-30 (Phase 8): multiple cameras run as independent `CameraWorker` threads in one
  vision process (D-50); per-camera event-handoff spool isolation and a lost-wakeup fix that cut
  hand-off p50 ≈102 ms → ≈2 ms (D-51); optional bounded per-camera latency percentiles (D-52);
  configuration-change reconciliation restarts only the changed worker (D-53); and a reproducible
  synthetic benchmark harness `vision/benchmarks/` (`python -m vision.benchmarks`) that
  establishes the one-camera baseline and scales 1/2/4/8 cameras (D-54). New tests:
  `vision/tests/{test_multi_camera,test_reliability,test_benchmarks}.py`, per-camera spool +
  metrics + manager cases, and `backend/tests/test_multi_camera_isolation.py` (incl. monitoring
  across logout/WS disconnect, NFR-01). **Backend 385 passed; vision 284 passed / 1 skipped;
  backend ruff clean (103 files); vision ruff clean (71 files).** No migration (head stays
  `0003_events_evidence`). **Limitations:** thread isolation, not OS-process (a hard native fault
  would still take down the shared process); benchmark uses a simulated detector on a local clip
  (not detection accuracy) on a CPU-only host; no live RTSP camera tested. **OQ-12 resolved**
  (D-50). No commit or push performed.
- 2026-10-30 (Phase 9): testing, evaluation, and documentation. New `backend/app/evaluation/`
  (fixed matching rules; micro/macro precision/recall/F1, FP/FN, timing/occupancy error, false
  alarms per hour) with a hand-authored synthetic `evaluation/sample/` and CLI
  (`python -m app.evaluation`); exhaustive route-enumerated security verification
  (`test_security_verification.py`, no defect found); retention/backup-restore verification
  (`test_retention_verification.py`, `scripts/verify_backup_restore.sh`); extended benchmark
  harness (GPU availability, duplication rate, recovery time, `detector_mode`: D-58); new docs
  `docs/{TESTING,EVALUATION,OPERATIONS,KNOWN_LIMITATIONS}.md` and scripts
  `scripts/{verify,verify_migrations,verify_backup_restore}.sh` (D-59); and a `.gitignore`
  evidence-pattern fix to stop hiding the `vision/evidence/` source package (D-60).
  **Backend 456 passed; vision 286 passed / 1 skipped; frontend 27 passed**; ruff/format clean;
  `alembic check` no drift (head `0003_events_evidence`). No runtime LLM; deterministic messages
  unchanged; `EVIDENCE_RETENTION_ON_REGISTER=false`. No commit or push performed.
- 2026-10-31 (local run procedure): added `docs/RUNNING_LOCALLY.md` (copy-paste start/verify/stop
  runbook, camera registration, troubleshooting) and `scripts/{start_local.sh,stop_local.sh}`
  (preflight + health-wait + PID/log management, process-group shutdown) so the stack can be run
  by hand without Docker (D-61). Verified on this host against the **system** PostgreSQL 18.6
  cluster (`127.0.0.1:5432`, additive `chronovision` role/database only): restored the full stack
  (backend `127.0.0.1:8000`, vision worker, dashboard `127.0.0.1:5173`), `/api/health` = `ok`,
  anonymous `/api/cameras` = `401`, login/settings/monitoring = `200`, `monitoring=stopped`,
  0 cameras; start/stop cycle and idempotent re-run pass, Vite child reaped on stop. `.env`, the
  database, and `EVIDENCE_DIR` untouched. No code changes; no commit or push performed.
- 2026-11-01 (Phase 10): generic live camera playback over MediaMTX + WebRTC (WHEP) for any
  RTSP/RTSPS camera. New `app/services/{live_gateway,live_service,credential_cipher}.py` +
  `app/schemas/live.py`; `GET /api/cameras/{id}/live` and `POST /api/cameras/{id}/live/start` (CSRF);
  opt-in `LIVE_PLAYBACK_ENABLED` + `MEDIAMTX_API_URL`/`MEDIAMTX_WEBRTC_URL` with fail-fast config
  validation; backend-authoritative source-on-demand gateway paths (`<prefix>-cam-<id>`, default
  `cv`); SSRF-validated and IP-pinned gateway source; per-camera RTSP
  credentials Fernet-encrypted at rest (write-only; `SECRET_KEY` rotation invalidates) with migration
  `0004_camera_stream_credentials`; `cryptography` dependency; frontend `api/live.ts`,
  `LivePlayer`, `LivePlaybackDialog`, dialog launch + unavailable notice (D-62–D-65;
  `docs/LIVE_PLAYBACK.md`). **Backend 497 passed; vision 286 passed / 1 skipped; frontend 38 passed**;
  backend ruff clean (119 files); vision ruff clean (77 files); `./scripts/verify.sh` PASSED;
  `./scripts/verify_migrations.sh` PASSED with migration head `0004_camera_stream_credentials` and no
  drift. The real MediaMTX **v1.21.3** binary was run against the shipped config (Control API
  add/patch/delete, invalid-source rejection, WHEP `201 Created` → `DELETE` `200` against a local
  `ffmpeg` H.264 loop). **Limitations:** no real IP camera, no real browser WebRTC session, no Docker
  daemon (compose service unexercised), no TURN; live playback is off by default. **Verification
  fixes:** reformatted `tests/test_live_playback.py` and the six `vision/evidence/*.py` modules
  (trailing newline + 3 unused imports) that the old `evidence/` `.gitignore` pattern had hidden from
  ruff (D-60). No runtime LLM; deterministic messages, `EVIDENCE_RETENTION_ON_REGISTER=false`, and all
  auth/CSRF/SSRF/evidence-path controls unchanged. No commit or push performed.

- 2026-11-02 (local-only hardening + live-camera verification): fixed the `GET
  /api/cameras/{id}/live` **HTTP 500** and the indefinitely **stuck `connecting`** state, then
  verified the real camera path end to end on this host.
  - **500 root cause:** `LiveGateway.path_status` did `int(payload.get("readers", 0) or 0)`, but
    MediaMTX v1.21.x returns `readers` as an **array** → `TypeError` → 500. Now accepts a list
    (length) or a count (`app/services/live_gateway.py`).
  - **Stuck-`connecting` root cause:** `camera_service.to_read` returned the raw persisted
    `camera.status`, so a camera whose worker died mid-`connecting` stayed `connecting` forever
    even though `/api/monitoring/status` already projected `disconnected`. `to_read` now returns
    `monitoring_service.effective_status(camera)`, so the list and the monitoring snapshot agree.
  - **Refresh path:** `useCameras()` gained a 5 s `refetchInterval` (the dashboard previously never
    re-read the list), and `websockets>=13,<18` is now a declared backend dependency so `/api/ws`
    actually upgrades (it was inert without it; the handshake now returns "Not authenticated"
    instead of failing).
  - **Test isolation:** `backend/tests/conftest.py` disables `.env` loading for the whole suite, so
    a developer's locally enabled flags (e.g. `LIVE_PLAYBACK_ENABLED=true`) can no longer change
    test outcomes; `test_config.py` still uses `Settings(_env_file=None, ...)`.
  - **Unrelated defect found while verifying and fixed:** `OpenCVFrameSource.close()` released the
    `VideoCapture` while the capture thread was inside `cap.read()`, a use-after-free in FFmpeg that
    **segfaulted the whole vision process on every worker stop/reload** (confirmed by
    `faulthandler`). `open`/`read`/`close` are now mutually exclusive (D-67).
  - **Live verification (real phone camera `rtsp://192.168.12.224:8554/live`, 960×540 h264):** the
    real worker read **1110 frames / processed 143 in 40 s** (~28 fps ingest, ~3.6 fps processed)
    with 0 processing/decode errors and a clean `connecting → active → stopped` lifecycle and clean
    shutdown (exit 0). With a **temporary validated room zone** it emitted and **persisted** a real
    `room_occupancy_change` event (deterministic templated message; the schema was empty before, so
    this was the first real event) plus `snapshot` (107 KB) and `clip` (1.2 MB / 6.2 s) evidence
    rows and files; the test event/evidence and the temporary configuration were then **removed**
    and the camera configuration restored to `{}`. Live playback was re-verified through the real
    MediaMTX: WHEP `201 Created` → 960×540 media → `DELETE` `200` at `http://127.0.0.1:8889`.
  - **Localhost-first:** `.env` `MEDIAMTX_WEBRTC_URL` changed from the LAN IP to
    `http://127.0.0.1:8889`; the gateway Control API and RTSP ingest remain loopback-only
    (`127.0.0.1:9997` / `127.0.0.1:8555`), and Vite already binds `127.0.0.1:5173`. The gateway
    `webrtcAddress` stays on all interfaces (WebRTC needs a reachable ICE candidate; D-68).
  - **Results:** backend **500 passed** (497 + 3 new regression tests), vision **286 passed / 1
    skipped** (separate process), frontend **38 passed**, backend ruff clean (114 files), vision
    ruff clean (77 files). No runtime LLM; deterministic messages, `EVIDENCE_RETENTION_ON_REGISTER=false`,
    and all auth/CSRF/SSRF/internal-channel/evidence-path controls unchanged. No commit or push
    performed.

## Live-view rotation (frontend-only, 2026-11-02 — superseded by D-72)

**Goal.** A phone camera publishes a landscape RTSP frame whose scene is portrait, so the live
feed appears rotated 90°. An operator needs to straighten it "on the go".

**Approach (display-only, no engine change).** `frontend/src/lib/videoRotation.ts` adds pure
quarter-turn helpers (`normalizeRotation`, `rotateCW`/`rotateCCW`, `displayAspect`, `layoutVideo`)
plus per-camera `localStorage` persistence (`chronovision.liveRotation.<cameraId>`).
`LivePlayer` gained rotate-left / rotate-right icon buttons, a current-angle chip, and a Reset
action; the `<video>` is sized so the rotated frame is shown fully (letterboxed, never cropped or
distorted) using the container's measured size (shared `frontend/src/lib/useElementSize.ts`, also
used by `CameraPreview`). The rotation **never** reaches the server or the analysis pipeline, and
it is **not** applied to the zone-editor preview, because zones are stored against the analysed
frame (D-71).

**Files.** New: `frontend/src/lib/videoRotation.ts`, `frontend/src/lib/useElementSize.ts`,
`frontend/src/lib/videoRotation.test.ts`. Changed: `frontend/src/components/LivePlayer.tsx`,
`frontend/src/components/LivePlaybackDialog.tsx` (passes `cameraId`),
`frontend/src/wizard/CameraPreview.tsx` (uses the shared size hook).

**Commands run and results (actually executed).**
- `npm run typecheck` — clean.
- `npm run lint` — clean.
- `npm run format:check` — clean.
- `npm run test` — **103 passed** (16 files); previously 84 (15 files).
- `npm run build` — `tsc --noEmit` + `vite build` OK.

**Limitations.** No real browser was driven here (no browser automation); the rotated geometry is
covered by unit tests and a deterministic stubbed element size in jsdom, not a live WHEP session in
a real browser.

## Detection-time rotation for sideways cameras (D-72, 2026-11-02)

**Problem found.** The operator reported that detection was "not right" even though the zone was
drawn. Diagnosis on the live `rtsp://…:8554/live` feed (960×540): the scene is physically rotated
90° clockwise, and the raw sideways frames were being fed to YOLO11n. On 12 captured frames the
real detector found **0** people raw vs **23** on the same frames rotated 90° clockwise (a single
frame: 0 vs 2 at confidence 0.25). The configured `entrance-1` zone and its `inside_side="right"`
were verified correct (the room side is "inside"; the hallway is "outside"), so the geometry was
not the cause.

**Fix.** `configuration.rotation` is a per-camera setting (`0/90/180/270`, default 0), validated by
`app.events.zones.parse_rotation` (unsupported values are rejected, never ignored). The worker
reads it into `CameraWorker._rotation`; `vision/ingestion/rotation.py` rotates **only the detector
input** (`rotate_frame`) and maps every detected box back into the original frame
(`map_bbox_from_rotated`) before tracking. Zones, boundaries, the bottom-centre anchor, tracking and
all event rules keep operating in the original camera frame, so **no zone was redrawn**. The same
value drives the live player: `LivePlayer` is now controlled (`whepUrl`, `rotation`, `onRotate`) and
`LivePlaybackDialog` persists changes through the existing camera PATCH (reverting the shown value
and surfacing the error on failure). The old `localStorage` display-only preference was removed.

**Files.** New: `vision/ingestion/rotation.py`, `vision/tests/test_rotation.py`. Changed:
`vision/camera_manager/worker.py`, `vision/tests/test_worker.py`, `backend/app/events/zones.py`,
`backend/app/events/__init__.py`, `backend/tests/test_event_zones.py`,
`frontend/src/lib/videoRotation.ts` (+ tests), `frontend/src/components/LivePlayer.tsx` (+ tests),
`frontend/src/components/LivePlaybackDialog.tsx`, `frontend/src/pages/CamerasPage.tsx`.

**Applied to the live camera.** `cameras.configuration.rotation` was set to `90` for camera 1
through the database (dashboard credentials are not available to the agent; D-68 precedent). The
worker reconciled the change, restarted, and the camera returned to `active` with `rotation=90`.
`LivePlaybackDialog` is the normal way to change it from the dashboard.

**Commands run and results (actually executed).**
- Backend: `.venv/bin/python -m pytest -o addopts="" -q` — **511 passed** (was 500; +11 rotation
  validation tests).
- Vision: `python -m pytest -o addopts="" vision/tests -q` — **308 passed, 1 skipped** (was 286;
  +21 rotation tests, including a worker-level test that the detector sees the rotated frame and
  the tracker receives the box mapped back).
- Frontend: `npm run test` — **102 passed** (16 files); `npm run typecheck`, `npm run lint`,
  `npm run format:check` clean; `npm run build` OK.
- Ruff lint/format clean for the changed backend and vision files.

**Limitations.** Evidence snapshots/clips were still captured from the original (raw) frame at the
time of this change — **superseded on 2026-11-02 by D-74**, which writes recorded evidence in the
camera rotation. No real browser WebRTC session was exercised. Detection improvement was validated
on captured frames and the worker's unit/integration path, not by watching a live person cross the
boundary in a browser.

## Zone-editor preview rotation (D-73, 2026-11-02)

**Problem.** Configuring zones on the same sideways camera was awkward: the zone editor drew over the
un-rotated preview, so the operator had to place zones against a picture rotated 90° from what they
saw. D-72 had already introduced the per-camera setting `configuration.rotation`; the wizard simply
did not use it.

**Fix (frontend-only, no engine change).** `WizardState` gained a required `rotation: Rotation`
(default `0`). `convert.ts` seeds it from `configuration.rotation` and writes it back on save when it
is non-zero **or** when the original config already had the key — so an untouched empty config keeps
the exact `{ zones, event_rules }` shape, and an explicit reset to `0` clears a previously saved
value. `ZoneEditor` gained rotate-left / rotate-right / reset controls and a `View {n}°` indicator;
`CameraPreview` shows the live (or clearly-labelled placeholder) feed rotated using the shared
`displayAspect`/`layoutVideo`/`getContentRect` maths; `ZoneCanvas` forward-rotates stored points for
drawing (`toDisplayPoint` in `coordinates.ts`) and inverse-rotates pointer input (`fromDisplayPoint`),
so every coordinate reported to the wizard is in the **original camera frame**. Rotating the preview
therefore never requires redrawing zones and never desynchronises the drawing surface from detection:
the one stored value still drives live monitoring and the detector (D-72).

**Files.** Changed: `frontend/src/wizard/coordinates.ts` (+ tests),
`frontend/src/wizard/wizardTypes.ts`, `frontend/src/wizard/convert.ts` (+ tests),
`frontend/src/wizard/ZoneCanvas.tsx` (+ tests), `frontend/src/wizard/CameraPreview.tsx`,
`frontend/src/wizard/ZoneEditor.tsx` (+ tests), `frontend/src/wizard/ZoneSetupWizard.tsx` (+ tests).
New: `frontend/src/components/LivePlaybackDialog.test.tsx` (reads the saved rotation and persists
changes through the camera PATCH).

**Commands run and results (actually executed).**
- Frontend: `npm run test` — **114 passed** (17 files; was 102/16 before the wizard rotation work);
  `npm run typecheck`, `npm run lint`, `npm run format:check` clean; `npm run build` OK.
- Targeted: `npx vitest run src/wizard` — **55 passed** (5 files); `npx vitest run
  src/components/LivePlaybackDialog.test.tsx` — **2 passed**.
- Backend and vision were not changed by D-73, so their suites were not re-run for this change.

**Limitations.** Evidence snapshots remained in the original frame and stayed sideways at the time
of this change (superseded on 2026-11-02 by **D-74**, which writes recorded evidence in the camera
rotation). No real browser session was used to click the wizard rotate controls against a live
camera; the transforms are unit-tested and the wizard is component-tested with mocked APIs.

## Evidence rotation for sideways cameras (D-74, 2026-11-02)

**Problem.** With D-72 (detection) and D-73 (wizard preview) the live view and the setup surface
were upright, but recorded snapshots/clips were still captured from the raw frame and appeared
sideways in the event timeline — the last inconsistency of the sideways-camera problem.

**Fix (vision-only; no engine, schema or frontend change).** `EvidenceManager` takes an optional
`rotation` (normalised with `vision.ingestion.rotation.normalize_rotation`, default `0`). At encode
time on the dedicated encoder thread — never the frame loop — it applies `rotate_frame` to the
snapshot image and to each retained clip frame before handing them to the store, so the written
bytes are upright. `vision.runtime._build_coordinator` seeds it from `configuration.rotation`, the
same value `CameraWorker` uses for detection, so config-change reconciliation (D-53) picks up a new
rotation with the rest of the config. `rotation=0` is an exact passthrough (no OpenCV call), and
already-stored evidence keeps its original orientation because rotation is applied only to
newly-encoded bytes.

**Files.** Changed: `vision/evidence/manager.py`, `vision/runtime.py`,
`vision/tests/test_evidence_manager.py` (+1 test), `vision/tests/test_runtime.py` (+1 test),
`frontend/src/components/LivePlaybackDialog.tsx` (caption wording only).

**Commands run and results (actually executed).**
- Vision: `backend/.venv/bin/python -m pytest -o addopts="" vision/tests -q` — **310 passed,
  1 skipped** (was 308/1; +2 rotation tests: a 90° snapshot/clip is transposed, and the runtime
  forwards the camera rotation).
- Frontend: `npm run test` — **114 passed** (17 files); `typecheck`/`lint`/`format:check` clean
  (caption-only edit; D-73's wizard rotation tests remain green).
- Backend and vision ruff: clean (see the `verify.sh` sweep in the session report).

**Limitations.** Rotation is applied to newly-encoded evidence only, so evidence captured before
this change stays in its original orientation. Verified with unit tests (a 90° snapshot/clip is
transposed) and the runtime wiring test; the real camera's new evidence bytes were not re-checked
against a live event.

## Runtime detection regression: stale worker process (D-75, 2026-11-02)

**Symptom.** After D-72 was implemented, the operator reported that detection was still not working
at runtime (no tracks/events from a person in view), even though the unit/integration tests and the
captured-frame diagnosis passed.

**Root cause — a stale process, not the code.** The vision runtime had started at **16:00:47**,
before the D-72 rotation code existed (`vision/camera_manager/worker.py` and
`vision/ingestion/rotation.py`, 16:47). Python had already imported the pre-rotation `CameraWorker`,
so `configuration.rotation=90` was read into nothing and the sideways 960×540 feed reached YOLO11n
**unrotated**. Restarting the *worker object* (which the manager does on a config change) is not
enough — the module stays in memory. The backend had the same defect for a different file:
`app.events.zones.parse_rotation` was added at **16:48** while the backend started at **16:00:46**, so
a config save through the dashboard/wizard could have dropped the `rotation` key.

**Fix (operational; no source change).** Restart the affected processes so they load current code:
vision at 17:59 and the backend at 18:02, both via `scripts/start_local.sh --no-frontend
--no-mediamtx`. Because `monitoring_service` holds the monitoring flag **in memory** (by design), the
backend restart returned monitoring to `stopped`; the operator re-activated it from the dashboard and
camera 1 returned to `active`.

**Verified at runtime after the restart.**
- Live capture through the real `YoloDetector` (`yolo11n.pt`, conf 0.25, person-only): raw frame
  **0** persons vs **1** at 90° clockwise (conf 0.83 and 0.49 on two captures) — the rotated path the
  worker now uses finds the person the raw frame misses.
- Internal plan reports `configuration.rotation = 90`; camera 1 `status=active`.
- Real persisted events from the rotation-enabled worker: `person_entering` (18:00:48) and
  `person_leaving` (18:01:08), both in the `Entrance` zone — rotation **and** the box-mapping back
  into the original frame worked end to end.

**Caveat.** The phone's RTSP server (`rtsp://192.168.12.224:8554/live`) is intermittently slow to
open: the worker logged 30-second `could not open stream` timeouts before it connected and reported
`active`. That is a source-availability issue, not a detection failure.

## Handoff Prompt (for a new OpenCode session)
> Read `AGENTS.md`, then `docs/IMPLEMENTATION_PROGRESS.md` (*Current Phase* + the Phase 11 and
> Phase 10 sections), `docs/ARCHITECTURE.md`, `docs/DECISIONS.md` (D-62–D-74; D-62–D-65 are Phase 10,
> D-66–D-68 are the 2026-11-02 local-only fixes/verification, D-69 is the Phase 11 zone & event setup
> wizard, D-70 is the local MediaMTX install/lifecycle durability, D-71 is the superseded
> display-only live-view rotation, D-72 is the per-camera detection rotation, D-73 is the
> zone-editor preview rotation, D-74 is evidence rotation, D-75 records that a runtime code change
> needs a process restart and that a backend restart resets the in-memory monitoring flag), and
> `docs/LIVE_PLAYBACK.md`.
> Phases 1–11 are **complete and verified**; do not restart them. Key facts: live playback is
> **opt-in** (`LIVE_PLAYBACK_ENABLED=true` **and** both `MEDIAMTX_API_URL`/`MEDIAMTX_WEBRTC_URL`;
> setting a URL while disabled fails startup) and off by default; the backend is authoritative for
> one stable, source-on-demand gateway path per camera (`<MEDIAMTX_PATH_PREFIX>-cam-<camera_id>`,
> default `cv`); the gateway source is SSRF-validated and IP-pinned (plain RTSP) or validate-only
> (RTSPS, D-28 residual); per-camera RTSP credentials are Fernet-encrypted at rest and write-only
> (rotating `SECRET_KEY` invalidates them, D-64); migration head is
> `0004_camera_stream_credentials`. The browser receives only an opaque path + WHEP URL — never the
> camera source or credentials — and the viewing path is separate from the analysis worker, so a
> gateway outage degrades only live view.
> Verified: backend **511 passed**, vision **310 passed / 1 skipped**, frontend **114 passed** (17
> files); `./scripts/verify.sh` PASSED; `./scripts/verify_migrations.sh` PASSED (head `0004`, no
> drift). The
> real MediaMTX **v1.21.3** binary was exercised against `deploy/mediamtx.yml` (Control API + a WHEP
> `201 Created` → `DELETE` handshake with a local `ffmpeg` loop), but **no real IP camera and no real
> browser WebRTC session** were tested, and the compose `mediamtx` service was not run (no Docker
> daemon here) — do not claim them.
> 2026-11-02 update: a **real phone camera** (`rtsp://192.168.12.224:8554/live`, 960×540) was driven
> through the production worker on this host — 1110 frames received / 143 processed in 40 s, clean
> shutdown (after D-67), and a real `room_occupancy_change` event with snapshot+clip evidence was
> persisted end to end (test data since removed). WHEP was re-verified against MediaMTX at
> `http://127.0.0.1:8889`. `MEDIAMTX_WEBRTC_URL` is now `http://127.0.0.1:8889` (localhost-first);
> no real browser session or LAN browser was exercised — do not claim them.
> 2026-11-02 live-view durability: the gateway process had vanished (its `/tmp` binary was cleared),
> so live view was unavailable while `LIVE_PLAYBACK_ENABLED=true` was still set. MediaMTX v1.21.3 is
> now installed at `~/.local/bin/mediamtx` and `scripts/start_local.sh` starts it (only when the flag
> is true and a binary is found; `--no-mediamtx` opts out), `scripts/stop_local.sh` stops it, and
> `docs/LIVE_PLAYBACK.md` §2.2 documents the install (D-70). Re-verified: `live_service.start_playback`
> → `available=true/state=live`, the gateway pulled the real camera (H264 + audio), and `ffmpeg` read
> the stream through `rtsp://127.0.0.1:8554/cv-cam-1`; still **no real browser WebRTC session**.
> 2026-11-02 runtime fix: detection was failing only because the running vision/backend processes
> predated the D-72/D-75 code — restart them after code changes. Restarting the backend resets the
> in-memory monitoring flag to `stopped`, so re-activate monitoring from the dashboard afterwards.
> Do not add a runtime LLM; do not weaken SSRF/auth/CSRF/internal-channel/evidence-path controls;
> keep `EVIDENCE_RETENTION_ON_REGISTER=false` and live playback off by default unless the user asks.
> Run the backend and vision suites as **separate** processes (mixing them causes spurious failures)
> plus the frontend suite and the migration drift check, and report actual results.
