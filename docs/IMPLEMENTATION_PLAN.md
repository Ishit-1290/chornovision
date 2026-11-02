# ChronoVision — Implementation Plan

**Status:** Proposed (Phase 0). Ordered phases, dependencies, deliverables, acceptance criteria.
**Date:** 2026-10-29
**Sources:** `AGENTS.md`, `../guidelines.md` (§18 milestones), `../workflow_requirements.md` (§13 milestones, §19 initial scope)
**Companions:** `docs/ARCHITECTURE.md`, `docs/REQUIREMENTS_TRACEABILITY.md`, `docs/OPEN_QUESTIONS.md`

This plan reconciles the two milestone lists in the source documents into a single
ordered sequence. The workflow document's milestones (`W` §13) are technology-oriented
and are the primary driver; the guidelines' milestones (`G` §18) are behaviour-oriented
and are folded in as acceptance criteria. Requirement IDs (e.g. FR-16, AC-05) refer to
`docs/REQUIREMENTS_TRACEABILITY.md`.

## Guiding rules

- One bounded feature group per phase; do not implement everything at once (CON-09).
- Build an early end-to-end vertical slice before completing every module in isolation
  (G §18, W §19).
- **One camera first**; benchmark before scaling (CON-08, NFR-13).
- Every phase ends with: tests actually run and reported, `git diff`/`git status`
  reviewed, `docs/IMPLEMENTATION_PROGRESS.md` updated, and consequential decisions
  recorded in `docs/DECISIONS.md` (A, "Definition of done").
- Blocking decisions must be resolved before dependent phases (see OQ refs).

---

## Phase 0 — Requirements verification and architecture planning *(this phase)*

**Status:** Complete pending user review.
**Goal:** Turn the source documents into traceable, testable plans before any code.

**Deliverables**
- `docs/REQUIREMENTS_TRACEABILITY.md` — requirement IDs, sources, phases, verification.
- `docs/ARCHITECTURE.md` — components, boundaries, data flow, deployment topology.
- `docs/IMPLEMENTATION_PLAN.md` — this document.
- `docs/OPEN_QUESTIONS.md` — unresolved questions and blocking status.
- Updated `docs/IMPLEMENTATION_PROGRESS.md` and `docs/DECISIONS.md`.

**Acceptance criteria**
- All seven activities are extracted with definitions, required logic, event types, and
  default thresholds where specified.
- Every requirement has an ID, a source reference, a phase, and a verification method.
- Conflicts (notably OQ-01, OQ-02) are recorded, not silently resolved.
- No application code, migrations, manifests, or scaffolding is created.

**Dependencies:** none.

---

## Phase 1 — Repository foundation and configuration

**Goal:** Establish the modular monorepo skeleton, config handling, secret hygiene, and
local service orchestration — without business features.

**Deliverables**
- Directory layout per `ARCHITECTURE.md` §7 (empty/placeholder module boundaries).
- `docker-compose.yml` for PostgreSQL (and MediaMTX when needed) with a persistent volume.
- `.gitignore` excluding secrets, `.env`, recordings, evidence, runtime logs,
  virtualenvs, DB files, caches (SEC-10).
- `.env.example` documenting required variables (no real secrets).
- Backend `pyproject.toml`, app config module that loads/validates configuration (NFR-09).
- `README.md` setup instructions skeleton.
- `docs/PROJECT_GUIDELINES.md` decision if required (OQ-08).

**Acceptance criteria**
- PostgreSQL starts via `docker compose up -d db` and accepts connections.
- Config loads from environment, validates required values, and fails clearly when
  missing (NFR-11 — no silent defaults for secrets).
- `git status` shows no secrets, evidence, or DB files staged.
- No application feature code beyond configuration/skeleton.

**Dependencies:** Phase 0. **Blocking questions:** none (OQ-08 is a documentation choice).

---

## Phase 2 — Backend foundation, database, and authentication

**Goal:** FastAPI + SQLAlchemy 2.x + Alembic foundation with secure single-admin auth,
per `W` §5, §6, §13 M2.

> **Status: complete (2026-10-29).** All deliverables implemented and verified; see
> `docs/IMPLEMENTATION_PROGRESS.md` (Phase 2) for commands and results. The Compose-based
> `docker compose up -d db` path was not available in this environment; the live migration
> was verified against a private local PostgreSQL cluster instead.

