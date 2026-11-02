# ChronoVision — Proposed Architecture

**Status:** Proposed (Phase 0), kept current per phase. Requires user confirmation where
marked. **Phases 1–6 are implemented** (foundation/config, backend+auth, cameras, vision
worker, temporal event engine, and event/evidence persistence); the per-section labels below
note what is implemented versus proposed. Frontend/streaming/review remain later phases.
**Date:** 2026-10-29
**Sources:** `AGENTS.md`, `../guidelines.md`, `../workflow_requirements.md`

This document describes the **proposed** component architecture, boundaries, data flow,
and deployment approach. Items are labelled:

- **[CONFIRMED]** — directly stated in the source documents.
- **[PROPOSED]** — a design choice made here to satisfy the sources; reversible and open to review.
- **[PENDING]** — depends on an unresolved decision (see `docs/OPEN_QUESTIONS.md`).

It does not restate every requirement; IDs refer to `docs/REQUIREMENTS_TRACEABILITY.md`.

---

## 1. Architectural principles

- **[CONFIRMED]** The vision pipeline is a system of independent per-camera background
  runtimes, never ordinary HTTP request handlers (NFR-02, CON-02).
- **[CONFIRMED]** Video analysis is independent of browser sessions; closing the dashboard
  does not stop monitoring (NFR-01, CON-07).
- **[CONFIRMED]** Detection is separated from temporal interpretation and from message
  generation. No runtime LLM (CON-01).
- **[CONFIRMED]** Configuration (thresholds, zones, sampling, evidence windows) is
  externalised and versioned (NFR-09).
- **[CONFIRMED]** Queues and rolling buffers are bounded (NFR-04).
- **[CONFIRMED]** The runtime must not depend on OpenCode/DeepSeek (CON-12).
- **[PROPOSED]** Keep the current single-machine deployment, but preserve clean module
  boundaries so the vision worker can later move to a dedicated host (W §1, §2.6).

---

## 2. Component view

```text
┌──────────────────────────────────────────────────────────────────────┐
│                            Browser                                     │
│  React + TypeScript + Vite + MUI dashboard                             │
│  - auth, overview, camera monitor, event timeline, event details,     │
│    settings                                                            │
│  - WebSocket client for live updates                                   │
│  - WebRTC-compatible player for live view                              │
└───────────────┬───────────────────────────────────────┬───────────────┘
                │ HTTPS REST + WebSocket                 │ WebRTC (live view)
                v                                        v
┌──────────────────────────────────────┐   ┌─────────────────────────────┐
│        FastAPI backend (Python)      │   │   Media gateway (MediaMTX)  │
│  - auth & sessions (Argon2id)         │   │   - ingests RTSP camera      │
│  - camera config & validation         │   │   - relays to WebRTC/JSON    │
│  - monitoring lifecycle               │   │   - hides internal creds     │
│  - event API + deterministic messages │   └──────────────┬──────────────┘
│  - evidence metadata & authorized     │                  │ RTSP
│    access                             │                  │
│  - WebSocket notifications            │                  │
│  - system health                      │                  │
└───────┬───────────────────────┬───────┘                  │
        │ SQLAlchemy            │ internal event handoff   │
        │ (sync/async)          │ internal event handoff   │
        v                       v                          │
┌───────────────┐   ┌──────────────────────────────────────┴──────────┐
│  PostgreSQL   │   │        Vision worker process (Python, GPU)         │
│  - users      │   │  Per-camera runtime (independent task/process):    │
│  - sessions   │   │   1. Camera/stream manager + state machine         │
│  - cameras    │   │   2. Frame ingestion (decode, timestamp, order)    │
│  - events     │   │   3. Frame preparation (resize/normalize/sample)   │
│  - evidence   │   │   4. Detection (YOLO person/object)                │
│  - audit_logs │   │   5. Tracking (ByteTrack, per-camera IDs)          │
│               │   │   6. Pose estimation (where required)              │
│               │   │   7. Temporal event engine (rules + lifecycle)     │
│               │   │   8. Evidence capture (bounded rolling buffer)     │
│               │   │   9. Event normalization + handoff                 │
│               │   │  10. Per-camera metrics/health                     │
└───────────────┘   └──────────────────────┬────────────────────────────┘
                                            │ writes
                                            v
                                  ┌───────────────────────┐
                                  │ Local filesystem       │
                                  │ data/evidence/...      │
                                  │ data/logs/             │
                                  │ data/backups/          │
                                  └───────────────────────┘
```

**[CONFIRMED]** Two video paths (W §4): an **analysis path** (camera → stream manager →
decoder → sampler → detector → tracker → event engine → persistence) and a **viewing
path** (camera/gateway → browser-compatible stream → React live view). They are separate
components; the analysis path runs without a browser.

---

## 3. Component responsibilities and boundaries

### 3.1 Frontend (React / TypeScript / Vite / MUI) — [CONFIRMED]
- Responsibilities: login/logout, protected routes, overview, camera listing + live view,
  monitoring controls, event timeline + filters, event details + evidence playback,
  camera health/status, camera & zone configuration, display of predefined messages.
- Boundaries: must not connect to PostgreSQL, hold camera credentials, or run CV
  (FR-50). Talks only to FastAPI (REST + WebSocket) and the media gateway for playback.
- **[PROPOSED]** TanStack Query for server state; React Router for navigation; a single
  WebSocket client module feeding a shared event store.

### 3.2 FastAPI backend (Python) — [CONFIRMED]
- Responsibilities: auth/authorization, camera configuration, monitoring lifecycle,
  event creation/retrieval, **deterministic message generation**, evidence metadata,
  DB transactions, WebSocket notifications, health reporting, config validation,
  retention/admin operations.
- Boundaries: no long-running video inference (NFR-02). Does not own the tracker or
  detector. Exposes REST + WebSocket per W §10.
- **[PROPOSED]** Layering: `api/` (routers) → `services/` (business logic incl. message
  rendering) → `repositories/` (SQLAlchemy 2.x) → `models/` (ORM) + `schemas/`
  (Pydantic). Auth in `auth/`. Templates in `event_messages/`.

