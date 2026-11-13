# Part 1 — Backend Foundation, Configuration & Security

**Presenter brief.** This part answers: *How does the backend start, how is it configured, and how
is every request authenticated and protected?* It is the substrate the other four parts stand on:
nothing else in the system is reachable until this part has validated configuration, opened the
database, and enforced auth.

**Code covered:** `backend/app/{__init__,main,config,db,utils}.py`,
`backend/app/api/{router,errors}.py`, all of `backend/app/auth/`,
`backend/app/services/{auth_service,admin_service}.py`,
`backend/app/models/{base,user,auth_session,audit_log}.py`,
`backend/app/repositories/{users,sessions,audit}.py`,
`backend/app/schemas/{auth,user}.py`, the `create-admin` half of `backend/app/cli.py`,
`backend/migrations/`, `.env.example`, `backend/pyproject.toml`, `backend/alembic.ini`,
`backend/tests/conftest.py`.

---

## 1. The 60-second summary

- The app is a **FastAPI + SQLAlchemy 2.0 + Pydantic v2** ASGI app (`app.main:app`). The database
  engine is created **lazily**, so importing the app does not require a reachable PostgreSQL.
- Settings come from a **validated `Settings` singleton** that **fails fast** on missing,
  short, or placeholder secrets. There is exactly one place secrets are read.
- Auth is **single-administrator**: Argon2id password hashes, server-side sessions with random
  tokens **stored only as SHA-256 hashes**, HttpOnly session cookie + a readable CSRF cookie,
  login rate limiting, and a constant-time-compared internal token for the worker channel.
- The database has **four migrations**, applied by Alembic whose URL is derived from settings,
  never from a committed file.
- Every error leaves the API in one shape — `{"detail": ...}` — and never leaks configuration,
  secrets, stream URLs, or credentials.

---

## 2. Key concepts to explain

| Concept | Where | Why it matters |
|---|---|---|
| Fail-fast, validated settings | `config.py` `Settings`, `get_settings()` | Misconfiguration is a startup crash, not a runtime surprise (e.g. `debug=true` in production is rejected) |
| Origin precedence | `config.py` model config | constructor args > environment > `<repo>/.env` > `backend/.env`; later files win |
| Lazy engine lifecycle | `db.py` `get_engine()`, `get_session_factory()`, `get_db()`, `dispose_engine()` | Tests swap in SQLite; production connects only when used |
| `SecretStr` everywhere | `config.py` | Secrets never appear in logs/repr |
| Hashed-at-rest tokens | `auth/security.py` `hash_token`; `models/auth_session.py` | A DB leak does not yield usable session/CSRF tokens |
| Constant-time comparison | `auth/security.py` `tokens_equal`, `auth/internal.py` | Avoids timing-based token probing |
| Two cookie types | `auth/cookies.py` | Session cookie is HttpOnly; CSRF cookie is deliberately readable by JS |
| Session rule set shared by REST and WS | `auth/dependencies.py` `resolve_session` | The WebSocket cannot be authenticated by a weaker check than REST |
| Timing-equalised login | `services/auth_service.py` `_dummy_password_hash`, `authenticate` | Unknown username still costs an Argon2 verify, so response time does not reveal account existence |
| Audit trail without secrets | `models/audit_log.py`, `repositories/audit.py` | Actions are recorded (`login`, `login_failed`, …); the `metadata` JSON must never hold secrets |

---

## 3. File map

### 3.1 Entry point, configuration, database