**Deliverables**
- FastAPI app with `/api/health` and `/api/health/cameras` (cameras endpoint may return
  empty until Phase 3).
- Initial models + Alembic migrations: `users`, `sessions`, `audit_logs` (and later
  `cameras`, `events`, `evidence`).
- Argon2id password hashing; server-side sessions (hashed tokens); HTTP-only/SameSite/
  Secure cookies; CSRF protection; login rate limiting; session expiry + revocation.
- Controlled admin creation command (SEC-12).
- Auth endpoints: `POST /api/auth/login`, `POST /api/auth/logout`, `GET /api/auth/me`.
- Auth tests and DB tests.

**Acceptance criteria**
- `alembic upgrade head` runs successfully against a fresh DB.
- Login succeeds with correct credentials; logout revokes the session.
- Unauthorized requests to protected endpoints are rejected (401/403).
- Session expiry and revocation behave correctly; expired/revoked sessions are rejected.
- Login attempts are rate-limited.
- No plaintext password or session token is stored or logged.
- Tests run and results reported (W §13 M2 completion criteria).

**Dependencies:** Phase 1. **Blocking questions:** none.

---

## Phase 3 — Camera configuration and monitoring lifecycle

**Goal:** Camera CRUD, per-camera lifecycle state machine, and explicit monitoring
start/pause/stop/status — still without video inference (W §10, G §5.1, §6).

> **Status: complete (2026-10-29).** All deliverables implemented and verified; see
> `docs/IMPLEMENTATION_PROGRESS.md` (Phase 3) for commands and results and
> `docs/DECISIONS.md` D-21–D-26 for the decisions. The Compose-based DB path was again
> unavailable; migrations were verified against a private local PostgreSQL cluster.
> **Documented limitation:** configuration-time SSRF validation is not authoritative
> across DNS rebinding/redirects; connection-time enforcement (resolve → verify every
> address → pin → refuse redirects) is carried into Phase 4 (D-22, OQ-14). Phase 3 `start`
> moves cameras to `connecting`, never `active`, because no processing worker exists yet.
> *Resolved in Phase 4 by D-28 (IP-literal pinning).*

**Deliverables**
- `cameras` model + migration; camera CRUD endpoints per W §10.
- Configuration validation and stream-address validation incl. SSRF defence (SEC-06).
- Per-camera lifecycle state machine (FR-03): configured, connecting, active, degraded,
  disconnected, reconnecting, stopped, failed.
- Monitoring endpoints controlling the **runtime**, not just the viewer (FR-47):
  `POST /api/monitoring/{start,pause,stop}`, `GET /api/monitoring/status`.
- Camera credentials stored server-side only; never returned by ordinary API responses.
- Health/state reporting for cameras (FR-04 partially).
- Unit tests for state transitions + API integration tests.

**Acceptance criteria**
- Cameras can be created, listed, fetched, and updated; responses never leak credentials.
- Invalid camera configuration and disallowed stream addresses are rejected.
- Monitoring status endpoints reflect explicit start/pause/stop and are observable.
- State transitions are unit-tested, including `disconnected` treated as distinct from
  "no activity" (FR-05).
- Tests run and results reported.

**Dependencies:** Phase 2. **Open questions (non-blocking):** camera/zone representation
is a detail here; zones are needed in EV-01/EV-03.

---

## Phase 4 — One-camera vision pipeline (vertical slice core)

> **Status: complete (2026-10-29).** All deliverables implemented and verified; see
> `docs/IMPLEMENTATION_PROGRESS.md` (Phase 4) for the exact commands/results and
> `docs/DECISIONS.md` D-27–D-33 for the decisions. Resolved OQ-14 with connection-time
> IP-literal pinning. Verified: real OpenCV decoding of a locally generated synthetic clip
> through the full worker path, real `supervision.ByteTrack` on synthetic detections, real
> YOLO weight load + one inference (opt-in test), 180 backend tests, 130 vision tests.
> **Not verified in this environment:** a live/authorised RTSP camera, and detector→ByteTrack
> on real person imagery (no offline person fixture). RAM/GPU metrics are deferred to
> Phase 9; this phase measures FPS/latency/queue/drop counters. Phase 5 is now complete
> (see the Phase 5 status block below).