### 3.3 Camera and stream manager — [CONFIRMED]
- Responsibilities: register/configure cameras; establish connections; start/stop
  processing; maintain camera IDs; monitor connection and frame-arrival; detect
  disconnections/stalls; bounded recovery; report failures (FR-01–FR-05).
- Owns the per-camera lifecycle state machine (G §6): configured, connecting, active,
  degraded, disconnected, reconnecting, stopped, failed.
- Boundary: a disconnected stream is a distinct state, not "no activity" (FR-05).
- **[PHASE 3 IMPLEMENTED — control plane only]** Configuration, validation, and the
  lifecycle state machine exist in the backend: `models/camera.py` (persisted config +
  `status`), `services/stream_validation.py` (SSRF/address policy, D-22),
  `services/lifecycle.py` (legal transitions; no direct `disconnected→active` edge),
  `services/camera_service.py` (CRUD + redaction), and `services/monitoring_service.py`
  (global start/pause/stop/status, D-24).
- **[PHASE 4 IMPLEMENTED]** The stream manager now lives in the independent worker
  (`vision/camera_manager/`). `CameraWorker` owns one camera end to end — connect,
  `connecting → active`, stall/disconnect detection, capped exponential reconnect,
  `degraded` on sustained frame drops, terminal `failed`, and clean `stopped` on
  stop/shutdown (FR-01–FR-06, D-27, D-31). A camera is reported `active` only after a real
  decodable frame was processed (D-24). Connection-time SSRF enforcement is
  `vision/net.py` (D-28).
- **[PHASE 8 IMPLEMENTED — multi-camera isolation]** Multiple cameras run as independent
  `CameraWorker` threads inside **one** vision process (`CameraManager`, `VISION_MAX_CONCURRENT_
  CAMERAS`). Each worker owns its capture thread, bounded frame queue, rolling buffer, tracker,
  `TemporalEventEngine`, evidence coordinator, and event handoff; nothing mutable is shared
  between cameras, so a failing or blocked camera affects only its own worker (FR-06, AC-04,
  D-50). A camera whose configuration changed is stopped and recreated so edited zones/rules
  take effect (D-53). OS-process-per-camera remains a documented **future option** (not
  implemented): a hard native fault (e.g. `SIGSEGV`/OOM in a decoder) would still take down
  the shared worker process.

### 3.4 Frame ingestion — [CONFIRMED]
- Receives frames; attaches camera ID + timestamp; preserves intra-stream ordering;
  handles invalid/delayed/missing frames explicitly (FR-07).
- **[PROPOSED]** Each camera has a bounded ingress queue; on overflow use the documented
  backpressure policy (drop-stale / adaptive sampling) with observable counters.
- **[PHASE 4 IMPLEMENTED]** `vision/ingestion/sources.py` is the only module that touches
  a decoder (`OpenCVFrameSource`, also used for prerecorded clips). It tags each frame with
  camera id, position, and monotonic/UTC arrival (`tag_frame`). A dedicated per-camera
  capture thread pushes sampled frames into a bounded `FrameQueue`
  (`VISION_QUEUE_MAXSIZE`, default 8) with an explicit drop policy (`drop_oldest` by
  default), so a slow detector can never grow memory without bound. Drops are counted and
  a sustained drop ratio reports `degraded` (D-33).

### 3.5 Frame preparation — [CONFIRMED]
- Resize, normalize, sample, and format-convert for downstream models without losing
  activity-relevant information (FR-09). Sampling policy is configuration and versioned.
- **[PHASE 4 IMPLEMENTED]** `vision/ingestion/prepare.py` provides `is_valid_frame`
  (rejects `None`, missing/degenerate shapes, non-numeric shapes), `SamplingPolicy`
  (target FPS from `VISION_PROCESS_TARGET_FPS`, default 5), and width-only resizing that
  preserves aspect ratio. Validity is checked in the worker loop before detection.

### 3.6 Detection — [CONFIRMED]
- Produces observations (people, packages/parcels, doors) with camera ID, timestamp,
  class, box/location, confidence, frame reference (FR-10). Must not emit temporal
  events (FR-11).
- **[CONFIRMED]** Initial model: pretrained YOLO detector (W §7). Fine-tuning only if
  evaluation shows the baseline is insufficient.
- **[PHASE 4 IMPLEMENTED]** `vision/detection/detector.py`: `YoloDetector` lazily imports
  Ultralytics, loads `VISION_DETECTOR_WEIGHTS` (default `yolo11n.pt`) on
  `VISION_DETECTOR_DEVICE` (default `cpu`), filters to the person class by default, and
  returns plain `Detection(class_id, class_name, confidence, bbox)` observations — it never
  emits events. `NullDetector` is the dependency-free test double. Models are loaded per
  worker and released on stop/failure (D-32).

### 3.7 Tracking — [CONFIRMED]
- Associates detections across frames within one camera; maintains track IDs; updates
  positions; tolerates temporary misses (FR-12). IDs are camera-scoped, not identities
  (FR-13); no silent merging on reacquisition (FR-14).
- **[CONFIRMED]** ByteTrack (W §7).
- **[PHASE 4 IMPLEMENTED]** `vision/tracking/tracker.py`: `ByteTrackTracker` wraps
  `supervision.ByteTrack` (lazy import) and converts detections to/from supervision's
  `Detections`; `IoUTracker` is a dependency-free fallback for tests. Trackers are
  **per camera only** (no cross-camera re-ID), and `reset()` is called on every new
  connection so no track survives a gap (FR-08, FR-14, D-31).

### 3.8 Pose estimation — [PROPOSED placement, CONFIRMED need]
- Needed for motionlessness and fall-from-bed (EV-06, EV-07). Pretrained YOLO-pose or
  MediaPipe Pose (W §7). Runs per camera; features feed the event engine.
- **[PHASE 5 LIMITATION]** No pose model is integrated yet. The event engine consumes an
  explicit `PoseObservation` input, so the potential-fall rule stays inactive without a
  producer and posture is never inferred from a person bounding box (D-39). Motionlessness
  in Phase 5 uses track-anchor displacement only, not pose.

