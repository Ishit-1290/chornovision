# ChronoVision — Requirements Traceability

**Status:** Planning baseline (Phase 0). Requirement IDs and phase mapping are stable;
per-phase implementation/verification status is tracked in
`docs/IMPLEMENTATION_PROGRESS.md`. As of **Phase 8**, the Phase 1–7 items remain verified.
Phase 7 implements the dashboard (FR-46, FR-49, FR-50, FR-52), event filtering/pagination
(FR-53), real-time WebSocket notifications (FR-48), human review (FR-44), evidence
protection, and read-only settings, plus the browser half of AC-09/AC-10 and SEC-04 on the
WebSocket. Live video (FR-51) and the media gateway (FR-54) were **not deployed** in Phases 1–9
(D-48); **Phase 10** now implements them as opt-in MediaMTX + WebRTC playback (D-62–D-65).
Phase 8 implements multi-camera isolation (FR-06, NFR-03, AC-04), configuration-change
reconciliation (FR-08/FR-47), per-camera latency percentiles, and a reproducible benchmark
harness (NFR-13, NFR-15). **Phase 9** adds reproducible verification scripts (W §13 M8), the
offline labelled-evaluation package and metrics (AC-14; G §16.2), extended runtime
benchmarking (NFR-06; G §16.3), security verification (SEC-04; G §17), retention and
backup/restore verification (FR-42/FR-43), and the consolidated documentation/known-limitations
set (AC-15). **Phase 10** implements opt-in live playback (FR-51, FR-54) with per-camera
credentials encrypted at rest (write-only) and an SSRF-validated, IP-pinned gateway source
(D-62–D-65). See D-44–D-65. **Date:** 2026-11-01

## Purpose

This document extracts the functional requirements, non-functional requirements,
constraints, and acceptance criteria from the authoritative project documents,
assigns stable identifiers, and maps each requirement to a planned implementation
phase and a verification method.

It is a traceability index, not a new specification. Where the source documents
disagree, the conflict is recorded here and carried into `docs/OPEN_QUESTIONS.md`
rather than resolved silently.

## Source document key

| Key | Document | Role |
|---|---|---|
| **A** | `AGENTS.md` (this repo) | Agent/project operating instructions; core constraints |
| **G** | `../guidelines.md` | Behavioural baseline: activities, event lifecycle, evaluation |
| **W** | `../workflow_requirements.md` | Technology stack, deployment, milestones, runtime LLM prohibition |

**Precedence note (OQ-01 → resolved by D-09).** `AGENTS.md` and the task brief state
"No runtime LLM or generative AI" and "Event messages must use deterministic templates."
This agrees with `W` §1 and §8. It conflicts with `G` §1, §2, §4.4, §12, which describe
an LLM-based description/summary component. The conflict was **resolved in favour of no
runtime LLM** (Decision D-09), following `A`, `W`, the task constraint, and the user's
explicit resolution. The conflict is **preserved as a documented note** (see
`docs/OPEN_QUESTIONS.md` OQ-01) and `G`'s LLM requirements are marked superseded. AC-11
becomes deterministic aggregation; AC-12 is satisfied by there being no runtime LLM
dependency at all. See `docs/DECISIONS.md`.

## Legend

- **Phase** refers to `docs/IMPLEMENTATION_PLAN.md`.
- **Verification** is the intended primary method; final method is confirmed per phase.
- Confidence of extraction: all items are direct extractions unless marked *(assumption)*.

---

## 1. Functional Requirements

### 1.1 Camera and stream management

| ID | Requirement | Source | Phase | Verification |
|---|---|---|---|---|
| FR-01 | Register and configure cameras (unique camera ID, name, stream reference, per-camera configuration). | G §5.1, §5; W §4, §6 | 3 | API tests + DB inspection |
| FR-02 | Establish stream connections and support explicit start/stop of processing. | G §5.1; W §3.4 | 3, 4 | Integration test with prerecorded/live source — **Phase 4:** `vision/runtime.py`, `camera_manager/`; `vision/tests/{test_runtime,test_manager,test_worker,test_integration_pipeline}.py`. Live RTSP not verified in this environment. |
| FR-03 | Maintain an independent lifecycle per camera: configured, connecting, active, degraded, disconnected, reconnecting, stopped, failed. | G §6 | 3, 8 | State-transition unit tests — **Phase 4:** worker drives runtime states; `backend/tests/test_lifecycle.py`, `vision/tests/test_worker.py`. **Phase 8:** multiple workers run concurrently, each with its own lifecycle; `vision/tests/test_multi_camera.py`, `test_reliability.py`. |
| FR-04 | Detect disconnections and stalled streams; initiate bounded recovery; report failures to the dashboard. | G §5.1, §6; W §3.4 | 3, 8 | Fault-injection integration test — **Phase 4:** open-failure/stall/reconnect/exhaustion tests in `vision/tests/test_worker.py`; read-time staleness projection in `backend/tests/test_monitoring_api.py`/`test_worker_registry.py`. **Phase 8:** stop-during-connect/backoff returns promptly and terminal failure idles without churn (`test_reliability.py`). |
| FR-05 | A disconnected stream must not be treated as a stream containing no activity. | G §5.1, §6 | 3 | Unit test on state semantics — **Phase 4:** no `disconnected→active` edge; tracker reset on every connection. |
| FR-06 | Camera failure must not terminate unrelated camera workers. | G §6; W §3.4, §16 | 8 | **Phase 8:** multi-camera fault-injection — a terminal-failing or blocked camera ends/stalls only its own worker while healthy cameras keep processing; per-camera spool isolation (`vision/tests/test_multi_camera.py`, `test_event_handoff.py`; `backend/tests/test_multi_camera_isolation.py`). Isolation is thread-per-camera in one process (D-50); OS-process-per-camera is a documented future option. |
| FR-07 | Preserve frame ordering within each stream as far as the source/architecture permits; handle invalid, delayed, and missing frames explicitly. | G §5.2 | 4 | Unit tests on ingestion edge cases — **Phase 4:** `vision/tests/{test_queue,test_sources,test_prepare}.py`. |
| FR-08 | Do not infer entry/exit across a period when the camera was unavailable (tracking-reset/recovery policy). | G §6 | 4, 8 | Scenario test — **Phase 4:** `test_tracker_is_reset_on_every_connection` in `vision/tests/test_worker.py`. **Phase 8:** tracker + event engine reset on every (re)connection and after a config-change restart (`test_reliability.py`, `test_manager.py`). |