**Goal:** Continuous per-camera processing of one camera with pretrained detection and
tracking, bounded buffers, and metrics (W §13 M3; G §4.1; NFR-01–NFR-06, NFR-13).

**Deliverables**
- Vision worker entry point (`vision/runtime`) with an **independent runtime** (FR-02).
- Camera/stream manager + frame ingestion with camera ID/timestamp tagging and bounded
  per-camera queue (FR-07, NFR-04).
- Frame preparation with configurable sampling policy (FR-09, FR-15, NFR-05).
- Pretrained YOLO person/object detector producing observations (FR-10, FR-11).
- ByteTrack per-camera tracking (FR-12, FR-13, FR-14).
- Prerecorded-clip input path first; then a live/RTSP input (W §4, §13 M3).
- Bounded rolling frame buffer skeleton (FR-35).
- Metrics: latency, FPS, RAM, GPU (NFR-06).
- Worker↔backend handoff per OQ-09 (at least a no-op/health channel in this phase).

**Acceptance criteria**
- Frames are processed continuously from a prerecorded clip and then a live source.
- Tracking persists across consecutive detections where possible.
- Memory usage remains bounded over a sustained run (no unbounded growth).
- Stream failures do not crash the whole application; a camera failure is isolated
  (FR-06 groundwork).
- Effective processed FPS and latency are measured and reported, distinct from the
  camera's input FPS (W §15).
- No video inference runs inside an HTTP handler.
- Tests run and results reported.

**Dependencies:** Phases 1–3. **Resolved questions:** OQ-09 → D-12 (handoff design),
OQ-06 → D-11 (buffer/limits structure), OQ-14 → D-28 (connection-time SSRF).
**Confirm:** one-camera scope (CON-08).

---

## Phase 5 — Temporal event engine and deterministic messages

**Goal:** Implement the seven activities as temporal rules with the full event lifecycle
and deterministic message templates — no runtime LLM (W §7, §8, §13 M4; FR-16–FR-34,
EV-01–EV-07).

**Sequencing within the phase** (earlier per recommended initial scope, W §19):
1. Entry/exit (`person_entered`/`person_left`) — EV-01, EV-02 (first vertical slice).
2. Occupancy/crowd — EV-03.
3. Door-open duration — EV-04.
4. Package unattended — EV-05.
5. Motionless — EV-06.
6. Potential fall — EV-07.

**Deliverables**
- Event lifecycle state machine: candidate/active/completed/uncertain/cancelled (FR-23),
  with creation/update/completion/cancellation and immediate complete for instantaneous
  events (FR-24).
- Dedup + temporal-consistency rules: persistence intervals, missed-detection tolerance,
  completion/cancellation conditions, new-occurrence rules (FR-17, FR-18, FR-19).
- Shared event contract fields and multi-timestamp semantics (FR-20, FR-25–FR-29).
- Pose-based features for EV-06/EV-07 (see `docs/ARCHITECTURE.md` §3.8).
- Seven deterministic message templates in `backend/app/event_messages/` with validation,
  sanitisation, fallbacks, and stored rendered message (FR-30–FR-34).
- Per-activity unit tests incl. ambiguous/challenging scenarios (G §16.1, W §15).
- Config for all thresholds, zones, and tolerances, versioned per run (NFR-09, FR-45).

**Acceptance criteria**
- Each of the seven activities emits the correct event type under its trigger conditions.
- Persistent events update over time and complete on observed end conditions (AC-06).
- Duplicate events are controlled by explicit temporal logic (AC-07, FR-17).
- A person already visible at stream start is not classified as entering; disappearing
  without a boundary crossing is not classified as leaving (EV-01/EV-02 semantics).
- Missing metadata yields safe template fallbacks; no external text-generation service
  is required (W §13 M4).
- Safety-relevant events (motionless, fall) are labelled conservatively and never as
  medical certainty (CON-10, NFR-07).
- Tests run and results reported.

**Dependencies:** Phase 4. **Resolved questions:** OQ-01 → D-09, OQ-02 → D-10.
**Open questions (non-blocking):** OQ-03/OQ-05 → resolved by D-35/D-36; OQ-04 → consumer
contract fixed (D-36/D-39), producer deferred.

