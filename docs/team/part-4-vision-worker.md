# Part 4 — The Vision Worker (Computer-Vision Pipeline)

**Presenter brief.** This part answers: *How does video actually get analyzed?* The vision worker
is an **independent background process** — never an HTTP handler, never dependent on a browser —
that connects to cameras, decodes frames, detects and tracks people, evaluates temporal rules into
events, captures evidence, and hands everything to the backend. This is the largest and most
"engineered" part of the codebase.

**Code covered:** all of `vision/` (excluding `vision/tests/`, summarized at the end).

---

## 1. The 60-second summary

- `python -m vision.runtime` starts the process. It reconciles stale camera state with the
  backend, then a **supervisor** polls the backend for the monitoring plan and **converges** a set
  of per-camera workers.
- Each camera is a `CameraWorker`: one **worker thread** runs the lifecycle + processing loop, and
  one **capture thread** decodes frames into a **bounded queue** so a slow detector can never grow
  memory without bound.
- The processing loop is: **decode → tag → sample → (optionally rotate for the detector) → YOLO
  detect → ByteTrack track → map boxes back → temporal event engine → evidence + handoff**. It ends
  with a `FrameObservation`; the same frames feed the rolling buffer and evidence capture.
- The **temporal event engine** is pure Python (no decoder/DB/network). One rule per activity;
  rules never stop each other; `reset()` on every new connection so no event is inferred across a
  gap. Door/package/pose rules exist but stay **inactive** until a producer exists.
- **Evidence** is captured off the frame loop by a dedicated encoder thread; a bounded queue + disk
  spool bounds memory; failures are explicit `failed` records, never silent gaps.
- **Handoff** to the backend is at-least-once + idempotent over authenticated internal HTTP with a
  bounded queue and a per-camera disk spool.
- Connection-time **SSRF pinning** (`net.py`) is the authoritative address check.

---

## 2. Key concepts to explain

| Concept | Where | Why it matters |
|---|---|---|
| Worker ≠ HTTP handler | `camera_manager/worker.py`, NFR-02 | Long-running analysis must not block requests |
| One worker thread + one capture thread | `worker.py` | Decoupling decode from inference; bounded queue absorbs jitter |
| Bounded queue, drop-oldest | `ingestion/queue.py` | Flat memory under load; drops are counted, and a sustained drop ratio → `degraded` |
| Rotation for detection only | `ingestion/rotation.py`, `worker.py` | Sideways feeds are rotated for the detector, boxes mapped back; zones stay in the original frame (D-72) |
| Detector emits observations, never events | `detection/detector.py` | Clean separation (FR-11) |
| Track IDs are camera-local, not identities | `tracking/tracker.py` | No cross-camera re-ID claim (FR-13) |
| Rules are isolated | `event_engine/engine.py` `_run` | One bad rule can't stop the others or the loop |
| Reset on reconnect | `worker.py` `_run_session` | No event across a stream gap; person at stream start is never "entering" (FR-08) |
| Non-blocking sink | `event_engine/types.py` `EventSink`, `evidence/coordinator.py` | Encoding/network never run on the frame thread |
| Bounded everything | buffer, queue, handoff, encoder queue, `_trim_states` | NFR-04 |
| At-least-once + idempotent delivery | `event_handoff.py`, `internal_client.py` | Safe retries |

---

## 3. File map

### 3.1 Entry point & orchestration

| File | What it does |
|---|---|
| `runtime.py` | `main(argv)`: settings → logging → `InternalClient` → `Supervisor`+`CameraManager` → startup `reconcile()` → signal handlers → `supervisor.run()` → `shutdown()`. `_build_worker`/`_build_coordinator` wire source/detector/tracker/engine/evidence |
| `config.py` | `VisionSettings` (`VISION_*`), `StreamHostMode` (PIN/HOSTNAME), `TrackerKind` (BYTETRACK/IOU); security values delegate to `app.config` |
| `supervisor.py` | `Supervisor.reconcile()` — poll plan, `manager.ensure(cameras)`; `run(stop_event)`; a temporarily unreachable backend is logged, not fatal |
| `health.py` | `WorkerHealth` + non-sensitive detail codes; reuses the backend's `CameraStatus` (no vocabulary drift) |

### 3.2 Camera lifecycle

| File | What it does |
|---|---|
| `camera_manager/manager.py` | `CameraManager.ensure` (declarative, lock-guarded): stops removed/dead/config-changed workers (config change ⇒ restart, D-53), starts up to `max_concurrent`, defers excess with a warning |
| `camera_manager/worker.py` | `CameraConfig`, `FrameObservation`, `CameraWorker` — state machine, reconnect/backoff, report/heartbeat, `_run_session`, `_capture_loop`, `_process_loop`, `_observe_events`, `_evaluate_degraded`. Terminal failures idle (no hot loop) |

### 3.3 Ingestion