### 3.9 Temporal event engine — [CONFIRMED, PHASE 5 IMPLEMENTED]
- `vision/event_engine/` maintains per-camera state per activity; evaluates triggers;
  creates/updates/completes/cancels events; prevents duplicates; updates
  confidence/uncertainty; handles missing observations; applies configured thresholds
  (FR-16–FR-24).
- Owns the event lifecycle state machine (candidate/active/completed/uncertain/cancelled)
  imported from the shared `app.events.lifecycle` module.
- Independent of anything downstream (messages, dashboard, evidence encoding). It has no
  decoder, detector, database, network, or HTTP dependency: the worker adapts detector and
  tracker output into an `EngineFrame`; rules return `EventTransition` objects, which the
  engine publishes to a non-blocking `EventSink` (`NullEventSink` by default in Phase 5).
- One rule object per activity type with the shared interface
  `observe(frame_observations) -> list[EventTransition]` and
  `on_stream_end(...) -> list[EventTransition]`. Rules are isolated: one rule raising is
  logged and skipped for that frame, never stopping the other rules or the camera loop.
- `reset()` runs on every new connection beside the tracker reset (FR-08), so no event is
  inferred across a stream gap and a person visible at stream start is never "entering".
- Identity is deterministic (UUIDv5 over camera/type/zone/track/start/per-camera sequence)
  and `state_version` increments per transition; every event carries `rule_version` and
  `config_version`. Times are UTC for persistence, monotonic for in-process durations.
- Zone/threshold configuration is per-camera `configuration` JSON, validated by
  `app.events.zones` before storage (HTTP 422 on malformed input) and again at engine
  build. Defaults are documented proposals (D-35/D-36).
- **Input availability (D-39):** Phase 4's YOLO detector is person-only. Door state,
  package classes, and pose are explicit optional inputs; rules requiring them are built
  only when their zone is configured and stay inactive until a producer exists. The engine
  never fabricates those observations. **No end-to-end door/package/fall detection is
  claimed in Phase 5.**
- **Implemented in Phase 6:** persistence, the bounded authenticated event handoff,
  evidence capture, and the authorized event/evidence read endpoints. **Still not
  implemented:** dashboard/WebSocket delivery and human review (Phases 7–8). See D-39–D-43.

### 3.10 Evidence manager — [CONFIRMED, PHASE 6 IMPLEMENTED]
- Maintains a bounded rolling frame buffer per camera; on trigger captures pre-event
  frames, trigger frame, and post-event frames; encodes a short clip; records source
  camera and time interval (FR-35–FR-38). Implemented in `vision/evidence/`: the manager
  keeps the pre-event window from the worker's bounded rolling buffer (FR-35), the store
  writes a snapshot and a short clip under `EVIDENCE_DIR` using safe relative paths
  (FR-38/FR-41), and an explicit `failed` record is produced on any capture error (FR-39).
- **Does not block the detection loop:** `EventSink.publish` on the frame thread only does
  bounded bookkeeping; encoding, disk writes, and network delivery happen on background
  threads with a bounded job queue (FR-37). Queue overflow records an explicit failure
  rather than growing without limit.
- **[RESOLVED OQ-06 → D-11, D-43]** All evidence limits are **configurable and versioned**:
  pre-event rolling buffer window, pre-event capture, post-event capture, clip duration,
  snapshot policy, retention period, storage cap, and eviction order. The 2026-10-29
  defaults were **confirmed**: 15 s buffer / 5 s pre / 5 s post / 5 s-FPS clip / 30-day
  retention / 25 GB cap / oldest-first. Deletion is **explicit only** — automatic
  retention-on-registration is disabled (`EVIDENCE_RETENTION_ON_REGISTER=false`), so
  retention runs via `prune-evidence` (FR-42).

### 3.11 Event normalization + persistence — [CONFIRMED, PHASE 6 IMPLEMENTED]
- Normalizes events to the shared contract (FR-25/26), persists events, updates, camera
  metadata, and history in PostgreSQL via SQLAlchemy/Alembic (FR-40);
  `backend/migrations/versions/0003_events_evidence.py` adds `events`,
  `event_transitions`, and `evidence`. Video stays on disk with relative paths in DB
  (FR-41).
- Preserves the distinction between event history and current ongoing state (FR-21): the
  `events` row holds current state, `event_transitions` holds immutable history.
- Persistence invariants (D-40): `event_id` is unique → idempotent upsert; a
  `state_version` that is not newer is a stale no-op; terminal states are immutable. The
  rendered deterministic message is stored once at write time and never regenerated.
- Review decisions **are** persisted (Phase 7, D-45): `PATCH /api/events/{id}` records
  `review_status` plus an audit row; the stored message, timestamps, lifecycle state, and
  confidence are never altered. Evidence pin/unpin is a separate audited mutation (D-46).

### 3.12 Deterministic message service — [CONFIRMED, PHASE 5+6 IMPLEMENTED]
- `backend/app/event_messages/` selects a template by `event_type`, interpolates
  validated metadata, sanitises untrusted values, applies safe fallbacks, and formats
  timestamps explicitly as UTC. Phase 6 renders the string **once at persistence time** and
  stores it on the event/transition rows (FR-30–FR-34); it is never regenerated when a
  template later changes (D-40).
- **No runtime LLM or external text-generation API** (CON-01/D-09). There is no prompt,
  network call, or model dependency in this package.
- Template keys use the canonical lowercase `snake_case` identifiers fixed in D-10.
  `room_occupancy_change` uses a distinct "Occupancy update ..." wording because W §8
  provides only one combined occupancy example; `crowd_forming` keeps the source
  "Occupancy threshold reached ..." wording (D-38).
- Sanitisation removes control characters and angle brackets, redacts `scheme://...` and
  `user:pass@` tokens, normalises Unicode, collapses whitespace, and bounds length.
  Missing/blank metadata falls back to `Unknown`, `Unknown zone`, `an unknown number of`,
  `an unknown time`, or `the bed area`.