> **Implementation status — COMPLETE (2026-10-29).** The Phase 5 status, exact files,
> commands, results, and limitations are recorded in `docs/IMPLEMENTATION_PROGRESS.md`
> (Phase 5) and decisions D-34–D-39. Summary: shared canonical contract and lifecycle in
> `backend/app/events/`; zones/thresholds and camera-config validation in
> `app/events/zones.py` + `camera_service`; all eight event types implemented in
> `vision/event_engine/rules/`; per-camera orchestration and error isolation in
> `vision/event_engine/engine.py`; worker frame adaptation/reset/finalisation; fixed
> deterministic templates and sanitisation in `backend/app/event_messages/`. Backend
> **306 passed**; vision **189 passed, 1 skipped**; ruff check/format clean; Alembic head
> remains `0002_cameras` with no schema change. **Honest limitation:** the Phase 4 YOLO
> detector is person-only, so door state, package classes, and pose are explicit interfaces
> without producers; EV-04/EV-05/EV-07 rules are unit-tested with synthetic inputs but are
> not end-to-end capable. Persistence/handoff/evidence remain Phase 6. Do not start Phase 6
> as part of this task.

---

## Phase 6 — Persistence and evidence

**Goal:** Persist events/history in PostgreSQL and capture/inspect evidence without
blocking the pipeline (W §13 M5; G §11; FR-35–FR-45).

**Deliverables**
- `events` and `evidence` models + migrations; event history + state transitions stored.
- Event persistence from the worker/backend handoff (FR-40) with camera attribution.
- Bounded rolling frame buffer finalised; snapshot + short-clip encoding on trigger
  (FR-36) via a separate evidence task (FR-37).
- Evidence files under `data/evidence/camera-<id>/YYYY/MM/DD/...`; relative paths in DB
  (FR-41); safe filenames; path-traversal prevention (FR-38).
- Authorized evidence endpoint `GET /api/evidence/{id}` that resolves paths inside the
  configured directory only (SEC-08).
- Retention/deletion policy + `retention_status` (FR-42); backup/restore procedure
  (FR-43).
- Failure handling: encoding failure leaves the event visible with explicit evidence
  status (FR-39).

**Acceptance criteria**
- Events persist across application restarts (W §13 M5).
- Evidence references remain valid; snapshots and clips are inspectable.
- Evidence access requires authorization; the directory is not publicly served; path
  traversal is rejected.
- Evidence processing does not block frame ingestion (measured).
- Storage growth is controlled by the retention policy.
- Recording/encoding failure and restart/recovery are tested.
- Tests run and results reported.

**Dependencies:** Phases 4–5. **Resolved questions:** OQ-06 → D-11,
OQ-09 → D-12. Confirm the retention/storage-cap defaults before shipping deletion.

> **Implementation status — COMPLETE (2026-10-29).** The Phase 6 status, exact files,
> commands, results, and limitations are recorded in `docs/IMPLEMENTATION_PROGRESS.md`
> (Phase 6) and decisions D-40–D-43. Summary: `events`/`event_transitions`/`evidence` models
> migrated by `0003_events_evidence`; idempotent, staleness-safe, terminal-immutable event
> persistence (`app/services/event_service.py`); bounded authenticated worker→backend handoff
> with disk spool (`vision/event_handoff.py`); off-loop snapshot/short-clip capture with safe
> relative paths (`vision/evidence/`); authorized `GET /api/evidence/{id}` and read-only
> `GET /api/events[/{id}]`; retention + `prune-evidence` CLI (FR-42); FR-43 backup/restore
> verified with a live PostgreSQL round-trip. Backend **353 passed**; vision **257 passed,
> 1 skipped**; ruff check/format clean; migration verified live (up + `alembic check` no
> drift + clean `downgrade base`). **Confirmed** (user, 2026-10-29): D-11 retention defaults
> stand (30 d / 25 GB / 5 s+5 s / 15 s rolling / oldest-first / protected never evicted) with
> automatic retention-on-registration **disabled** — deletion only via the explicit CLI.
> **Honest limitations:** the Phase 4 YOLO detector is person-only, so door/package/pose event
> rules have interfaces but no producer (EV-04/EV-05/EV-07 not end-to-end); no live RTSP camera
> was tested (fixtures/fakes only); multi-camera process isolation is Phase 8. Do not start
> Phase 7 as part of this task.