### 1.2 Frame preparation, detection, and tracking

| ID | Requirement | Source | Phase | Verification |
|---|---|---|---|---|
| FR-09 | Prepare frames for analysis (resize, normalize, sample, format-adapt) without discarding activity-relevant information. | G §5.3; W §4 | 4 | Unit + visual sanity checks — **Phase 4:** `vision/ingestion/prepare.py`, `vision/tests/test_prepare.py`. |
| FR-10 | Detect relevant entities (people, supported objects such as packages and doors). Each detection carries camera ID, frame timestamp, class, bounding box/location, confidence, frame reference. | G §5.4; W §7 | 4 | Detection unit tests on labelled clips — **Phase 4:** `vision/detection/detector.py`, `test_detector_tracker.py`; real YOLO load+inference verified opt-in (`VISION_TEST_WEIGHTS=1`). |
| FR-11 | Detection must not independently declare complex temporal events from a single observation. | G §5.4 | 4, 5 | Design/interface review + tests — **Phase 4:** detector returns only `Detection` observations; no event types exist yet. |
| FR-12 | Track detections across frames within one camera; maintain track IDs; update positions; tolerate temporary missed detections. | G §5.5; W §7 | 4 | Tracking tests; ID-switch metric — **Phase 4:** `vision/tracking/tracker.py` (ByteTrack + IoU fallback), `test_detector_tracker.py`. |
| FR-13 | Track identifiers are scoped to a camera and must never be treated as real-world identities. | G §5.5; W §4 | 4 | Interface review + tests — **Phase 4:** one tracker instance per `CameraWorker`; no cross-camera state. **Phase 8:** concurrent cameras keep distinct tracker/engine instances and per-camera attribution (`vision/tests/test_multi_camera.py`). |
| FR-14 | Tolerate track loss/reacquisition without silently merging unrelated entities. | G §5.5 | 4 | Scenario test — **Phase 4:** tracker reset per connection; camera-scoped IDs. |
| FR-15 | Apply controlled frame sampling with a documented policy. | G §4.1; W §4, M3 | 4 | Config + benchmark test — **Phase 4:** `SamplingPolicy` + `VISION_PROCESS_TARGET_FPS`; `test_prepare.py`. |

### 1.3 Temporal event engine

| ID | Requirement | Source | Phase | Verification |
|---|---|---|---|---|
| FR-16 | Maintain per-camera temporal state and evaluate activity trigger conditions over time. | G §4.2, §5.6 | 5 | Unit tests per activity |
| FR-17 | Support event creation, update, completion, cancellation, duplicate prevention, confidence/uncertainty updates, and handling of missing observations. | G §5.6, §7, §10 | 5 | State-machine unit tests |
| FR-18 | Support activity-specific duration thresholds and minimum persistence intervals. | G §5.6, §10 | 5 | Config-driven unit tests |
| FR-19 | Event categories must be emitted only when triggering conditions are satisfied, not at fixed reporting intervals. | G §4.3 | 5 | Unit tests |
| FR-20 | Distinguish event start time, trigger/detection time, completion time, and last-updated time. | G §7, §9 | 5 | Schema + unit tests |
| FR-21 | Maintain event history distinct from the current state of an ongoing event; preserve meaningful state transitions. | G §5.8, §10 | 5, 6 | DB tests |
| FR-22 | Emit events before the stream ends (no wait for full recording). | G §4.1, §17 | 5 | Integration test |
| FR-23 | Represent each event as a stateful object with lifecycle states: candidate, active, completed, uncertain, cancelled. | G §7; W §7 | 5 | State-machine tests |
| FR-24 | Instantaneous events (e.g., boundary crossing) may be created and completed immediately. | G §7 | 5 | Unit test |

### 1.4 The seven activities

