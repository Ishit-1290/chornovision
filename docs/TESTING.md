# ChronoVision — Testing Guide

**Phase:** 10 (adds generic live-playback verification; testing/evaluation baseline from Phase 9)
**Status:** Current. Every command below was executed on the development host and its result is
recorded in `docs/IMPLEMENTATION_PROGRESS.md` (Phases 9–10).

This document is the single, reproducible reference for running ChronoVision's checks. It
states the prerequisites, the exact commands, what each command covers, and the honest
limitations (a test is only claimed to pass if it was actually run).

## Prerequisites

| Requirement | Needed for | Notes |
|---|---|---|
| Python 3.11+ (verified 3.14.7) | backend + vision tests | |
| `backend/.venv` created with `pip install -e ".[dev]"` | backend tests, ruff, alembic | CV packages optional |
| Node.js 20+ / npm (verified Node 26, npm 12) | frontend tests | `cd frontend && npm install` first |
| PostgreSQL 15+ client/server binaries | backup/restore + migration-drift scripts | verified PostgreSQL 18.6 |
| `docker compose` (optional) | running the real services | not needed for the test suites |

The backend and vision test suites use **in-memory SQLite** and never require a running
PostgreSQL. The backup/restore and migration-drift scripts start their own **disposable**
`initdb` cluster under a temporary directory and remove it on exit; they never touch the
application database or evidence directory.

## One-command verification

```bash
# From the repository root.
scripts/verify.sh
```

`scripts/verify.sh` runs, in order:

1. backend tests (`pytest`)
2. vision tests (`pytest vision/tests`)
3. backend ruff lint + format check
4. vision ruff lint + format check
5. frontend tests, lint, format check, and typecheck (skipped with a notice if
   `frontend/node_modules` is absent)
6. Alembic offline render (`alembic upgrade head --sql`), no database required

It exits non-zero on the first failure. The two database-backed scripts are run separately
because they start a PostgreSQL cluster:

```bash
scripts/verify_migrations.sh       # live "alembic upgrade head" + "alembic check" (drift)
scripts/verify_backup_restore.sh   # pg_dump/pg_restore round trip + evidence accessibility
```

## Manual commands (what `verify.sh` runs)

### Backend

```bash
cd backend
./.venv/bin/python -m pytest            # all backend tests
./.venv/bin/ruff check .                # lint
./.venv/bin/ruff format --check .       # formatting
```

### Vision worker

Run the vision tests **from the repository root** so the top-level `vision` package is
importable, using the backend virtualenv (the CV packages live there):

```bash
backend/.venv/bin/python -m pytest vision/tests
backend/.venv/bin/ruff check  --config backend/pyproject.toml vision
backend/.venv/bin/ruff format --check --config backend/pyproject.toml vision
```

> **Do not** run the backend and vision suites in a single `pytest` invocation. They set up
> different process environments (the backend tests load validated application settings from
> environment variables and override the database dependency; the vision tests exercise a
> separate worker package). One `pytest` process mixing them can leak configuration between
> the two and produce spurious failures. Run them as separate commands, as above — that is
> the documented and verified method.

### Frontend

```bash
cd frontend
npm test           # vitest (jsdom)
npm run lint       # eslint
npm run format:check
npm run typecheck  # tsc --noEmit
npm run build      # production build (tsc + vite build)
```

### Migrations (offline and live)

```bash
# Offline DDL render — no database connection required:
cd backend && \
  POSTGRES_PASSWORD="offline-render-password-not-a-real-secret" \
  SECRET_KEY="offline-render-secret-key-$(printf 'e%.0s' {1..32})" \
  INTERNAL_API_TOKEN="offline-render-internal-token-$(printf 'f%.0s' {1..32})" \
  ENVIRONMENT=test \
  ./.venv/bin/alembic upgrade head --sql

# Live drift check on a disposable cluster (ORM models vs migrated schema):
scripts/verify_migrations.sh
```

## Optional / environment-gated checks