---

## Phase 7 — Web dashboard

**Goal:** React/TS/Vite/MUI dashboard with auth, overview, live view, event timeline and
details, real-time updates, and settings (W §13 M6, §11; FR-46–FR-54).

**Deliverables**
- Login + protected routes.
- Overview dashboard (camera counts, monitoring status, active/recent events, health).
- Camera monitoring page (list, live video, connection/monitoring status, zones, metrics).
- Event timeline (type, camera, timestamp, duration, confidence, status, message,
  evidence availability) with filter/sort/pagination.
- Event details (description = predefined message, timestamps, attributes, confidence,
  status, snapshot + clip, review status).
- WebSocket notifications for live updates (FR-48).
- Settings (camera, zone, thresholds, retention, monitoring behaviour) validated
  backend-side.
- Health/error states; frontend tests + Playwright E2E.
- Media gateway live playback (may slip to Phase 8 if pipeline stability first).

**Acceptance criteria**
- Login works end to end; protected routes redirect unauthenticated users.
- Camera and event data load from the backend; filtering/sorting/pagination work.
- New events appear without manual refresh (AC-10).
- Evidence access from the browser is authorized; dashboard failures do not stop the
  worker (W §13 M6).
- No LLM summary panel; the predefined message is the authoritative description
  (FR-50).
- Stream health is shown separately from "no events" (FR-52).
- Tests run and results reported.

**Dependencies:** Phases 2–6. **Open questions (non-blocking):** OQ-10 (review scope),
OQ-12 (multiple cameras shown vs. one).

> **Implementation status — COMPLETE (2026-10-30).** The Phase 7 status, exact files,
> commands, results, and limitations are recorded in `docs/IMPLEMENTATION_PROGRESS.md`
> (Phase 7) and decisions D-44–D-49. Summary: a React 19 / TypeScript / Vite / MUI dashboard
> (`frontend/`) with login + protected routes, overview, cameras, event timeline (filters,
> ordering, pagination), event detail (deterministic message, transitions, evidence viewer),
> read-only settings, and a same-origin session-cookie + CSRF model (D-44). The deferred human
> review is implemented as audited mutations: `PATCH /api/events/{id}` (`review_status`, D-45)
> and `PATCH /api/evidence/{id}` (`protected`/`retained`, D-46). Real-time updates use an
> authenticated `/api/ws` that only carries lightweight cache-invalidating notifications, with
> refetch-on-reconnect for missed updates (D-47). **Deliberately deferred (documented, not
> faked):** live video playback (no MediaMTX/WebRTC gateway; D-48 — **superseded by Phase 10**), and Playwright E2E
> (component/unit + backend integration tests were used instead). **Honest limitations:**
> unchanged person-only detector → door/package/pose rules have no producer (EV-04/EV-05/EV-07
> not end-to-end); no live RTSP camera was tested; the WebSocket fan-out is in-process
> (single uvicorn worker).

---

## Phase 8 — Multiple cameras and reliability

**Goal:** Independent camera runtimes, reconnection/degraded handling, per-camera health,
and benchmarking before scaling (W §13 M7; G §6, §14; FR-03–FR-06, FR-08, NFR-03).

**Deliverables**
- Independent per-camera runtimes with isolation (FR-06).
- Reconnection and degraded states (FR-04); tracking-reset/recovery policy so entry/exit
  is not inferred across downtime (FR-08).
- Per-camera health metrics and observability.
- Benchmarking of increasing camera counts; resolution/sampling tuning.
- Simultaneous event generation tests; verify monitoring survives browser logout (NFR-01).

**Acceptance criteria**
- Camera failures are isolated; unrelated cameras keep running (AC-04, FR-06).
- Events retain correct camera association.
- Resource usage stays within measured limits on the target hardware (NFR-15).
- Runtime behaviour is observable and recoverable; reconnection is explicit.
- Benchmarks reported; one-camera baseline established before scaling (NFR-13).
- Tests run and results reported.