| ID | Activity | Canonical event type(s) | Source | Phase | Verification |
|---|---|---|---|---|---|
| EV-01 | Person entering an area (valid inward boundary crossing). | `person_entering` | G §8.1; W §7, §8 | 5 | Labelled-clip detection tests |
| EV-02 | Person leaving an area (valid outward crossing). | `person_leaving` | G §8.2; W §7, §8 | 5 | Labelled-clip detection tests |
| EV-03 | Occupancy / crowd threshold exceeded. | `room_occupancy_change`, `crowd_forming` | G §8.3; W §7, §8 | 5 | Occupancy-count accuracy + threshold tests |
| EV-04 | Door left open beyond a configured duration (default 60 s for testing). | `door_open_too_long` | G §8.4; W §7, §8 | 5 | Duration-timer tests |
| EV-05 | Package left unattended near an entrance (default 30–60 s stationarity). | `package_left_at_entrance` | G §8.5; W §7, §8 | 5 | Temporal-rule tests; uncertain-case tests |
| EV-06 | Person remaining motionless beyond a configured duration (default 120 s). | `person_motionless` | G §8.6; W §7, §8 | 5 | Inactivity-timer tests; confounder tests |
| EV-07 | Potential fall near a bed. | `fall_from_bed` | G §8.7; W §7, §8 | 5 | Pose/transition tests; ambiguous-case tests |

**Event-type identifiers (OQ-02 → resolved by D-10).** `event_type` values are
**lowercase `snake_case`** canonical identifiers, used consistently across the API,
database, message templates, frontend, and tests. `G` §8.3 explicitly requires two
"related but distinct" occupancy event categories, so `room_occupancy_change` and
`crowd_forming` are both retained. The UPPER_SNAKE_CASE names in `W` §8 are treated as
illustrative only and are superseded.

### 1.5 Event data contract and timestamps

| ID | Requirement | Source | Phase | Verification |
|---|---|---|---|---|
| FR-25 | All events use a consistent structured representation. | G §9; W §6 | 5 | Schema tests |
| FR-26 | Core event fields: `event_id`, `camera_id`, `event_type`, `entity_id`, `start_time`, `trigger_time`, `last_updated_at`, `end_time`, `status`, `confidence`, `severity`, `description`/`message`, `evidence_refs`, `attributes`, `review_status`. | G §9; W §6 | 5 | ORM/Pydantic schema review + tests |
| FR-27 | Preserve source timestamps; maintain a consistent time basis per camera; use monotonic timing for in-process durations; do not assume cross-camera clock sync; distinguish event time from detection/publication time; represent unknown timestamps explicitly. | G §9 | 5 | Unit tests |
| FR-28 | Confidence values must originate from documented model outputs or an explicit scoring procedure; no fabricated confidence; use an uncertainty category when no reliable numeric measure exists. | G §9 | 5 | Tests + review |
| FR-29 | Event schema may include zone IDs, threshold values, duration, source timestamps, configuration versions. | G §9; W §15.6 | 5 | Schema review |

### 1.6 Deterministic event messages (no LLM)

| ID | Requirement | Source | Phase | Verification |
|---|---|---|---|---|
| FR-30 | Every event message is generated deterministically by application logic. No LLM or external text-generation API at runtime. | A; W §1, §8 | 5 | Unit tests + dependency audit |
| FR-31 | Template selected by `event_type`; validated metadata is interpolated; final message stored on the event record. | W §8 | 5 | Unit tests |
| FR-32 | Templates live in a dedicated module/config; stable identifiers; required-variable validation; consistent timestamp formatting; sanitize untrusted values; safe fallbacks for missing metadata; do not regenerate old messages unexpectedly. | W §8 | 5 | Unit tests |
| FR-33 | Keep structured metadata separate from display text; express uncertainty/confidence in structured fields, not invented prose. | W §8 | 5 | Review + tests |
| FR-34 | Provide the seven predefined templates (entering, leaving, occupancy, door-open, package, motionless, potential fall) using the wording defined in `W` §8. | W §8 | 5 | Unit tests |

### 1.7 Evidence capture

| ID | Requirement | Source | Phase | Verification |
|---|---|---|---|---|
| FR-35 | Maintain a bounded rolling frame buffer per camera (max size/duration). | G §5.7, §11; W §9 | 4, 6 | Memory-bound tests — **Phase 4 skeleton:** `vision/buffer.py` + `test_buffer.py`; **Phase 6:** bound derived from `EVIDENCE_ROLLING_BUFFER_SECONDS` × process FPS with a byte cap (`worker._rolling_buffer_items`), fed to evidence. |
| FR-36 | On trigger, retain pre-event frames, the trigger frame, post-event frames, and encode a short clip with source timestamps. | G §5.7, §11; W §9 | 6 | **Phase 6:** `vision/evidence/manager.py` + `store.py`; `test_evidence_manager.py`, `test_evidence_store.py` (pre/post windows, snapshot + clip). |
| FR-37 | Evidence capture must not block the primary detection loop (separate task/bounded queue). | G §5.7, §11; W §9 | 6 | **Phase 6:** dedicated encoder thread + bounded job queue; `test_capture_bookkeeping_does_not_block_the_frame_caller`, `test_encoder_queue_overflow_records_a_failure_instead_of_growing`. |
| FR-38 | Each evidence item identifies source camera and time interval; generate safe filenames; prevent path traversal. | G §11; W §6, §9 | 6 | **Phase 6:** `vision/evidence/paths.py`, `app/services/evidence_service.py`; `test_evidence_paths.py`, `test_evidence_service.py` (traversal/symlink/absolute rejected). |
| FR-39 | If evidence generation fails, the event remains visible with an explicit evidence-generation status. | G §11; W §9 | 6 | **Phase 6:** explicit `failed` records (encode error, empty file, no frames, overload); `test_evidence_store.py`, `test_evidence_manager.py`, `test_evidence_api.py`. |

