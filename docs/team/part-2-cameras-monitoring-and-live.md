# Part 2 — Cameras, Monitoring Control Plane & Live Playback

**Presenter brief.** This part answers: *How does an operator define a camera, how does the system
decide it is safe to connect to, how is a camera's lifecycle tracked, how is monitoring started and
stopped, and how does opt-in live view work without weakening any of that?* Everything here is on
the **backend**; the actual pixels are decoded in the vision worker (Part 4).

**Code covered:** routes `api/routes/{cameras,monitoring,health,settings}.py`;
services `camera_service.py`, `stream_validation.py`, `lifecycle.py`, `monitoring_service.py`,
`worker_registry.py`, `live_gateway.py`, `live_service.py`, `credential_cipher.py`;
`models/camera.py`; schemas `{camera,monitoring,health,live,settings}.py`;
`repositories/cameras.py`; migrations `0002_cameras.py` and `0004_camera_stream_credentials.py`.

---

## 1. The 60-second summary

- A **camera** is a row with a name, a **redacted** stream reference, an optional encrypted RTSP
  credential pair, `enabled`, a JSON `configuration` (zones/rules — Part 3), and a lifecycle
  `status`.
- Stream references are **SSRF-validated at configuration time** (`stream_validation.py`) and
  **re-validated at connection time** by the worker (Part 4 `net.py`); the backend never stores or
  returns embedded credentials.
- The lifecycle is an explicit **state machine** (`lifecycle.py`): `configured`, `connecting`,
  `active`, `degraded`, `disconnected`, `reconnecting`, `stopped`, `failed`. Notably there is **no
  direct `disconnected → active`** edge — recovery must pass through `reconnecting`/`connecting`,
  which forces the tracker/event-engine reset (FR-08).
- The **monitoring control plane** is a thread-safe, in-memory global state
  (`stopped`/`running`/`paused`) with `start`/`pause`/`stop`. The backend never claims a camera is
  `active`; only the worker's authenticated report can.
- **Staleness is projected at read time** (`effective_status`): a processing camera whose worker
  has not reported within `WORKER_HEARTBEAT_TIMEOUT_SECONDS` (default 15 s) is shown as
  `disconnected` without mutating the row (D-24, D-30).
- **Live playback is opt-in** via MediaMTX + WebRTC/WHEP (D-62–D-65). It is a *separate viewing
  path*: the vision worker keeps its own camera connection, and a gateway outage degrades only live
  view.

---

## 2. Key concepts to explain

| Concept | Where | Why it matters |
|---|---|---|
| SSRF address policy | `stream_validation.py` | Metadata IPs, loopback, link-local, multicast, reserved, unspecified are always blocked; RFC1918/ULA configurable; embedded credentials rejected |
| Redaction | `camera_service.to_read`, `redact_stream_reference` | The API returns scheme/host/port/path only |
| Encrypted, write-only credentials | `credential_cipher.py`, `models/camera.py` | Fernet-encrypted with a key derived from `SECRET_KEY`; API exposes only `has_stream_credentials` |
| Lifecycle state machine | `lifecycle.py` `LEGAL_TRANSITIONS`, `transition`, `PROCESSING_STATES`, `STARTABLE_STATES` | Illegal transitions raise rather than silently corrupting state |
| In-memory control plane | `monitoring_service.py` `MonitoringController` | Monitoring is independent of browser sessions; deliberately no DB access |
| Read-time staleness projection | `monitoring_service.effective_status` | One rule makes the camera list and the monitoring snapshot agree |
| Worker registry | `worker_registry.py` | The backend remembers the last authenticated worker report per camera |
| Opt-in + SSRF-pinned gateway source | `live_service.gateway_source_url`, `live_gateway.py` | Camera source/credentials never reach the browser |

---

## 3. File map

### 3.1 Domain model & schema