| File | What it does |
|---|---|
| `app/main.py` | `create_app()` app factory (title/version/lifespan), `configure_logging`, `lifespan` disposes the engine on shutdown; module-level `app` |
| `app/config.py` | `Environment`/`LogLevel`/`SameSite` enums, `Settings`, validators (`_validate_secret`, `_check_environment`, `_check_live_playback`), properties (`is_production`, `allowed_stream_schemes`, `database_url`), `get_settings()`/`clear_settings_cache()` |
| `app/db.py` | cached engine + session factory, `get_db()` FastAPI dependency, `dispose_engine()` |
| `app/utils.py` | `utcnow()`, `ensure_utc()` (naive datetimes are treated as UTC — SQLite compatibility) |
| `app/api/router.py` | `api_router` composing health, auth, cameras, monitoring, events, evidence, settings, realtime, internal |
| `app/api/errors.py` | `register_exception_handlers`: `StarletteHTTPException` → `{"detail": …}` preserving status/headers; `RequestValidationError` → 422 `{"detail": "Validation error", "errors": [...]}` |

### 3.2 Auth & security (`app/auth/`)

| File | What it does |
|---|---|
| `security.py` | `hash_password`/`verify_password`/`password_needs_rehash` (Argon2id), `generate_session_token`/`generate_csrf_token`, `hash_token` (SHA-256), `tokens_equal` (`hmac.compare_digest`) |
| `cookies.py` | `set_session_cookie` (HttpOnly), `set_csrf_cookie` (readable by JS), `clear_auth_cookies` |
| `dependencies.py` | `AuthContext`, `resolve_session`, `get_auth_context`, `get_current_user`, `enforce_csrf`, `get_csrf_auth_context`, `get_login_limiter`/`reset_login_limiter` |
| `internal.py` | `INTERNAL_TOKEN_HEADER = "X-Internal-Token"`, `require_internal_token` (constant-time; required even on loopback) |
| `rate_limit.py` | `LoginRateLimiter` (fixed window per host+username), `login_rate_limit_key` |

### 3.3 Auth services, models, repositories, schemas

| File | What it does |
|---|---|
| `services/auth_service.py` | `authenticate`, `create_session`, `revoke_session`, dummy-hash timing equalisation |
| `services/admin_service.py` | `create_admin` + `AdminError`/`InvalidUsernameError`/`WeakPasswordError`/`UserExistsError` |
| `models/base.py` | `Base(DeclarativeBase)`; `Base.metadata` is the Alembic target |
| `models/user.py` | `User` |
| `models/auth_session.py` | `UserSession` (hashed tokens, expiry, revocation) |
| `models/audit_log.py` | `AuditLog` (`metadata` JSON mapped to attribute `log_metadata`) |
| `repositories/{users,sessions,audit}.py` | Parameterised queries only; `audit.record(...)` never receives secrets |
| `schemas/{auth,user}.py` | `LoginRequest/Response`, `MessageResponse`, `UserRead` (no hashes) |

### 3.4 CLI (admin provisioning) and migrations

| File | What it does |
|---|---|
| `app/cli.py` → `create-admin` | Reads the password from stdin / `CHRONOVISION_ADMIN_PASSWORD` / interactive `getpass` — **never** a plain-text flag; exit codes 0/1/2 |
| `migrations/env.py` | Loads the DB URL from `app.config` (no committed credentials); `compare_type=True`, `compare_server_default=True` |
| `migrations/versions/0001_initial_auth.py` | `users`, `sessions`, `audit_logs` + FK rules |
| `migrations/versions/0002_cameras.py` | `cameras` (+ status/enabled/JSON configuration) — *introduced here, detailed in Part 2* |
| `migrations/versions/0003_events_evidence.py` | `events`, `event_transitions`, `evidence` — *detailed in Part 3* |
| `migrations/versions/0004_camera_stream_credentials.py` | nullable encrypted credential column — *detailed in Part 2* |

---

## 4. How a protected request works, end to end

1. Uvicorn imports `app.main:app` → `create_app()` → `get_settings()` **fails fast** if config is
   invalid → logging configured → exception handlers registered → routers mounted.
2. A request hits a route. Read-only + authenticated routes depend on `get_auth_context`; the
   browser's HttpOnly session cookie is read and passed to `resolve_session`, which rejects
   missing/unknown/revoked/expired/inactive sessions.
3. State-changing routes depend on `get_csrf_auth_context`: same session check **plus**
   `enforce_csrf`, which compares the `X-CSRF-Token` header (hashed) against the session's stored
   CSRF hash with `tokens_equal`.