### 1.8 Persistence and retention

| ID | Requirement | Source | Phase | Verification |
|---|---|---|---|---|
| FR-40 | Persist normalized events, event updates, camera metadata, review decisions, and analysis history in PostgreSQL. | G §5.8; W §6 | 6 | **Phase 6:** `events`/`event_transitions`/`evidence` models + `0003_events_evidence`; `app/services/event_service.py`; `test_event_persistence.py`, `test_internal_events_api.py` (idempotent/ordered/immutable). |
| FR-41 | Store video/snapshot files on the filesystem and only relative paths in PostgreSQL. | W §6 | 6 | **Phase 6:** relative path only in `evidence.relative_path`; `vision/evidence/store.py` + `app/services/evidence_service.py`; `test_evidence_service.py`. |
| FR-42 | Define and apply evidence retention and deletion policies; `retention_status`. | G §15.5; W §6, §16 | 6, 9 | **Phase 6:** `evidence_service.run_retention` + `prune-evidence` CLI; `test_evidence_service.py` (time + cap, oldest-first, protected never evicted). **Phase 9:** end-to-end verification of expiry, cap oldest-first, protected-never-evicted, `blocked_by_protection`, file-unlink/row-retention, and retention-not-on-register (`test_retention_verification.py`; D-57). |
| FR-43 | Record important metadata and support backup/restore. | W §6, §16 | 6, 9 | **Phase 6:** structured metadata persisted (D-40) and documented `pg_dump`/`pg_restore` + evidence-tree procedure; verified with a **live PostgreSQL round-trip** (D-43). **Phase 9:** `scripts/verify_backup_restore.sh` performs a full disposable-cluster round trip and checks row counts, FK integrity, and evidence accessibility/identity (D-57); procedure documented in `docs/OPERATIONS.md`. |
| FR-44 | Persist optional human-review decisions separately from original model output (`review_status`) to preserve traceability. | G §13.7; W §6 | 7 | **Phase 7:** `PATCH /api/events/{id}` changes only `review_status` + audited note; message/timestamps/state untouched (`test_event_review_api.py`); separate audited evidence pin/unpin (`test_evidence_protection_api.py`). |
| FR-45 | Preserve model version, configuration, event-rule version, and runtime metadata with each event where practical. | G §15.6 | 5, 6 | Schema + test |

### 1.9 API, dashboard, and real-time delivery

| ID | Requirement | Source | Phase | Verification |
|---|---|---|---|---|
| FR-46 | Backend REST + WebSocket API exposing auth, cameras, monitoring, events, evidence, and health endpoints as specified in `W` §10. | W §10 | 3, 7 | **Phase 7:** adds `PATCH /api/events/{id}`, `PATCH /api/evidence/{id}`, `GET /api/settings`, `/api/ws`; OpenAPI + integration tests (`test_event_review_api.py`, `test_evidence_protection_api.py`, `test_settings_api.py`, `test_ws_api.py`). |
| FR-47 | Monitoring endpoints control the analysis runtime, not just the browser viewer. | W §3.4, §10 | 3, 8 | Integration test — **Phase 8:** monitoring continues (analysis unaffected) across browser **logout** and **WebSocket disconnect** (`backend/tests/test_multi_camera_isolation.py`, NFR-01); a configuration change is reconciled by restarting only the changed worker (`vision/tests/test_reliability.py`, D-53). |
| FR-48 | Publish current camera status, event updates, stream failures, and processing health to the Web UI without manual reload. | G §5.10, §13; W §10 | 7 | **Phase 7:** authenticated `/api/ws` + bounded in-process `EventBroadcaster`; lightweight notifications invalidate REST caches; reconnect refetches missed updates (`test_ws_api.py`, `test_event_broadcaster.py`, `RealtimeProvider.test.tsx`). Playwright E2E not used (component/integration tests). |
| FR-49 | Dashboard pages: login, overview, camera monitoring, event timeline (filter/sort), event details, settings. | W §11 | 7 | **Phase 7:** React/Vite/MUI pages with protected routes; Vitest component tests (`frontend/src/**/*.test.tsx`). |
| FR-50 | Frontend must not connect directly to PostgreSQL, store camera credentials, or run the primary CV pipeline; no LLM summary panel (predefined message is authoritative). | W §2.1, §11 | 7 | **Phase 7:** frontend only calls `/api`; no DB client, no token storage, no LLM; the stored deterministic message is the description. |
| FR-51 | Live camera view via a browser-compatible protocol (e.g., WebRTC via MediaMTX); clear when overlays are delayed/unavailable. | G §13.2; W §2.5, §4 | 10 | **Phase 10 (D-62–D-65):** opt-in MediaMTX + WebRTC (WHEP); `GET /api/cameras/{id}/live` + `POST .../live/start`; native `RTCPeerConnection` `LivePlayer`; per-camera RTSP credentials encrypted at rest and write-only (D-64). The UI states live view is unavailable when playback is off. Verified with a fake gateway (`test_live_playback.py`, `LivePlayer.test.tsx`) and a real MediaMTX v1.21.3 process; **no real camera/browser** claimed. |
| FR-52 | Distinguish live vs finalized summaries; display stream health separately from absence of events. | G §13.5, §13.6 | 7 | **Phase 7:** overview shows camera/health status separately from the event timeline; no live/finalized summary is fabricated. |
| FR-53 | Support filtering by camera, event type, date range, and status with pagination. | W §10 | 7 | **Phase 7:** `GET /api/events` gains `review_status` + `order`; frontend timeline filters camera/type/status/review/since and paginates (`test_events_api.py`, `EventsPage.test.tsx`). |
| FR-54 | Media gateway relays streams; internal camera URLs/credentials stay on the backend. | W §2.5 | 10 | **Phase 10 (D-63/D-65):** MediaMTX gateway relays streams; the backend registers a stable source-on-demand path per camera and the gateway source is SSRF-validated/IP-pinned; the browser receives only an opaque path + WHEP URL, so camera URLs/credentials stay on the backend (`test_live_playback.py`). |