| File | What it does |
|---|---|
| `ingestion/sources.py` | `RawFrame`, `Frame`, `FrameSource`, `OpenCVFrameSource` (the **only** decoder; `open/read/close` serialised by a lock to avoid a use-after-free segfault), `tag_frame` |
| `ingestion/queue.py` | `DropPolicy`, `FrameQueue` (bounded, thread-safe, drop-oldest default, counters) |
| `ingestion/prepare.py` | `is_valid_frame`, `SamplingPolicy` (target FPS), `prepare_frame`/`resize_width` (aspect-preserving) |
| `ingestion/rotation.py` | `normalize_rotation`, `rotated_size`, `rotate_frame`, `map_bbox_from_rotated` (exact inverse quarter-turn) |

### 3.4 Detection & tracking

| File | What it does |
|---|---|
| `detection/detector.py` | `Detection`, `Detector` protocol, `NullDetector` (test double), `YoloDetector` (lazy Ultralytics import; person-only by default) |
| `tracking/tracker.py` | `Track`, `Tracker` protocol, `ByteTrackTracker` (supervision.ByteTrack), `IoUTracker` (dependency-free fallback) |

### 3.5 Temporal event engine

| File | What it does |
|---|---|
| `event_engine/types.py` | `EntityObservation`, `DoorState`/`DoorStateObservation`, `Posture`/`PoseObservation`, `EngineFrame`, `EventSink`/`NullEventSink` |
| `event_engine/base.py` | `BaseRule`, deterministic `EventIdFactory` (UUIDv5), `ActiveEvent`, severity/certainty helpers, transition producers (`_open`/`_update`/`_resolve`/`_cancel`/`_mark_uncertain`), `_trim_states` |
| `event_engine/engine.py` | `TemporalEventEngine` (`from_camera`, `observe`, `on_stream_end`, `reset`, `_run`/`_publish`) + `build_engine` |
| `event_engine/geometry.py` | Normalised geometry: `box_bottom_center`, `point_in_polygon`, `in_zone`, `boundary_side`/`boundary_offset` |
| `rules/boundary.py` | `BoundaryCrossingRule` — entry/exit (instant events); needs the entrance boundary; confirm-frames + cooldown |
| `rules/occupancy.py` | `OccupancyRule` — `room_occupancy_change` (instant) and `crowd_forming` (persistent, with hysteresis) |
| `rules/motionless.py` | `MotionlessRule` — always built; anchor-displacement based; absence marks uncertain, never completes |
| `rules/fall.py` | `FallRule` — **waiting for a pose producer**; potential fall, never medical |
| `rules/door.py` | `DoorOpenRule` — **waiting for a door-state producer**; holds last state across brief unknowns |
| `rules/package.py` | `PackageRule` — **waiting for package-class detections**; stationary logic + proximity ⇒ low certainty |

### 3.6 Evidence

| File | What it does |
|---|---|
| `evidence/paths.py` | `build_relative_path`, `sanitize_component`, `is_safe_relative_path`, `resolve_within_root` — names never derived from untrusted data |
| `evidence/encoding.py` | `EvidenceEncoder` protocol, `OpenCVEncoder` (snapshot `imwrite`, clip `VideoWriter`), lazy OpenCV |
| `evidence/store.py` | `EvidenceRecord`, `EvidenceStore.save_snapshot`/`save_clip`/`_write` — explicit `failed` on error |
| `evidence/manager.py` | `EvidencePolicy`, `EvidenceManager` — pre/post windows from the rolling buffer, bounded encoder thread, `_Collection`/`_EncodeJob`, counters |
| `evidence/coordinator.py` | `EvidenceCoordinator.publish` — handoff first, then capture; delegates `on_frame`/`on_stream_end`/`reset` |

### 3.7 Handoff, internal comms, SSRF, support, benchmarks

| File | What it does |
|---|---|
| `event_handoff.py` | `EventHandoff` — bounded deque + deliverer thread + bounded per-camera disk spool; transient vs permanent error handling; counters |
| `internal_client.py` | `InternalClient` — plan fetch, state report, reconcile, event submit, evidence register; `X-Internal-Token`; transient vs `PermanentInternalError` |
| `net.py` | `resolve_and_validate` → `PinnedTarget` (validate every address, fail closed, pin IP for plain RTSP) |
| `buffer.py` | `RollingFrameBuffer` — bounded by count **and** approximate bytes; oversized item refused |
| `metrics.py` | `StreamMetrics` — thread-safe counters + optional bounded latency ring → p50/p95/p99 |
| `benchmarks/harness.py`, `benchmarks/__main__.py` | Reproducible synthetic benchmark: real worker/manager, real OpenCV decode of a generated clip, simulated detector; FPS, latency percentiles, queue depth/drops, RSS/CPU, GPU availability, handoff duplication, recovery time |

---

## 4. How it works end to end (one camera)

1. **Startup:** `reconcile()` clears stale processing rows; the supervisor polls the plan.
2. **Ensure:** when monitoring is `running`, `CameraManager.ensure` creates a `CameraWorker`.
3. **Connect:** `_validate_target` → `net.resolve_and_validate` (SSRF, pin) → `OpenCVFrameSource.open()`
   → read first frame; report `connecting`.