### 3.13 Dashboard update service (WebSocket) — [CONFIRMED, PHASE 7 IMPLEMENTED]
- **[PHASE 7 IMPLEMENTED]** `GET`/`WS /api/ws` is authenticated with the same session cookie
  as the REST API (shared `resolve_session`); unauthenticated/revoked sessions get an `error`
  frame and close code 1008. `EventBroadcaster` fans out lightweight notifications (event,
  camera status, monitoring state, evidence retention) to bounded per-subscriber queues; a slow
  client drops its oldest item. Payloads never contain evidence bytes, stream references, or
  credentials — the browser re-reads authorized detail through REST and treats notifications as
  React Query cache invalidations (refetch-all on every reconnect for missed updates). Fan-out
  is in-process (single uvicorn worker; a shared bus would be required to scale out). Opening
  the page/socket never starts monitoring (D-47). The handler's cleanup path intentionally does
  not `await` (the send/receive tasks are cancelled and drained by a done-callback): an `await`
  in `finally` can surface a spurious `CancelledError` when the server cancels the handler during
  close, so teardown stays synchronous (D-49).
- Settings: authenticated read-only `GET /api/settings` exposes the effective non-sensitive
  evidence/retention policy plus current storage usage; policy mutation and deletion remain
  environment/CLI-controlled (D-48).

### 3.14 Monitoring / health — [CONFIRMED]
- Structured operational logs (separate from the user event timeline, NFR-10) and
  per-camera metrics (FPS, latency, queue depth, decode/encode failures).
- Health endpoints `GET /api/health`, `GET /api/health/cameras`.
- **[PHASE 3 IMPLEMENTED]** The monitoring **control plane** (`POST /api/monitoring/
  {start,pause,stop}`, `GET /api/monitoring/status`) and non-sensitive camera health
  (`GET /api/health/cameras`: id + status + counts only) exist, driven by an in-memory,
  thread-safe controller (D-24, D-26).
- **[PHASE 4 IMPLEMENTED]** Runtime health now comes from the worker. The backend keeps an
  in-memory `WorkerRegistry` fed by authenticated internal reports, and
  `monitoring_service.effective_status` projects a stale processing camera as
  `disconnected` at read time using `WORKER_HEARTBEAT_TIMEOUT_SECONDS` (default 15 s) — no
  per-request background task (D-29, D-30). Per-camera `StreamMetrics` (ingest/process FPS,
  latency last/avg/max, queue depth, drop/invalid/decode/processing counters, uptime) are
  computed in the worker and only aggregate, non-sensitive numbers cross the channel.
  `/api/health/cameras` keeps its exact `{count, by_status, cameras:[{id,status}]}` shape.
- **[PHASE 8 IMPLEMENTED]** Per-camera `StreamMetrics` optionally keep a bounded ring of recent
  latencies and report nearest-rank p50/p95/p99 (disabled by default; D-52). The reproducible
  benchmark harness `vision/benchmarks/` (`python -m vision.benchmarks`) drives the real worker
  stack with a synthetic detector and reports per-camera FPS/latency/queue/drops plus RSS/CPU
  (D-54).
- **[PHASE 9 IMPLEMENTED]** Runtime metrics are completed: the harness reports **GPU
  availability** explicitly (`gpu.available` + reason, never omitted), event-handoff
  **duplication rate**, and **recovery time** after a simulated stream outage, and tags camera
  runs `detector_mode: "synthetic"` (D-58). Detection-quality evaluation is an **offline**
  package, `backend/app/evaluation/` (`python -m app.evaluation`), that compares reference vs.
  detected events under fixed matching rules and reports per-activity precision/recall/F1,
  FP/FN, timing/occupancy error, and micro/macro aggregates (D-55). Reproducible verification
  lives in `scripts/` (`verify.sh`, `verify_migrations.sh`, `verify_backup_restore.sh`), backed
  by `docs/TESTING.md`, `docs/EVALUATION.md`, `docs/OPERATIONS.md`, and
  `docs/KNOWN_LIMITATIONS.md` (D-59). GPU, real-footage, and real-camera measurements remain
  unavailable and are recorded as such.

---

## 4. End-to-end data flow

### 4.1 Analysis path (per camera)

```text
1. Camera/RTSP source
     -> Camera & Stream Manager: connect, set state Connecting->Active
2. Frame Ingestion: decode, attach (camera_id, source_ts, arrival_ts),
   push to bounded per-camera queue
3. Frame Preparation: resize/normalize, apply sampling policy
4. Detection: YOLO -> observations {class, box, conf, frame_ref, ts}
5. Tracking: ByteTrack associates observations -> tracks {track_id, box, ...}
6. Pose (when activity requires): pose/landmark features
7. Temporal Event Engine: for each rule, observe() -> transitions
     creates/updates/completes/cancels events; applies thresholds & dedup
     [PHASE 5: implemented; publishes to a non-blocking sink, no persistence]
8. Evidence Manager: on trigger, snapshot pre/post window; encode short clip
9. Event Normalization: fill shared event contract (timestamps, status,
   confidence, severity, attributes, evidence_refs, config version)
10. Message Service: render deterministic message from template + metadata
11. Event Store handoff -> FastAPI -> PostgreSQL (event + evidence metadata)
12. Dashboard Update Service -> WebSocket notification to browsers
13. (Bounded metrics/logs updated throughout)
```

Key rules: events are emitted when conditions are satisfied, not at fixed intervals
(FR-19); a single frame never establishes a temporal event (FR-11); unknown/uncertain
outcomes are represented explicitly (NFR-07).