---

## 2. Non-Functional Requirements

| ID | Requirement | Source | Phase | Verification |
|---|---|---|---|---|
| NFR-01 | Continuous processing while monitoring is active; no dependence on an open browser. | A; G §4.1; W §3.4 | 4, 8 | Integration test — **Phase 4:** worker supervised independently of any session; monitoring plan polled by `vision/supervisor.py`. **Phase 8:** monitoring keeps running (and cameras stay `active`) across browser logout and WebSocket disconnect (`backend/tests/test_multi_camera_isolation.py`). |
| NFR-02 | Processing runs in independent background workers, not HTTP handlers. | A; W §2.2, §3.1 | 4 | Architecture review — **Phase 4:** `python -m vision.runtime`; explicit `CameraManager` ownership/shutdown (`test_manager.py`, `test_supervisor.py`). |
| NFR-03 | Resource isolation: a slow pipeline/encoder must not block other cameras. | G §14.3; W §16 | 4, 8 | **Phase 8:** a blocked camera (its detector stalls) does not block another camera's processing; concurrent cameras have independent queues/buffers/handoff; RSS/CPU measured per camera count (`vision/tests/test_multi_camera.py`, benchmark harness). Isolation is thread-per-camera in one process (D-50). |
| NFR-04 | Bounded frame queues and rolling buffers; no unbounded memory growth over long runs. | G §14.2, §14.4; W §3.4 | 4 | Soak test — **Phase 4:** bounded `FrameQueue` and `RollingFrameBuffer`; `vision/tests/{test_queue,test_buffer}.py`. |
| NFR-05 | Documented backpressure policy (bounded queues, drop stale frames, adaptive sampling). | G §14.2 | 4 | Config + tests — **Phase 4:** explicit drop policy + `degraded` signal (`test_queue.py`, `test_worker.py`). |
| NFR-06 | Measure latency (frame arrival→processing→trigger→publication→evidence→summary) and throughput; no unmeasured "real-time" claims. | G §4.6, §14.1, §16.3; W §15 | 4, 8, 9 | Metrics harness — **Phase 4:** `vision/metrics.py` measures ingest/process FPS, latency, queue/drop counts (`test_metrics.py`). **Phase 8:** optional bounded per-camera latency p50/p95/p99 (D-52) surfaced in the benchmark report. **Phase 9:** harness extended with explicit GPU availability, event-duplication rate, and recovery time (D-58); measured figures in `docs/IMPLEMENTATION_PROGRESS.md` (Phase 9). |
| NFR-07 | Explicit uncertainty handling; conservative labelling for safety-relevant activities. | G §4.5, §8.7 | 5 | Tests |
| NFR-08 | Modular boundaries with defined inputs, outputs, and failure behaviour. | G §15.1; W §12 | all | Review |
| NFR-09 | Configuration externalised (thresholds, zones, sampling, tolerances, evidence durations); record effective config/version per run. | G §15.2; W §15.6 | 3–6 | Config tests |
| NFR-10 | Structured operational logs for state changes, delays, failures, event transitions; logs separate from user timeline; avoid sensitive video in logs. | G §15.4 | all | Log review |
| NFR-11 | Distinguish failure classes (connection, decode, detection, tracking, event, evidence, persistence, dashboard, LLM) and never convert errors into empty successes; bounded retries. | G §15.3 | 3–7 | Fault-injection tests |
| NFR-12 | Reproducibility: preserve model/config/rule versions with events. | G §15.6 | 5, 6 | Review |
| NFR-13 | Start with one camera; benchmark before scaling. | A; G §18; W §3.1 | 4, 8, 9 | **Phase 8:** reproducible benchmark harness `vision/benchmarks/` (`python -m vision.benchmarks`) establishes the one-camera baseline and scales 1/2/4/8 cameras on the target hardware, reporting FPS, latency percentiles, queue depth, drops, RSS, and CPU (`vision/tests/test_benchmarks.py`, D-54). **Phase 9:** same harness extended with GPU/recovery/duplication metrics (D-58). |
| NFR-14 | Modular monorepo structure per `W` §12 (frontend, backend, vision, data). | W §12 | 1 | Layout review |
| NFR-15 | Local-first deployment on the Lenovo Legion 5 (RTX 3060 Laptop 6 GB, 16 GB RAM, EndeavourOS). | W §3.1, §3.2 | 1 | Environment verification — **Phase 8:** benchmark records host CPU/RSS/OpenCV/Python; **this environment was CPU-only (no CUDA/GPU, 16 CPUs, ~15 GiB RAM)**, so GPU figures are not claimed (see `docs/IMPLEMENTATION_PROGRESS.md` limitations). **Phase 9:** GPU reported explicitly as `available:false` with a reason; no GPU performance claimed (D-58, `docs/KNOWN_LIMITATIONS.md`). |