**Dependencies:** Phases 4–7. **Open question (non-blocking):** OQ-12 (confirm
multi-camera is in initial acceptance vs. deferred — see AC-01 vs. NFR-13).

> **Implementation status — COMPLETE (2026-10-30).** The Phase 8 status, exact files,
> commands, results, and limitations are recorded in `docs/IMPLEMENTATION_PROGRESS.md`
> (Phase 8) and decisions D-50–D-54. Summary: multiple cameras run as independent
> `CameraWorker` threads in one vision process (D-50), each with its own tracker/engine/
> evidence/handoff and per-camera spool isolation (D-51); a configuration change restarts only
> the changed worker (D-53); per-camera latency percentiles are optional and bounded (D-52);
> and `vision/benchmarks/` (`python -m vision.benchmarks`) gives a reproducible synthetic
> benchmark (D-54). **Honest limitations:** isolation is thread-based, not OS-process-based
> (a hard native fault would still take down the shared process); the benchmark uses a
> simulated detector at a configured per-frame cost (not real-footage accuracy) and was run on
> a **CPU-only** host (no GPU); no real RTSP camera was tested. **OQ-12 resolved** (multi-camera
> is in initial acceptance; one-camera baseline established first).

---

## Phase 9 — Testing, evaluation, and documentation

**Goal:** Reproducible tests, measured detection/runtime metrics, honest limitations,
and setup/deployment docs (W §13 M8, §15; G §16, §17).

**Deliverables**
- Unit, DB/API integration, and browser/E2E test suites run reproducibly.
- Labelled evaluation set; per-activity precision, recall, F1, false-positive/negative
  counts, timing error, occupancy error; matching rules defined before scoring (G §16.2).
- Runtime metrics: FPS, end-to-end latency, multi-stream delay, resource use, recovery
  time, dropped-frame rate, duplication rate, stability over time (G §16.3, W §15).
- Security verification: auth boundaries, unauthorized media/API requests, logout-while-
  monitoring.
- Retention/backup-restore verification.
- Known limitations documented (AC-15); setup/deployment instructions (W §13 M8).
- Optional: academic demonstration walkthrough.

**Acceptance criteria**
- Tests are reproducible; another developer can set up and run the project (W §13 M8).
- Performance and detection quality are measured on representative footage (AC-14).
- Security requirements verified; known limitations documented.
- Results reported honestly; no unverified "real-time" claims (G §4.6).

**Dependencies:** All previous phases.

> **Phase 9 status — complete (2026-10-30).** Delivered: reproducible one-command verification
> (`scripts/verify.sh`) plus disposable-cluster migration-drift (`scripts/verify_migrations.sh`)
> and backup/restore (`scripts/verify_backup_restore.sh`) scripts; an offline labelled-evaluation
> package (`backend/app/evaluation/`, `python -m app.evaluation`) computing per-activity
> precision/recall/F1, FP/FN, timing error, and occupancy error under fixed, documented matching
> rules, with a clearly-**synthetic** sample dataset (no real accuracy claimed); an extended
> Phase 8 benchmark harness adding **GPU availability**, **duplication rate**, and **recovery
> time**; security verification (exhaustive 401/403 sweep, logout-while-monitoring, WS auth,
> internal channel, SSRF, evidence-path confinement); retention and backup/restore verification
> on disposable environments; and docs (`docs/TESTING.md`, `docs/EVALUATION.md`,
> `docs/OPERATIONS.md`, `docs/KNOWN_LIMITATIONS.md`). Decisions D-55…D-59. **Honest limits:** no
> labelled footage, no real RTSP camera, no GPU, no browser/E2E suite; door/package/pose rules
> still have no producer (`docs/KNOWN_LIMITATIONS.md`). OQ-07/OQ-08 resolved.

---

## Phase 10 — Generic live camera playback (MediaMTX + WebRTC)

**Goal:** Browser-compatible **live** camera view for any registered RTSP/RTSPS camera, kept
separate from the analysis pipeline, without exposing internal camera URLs or credentials
(FR-51, FR-54; G §13.2; W §2.5, §4).

**Deliverables**
- Opt-in MediaMTX + WebRTC (WHEP) gateway with a bounded, backend-authoritative Control-API client.
- One stable, source-on-demand gateway path per camera; re-registration on create/update and
  removal on disable.