**[PHASE 4 IMPLEMENTED SCOPE]** Steps 1–5 plus per-camera metrics are implemented for one
camera: connect (with connection-time SSRF pinning), decode, tag, bounded queue, sample/
validate, detect, and track, ending in `FrameObservation(camera_id, track_id|None, box,
confidence, ...)` held in a bounded rolling buffer skeleton (FR-35). Steps 6–12 — pose,
temporal event rules, evidence capture, event normalization/persistence, deterministic
messages, and WebSocket notifications — were **not** implemented in Phase 4.
**[PHASE 5+6 IMPLEMENTED SCOPE]** Steps 6–8 and 10–11 (temporal rules, event normalization,
deterministic message rendering, and event + evidence-metadata persistence into PostgreSQL)
plus step 9 evidence capture are now implemented (Phases 5–6; D-34–D-43).
**[PHASE 7 IMPLEMENTED SCOPE]** Step 12 (WebSocket notifications) and the dashboard are now
implemented (D-44–D-49).
**[PHASE 10 IMPLEMENTED SCOPE]** The viewing path (4.2) is now implemented as an **opt-in**
MediaMTX + WebRTC (WHEP) live view (D-62–D-65). It is disabled by default; when no gateway is
configured the UI keeps the honest "live view unavailable" state and only stored snapshot/clip
evidence is viewable (D-48 fallback retained).

### 4.2 Viewing path (independent)
- **[PHASE 10 IMPLEMENTED — D-62…D-65]** A separate browser-compatible viewing path
  (`Camera/RTSP/RTSPS -> MediaMTX -> WebRTC/WHEP -> React live view`) is implemented and kept
  independent of analysis. The backend registers one stable, source-on-demand gateway path per
  camera (`<prefix>-cam-<id>`) through MediaMTX's Control API, injecting camera credentials only
  server-side and never exposing the camera source to the browser. Overlay availability is out of
  scope; the UI degrades honestly to stored evidence when the gateway is absent (FR-51).
  - **Opt-in:** enabled only when `LIVE_PLAYBACK_ENABLED=true` **and** both `MEDIAMTX_*` URLs are
    set; URLs set while disabled fail startup.
  - **Isolation:** the vision worker keeps its own camera connection; a gateway outage degrades
    only live view (D-62). No duplicate analysis connection is created.
  - **SSRF:** the source URL is validated and (for plain RTSP) IP-pinned with the same policy as
    monitoring before the gateway ever sees it (D-65).

### 4.3 Timestamp handling

- Preserve source timestamps per camera; use monotonic timing for in-process durations;
  do not assume cross-camera clock sync (FR-27).
- Carry both event time and detection/publish time; represent unknown timestamps
  explicitly.

---

## 5. Event model (canonical shape — Phase 5 contract, **Phase 6 persisted** in `app/events/types.py` + `app/models/event.py`)

Fields per FR-26 (G §9 + W §6), **stored in the `events` table** (Phase 6,
`backend/migrations/versions/0003_events_evidence.py`):

`event_id` (deterministic UUIDv5), `camera_id`, `event_type`, `entity_id?`, `zone_id?`,
`zone_name?`, `start_time`, `trigger_time`, `last_updated_at`, `end_time?`, `status`,
`state_version` (monotonic per-event revision), `confidence?` / `certainty`, `severity`,
`message` (rendered and stored once at write time), `attributes` (JSON: activity-specific +
zone/threshold/duration/rule/config version), `evidence_refs`, `review_status`, `created_at`.

The Phase 5 in-memory contract is `EventSnapshot` + `EventTransition` in
`backend/app/events/types.py`, imported by the worker (no duplicated schema). Timestamps
are timezone-aware UTC; rules use monotonic time for durations. `confidence` is populated
only from a real source value; otherwise it is `None` and `certainty` carries
high/medium/low/unknown (D-34).

**[RESOLVED OQ-02 → D-10]** Canonical `event_type` identifiers are **lowercase
`snake_case`**, used consistently across API, database, templates, frontend, and tests:

| Activity | Canonical `event_type` |
|---|---|
| Person entering | `person_entering` |
| Person leaving | `person_leaving` |
| Room occupancy change | `room_occupancy_change` |
| Crowd forming | `crowd_forming` |
| Door open too long | `door_open_too_long` |
| Package left at entrance | `package_left_at_entrance` |
| Person motionless | `person_motionless` |
| Potential fall from bed | `fall_from_bed` |

`../guidelines.md` §8.3 explicitly requires two "related but distinct" occupancy
categories, so two occupancy event types are retained. The UPPER_SNAKE_CASE names in
`../workflow_requirements.md` §8 are illustrative and superseded.

**Event lifecycle** (FR-23, D-37): `candidate → {active, uncertain, cancelled}`,
`active → {completed, uncertain, cancelled}`, `uncertain → {active, completed,
cancelled, uncertain}`; `completed` and `cancelled` are terminal with no outgoing edges.
Instantaneous events (entry, exit, occupancy change) are created and completed immediately
(FR-24). Persistent events update at bounded intervals and complete only on an observed
end condition; a stream/session end leaves them `uncertain` (missing observation is not
completion). A later recurrence receives a new event id.

---

## 6. Proposed process/deployment topology

**[PROPOSED]** Single machine (W §3.2), start simple, preserve boundaries:

| Process | Technology | Notes |
|---|---|---|
| Frontend dev server | Vite (browser) | port 5173 |
| Backend API | FastAPI/uvicorn | port 8000 |
| Vision worker | Python, GPU | separate process; `python -m vision.runtime` (to be implemented) |
| PostgreSQL | Docker container + volume | port 5432 |
| Media gateway | MediaMTX (v1.21.3, opt-in) | WebRTC `8889/tcp` + ICE `8189/udp` (browser), Control API `9997/tcp` (loopback), RTSP `8554/tcp` (loopback diagnostics) |
| Evidence/logs | local filesystem | `data/evidence`, `data/logs`, `data/backups` |

- **[PHASE 1]** Only the PostgreSQL service exists so far: `docker compose up -d db`,
  image `postgres:16-alpine` (pinned major), bound to `127.0.0.1:5432` (SEC-09), data in
  the named volume `chronovision-db-data`. The backend, worker, and media gateway
  processes are added in later phases.
- **[PHASE 2]** The **Backend API** process now exists: `uvicorn app.main:app` serves the
  health and authentication endpoints, uses the validated settings for the database URL,
  and creates its engine lazily.