---

## 3. Security and Privacy Requirements

| ID | Requirement | Source | Phase | Verification |
|---|---|---|---|---|
| SEC-01 | Single administrator account; login/logout; session validation; expiration and revocation. | W §5 | 2 | Auth tests |
| SEC-02 | Passwords hashed with Argon2id; no plaintext; credentials never logged or shipped to frontend. | W §5 | 2 | Test + review |
| SEC-03 | Server-side sessions with random unguessable IDs; HTTP-only, SameSite, Secure-under-HTTPS cookies; CSRF protection for state-changing cookie-auth requests. | W §5 | 2 | Security tests |
| SEC-04 | Authorization enforced on every protected REST and WebSocket endpoint, and on all video/snapshot/evidence access. | G §15.5; W §5, §16 | 2, 7, 9 | **Phase 7:** `/api/ws` reuses the session resolver; unauthenticated/revoked clients get an error frame + close 1008 and never a notification (`test_ws_api.py`); review/protection/settings require auth + CSRF for writes. **Phase 9:** exhaustive sweep asserting 401 on every protected route and 403 for state-changing routes without CSRF, plus logout-while-monitoring invalidation and internal-channel isolation (`test_security_verification.py`; D-56). |
| SEC-05 | Rate-limit login attempts. | W §5 | 2 | Rate-limit test |
| SEC-06 | Validate camera configurations and input sources; prevent SSRF via user-controlled stream addresses. | G §15.5 | 3 | Security test — **Phase 3:** configuration-time policy (`backend/tests/test_stream_validation.py`). **Phase 4:** authoritative connection-time IP-literal pinning (`vision/net.py`, `vision/tests/test_net.py`: IPv4/IPv6, mapped, metadata, DNS-change, rejected schemes/credentials). |
| SEC-07 | Protect camera credentials and secrets; keep secrets out of Git. | A; G §15.5; W §5, §16 | 1, 2 | Repo scan + review |
| SEC-08 | Evidence delivered only through authorized backend endpoints; directory not publicly served; safe filenames; no path traversal. | G §15.5; W §6 | 6, 9 | **Phase 6:** authenticated `GET /api/evidence/{id}` (never a static dir); relative-path-only storage resolved inside `EVIDENCE_DIR` with absolute/`..`/drive-letter/escaping-symlink rejection (`app/services/evidence_service.py`, `vision/evidence/paths.py`); `test_evidence_api.py`, `test_evidence_service.py`, `test_evidence_paths.py`. **Phase 9:** corroborated by the security sweep (non-integer evidence ids rejected; stored escaping paths never served; `test_security_verification.py`). |
| SEC-09 | Bind dev services to localhost unless cross-device access is explicitly required; restrict service ports; HTTPS beyond localhost. | W §3.2, §16 | 1, 9 | Config review |
| SEC-10 | Exclude secrets, `.env`, recordings, evidence, runtime logs, virtualenvs, DB files, caches from Git (`.gitignore`). | A; W §6, §12 | 1, 9 | **Phase 1:** `.gitignore` created and reviewed. **Phase 9:** the overly-broad `evidence/` pattern (which also hid the source package `vision/evidence/`) was anchored to `/evidence/` so product source is committed while runtime evidence stays ignored (D-60); verified with `git check-ignore`. |
| SEC-11 | Use authorized footage and consent for demos; define retention/deletion. | G §15.5; W §16 | 9 | **Phase 9:** retention/deletion semantics verified and documented (`docs/OPERATIONS.md` §Evidence retention; `test_retention_verification.py`); no third-party footage is used — the only sample dataset is explicitly synthetic (`docs/EVALUATION.md`). Consent for any real demo footage remains a process step. |
| SEC-12 | Create initial administrator via a controlled setup command / secure env config; no hardcoded default production password. | W §5 | 2 | Setup-command test |
| SEC-13 | Keep coding-agent credentials separate from runtime application credentials. | W §16 | 1 | Process review |

---

## 4. Constraints

| ID | Constraint | Source |
|---|---|---|
| CON-01 | No runtime LLM, generative summaries, or text-generation service; event messages use deterministic templates. | A; W §1, §8, §17 |
| CON-02 | Camera processing and tracking are independent per camera; no cross-camera re-identification. | A; G §3.2, §5.5; W §4 |
| CON-03 | Zones are predefined and camera-specific (no automatic room-layout discovery). | A; G §3.2 |
| CON-04 | Monitoring runs continuously only while explicitly active (start/pause/stop). | A; W §3.4 |
| CON-05 | Preserve evidence snapshots and short clips for relevant events. | A; G §11; W §9 |
| CON-06 | PostgreSQL stores structured application data; video on filesystem. | A; W §6 |
| CON-07 | Keep browser video viewing separate from the analysis pipeline. | A; W §4 |
| CON-08 | Start with one camera; benchmark before scaling. | A; G §18; W §3.1, §19 |
| CON-09 | Do not implement all features at once; small verifiable milestones. | A; W §18, §19 |
| CON-10 | Excluded initially: facial recognition/identity, cross-camera re-ID, emergency-service contact, clinical medical detection, unrestricted NL video understanding, automatic room discovery, guaranteed detection, intent/wrongdoing conclusions. | G §3.2 |
| CON-11 | Avoid Kubernetes, Kafka/Redis (pre-need), vector DB, runtime LLM, from-scratch model training, public registration, multi-tenancy, distributed cloud infra. | W §17 |
| CON-12 | Runtime app must not depend on OpenCode/DeepSeek or any coding-agent availability. | A; W §2.6, §18 |
| CON-13 | Model licenses must be verified before distributing the application. | W §7 |
| CON-14 | Parent-level requirement documents are maintained outside the repo and must not be modified/duplicated without approval. | A |