| File | What it does |
|---|---|
| `models/camera.py` | `CameraStatus` StrEnum (8 states) + `Camera` (unique name, `stream_reference`, nullable `stream_credentials_encrypted`, `enabled`, indexed `status`, JSON `configuration`). `disconnected` is a *stream* state, never "no activity" |
| `schemas/camera.py` | `CameraCreate`/`CameraUpdate` (write-only `stream_username`/`stream_password`, must be supplied together; `clear_stream_credentials` cannot be combined with new creds), `CameraRead` (redacted, `has_stream_credentials`) |
| `schemas/monitoring.py`, `schemas/health.py`, `schemas/settings.py`, `schemas/live.py` | Response shapes; `live.LivePlaybackInfo` contains only status + opaque path + WHEP URL |
| `repositories/cameras.py` | `add`, `get_by_id`, `get_by_name`, `list_all`, `list_by_statuses`, `save` |

### 3.2 Services

| File | What it does |
|---|---|
| `camera_service.py` | `create_camera`/`update_camera` (name uniqueness, config + stream validation, credential encrypt/set/clear; disabling a processing camera stops it), `to_read` (redaction + **effective** status). Exceptions: `CameraNameConflict`, `InvalidStreamReference`, `InvalidCameraConfiguration` |
| `stream_validation.py` | `validate_stream_reference`, `redact_stream_reference`, `build_source_url`, `validate_stream_host`, `pin_stream_host`, `is_disallowed_address`, `default_resolver`; metadata host/address blocklists |
| `lifecycle.py` | `LEGAL_TRANSITIONS`, `PROCESSING_STATES`, `STARTABLE_STATES`, `coerce_status`, `can_transition`, `transition` (+ `InvalidStateTransition`) |
| `monitoring_service.py` | `MonitoringController` (start/pause/stop), `_transition_cameras`, `start_monitoring`/`pause_monitoring`/`stop_monitoring`, `effective_status`, `monitoring_snapshot` |
| `worker_registry.py` | `WorkerReport`, `WorkerHealthRegistry` (`record`/`get`/`last_seen`/`forget`/`clear`/`snapshot`) |
| `credential_cipher.py` | `encrypt_credentials`/`decrypt_credentials` (`v1:` prefix; key = SHA-256(context ‖ SECRET_KEY); `CredentialError`) |
| `live_gateway.py` | `LiveGateway`: fixed `/v3/*` MediaMTX endpoints; `path_name`, `whep_url`, `health`, `ensure_path`, `remove_path`, `path_status`. Never a general URL fetcher |
| `live_service.py` | `gateway_source_url` (validate + pin + inject creds server-side), `playback_status`, `start_playback`, `on_camera_changed`, `remove_camera` |

### 3.3 Routes

| Route | Auth | Notes |
|---|---|---|
| `GET /api/cameras` | session | list; redacted; effective status |
| `POST /api/cameras` | session + CSRF | 201; 409 duplicate name; 422 invalid/unsafe stream or invalid zones/rules |
| `GET /api/cameras/{id}` | session | 404 if unknown |
| `PATCH /api/cameras/{id}` | session + CSRF | partial update; set/clear credentials; validates zones/rules |
| `GET /api/cameras/{id}/live` | session | read-only live status; never mutates the gateway |
| `POST /api/cameras/{id}/live/start` | session + CSRF | idempotent path (re)registration; never starts monitoring |
| `POST /api/monitoring/{start,pause,stop}` | session + CSRF | legal transition else 409; audits + broadcasts |
| `GET /api/monitoring/status` | session | global state + per-camera effective state + counts |
| `GET /api/health` | none | `ok`/`degraded`; runs `SELECT 1` |
| `GET /api/health/cameras` | none | non-sensitive: count, `by_status`, `{id, status}` only |
| `GET /api/settings` | session | read-only effective policy + storage usage (no secrets) |

---

## 4. How it works end to end

**Registering a camera.** `POST /api/cameras` → `camera_service.create_camera` validates the name,
delegates stream checks to `validate_stream_reference`, delegates configuration checks to
`app.events.zones.validate_camera_configuration` (Part 3), encrypts credentials if a pair is
supplied, stores `status=configured`. A best-effort call to `live_service.on_camera_changed`
registers a gateway path **only if live playback is enabled** (and never fails the request).

**Starting monitoring.** `POST /api/monitoring/start` → `monitoring_service.start_monitoring`
flips the in-memory controller to `running` and moves **enabled, startable** cameras to
`connecting`. The worker (Part 4) polls `GET /api/internal/cameras`, sees `running`, and starts a
worker per camera. Only when the worker has processed a real frame does it `POST
/api/internal/cameras/{id}/state` with `active` (Part 3/4), which the backend persists and
broadcasts.