- **[PHASE 4]** The **Vision worker** process now exists: `python -m vision.runtime` (run
  from the repository root with the backend virtualenv). It reconciles camera state with
  `POST /api/internal/reconcile` at startup, polls `GET /api/internal/cameras` for the
  monitoring plan, starts/stops `CameraWorker` threads through `CameraManager`, and reports
  state transitions with `POST /api/internal/cameras/{id}/state`. All internal routes use
  `X-Internal-Token`, are excluded from OpenAPI, and reject browser sessions. The worker has
  no database access; the backend remains authoritative for persistence.
  **[PHASE 10]** The **Media gateway** process now exists as an opt-in MediaMTX v1.21.3 service
  (`docker compose --profile playback up -d mediamtx`) providing the browser WebRTC/WHEP viewing
  path (D-62–D-65); it is independent of the vision worker and disabled by default. See
  `docs/LIVE_PLAYBACK.md`.
- **[RESOLVED OQ-09 → D-12, PHASE 6 IMPLEMENTED]** Vision worker ↔ backend handoff is
  **authenticated internal HTTP**: the worker `POST`s normalized events and evidence metadata
  to internal FastAPI endpoints using a constant-time-compared shared token
  (`X-Internal-Token`, from `INTERNAL_API_TOKEN`). Payloads are strictly validated with
  Pydantic; submissions are idempotent upserts keyed by a stable `event_id`; retries use
  bounded exponential backoff on transient errors only, with a bounded local spool on
  exhaustion. No broker, no direct DB write by the worker. Full specification in
  `docs/OPEN_QUESTIONS.md` (OQ-09). The Phase 4 health channel reuses the same token and
  client (`vision/internal_client.py`, stdlib `urllib`); Phase 6 adds the event and evidence
  payloads.
- **[PHASE 5]** Each `CameraWorker` builds and resets a per-camera `TemporalEventEngine`.
  Processed frames are adapted to `EngineFrame` and transitions are published to an
  `EventSink` (D-39).
- **[PHASE 6]** The worker now publishes transitions to an `EvidenceCoordinator` that both
  **hands events off** to the backend (`vision/event_handoff.py`: bounded in-memory queue +
  bounded on-disk spool, authenticated delivery, capped retries) and **captures evidence**
  (`vision/evidence/`: snapshot + short clip encoded off the frame loop). The backend
  persists via `POST /api/internal/events` and
  `POST /api/internal/events/{event_id}/evidence`, and serves read-only
  `GET /api/events` + `GET /api/evidence/{id}`. Door state, package classes, and pose
  producers are still not implemented (D-39).
- **[PHASE 8 IMPLEMENTED]** A single vision-worker **process** hosts multiple cameras as
  independent per-camera threads (`VISION_MAX_CONCURRENT_CAMERAS`), each with its own
  lifecycle, tracker, event engine, evidence pipeline, and per-camera handoff spool
  (`handoff-<camera_id>-*.json`, bounded per camera; D-50/D-51). One-camera remains the
  default. OS-process-per-camera is a documented future scaling option, not implemented. The
  reproducible benchmark harness `vision/benchmarks/` measures throughput/latency/RSS/CPU for
  increasing camera counts before scaling (NFR-13; D-54).
- **[PROPOSED]** Run the vision worker natively first to avoid making container GPU
  configuration an early blocker (W §14); containerise later if desired.
- **[RESOLVED]** The **backend renders all messages** from normalized events (single
  enforcement point for D-09); the worker does not render or hold templates.

---

## 7. Proposed source layout

Follows W §12, extended with the planning docs created in this phase:

```text
chronovision/
├── AGENTS.md
├── README.md                          (Phase 1: created)
├── docker-compose.yml                 (Phase 1: PostgreSQL only)
├── .env.example                       (Phase 1: placeholders only)
├── .gitignore                         (Phase 1; Phase 9: evidence pattern anchored to root, D-60)
├── docs/
│   ├── REQUIREMENTS_TRACEABILITY.md   (Phase 0)
│   ├── ARCHITECTURE.md                (Phase 0)
│   ├── IMPLEMENTATION_PLAN.md         (Phase 0)
│   ├── OPEN_QUESTIONS.md              (Phase 0)
│   ├── DECISIONS.md
│   ├── IMPLEMENTATION_PROGRESS.md
│   ├── TESTING.md                     (Phase 9: reproducible commands)
│   ├── EVALUATION.md                  (Phase 9: labels + metrics)
│   ├── OPERATIONS.md                  (Phase 9: deploy/retention/backup)
│   └── KNOWN_LIMITATIONS.md           (Phase 9: AC-15)
├── scripts/                           (Phase 9: verify.sh, verify_migrations.sh,
│                                       verify_backup_restore.sh)
├── evaluation/sample/                 (Phase 9: clearly-synthetic label + detection JSON)
├── frontend/           (React 19/TS/Vite/MUI — Phase 7 implemented)
│   ├── package.json    (scripts: dev, build, typecheck, lint, format, test)
│   ├── vite.config.ts  (dev proxy /api + ws; Vitest/jsdom)
│   ├── eslint.config.js, .prettierrc.json, tsconfig.json
│   └── src/
│       ├── api/        (typed client, CSRF, auth/cameras/events/evidence/
│       │                monitoring/settings/health, WebSocket client)
│       ├── auth/       (AuthProvider/context/useAuth, ProtectedRoute)
│       ├── realtime/   (RealtimeProvider, useRealtime)
│       ├── layout/     (AppLayout nav + session/logout)
│       ├── pages/      (Login, Overview, Cameras, Events, EventDetail,
│       │                Settings, NotFound)
│       ├── components/ (status chips, loading/error/empty states)
│       ├── hooks/      (React Query hooks/mutations)
│       ├── lib/        (formatting helpers)
│       ├── test/       (setup, providers, fixtures)
│       └── main.tsx, App.tsx, theme.ts
├── backend/
│   ├── pyproject.toml                 (Phase 1; Phase 2: web/db/auth deps + script)
│   ├── alembic.ini                    (Phase 2)
│   ├── app/
│   │   ├── __init__.py                (Phase 1; Phase 3: version 0.3.0)
│   │   ├── config.py                  (Phase 1; Phase 3: camera/SSRF settings, D-22)
│   │   ├── db.py                      (Phase 2: lazy engine + session lifecycle)
│   │   ├── utils.py                   (Phase 2: UTC helpers)
│   │   ├── main.py                    (Phase 2: FastAPI app factory + lifespan)
│   │   ├── cli.py                     (Phase 2: `create-admin`; Phase 6: `prune-evidence`)
│   │   ├── api/                       (Phase 2: router, error handlers, routes)
│   │   │   └── routes/{health,auth}.py   (Phase 3: + cameras.py, monitoring.py;
│   │   │                                   Phase 6: + events.py, evidence.py, internal.py;
│   │   │                                   Phase 7: + realtime.py, settings.py)
│   │   ├── auth/                      (Phase 2: security, sessions, CSRF, rate limit;
│   │   │                               Phase 4: internal.py token check)
│   │   ├── models/                    (Phase 2: users, sessions, audit_logs;
│   │   │                               Phase 3: cameras + CameraStatus;
│   │   │                               Phase 6: event.py, evidence.py)
│   │   ├── schemas/                   (Phase 2: Pydantic request/response models;
│   │   │                               Phase 3: camera.py, monitoring.py, health.py;
│   │   │                               Phase 6: event.py, evidence.py, internal.py;
│   │   │                               Phase 7: settings.py)
│   │   ├── repositories/              (Phase 2: parameterised DB helpers;
│   │   │                               Phase 3: cameras.py; Phase 6: events.py, evidence.py)
│   │   ├── services/                  (Phase 2: auth + admin provisioning;
│   │   │                               Phase 3: camera_service.py,
│   │   │                               stream_validation.py, lifecycle.py,
│   │   │                               monitoring_service.py;
│   │   │                               Phase 4: worker_registry.py;
│   │   │                               Phase 6: event_service.py, evidence_service.py;
│   │   │                               Phase 7: event_broadcaster.py)
│   │   ├── schemas/internal.py        (Phase 4: internal worker channel)
│   │   ├── events/                    (Phase 5: canonical contract, lifecycle, zones)
│   │   ├── event_messages/            (Phase 5: deterministic templates)
│   │   └── evaluation/                (Phase 9: offline matching/metrics/CLI, D-55)
│   ├── migrations/                    (Phase 2: Alembic env + 0001_initial_auth;
│   │                                   Phase 3: 0002_cameras;
│   │                                   Phase 6: 0003_events_evidence)
│   └── tests/                         (Phase 1: config; Phase 2: db/auth/health;
│                                       Phase 3: stream validation, lifecycle,
│                                       camera API, monitoring API;
│                                       Phase 5: events/messages;
│                                       Phase 6: event persistence, evidence service,
│                                       events/evidence/internal APIs;
│                                       Phase 7: review/protection/settings/ws;
│                                       Phase 8: multi-camera isolation;
│                                       Phase 9: evaluation, security verification,
│                                       retention verification)
├── vision/                            (Phase 4: worker runtime)
│   ├── runtime.py                     (Phase 4: `python -m vision.runtime`)
│   ├── supervisor.py                  (Phase 4: plan poll + reconcile loop)
│   ├── config.py                      (VisionSettings / VISION_*)
│   ├── net.py                         (Phase 4: connection-time SSRF pinning, D-28)
│   ├── internal_client.py             (worker → backend internal HTTP)
│   ├── health.py, metrics.py, buffer.py
│   ├── event_handoff.py               (Phase 6: bounded authenticated handoff + spool)
│   ├── evidence/{paths,encoding,store,manager,coordinator}.py (Phase 6)
│   ├── camera_manager/{worker,manager}.py   (Phase 4 lifecycle + ownership)
│   ├── ingestion/{sources,queue,prepare}.py (Phase 4)
│   ├── detection/detector.py          (Phase 4: YOLO + NullDetector)
│   ├── event_engine/                  (Phase 5: temporal rules + orchestration)
│   ├── benchmarks/{harness,__main__}.py     (Phase 8; Phase 9: GPU/recovery/duplication)
│   └── tracking/tracker.py            (Phase 4: ByteTrack + IoUTracker)
├── vision/tests/                      (Phase 4–9 tests + fakes)
└── data/{evidence,logs,backups}       (runtime; not committed)
```

**[CONFIRMED]** `data/` is runtime storage and must not be committed (CON-06, SEC-10).
**[RESOLVED]** The `.gitignore` covering secrets, env files, recordings, evidence, DB
files, and caches was created in Phase 1 (SEC-10). In Phase 1 the future backend module
directories (`api`, `auth`, `models`, `schemas`, `services`, `repositories`,
`event_messages`) and `frontend/`/`vision/` were **documented but not created**, so that
no empty structure predates its owning phase.
**[PHASE 2]** The backend module directories `api/`, `auth/`, `models/`, `schemas/`,
`repositories/`, and `services/` now exist and are populated (see D-15–D-20);
`event_messages/` and `frontend/`/`vision/` remain deferred to their owning phases.
**[PHASE 3]** `cameras` is added to `models/`, `migrations/0002_cameras.py` extends the
chain, and the camera/monitoring surface is added across `api/routes/`, `schemas/`,
`repositories/`, and `services/` (see D-21–D-26).
**[PHASE 4]** The top-level `vision/` package now exists with its runtime entry point,
worker/manager, ingestion, detection, tracking, SSRF, metrics, and internal-client modules
(see D-27–D-33); `vision` is a separate runtime and is **not** a backend dependency.
**[PHASE 5]** `backend/app/events/` and `backend/app/event_messages/` now exist (canonical
contract, lifecycle, zones, deterministic renderer; D-34–D-39), and `vision/event_engine/`
holds the temporal rules (see D-34–D-39). `frontend/` and the `pose` producer remain
deferred.
**[PHASE 6]** Event/evidence persistence and delivery now exist: `events`/`evidence` models,
`app/services/{event_service,evidence_service}.py`, `repositories/{events,evidence}.py`,
`schemas/{event,evidence}.py`, routes `events.py`/`evidence.py`/`internal.py`,
`migrations/0003_events_evidence.py`, the `prune-evidence` CLI, and `vision/event_handoff.py`
+ `vision/evidence/` (see D-40–D-43).
**[PHASE 7]** The `frontend/` dashboard now exists (React/TS/Vite/MUI), plus
`app/services/event_broadcaster.py`, routes `realtime.py` (`/api/ws`) and `settings.py`
(`GET /api/settings`), the `PATCH` review/protection mutations, and the `review_status`/`order`
event filters (see D-44–D-49).
**[PHASE 10]** The opt-in live-view path now exists: `app/services/live_gateway.py` (MediaMTX v3
Control-API client), `app/services/live_service.py` (registration/status),
`app/services/credential_cipher.py` (Fernet credential store), `app/schemas/live.py`, the two live
endpoints, the `cameras.stream_credentials_encrypted` column
(`migrations/0004_camera_stream_credentials.py`), the `deploy/mediamtx.yml` config + `mediamtx`
compose service, `frontend/src/api/live.ts` + `components/{LivePlayer,LivePlaybackDialog}.tsx`, and
`docs/LIVE_PLAYBACK.md` (see D-62–D-65).
**[PHASE 9]** Verifiable testing/evaluation/docs added: `backend/app/evaluation/` (offline
matching + metrics + CLI, D-55) with a clearly-**synthetic** `evaluation/sample/` dataset;
`scripts/` (`verify.sh`, `verify_migrations.sh`, `verify_backup_restore.sh`); the
`docs/{TESTING,EVALUATION,OPERATIONS,KNOWN_LIMITATIONS}.md` set; and the extended
`vision/benchmarks/` harness (GPU availability, duplication rate, recovery time; D-58). The
`API_SPEC.md`/`DATABASE_SCHEMA.md` documents named in W §12 are **not** created as separate
files (OQ-08 resolved): the API surface stays in the README endpoint table plus the running
OpenAPI schema, and the schema stays in this document plus the Alembic migrations.

