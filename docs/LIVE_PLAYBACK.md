# Live Camera Playback (MediaMTX + WebRTC)

**Phase 10 — FR-51 / FR-54; decisions D-62–D-65.**

ChronoVision can show a camera's live picture in the dashboard over WebRTC, using
[MediaMTX](https://mediamtx.org) as a media gateway. It works with **any** RTSP/RTSPS camera
address registered through the normal camera API/UI; nothing is hard-coded to a single camera.

The viewing path is deliberately separate from the analysis path:

```text
Camera (RTSP/RTSPS) ──► vision worker ──► detection/tracking ──► events/evidence
        │
        └────────────► MediaMTX ──WHEP/WebRTC──► browser player
```

* The vision worker keeps pulling the camera and producing events/evidence exactly as before.
  Live playback is **not** required for monitoring, and monitoring does **not** start playback.
* A gateway crash, restart, or misconfiguration degrades **only** live view. Camera management,
  monitoring, events, and evidence keep working (covered by `test_gateway_failure_does_not_break_camera_management`).

> **Verification status.** The feature is implemented and covered by backend integration tests
> and frontend component tests (both use a **faked** gateway). The real MediaMTX **v1.21.3** binary
> was also run locally against the shipped `deploy/mediamtx.yml`: configuration load, Control API
> health/path add/patch/delete, invalid-source rejection, and a full WHEP `POST` → `201 Created` +
> `Location` → `DELETE` handshake were all exercised (using a local `ffmpeg` H.264 loop as the
> camera). A **real camera** and a **real browser** WebRTC session were still not available, so
> end-to-end browser playback is **not** claimed as verified. See
> [Verification](#8-verification-honest-status).

---

## 1. Enabling playback (opt-in)

Playback is disabled by default. Deploying MediaMTX alone never turns it on — two independent
switches must agree:

1. `LIVE_PLAYBACK_ENABLED=true`
2. Both `MEDIAMTX_API_URL` and `MEDIAMTX_WEBRTC_URL` set.

If the URLs are set while the flag is `false`, the application **fails fast at startup** instead
of silently activating a gateway. This is what keeps `cp .env.example .env` (where both URLs are
commented out) safe.

| Variable | Default | Meaning |
|---|---|---|
| `LIVE_PLAYBACK_ENABLED` | `false` | Master opt-in switch. |
| `MEDIAMTX_API_URL` | — | Backend → gateway Control API, e.g. `http://127.0.0.1:9997`. Internal only. |
| `MEDIAMTX_WEBRTC_URL` | — | Browser-facing WebRTC base, e.g. `http://192.168.1.20:8889`. Must be reachable from the operator's browser. |
| `MEDIAMTX_API_USERNAME` / `MEDIAMTX_API_PASSWORD` | empty | Optional HTTP Basic auth for the Control API. |
| `MEDIAMTX_PATH_PREFIX` | `cv` | Gateway paths are `<prefix>-cam-<camera_id>`. |
| `MEDIAMTX_REQUEST_TIMEOUT_SECONDS` | `2` | Control-API request timeout. |
| `LIVE_GATEWAY_CLOSE_AFTER_SECONDS` | `10` | Close the camera connection this long after the last viewer leaves (`0` = keep open). |
| `LIVE_GATEWAY_PIN_HOSTS` | `true` | Pin the validated camera IP literal in the gateway source URL (D-65). |

The dashboard also reads `GET /api/settings` (`live_playback_enabled`) to say honestly whether
live view is configured.

---

## 2. Deploying the gateway

### 2.1 Docker Compose (provided)

The repository ships `deploy/mediamtx.yml` and an opt-in compose service:

```bash
# 1. Configure .env (see .env.example)
#    LIVE_PLAYBACK_ENABLED=true
#    MEDIAMTX_API_URL=http://127.0.0.1:9997
#    MEDIAMTX_WEBRTC_URL=http://<host-or-LAN-IP>:8889
#    # Optional, only for a non-loopback Control API:
#    # MEDIAMTX_API_USERNAME=api
#    # MEDIAMTX_API_PASSWORD=<a strong value>
# 2. Start the gateway (profile `playback` keeps it off by default)
docker compose --profile playback up -d mediamtx
docker compose ps
```

`mediamtx` uses **host networking** so WebRTC can advertise a LAN-reachable ICE candidate and the
backend can reach the Control API on `127.0.0.1:9997`. It is Linux-only; on Docker Desktop use a
bridge network and publish UDP `8189` plus TCP `8889`, then set `webrtcAdditionalHosts` in the
config to the host's reachable address.

The shipped `deploy/mediamtx.yml` grants Control-API access to localhost **anonymously** (the same
default as the stock MediaMTX config: a second `user: any` entry with `ips: ["127.0.0.1", "::1"]`
and the `api` permission). With host networking the backend reaches that API on loopback, so the
empty `MEDIAMTX_API_USERNAME`/`MEDIAMTX_API_PASSWORD` defaults work and nothing has to be injected
into the container. Set both variables (and add a matching `authInternalUsers` entry with a real
password) only if you run the API on a non-loopback interface.

Ports used by the shipped config:

| Port | Purpose | Exposure |
|---|---|---|
| `8889/tcp` | WebRTC/WHEP signalling + media over TCP | browser-facing (LAN) |
| `8189/udp` | WebRTC ICE / media over UDP | browser-facing (LAN) |
| `9997/tcp` | Control API | loopback / internal only |
| `8554/tcp` | RTSP diagnostics (`ffprobe`/`ffplay`) | loopback only |

### 2.2 Standalone MediaMTX

```bash
mediamtx /path/to/chronovision/deploy/mediamtx.yml
```

Install the pinned build (v1.21.3, matching the compose image) to a stable path — not `/tmp`, which
gets cleared and silently breaks live view:

```bash
mkdir -p ~/.local/bin
curl -fsSL -o /tmp/mediamtx.tgz \
  https://github.com/bluenviron/mediamtx/releases/download/v1.21.3/mediamtx_v1.21.3_linux_amd64.tar.gz
tar -xzf /tmp/mediamtx.tgz -C /tmp mediamtx
install -m 0755 /tmp/mediamtx ~/.local/bin/mediamtx
```

`scripts/start_local.sh` starts this binary automatically when `LIVE_PLAYBACK_ENABLED=true` and it
is found on `PATH` or at `~/.local/bin/mediamtx` (use `--no-mediamtx` to skip); `scripts/stop_local.sh`
stops it.

The shipped config permits anonymous Control-API access from localhost, so a standalone run on the
same host as the backend needs no extra environment variable. If you expose the API on another
interface, edit `deploy/mediamtx.yml` to give the API user a real password and set
`MEDIAMTX_API_USERNAME`/`MEDIAMTX_API_PASSWORD` to match. Do **not** leave the API reachable with no
credentials.

### 2.3 HTTPS and mixed content

The WebRTC handshake itself does not need TLS, but browsers block `http://` subresources from an
`https://` page. If the dashboard is served over HTTPS, set `MEDIAMTX_WEBRTC_URL` to `https://…`
and enable `webrtcEncryption` + certificate paths in `mediamtx.yml`.

---

## 3. Using it

1. Register a camera normally (`POST /api/cameras` or the Cameras page). The stream reference must
   be `rtsp://` or `rtsps://` (D-22) — see §4 if the camera needs authentication.
2. Open **Cameras → Live**. The dialog calls `POST /api/cameras/{id}/live/start` (idempotent),
   reads the returned WHEP URL, and negotiates the WebRTC session.
3. Closing the dialog closes the peer connection, deletes the WHEP session, and (after
   `LIVE_GATEWAY_CLOSE_AFTER_SECONDS`) lets the gateway disconnect from the camera.

The player is a minimal WHEP client that uses the browser's native `RTCPeerConnection`. It sends
**no cookies** to the gateway (`credentials: omit`) because the gateway is a separate origin.

### API

| Method | Path | Auth | Notes |
|---|---|---|---|
| `GET` | `/api/cameras/{id}/live` | session | Read-only status; never mutates the gateway. |
| `POST` | `/api/cameras/{id}/live/start` | session + CSRF | Create/refresh the gateway path, then return status. Idempotent; never starts monitoring. |

Response (`LivePlaybackInfo`):

```json
{
  "available": true,
  "state": "connecting",
  "protocol": "webrtc",
  "path": "cv-cam-3",
  "whep_url": "http://192.168.1.20:8889/cv-cam-3/whep",
  "detail": null
}
```

Camera source URLs, hostnames, and credentials are **never** part of this contract.

### States

| `state` | Meaning |
|---|---|
| `unavailable` | Playback disabled, camera disabled, or the gateway is unreachable. `detail` gives a short reason (never a source address). |
| `connecting` | Path registered; no reader/stream yet (or the source is starting). |
| `live` | Gateway reports the path online/ready. |
| `disconnected` | A viewer is attached but the source is not producing frames (camera offline/streaming failure). |
| `error` | The stored credentials could not be decrypted, or the source was rejected by validation. |

---

## 4. Camera authentication (encrypted at rest)

Cameras that require RTSP authentication no longer need embedded `user:pass@` URLs (which D-22
rejects). Store a credential pair separately:

```bash
# Create with credentials (write-only)
curl -X POST http://127.0.0.1:8000/api/cameras \
  -H 'Content-Type: application/json' -H "X-CSRF-Token: $CSRF" -b cookies.txt \
  -d '{"name":"Front Door","stream_reference":"rtsp://192.168.1.50:554/live",
       "stream_username":"operator","stream_password":"<secret>"}'

# Update: set a new pair ...
curl -X PATCH …/api/cameras/3 -d '{"stream_username":"operator","stream_password":"<secret>"}'
# ... or remove it
curl -X PATCH …/api/cameras/3 -d '{"clear_stream_credentials":true}'
```

* The pair is serialised as JSON and encrypted with **Fernet** (AES-128-CBC + HMAC-SHA256).
* The key is derived from `SECRET_KEY` with a domain-separation constant, so no extra secret is
  required. **Rotating `SECRET_KEY` invalidates stored credentials**: they must be re-entered, and
  live playback reports `state: "error"` with "stored camera credentials are unavailable" until
  then. Monitoring/events/evidence are unaffected.
* The ciphertext is the only persisted form. Responses expose only
  `has_stream_credentials: true/false`; the pair is never returned, logged, or included in an
  error message. Only the internal gateway-registration path decrypts it.
* `stream_username` and `stream_password` must be provided together; `clear_stream_credentials`
  cannot be combined with a new pair (HTTP 422).
* The additive migration `0004_camera_stream_credentials` adds a nullable
  `cameras.stream_credentials_encrypted` column. **Downgrading drops the column and destroys the
  stored credentials** (they are not recoverable elsewhere).

---

## 5. Security model

| Concern | Control |
|---|---|
| Opt-in | Two switches; URLs without `LIVE_PLAYBACK_ENABLED=true` fail startup. |
| Authorization | Both live endpoints require an authenticated session; `start` also requires CSRF. |
| SSRF (source) | The camera reference is validated with the same policy as monitoring. For plain RTSP the hostname is resolved, **every** address validated, and one pinned as an IP literal before it reaches the gateway (`LIVE_GATEWAY_PIN_HOSTS=true`). RTSPS with a hostname uses **validate-only** because pinning would break TLS/SNI — a documented residual (same trade-off as `VISION_STREAM_HOST_MODE=hostname`, D-28). |
| Redirects | The gateway path is registered with a validated, IP-pinned camera `source` and never with `source: redirect`, so bypassing validation via a `sourceRedirect` target is not possible (D-65). (`sourceRedirect` is a MediaMTX string option that names the target for a `redirect` source; it is not a "follow redirects" toggle.) |
| Gateway is trusted/internal | `LiveGateway` only requests fixed `/v3/...` endpoints on the operator-configured `MEDIAMTX_API_URL`; it is not a general URL fetcher and cannot be pointed at a camera or arbitrary host. |
| Credential exposure | Credentials are decrypted only in-process and placed in the gateway request body. They are never in API responses, logs, exception messages, or the browser. |
| Browser isolation | The browser receives only `whep_url` + an opaque `cv-cam-<id>` path; no camera address, no credentials, and no session cookie is sent to the gateway. |
| Failure isolation | Every gateway call on camera create/update is best-effort; a gateway outage never fails camera management. |

---

## 6. How registration works

* **Path name:** `"<MEDIAMTX_PATH_PREFIX>-cam-<camera_id>"` — stable, unique per camera, and
  derived only from the numeric id (no camera data). A repeated start refreshes the same path.
* **On camera create/update:** `live_service.on_camera_changed` registers or refreshes the path
  (best-effort). Disabling a camera removes its path.
* **Source-on-demand:** paths are registered with `sourceOnDemand: true`, so an idle camera is not
  connected twice; the gateway pulls only while a viewer is attached.
* **After a backend restart:** existing paths are not re-pushed automatically, but opening the
  Live dialog calls `POST …/live/start`, which re-registers the path. Because the gateway config is
  mounted read-only, Control-API changes are runtime-only and do not persist across a gateway
  restart; the same `start` call recreates them.
* **No duplicate analysis:** the vision worker's capture is separate; live view does not change
  the monitoring plan or per-camera lifecycle.

---

## 7. Troubleshooting

| Symptom | Likely cause | Fix |
|---|---|---|
| UI: "live video playback is not available" | `live_playback_enabled` is false | Set `LIVE_PLAYBACK_ENABLED=true` and both URLs, restart the backend. |
| `state: unavailable`, detail "gateway unavailable (unreachable)" | Backend cannot reach `MEDIAMTX_API_URL` | Check MediaMTX is running, the address/port, and host/network reachability. |
| detail "gateway unavailable (unauthorized)" | Control-API credentials mismatch | If you set `MEDIAMTX_API_USERNAME`/`PASSWORD`, they must match an `authInternalUsers` entry that grants the `api` action. With the shipped config the API is anonymous on loopback, so leave both empty. |
| detail "camera source rejected (loopback address)" | Camera URL points at loopback/metadata | Use the camera's LAN address; those destinations are always rejected (D-22). |
| detail "stored camera credentials are unavailable" | `SECRET_KEY` changed after storing credentials | Re-enter the camera's username/password. |
| Player "rejected playback (HTTP 404)" | Path not registered yet / wrong base URL | Open Live again (calls `start`); verify `MEDIAMTX_WEBRTC_URL` includes the port and no trailing `/whep`. |
| Player "rejected playback (HTTP 401/403)" | Gateway WebRTC auth / CORS | Keep `webrtcAllowOrigins` permissive for the dashboard origin and verify the gateway's user permissions include `read`. |
| Connects but black/never "Live" | ICE cannot reach the host | Ensure UDP `8189` is reachable and the advertised host is correct (`webrtcIPsFromInterfaces` / `webrtcAdditionalHosts`). |
| Works on the host but not another LAN device | `MEDIAMTX_WEBRTC_URL` is `127.0.0.1` | Use the host's LAN IP (or a reverse proxy) in `MEDIAMTX_WEBRTC_URL`. |
| HTTPS dashboard cannot play HTTP gateway | Mixed content | Serve the gateway over HTTPS (`webrtcEncryption`) and use `https://`. |
| Camera shown "disconnected" while the camera works in another app | Gateway cannot log in / stream is H.265-only | Check credentials; browsers generally need H.264 for WebRTC. |

---

## 8. Verification (honest status)

Verified on the development host:

* **MediaMTX v1.21.3 (static binary, real process)** run against the shipped `deploy/mediamtx.yml`:
  * the config loads and the chosen listeners start (`[API] 127.0.0.1:9997`, `[WebRTC] :8889`, ICE
    `:8189`, `[RTSP] 127.0.0.1:8554`); unused servers (`rtmp`/`hls`/`srt`/`playback`/`moq`) stay off;
  * Control API `GET /v3/config/global/get` → `200`;
  * the `LiveGateway` client `ensure_path` creates the path (`POST /v3/config/paths/add/...`), and a
    second call exercises the `PATCH` branch; the stored config is exactly
    `source` (camera URL), `sourceOnDemand: true`, `sourceOnDemandCloseAfter: "10s"`,
    `rtspTransport: "tcp"`;
  * `remove_path` deletes it and is idempotent;
  * an invalid source is rejected by the gateway (`GatewayError`, reason `rejected`);
  * a full WHEP handshake against a local `ffmpeg` H.264 loop: `POST .../whep` → **`201 Created`**
    with `Location: /cv-cam-99/whep/<uuid>` and a valid SDP answer, then `DELETE <Location>` →
    **`200`**.
* **Backend:** `pytest` — see the counts in §8.1. `tests/test_live_playback.py` covers encrypted
  credential round-trip/tamper rejection, write-only credentials, auth + CSRF on both live
  endpoints, state mapping (`unavailable`/`connecting`/`live`/`disconnected`), gateway-failure
  isolation, stable unique paths, cleanup on disable, source validation/pinning
  (loopback/metadata/`::1` rejected), credential injection, RTSPS validate-only behaviour, and the
  MediaMTX `/v3` request/error mapping.
* **Frontend:** `npm test` — **38 passed**, including `LivePlayer.test.tsx` (WHEP offer/answer,
  error reporting, retry, cleanup/DELETE, missing-WebRTC fallback) and page tests for the live
  notice and dialog.
* `npm run typecheck`, `npm run lint`, `npm run format:check` — clean.

**Not verified here (no hardware/service available):**

* A **real IP camera** and a **real browser** WebRTC session. The MediaMTX process and WHEP contract
  *were* exercised, but with a local `ffmpeg` loop and a hand-written SDP offer, not a camera and
  not a browser.
* WebRTC over the public internet / NAT traversal (no TURN server is configured by default).
* RTSPS hostname pinning (validate-only) against a real certificate.
* The Docker Compose service itself (the Docker daemon was not reachable on the development host);
  MediaMTX was run directly from the pinned binary instead.

Do **not** describe the numbers above as evidence of real-camera browser playback; they are
automated checks of the application-side contract plus a real gateway process talking to a
synthetic H.264 source.

### 8.1 Test counts

The counts are recorded in `docs/IMPLEMENTATION_PROGRESS.md` (Phase 10) and are reproduced by
running the backend and vision suites in separate processes:

```bash
cd backend && ./.venv/bin/python -m pytest -q
cd vision  && ./.venv/bin/python -m pytest -q
cd frontend && npm test
```

---

## 9. Limitations

* **H.264 is the practical codec for browser WebRTC.** H.265/HEVC-only cameras may not play without
  gateway re-encoding, which is out of scope.
* **No TURN server.** The shipped config uses interface addresses and optional STUN only; symmetric
  NAT or restrictive firewalls may prevent playback.
* **RTSPS hostname residual:** TLS/SNI requires the real hostname, so the gateway re-resolves it;
  DNS rebinding between validation and connect is the same documented residual as D-28.
* **Gateway paths are not persisted** by the shipped read-only config mount; they are recreated on
  demand. This is intentional (the backend stays authoritative) but means MediaMTX restart loses
  idle registrations until the next `start`.
* **Resource contention:** MediaMTX and the vision worker both pull the same camera; a very weak
  camera or uplink may show reduced analysis frame rate while someone is watching.