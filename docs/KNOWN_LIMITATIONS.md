# ChronoVision — Known Limitations

**Phase:** 10 (AC-15, W §13 M8: "document known limitations")
**Status:** Current as of Phase 10.

This is the consolidated, honest list of what ChronoVision does **not** do or has **not**
verified. It is deliberately explicit so no reader mistakes implemented scaffolding for
verified capability. Details and decisions are cross-referenced.

## Detection and activity coverage

- **The detector is person-only.** The pretrained YOLO model (default `yolo11n.pt`) detects
  people. There is **no door-state, package, or pose producer**, so:
  - `door_open_too_long` — rule and consumer contract implemented (D-36/D-39), but nothing
    feeds it door state; it stays inactive.
  - `package_left_at_entrance` — needs an object/package class not produced by the detector.
  - `fall_from_bed` — needs pose/bed-posture input; inactive until a pose source is integrated.
  These are documented as deferred inputs, not working features.
- **No real-world accuracy has been measured.** No labelled footage or camera was available, so
  only the evaluation *infrastructure* plus a clearly-synthetic sample exist
  (`docs/EVALUATION.md`). Do **not** claim precision/recall/F1 for real scenarios.
- Activity rules run on simulated/unit inputs and the synthetic benchmark; thresholds
  (occupancy, crowd, fall window, door tolerance) are tunable proposals tuned only in tests,
  not on real footage.

## Live video

- **Live playback is implemented but opt-in, and real-camera browser playback is not verified.**
  Phase 10 provides a MediaMTX + WebRTC (WHEP) viewing path (D-62–D-65) that is disabled unless
  `LIVE_PLAYBACK_ENABLED=true` and both `MEDIAMTX_*` URLs are set. The real MediaMTX **v1.21.3**
  binary and the shipped config were exercised end-to-end against a local `ffmpeg` H.264 loop
  (Control API add/patch/delete + a WHEP `POST 201`/`DELETE 200` handshake), but **no physical
  camera and no real browser** WebRTC session were available. Automated backend/frontend tests use
  a **faked** gateway. Do **not** describe the tests as proof of real-camera playback. See
  `docs/LIVE_PLAYBACK.md` §8.
- **Browser playback practically requires H.264.** MediaMTX forwards the camera's tracks without
  transcoding, so an H.265/HEVC-only camera may negotiate a WHEP session yet fail in the browser
  ("codecs not supported by client" was reproduced with the real binary using a High-profile
  clip; a Constrained-Baseline clip played). Re-encoding is out of scope.
- **No TURN server** is configured; WebRTC across symmetric NAT / restrictive firewalls may fail.
- **RTSPS hostname is validate-only** (pinning would break TLS/SNI): the gateway re-resolves the
  hostname, so DNS rebinding between validation and connect remains the documented D-28 residual.
- **Gateway paths are runtime-only**: the config is mounted read-only, so an idle registration is
  lost on a gateway restart and is recreated by the next `start` call.
- **The Docker Compose service was not run here** (Docker daemon unavailable); MediaMTX was run
  directly from the pinned binary. Compose is documented but not container-verified locally.
- **No real RTSP camera was tested.** The pipeline's connection-time SSRF enforcement, decode
  path, and reconnect logic are exercised with generated clips and unit tests, not a physical
  camera.

## Multi-camera isolation

- Isolation is **thread-based**: multiple cameras are independent worker threads in a single
  vision process (D-50). A failing or blocked camera does not affect the others, but a **hard
  native fault** (e.g. a segfault in a decoder) would still take down the shared process.
  OS-process-per-camera is a documented future option, not implemented.
- The one-camera baseline and scaling numbers come from the **synthetic** benchmark
  (simulated detector); they are not from real cameras (see "Performance").

## Performance

- **CPU-only host; no GPU.** The development/verification host has no CUDA device
  (`torch 2.15.0+cpu`, `cuda.is_available() == False`). GPU utilization/memory is reported
  honestly as `available: false` with a reason; **no GPU performance was measured or claimed**.
- Benchmark figures describe the **pipeline scaffolding** at a configured per-frame detector
  cost with a generated clip — **not** detection accuracy, and **not** a real-time guarantee.
  Timing is machine-dependent.
- Real-footage and real-camera measurements remain unavailable (see above).

## Runtime LLM / summarisation

- **No runtime LLM or generative AI.** Event messages are deterministic templates. The
  guidelines' LLM-based summary wording (AC-11/AC-12) is superseded by deterministic
  aggregation (D-09, OQ-01/OQ-11). LLM prose, if ever required, must be an explicit, separate,
  non-critical offline scope change.

## Security residual

- Configuration-time stream validation cannot defeat DNS rebinding by itself; the authoritative
  check is the worker's connection-time IP-literal pinning (`VISION_STREAM_HOST_MODE=pin`,
  D-28). `hostname` mode is a documented opt-in residual that re-introduces re-resolution.
- Protection is designed for a **single administrator** account; there is no multi-user
  role/permission model.
- Asynchronous evidence retention is explicit/operator-driven
  (`EVIDENCE_RETENTION_ON_REGISTER=false`); there is no built-in scheduler.

## Testing gaps

- No browser/E2E (Playwright) suite; frontend coverage is component-level vitest.
- No real-dataset evaluation run (tooling only).
- Backup/restore and migration-drift are verified on **disposable** local clusters, not against
  a production backup provider or remote object storage.