---

## 8. Security architecture

- **Auth:** single administrator; Argon2id password hashing; server-side sessions with
  random tokens (hashed at rest); HTTP-only/SameSite cookies; CSRF protection; login
  rate limiting; session expiry + revocation (SEC-01–SEC-05, SEC-12).
- **AuthZ on media:** all video/snapshot/evidence access routed through authorized
  backend endpoints; the evidence directory is never publicly served; safe filenames;
  path-traversal prevention (SEC-04, SEC-08). **[PHASE 6]** `GET /api/evidence/{id}` requires
  an authenticated session, resolves the stored relative path inside `EVIDENCE_DIR`, and
  rejects absolute/`..`/drive-letter/escaping-symlink paths; the directory is never mounted
  or served statically (D-42).
- **Secrets:** camera credentials and secrets stay on the backend; never in the
  frontend or Git; validate stream addresses to prevent SSRF (SEC-06, SEC-07).
  **[PHASE 3]** Camera responses are **redacted** (scheme/host/port/path only) and
  embedded credentials in stream references are rejected outright (D-21, D-22, D-25).
  **[PHASE 10]** Cameras that need RTSP authentication store a Fernet-encrypted
  `{"username","password"}` pair (`cameras.stream_credentials_encrypted`, D-64); the API is
  write-only and exposes only `has_stream_credentials`; the key is derived from `SECRET_KEY`.
  The plaintext is decrypted only in-process for gateway registration and is never logged,
  returned, or put in an exception. The browser receives only an opaque `cv-cam-<id>` path and
  WHEP URL and sends no cookies to the gateway (D-62).
  **[PHASE 4]** Connection-time SSRF enforcement is implemented in `vision/net.py`
  (D-28, resolves OQ-14): immediately before opening a stream the worker re-checks the
  scheme/credential/destination policy on **every** resolved address (fail closed), then
  replaces the hostname with the validated IP literal handed to the decoder, so
  OpenCV/FFmpeg cannot re-resolve and DNS rebinding cannot redirect the socket. Redirects
  and alternate protocol handlers are not used, and no generic URL-fetch/proxy endpoint
  exists. **Residual:** `VISION_STREAM_HOST_MODE=hostname` is a documented opt-in needed
  for TLS certificate/SNI or vhost routing, and re-introduces re-resolution (mitigation:
  keep `pin`; restrict the allowed schemes/hosts). Pinning also means the TLS
  certificate is checked against the IP unless hostname mode is used.
- **Network:** bind to localhost by default; HTTPS and restricted ports beyond localhost
  (SEC-09).
- **Audit:** `audit_logs` records actions without secrets/tokens/credentials.

---

## 9. Known architectural risks

1. **Superseded LLM requirement (OQ-01 → D-09):** `G` describes an LLM summary component;
   `A`/`W` and the project decision forbid a runtime LLM. This architecture adopts
   no-runtime-LLM and marks `G`'s LLM requirements as superseded. The conflict remains
   documented so it is never silently erased. If LLM prose is ever required, it must be a
   separately-labelled, non-critical **offline/opt-in** scope change — never a runtime
   dependency of the detection or event pipeline.
2. **6 GB VRAM / 16 GB RAM budget (NFR-15):** detection + pose + tracking per camera may
   not scale to many cameras without resolution/sampling tuning. Benchmark before
   scaling (NFR-13).
3. **Live-view + analysis resource contention:** MediaMTX and the vision worker each pull the
   same camera (D-62 deliberately avoids shared ingest), so a weak camera/uplink may show a
   reduced analysis frame rate while someone is watching. Keep them separate and measure; the
   gateway uses source-on-demand so idle cost is zero. Not yet measured against a real camera.
4. **Fall/medical semantics (CON-10, G §8.7):** architecture must never present these as
   confirmed medical events; conservative labelling is required.
5. **Event-type naming drift (OQ-02 → D-10):** identifiers are now fixed as lowercase
   `snake_case`; any change is migration work across DB, templates, frontend, and tests,
   so the canonical set must be treated as stable.
6. **Handoff coupling (OQ-09 → D-12):** the worker→backend link is now specified as
   authenticated internal HTTP with idempotent upserts; the interface must be versioned
   to avoid eroding the module boundary.