4. The worker's `/api/internal/*` routes depend on `require_internal_token` instead of a session
   — a shared secret compared with `hmac.compare_digest`, never logged.
5. Any raised error is normalised by `api/errors.py` into `{"detail": …}` (or a 422 with an
   `errors` list) without echoing configuration or secrets.

Login is the one special path: `POST /api/auth/login` rate-limits by `host|username`
(`LoginRateLimiter`), calls `authenticate` (always a hash verify, even for unknown users), and on
success creates a session and sets both cookies. Failures are audited.

---

## 5. Design decisions worth calling out

- **Single administrator, server-side sessions** (see `docs/DECISIONS.md` D-15–D-20 for the Phase 2
  auth decisions). No JWTs; sessions can be revoked server-side.
- **Deliberate CSRF cookie design:** the CSRF value must be readable by JavaScript to be echoed,
  so it is intentionally *not* HttpOnly — while the session token is.
- **Validation is a feature, not a nuisance:** `_check_environment` forbids `debug` in production
  and `SameSite=none` without `secure`; `_check_live_playback` (owned by Part 2) rejects the
  gateway URLs being set while playback is disabled.
- **`get_db` is the single DB seam** — tests override it with an in-memory SQLite factory, so the
  whole suite runs without PostgreSQL.

---

## 6. Honesty & security notes to state plainly

- The login rate limiter is **in-memory and per-process**; it resets on restart. This is documented
  and acceptable for a single-process prototype (the same caveat applies to the monitoring
  controller and worker registry in Part 2, and the broadcaster in Part 3).
- The internal token is required **even on loopback** — there is no "trusted localhost" shortcut.
- Validation-error responses currently echo Pydantic's `errors()` verbatim; a submission review
  flagged that this can include the rejected `input` (a privacy concern on a 422 for login/camera
  credentials). It is recorded as a deferred behavior fix in `docs/DECISIONS.md` (D-76) and
  `docs/IMPLEMENTATION_PROGRESS.md`; presenters should mention it as a known open item rather than
  a solved problem.

---

## 7. Tests that prove this part

| Test file | Proves |
|---|---|
| `tests/test_config.py` | Settings parsing, placeholder/short-secret rejection, environment rules |
| `tests/test_security.py` | Password hashing + token helpers |
| `tests/test_rate_limit.py` | Login rate limiter window/retry semantics |
| `tests/test_admin_service.py` | Admin provisioning + CLI |
| `tests/test_auth_api.py` | login / logout / me |
| `tests/test_models.py` | ORM models + metadata registration |
| `tests/test_security_verification.py` | Route-enumerated sweep: 401 on every protected route, 403 without CSRF on state-changing routes |
| `tests/conftest.py` | Disables `.env` loading so a developer's local env can't change test outcomes; SQLite DB + auth fixtures |

`scripts/verify.sh` runs `alembic upgrade head --sql` (offline render);
`scripts/verify_migrations.sh` runs the authoritative live drift check.

---

## 8. Likely questions

- *Where are secrets read?* Only in `config.py`; `SecretStr` everywhere; the migration env reads
  the URL from settings, not from `alembic.ini`.
- *What stops a stolen DB from yielding sessions?* Tokens are stored as SHA-256 hashes; only
  high-entropy raw tokens exist in the browser.
- *Why can't the WebSocket be less strict?* It shares `resolve_session` with REST.
- *How do tests run without PostgreSQL?* `get_db` is overridden with SQLite in `conftest.py`.

## 9. Connects to

- **Part 2** builds on this: cameras/monitoring add their models, services, and routes using the
  same auth dependencies and `LifecycleError`-style exceptions.
- **Part 3** uses the same session/CSRF/internal dependencies for events/evidence and the
  real-time WebSocket.
- **Part 4** authenticates to the backend with the internal token defined here.
- **Part 5** consumes `/api/auth/*`, `/api/health`, and the cookie/CSRF contract from the browser.