4. **Session:** reset tracker + engine + evidence + buffer (FR-08); start the capture thread.
5. **Capture:** decode → tag (`tag_frame`) → sample (`SamplingPolicy`) → bounded `FrameQueue`.
6. **Process:** dequeue → validate → `prepare_frame` → if a rotation is configured, `rotate_frame`
   for the detector then `map_bbox_from_rotated` → `YoloDetector.detect` → `tracker.update` →
   build `EngineFrame` → `engine.observe`. The **original** frame goes to the rolling buffer and
   `evidence.on_frame`. First processed frame ⇒ report `active`; sustained drops ⇒ `degraded`.
7. **Events:** each rule returns `EventTransition`s; the engine publishes them to the
   `EvidenceCoordinator`, which enqueues a handoff event and starts an evidence capture.
8. **Evidence:** after the post-event window (or on stream end), the encoder thread writes a
   snapshot + clip (rotated to match the view) and the record is enqueued for handoff.
9. **Handoff:** the deliverer thread POSTs events and evidence to the backend; transient errors
   retry with backoff and can spill to a bounded per-camera disk spool.
10. **Disconnect:** `disconnected` → `reconnecting` (capped exponential backoff) → repeat; exhausted
    attempts or an insecure target ⇒ terminal `failed` and the worker idles.

---

## 5. Design decisions worth calling out

- **D-27/D-31/D-33:** worker-owned lifecycle, reconnect/backoff, bounded queue + drop policy with
  observable counters (`degraded` on a sustained drop ratio).
- **D-28:** connection-time SSRF pinning is enforced here (with `HOSTNAME` mode as a documented
  residual for TLS/SNI).
- **D-32:** lazy YOLO loading and per-worker model release.
- **D-34/D-39:** rules with missing producers stay inactive; posture is never inferred from a
  bounding box.
- **D-50/D-51:** thread-per-camera in one process; per-camera spool `handoff-<camera_id>-*.json`;
  OS-process-per-camera remains a future option (a native decoder fault still takes down the shared
  process).
- **D-53:** a configuration change stops and recreates only that camera's worker.
- **D-72/D-74:** one per-camera `configuration.rotation` straightens detection input, the live view
  (Part 5), and newly-encoded evidence; stored zone geometry stays in the original frame.
- **D-54/D-58:** the benchmark harness measures *pipeline scaffolding at a configured detector
  cost*, never accuracy; GPU availability is reported explicitly.

---

## 6. Honesty & limitations to state plainly

- **Person-only detector today.** Entry/exit, occupancy/crowd, and motionlessness can run; door,
  package, and fall rules are built only when their zone is configured and **stay inactive** without
  their producers. No end-to-end door/package/fall detection is claimed.
- Motionlessness is **not** a medical conclusion; quiet sitting/sleeping are documented confounders.
- Fall is a **potential** fall, never a diagnosis.
- The spool is best-effort, **not a WAL**: a crash exactly at the wrong moment can lose one item.
- `VISION_STREAM_HOST_MODE=hostname` re-introduces re-resolution (documented residual).
- Multi-camera isolation is **thread-based**; a hard native fault still crashes the shared process.
- Benchmarks use a **synthetic detector** and report machine-dependent numbers; real detection
  accuracy and real RTSP/GPU results are not claimed.

---

## 7. Tests (one line each, `vision/tests/`)

`test_runtime` (wiring), `test_supervisor` (plan loop), `test_manager` (ensure/stop), `test_worker`
(lifecycle), `test_reliability` (reconnect/backoff/terminal), `test_multi_camera` (isolation),
`test_sources`, `test_queue`, `test_prepare`, `test_rotation`, `test_net` (SSRF pinning),
`test_detector_tracker`, `test_buffer`, `test_metrics`, `test_event_engine`,
`test_event_boundary`/`occupancy`/`motionless`/`fall`/`door`/`package`, `test_worker_events`,
`test_worker_evidence`, `test_evidence_manager`/`coordinator`/`store`/`paths`,
`test_event_handoff`, `test_internal_client`, `test_benchmarks`, and
`test_integration_pipeline` (optional real YOLO). Fakes live in `vision/tests/fakes.py`.

---

## 8. Likely questions

- *Why a separate process?* NFR-02/CON-02: analysis must not be an HTTP handler, and it must keep
  running without a browser.
- *How is memory bounded?* Every queue/buffer/spool has a cap; overflow is counted or produces an
  explicit failure.
- *What happens when the detector is slow?* The bounded queue drops stale frames and reports
  `degraded`; the capture thread keeps the latest data flowing.
- *How do sideways cameras work?* `configuration.rotation` rotates only the detector input and maps
  boxes back; zones/rules/evidence stay consistent (D-72/D-74).

## 9. Connects to

- **Part 1** supplies the internal token and settings; the worker uses the same SSRF policy
  (`vision/net.py` reuses `app.services.stream_validation`).
- **Part 2** owns the cameras and the monitoring plan the worker polls; the lifecycle vocabulary is
  shared.
- **Part 3** owns the event contract (`app/events`) the engine imports and the internal endpoints it
  POSTs to.
- **Part 5** displays the events/evidence this part produces and exposes the rotation setting the
  worker reads.