**Reading status.** Every read goes through `effective_status`: if a camera is in a processing
state but the last worker report/heartbeat is older than the timeout, it is shown `disconnected`.
The row is untouched, so status is a *projection*, not a background job.

**Live view.** `GET /api/cameras/{id}/live` returns a status; `POST .../live/start` asks the
gateway to (re)register a stable path `"<prefix>-cam-<id>"`. `gateway_source_url` reuses the same
SSRF policy as monitoring, pins the validated IP for plain RTSP, and injects decrypted credentials
**only** into the gateway request body. The browser receives only an opaque path + WHEP URL and
sends no cookies to the gateway.

---

## 5. Design decisions worth calling out

- **D-21–D-26** (Phase 3): camera CRUD, redaction, the SSRF policy, the lifecycle state machine,
  the monitoring control plane, and worker-registry-backed status.
- **D-24/D-29/D-30:** the backend is authoritative for state; `active` only from a real processed
  frame; staleness projected at read time.
- **D-27/D-31:** the lifecycle lives in the worker (Part 4); the backend keeps the *legal*
  transitions and the persisted status.
- **D-28:** connection-time SSRF pinning is the authoritative check (worker); config-time
  resolution is off by default to avoid DNS rebinding.
- **D-50:** multi-camera is thread-based per camera inside one worker process; a failing camera does
  not affect others. OS-process-per-camera is a documented future option.
- **D-62–D-65:** live playback is opt-in, uses one stable on-demand path per camera, stores
  credentials encrypted and write-only, and SSRF-hardens the gateway source. URLs set while the
  feature is disabled is a **startup error**, never a silent enable.
- **Migration `0004` downgrade destroys stored credentials** — a deliberate, documented
  consequence.

---

## 6. Honesty & security notes to state plainly

- Camera credentials are write-only: the API never returns them, and a blank `stream_reference` on
  edit means "leave unchanged" (it never echoes the redacted value back as if it were real).
- The gateway pulls the **same** camera independently of the worker, so a weak uplink can show a
  reduced analysis rate while someone watches; the path is source-on-demand, so idle cost is zero.
  This has **not** been measured against a real camera.
- Live playback off by default; when no gateway is configured the UI says so and falls back to
  stored evidence.
- Real-browser WebRTC and (in general) real IP cameras are not claimed in the documentation.

---

## 7. Tests that prove this part

| Test file | Proves |
|---|---|
| `tests/test_camera_api.py` | Camera CRUD, redaction, validation |
| `tests/test_camera_config_api.py` | Zone/rule configuration validation through the API |
| `tests/test_stream_validation.py` | SSRF address policy + redaction |
| `tests/test_lifecycle.py` | Legal/illegal camera transitions |
| `tests/test_monitoring_api.py` | start/pause/stop/status semantics |
| `tests/test_worker_registry.py` | Report storage + staleness projection |
| `tests/test_health_api.py` | health + camera health shapes |
| `tests/test_settings_api.py` | Read-only settings |
| `tests/test_live_playback.py` | Config gating, gateway client/service boundaries, live API |
| `tests/test_multi_camera_isolation.py` | Per-camera isolation/attribution (FR-06, AC-04) |

---

## 8. Likely questions

- *What stops an SSRF?* Blocklists + "validate every resolved address, fail closed" at two points;
  the authoritative one pins the IP literal handed to the decoder.
- *Why is the monitoring flag in memory?* So analysis is independent of any browser session
  (CON-07); the cost is that a restart returns to `stopped` and the worker reconciles stale rows.
- *Can the browser ever see a camera URL or password?* No — redaction on read, opaque gateway path
  on live view, write-only credentials.

## 9. Connects to

- **Part 1** supplies auth/CSRF dependencies, settings, and the DB session.
- **Part 3** owns the zone/rule configuration that `cameras` validates and the internal
  event/state endpoints the worker reports to.
- **Part 4** is the process that connects, decodes, and drives the lifecycle.
- **Part 5** is the UI that creates cameras, edits zones, and opens the live dialog.