- SSRF-hardened gateway source (resolve + validate every address + IP-pin for RTSP; validate-only
  for RTSPS).
- Per-camera RTSP credentials encrypted at rest and write-only through the API.
- Native `RTCPeerConnection` WHEP player plus an honest live/unavailable notice in the dashboard.

**Acceptance criteria**
- Live playback is opt-in (default off) and degrades **only** live view when the gateway is absent;
  monitoring, events, and evidence are unaffected.
- The browser receives only an opaque path + WHEP URL; no camera address, credentials, or session
  cookie is sent to the gateway.
- The UI never fabricates a feed; when playback is not configured it states that live view is
  unavailable.

**Dependencies:** Phases 3 (camera config/validation) and 7 (dashboard).

> **Phase 10 status — complete (2026-11-01).** Delivered: `app/services/{live_gateway,live_service,
> credential_cipher}.py` + `app/schemas/live.py`; `GET /api/cameras/{id}/live` and
> `POST /api/cameras/{id}/live/start` (CSRF); opt-in `LIVE_PLAYBACK_ENABLED` +
> `MEDIAMTX_API_URL`/`MEDIAMTX_WEBRTC_URL` with fail-fast config validation; migration
> `0004_camera_stream_credentials`; `cryptography` dependency; frontend `api/live.ts`, `LivePlayer`,
> `LivePlaybackDialog`; `deploy/mediamtx.yml` + compose `playback` profile; `docs/LIVE_PLAYBACK.md`.
> Decisions D-62–D-65; **OQ-13 superseded for live view** (the D-48 truthful fallback is retained
> when playback is off). Verified: backend **497 passed**, vision **286 passed / 1 skipped**,
> frontend **38 passed**; `scripts/verify.sh` PASSED; `scripts/verify_migrations.sh` PASSED (head
> `0004`, no drift); a real MediaMTX **v1.21.3** process exercised the Control API and a WHEP
> `201 Created` → `DELETE` `200` handshake against a local `ffmpeg` H.264 loop. **Honest limits:**
> no real IP camera, no real browser WebRTC session, no Docker daemon (compose service unexercised),
> no TURN.

---

## Dependency graph

```text
Phase 0 -> Phase 1 -> Phase 2 -> Phase 3 -> Phase 4 -> Phase 5 -> Phase 6 -> Phase 7
                                                     \                        /
                                                      -> Phase 8 (needs 4-7) <-
                                                                 |
                                                                 v
                                                            Phase 9 -> Phase 10
```

## Decision status summary

Resolved (see `docs/DECISIONS.md`):

| Question | Resolution | Decision |
|---|---|---|
| OQ-01 runtime LLM vs none | No runtime LLM; deterministic templates (conflict preserved) | D-09 |
| OQ-02 event-type identifiers | Lowercase `snake_case`; two occupancy types | D-10 |
| OQ-06 buffer/retention limits | Configurable; defaults are proposals | D-11 |
| OQ-09 worker↔backend handoff | Authenticated internal HTTP | D-12 |

Still open (non-blocking unless noted):

| Question | Affects |
|---|---|
| OQ-03 occupancy/crowd threshold | Phase 5 (EV-03) |
| OQ-04 door-state method | Phase 5 (EV-04) |
| OQ-05 bed/floor + fall criteria | Phase 5 (EV-07) |
| OQ-07 latency/throughput targets | ~~Phase 4/9~~ **Resolved → D-58** (measured via extended harness) |
| OQ-08 missing named docs | ~~documentation phases~~ **Resolved → D-59** (referenced/created) |
| OQ-10 human-review scope | Phase 7 |
| OQ-12 multi-camera acceptance timing | ~~Phase 7/8, AC-01~~ **Resolved → D-50** (initial acceptance; benchmarked first) |
| OQ-13 live-view timing | Phase 7/8 |

## Recommended first milestone (Phase 1 start)

Start with **Phase 1**, then **Phase 2**, then the **one-camera end-to-end vertical
slice**: Phase 3 → Phase 4 → entry/exit only in Phase 5 → Phase 6 snapshot evidence →
Phase 7 basic timeline. This matches `W` §19 (recommended initial scope) and gives an
early demonstrable slice before adding the remaining activities.