---

## 5. Acceptance Criteria (functional completion)

From `G` §17. These define functional completion but not numerical accuracy/latency targets.

| ID | Acceptance criterion | Phase | Verification |
|---|---|---|---|
| AC-01 | A user can configure and start multiple camera streams. | 3, 8 | **Phase 8:** backend accepts multiple cameras and monitoring starts one worker per camera up to `VISION_MAX_CONCURRENT_CAMERAS`; exercised concurrently in tests + benchmark (`vision/tests/test_multi_camera.py`, `backend/tests/test_multi_camera_isolation.py`). Live RTSP not tested here (D-50). |
| AC-02 | Each stream is processed continuously while active. | 4 | Integration/soak |
| AC-03 | Events can be generated before the stream ends. | 5 | Integration |
| AC-04 | Each camera has independent tracking and event-processing state. | 4, 8 | **Phase 8:** concurrent cameras keep separate tracker/engine/evidence/handoff instances; events are attributed to the producing camera and one camera's failure/blockage leaves others healthy (`vision/tests/test_multi_camera.py`; D-50). |
| AC-05 | All seven activities have an implemented detection path. | 5 | Per-activity tests |
| AC-06 | Persistent events update over time and complete on observed end conditions. | 5 | State-machine tests |
| AC-07 | Duplicate events are controlled through explicit temporal logic. | 5 | Dedup tests |
| AC-08 | Event records include timestamps, camera attribution, status, and evidence references where available. | 5, 6 | **Phase 6:** `events`/`event_transitions` columns (start/trigger/end times, `camera_id`, status, `rule_version`/`config_version`) + linked `evidence` metadata; `test_event_persistence.py`, `test_events_api.py`. |
| AC-09 | Relevant evidence frames and clips can be inspected. | 6, 7 | **Phase 6:** bytes retrievable via `GET /api/evidence/{id}` (`test_evidence_api.py`). **Phase 7:** dashboard event-detail viewer renders snapshots/clips and supports pin/unpin (`EventDetailPage.test.tsx`, `test_evidence_protection_api.py`). |
| AC-10 | Dashboard displays new events and stream-health changes without manual reload. | 7 | **Phase 7:** authenticated `/api/ws` notifications invalidate REST caches; refetch on reconnect recovers missed updates (`test_ws_api.py`, `RealtimeProvider.test.tsx`). |
| AC-11 | Camera-level and overall summaries are generated from structured events. | 5, 7 | *(OQ-01 resolved → D-09: deterministic aggregation, not LLM)* |
| AC-12 | LLM failure does not stop the core event-detection pipeline. | 5 | *(OQ-01 resolved → D-09: no runtime LLM dependency exists at all; stronger than the criterion)* |
| AC-13 | Stream interruption and recovery are handled explicitly. | 8 | **Phase 8:** bounded reconnect/backoff, prompt stop while connecting/backing off, tracker+engine reset on every (re)connection, terminal failure idles without restart churn (`vision/tests/test_reliability.py`). |
| AC-14 | Performance and detection quality are measured on representative test footage. | 9 | Metrics report — **Phase 8 partial:** pipeline throughput/latency/RSS/CPU measured with a synthetic detector (D-54). **Phase 9:** runtime metrics extended with GPU/recovery/duplication (D-58) and detection-quality tooling built (`backend/app/evaluation/`, D-55) with a clearly-synthetic sample; **no real-footage accuracy was measured** (no labelled footage/camera available) — `docs/EVALUATION.md`, `docs/KNOWN_LIMITATIONS.md`. |
| AC-15 | Known limitations and uncertain detections are documented. | 9 | **Phase 9:** consolidated in `docs/KNOWN_LIMITATIONS.md` (detector person-only, no live video/RTSP, thread-based isolation, CPU-only/no GPU, no real-footage accuracy, security residuals, testing gaps); uncertain detections carry an `uncertain` lifecycle state and are surfaced in the UI (Phase 5/7). |

---

## 6. Conflicts and gaps carried into `OPEN_QUESTIONS.md`