```bash
# Real YOLO weights (downloads yolo11n.pt; not run in CI):
VISION_TEST_WEIGHTS=1 backend/.venv/bin/python -m pytest \
  vision/tests/test_integration_pipeline.py::test_real_yolo_loads_and_runs

# Runtime benchmark (see docs/TESTING.md §"Benchmarks" and docs/OPERATIONS.md):
POSTGRES_PASSWORD=... SECRET_KEY=... INTERNAL_API_TOKEN=... ENVIRONMENT=test \
  backend/.venv/bin/python -m vision.benchmarks --cameras 1,2,4 --duration 8 \
  --detector-cost-ms 20 --output /tmp/benchmark.json

# Event evaluation on the clearly-synthetic sample (see docs/EVALUATION.md):
cd backend
./.venv/bin/python -m app.evaluation \
  --labels ../evaluation/sample/synthetic_labels.json \
  --detected ../evaluation/sample/synthetic_detected.json --window-hours 2
```

## Concurrency-sensitive tests

These exercise threads/queues and are repeated when validating:

- vision: `test_multi_camera.py`, `test_reliability.py`, `test_event_handoff.py`,
  `test_metrics.py`
- backend: `test_event_broadcaster.py`, `test_multi_camera_isolation.py`,
  `test_worker_registry.py`

```bash
backend/.venv/bin/python -m pytest vision/tests/test_multi_camera.py \
  vision/tests/test_reliability.py vision/tests/test_event_handoff.py \
  vision/tests/test_metrics.py
cd backend && ./.venv/bin/python -m pytest tests/test_event_broadcaster.py \
  tests/test_multi_camera_isolation.py tests/test_worker_registry.py
```

## What is covered (Phase 9 additions)

- `backend/tests/test_evaluation.py` — matching rules, per-activity/timing/occupancy metrics,
  loaders, and the evaluation CLI (see `docs/EVALUATION.md`).
- `backend/tests/test_security_verification.py` — exhaustive auth sweep, CSRF, logout while
  monitoring, WebSocket auth, internal channel, SSRF, evidence-path confinement.
- `backend/tests/test_retention_verification.py` — expiry, disk cap oldest-first, protected
  evidence, `blocked_by_protection`, file-unlink/row-retention, and retention-not-on-register.
- `vision/tests/test_benchmarks.py` — GPU reporting, duplication rate, recovery time, and the
  existing camera/encode/handoff benchmarks.

## What is covered (Phase 10 additions)

- `backend/tests/test_live_playback.py` — encrypted-credential round-trip/tamper rejection,
  write-only credentials, auth + CSRF on both live endpoints, state mapping, gateway-failure
  isolation, stable unique paths, cleanup on disable, gateway-source SSRF validation/pinning,
  credential injection, RTSPS validate-only, and MediaMTX `/v3` request/error mapping (fake gateway).
- `frontend/src/components/LivePlayer.test.tsx` — WHEP offer/answer, error reporting, retry,
  cleanup/`DELETE`, and the missing-WebRTC fallback (a `RTCPeerConnection` test double).
- A real MediaMTX **v1.21.3** process against `deploy/mediamtx.yml` was exercised manually
  (Control API add/patch/delete + a WHEP `201`/`DELETE 200` handshake with a local `ffmpeg` H.264
  loop). This is **not** part of `verify.sh`, and **no real camera or browser** was tested — see
  `docs/LIVE_PLAYBACK.md` §8.

## Limitations of the test suite (honest)

- No real RTSP camera, GPU, or branded sensor is available on the development host; tests and
  benchmarks that would need them are skipped or explicitly report the hardware as unavailable
  (see `docs/KNOWN_LIMITATIONS.md`).
- The door/package/pose rules have no detector producer yet, so their end-to-end behaviour is
  not exercised with real objects (rule-level tests only).
- There is no browser/E2E (Playwright) suite; frontend coverage is component-level Vitest.
- Benchmark numbers are machine-dependent and describe pipeline scaffolding, not detection
  accuracy.