| Ref | Issue | Status | Where |
|---|---|---|---|
| OQ-01 | Runtime LLM summarization (`G` §12, AC-11, AC-12) vs. no-runtime-LLM (`A`, `W` §1/§8, CON-01). | **Resolved → D-09** (no runtime LLM; conflict preserved as a note) | §1.6, AC-11/12 |
| OQ-02 | Event-type identifier casing and count differ (`G` §8 vs. `W` §8). | **Resolved → D-10** (lowercase snake_case; two occupancy types per `G` §8.3) | §1.4 |
| OQ-03 | Occupancy/crowd default threshold and persistence interval unspecified. | **Resolved → D-35/D-36** (configurable defaults; retained-count semantics) | EV-03 |
| OQ-04 | Door-state determination method (classifier vs. geometric) unspecified. | Partially resolved → D-36/D-39 (consumer contract fixed; producer deferred) | EV-04 |
| OQ-05 | Bed/floor region and pose-fall criteria thresholds unspecified. | **Resolved → D-35/D-36** (predefined zones + configurable transition window) | EV-07 |
| OQ-06 | Evidence rolling-buffer size/duration and retention limits unspecified. | **Resolved → D-11** (configurable; defaults are proposals) | FR-35, FR-42 |
| OQ-07 | Latency/throughput numerical targets unspecified (must be established experimentally). | **Resolved → D-58** (measured with the extended Phase 9 harness; targets set empirically) | NFR-06, AC-14 |
| OQ-08 | `docs/PROJECT_GUIDELINES.md`, `API_SPEC.md`, `DATABASE_SCHEMA.md`, `TESTING.md` (named in `W` §12) not yet created. | **Resolved → D-59** (parent docs referenced; `TESTING`/`EVALUATION`/`OPERATIONS`/`KNOWN_LIMITATIONS` created) | Phase 0+ |
| OQ-09 | Vision worker ↔ backend handoff mechanism unspecified. | **Resolved → D-12** (authenticated internal HTTP) | Phase 4/6 |
| OQ-10 | Human-review enablement in initial scope (`G` §3.1 "optional") vs. `W` §11 event-details review status. | **Resolved → D-45** (audited `review_status` mutation, Phase 7) | FR-44 |
| OQ-11 | `G` §5.9/§12 summary generation module vs. no-summary under CON-01. | **Resolved → folded into D-09** (deterministic aggregation) | AC-11 |
| OQ-12 | Multi-camera timeline for AC-01 is in `G` §17, but NFR-13/CON-08 require one camera first. | **Resolved → D-50** (multi-camera in initial acceptance; Phase 8 implemented isolation with a one-camera benchmark first) | AC-01 |
| OQ-13 | Live-view inclusion timing. | **Resolved → D-48** (deferred) and **superseded for live view → D-62–D-65** (Phase 10 opt-in MediaMTX + WebRTC playback) | FR-51, FR-54 |
| OQ-14 | Authoritative connection-time SSRF enforcement (DNS rebinding / redirect pinning) cannot be done by configuration-time URL validation. | **Resolved → D-28** (IP-literal pinning; `hostname` mode is documented residual) | SEC-06, Phase 4 |

---

## 7. Verification method summary

| Method | Applies to |
|---|---|
| Unit tests (Pytest) | Event engine, message templates, timers, ingestion edge cases |
| Integration tests | API, DB, WebSocket, evidence pipeline, auth |
| Fault-injection tests | Disconnection, decode failure, encoding failure, DB unavailability |
| Browser/E2E tests (Playwright) | Dashboard, live updates, auth boundaries |
| Labelled-clip evaluation | Precision/recall/F1 per activity, occupancy accuracy, timing error |
| Benchmark harness | FPS, latency, RAM/GPU, dropped frames, queue depth |
| Manual review | Architecture boundaries, security posture, documentation consistency |

Tests are run per implemented phase; the results are recorded in
`docs/IMPLEMENTATION_PROGRESS.md`. Phase 2 verified the auth/database foundation; Phase 3
verified camera configuration, stream-address validation (SEC-06), the lifecycle state
machine, and the monitoring control plane. Phase 4 verified the independent worker
runtime, connection-time SSRF pinning, bounded ingestion, detection/tracking boundaries,
metrics, and the authenticated worker-health channel. Phase 5 verified the canonical event
contract and lifecycle, entry/exit and occupancy/crowd rules, door/package/motionless/fall
rules (with synthetic inputs for the inputs no detector produces yet), per-camera engine
orchestration and error isolation, camera-config validation (HTTP 422), deterministic
message templates/sanitisation/fallbacks, and worker frame adaptation/reset/finalisation.
Backend **306 passed**; vision **189 passed, 1 skipped** (the skip is the opt-in
real-weights test). No database schema change was made in Phase 5; the Alembic head remains
`0002_cameras`. Phase 6 verified event persistence (idempotent/ordered/immutable), evidence
snapshot/clip capture and authorized serving, and retention/backup-restore (`0003_events_evidence`;
backend **353**, vision **257 passed / 1 skipped**). Phase 7 verified the dashboard, real-time
delivery, and audited review (backend **377**, frontend **27**, and the D-49 WebSocket teardown
fix). Phase 8 verified multi-camera isolation/reliability, configuration-change reconciliation,
per-camera latency percentiles, and the reproducible benchmark harness (backend **385**,
vision **284 passed / 1 skipped**); isolation is thread-per-camera in one process (D-50).
Phase 9 verified the evaluation tooling (matching/metrics/loaders/CLI on the synthetic sample),
the exhaustive security sweep, retention and backup/restore on disposable environments, and the
extended benchmark harness (GPU/recovery/duplication), and added the documentation set
(TESTING/EVALUATION/OPERATIONS/KNOWN_LIMITATIONS). Final totals: backend **456**, vision
**286 passed / 1 skipped**, frontend **27**; ruff/format clean; `alembic check` reports no drift;
backend+vision concurrency subsets stable across three repeats. **No real-footage detection
accuracy, real RTSP camera, GPU, or browser/E2E suite was available** — recorded honestly
(`docs/KNOWN_LIMITATIONS.md`).
